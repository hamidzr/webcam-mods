"""Optional AVFoundation capture with a single newest-frame mailbox."""

from threading import Condition, Event, Thread
from collections.abc import Sequence
from typing import Any, Iterator
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from webcam_mods.settings import load_settings
from webcam_mods.input.input import AdapterMetadata, FrameInput
from webcam_mods.macos.availability import camera_unavailable_reason, lid_closed

_delegate_class: Any = None


def is_obs_output_device(device: Any) -> bool:
    """Identify our OBS output by manufacturer/model, independent of display name."""
    return str(device.manufacturer()).casefold() == "obs project" or str(
        device.modelID()
    ).casefold() in {"obs camera extension", "obs virtual camera"}


def select_capture_device(devices: Sequence[Any], index: int) -> tuple[int, Any]:
    """Index input candidates after excluding our OBS virtual-camera output."""
    inputs = [
        (i, device)
        for i, device in enumerate(devices)
        if not is_obs_output_device(device)
    ]
    if not inputs:
        raise ValueError("no input cameras available after excluding OBS output")
    if type(index) is not int or not 0 <= index < len(inputs):
        raise ValueError(
            f"camera index {index} unavailable ({len(inputs)} inputs after excluding OBS output); use --input-device 0 or VIDEO_IN=0 for the first input"
        )
    selected_index, device = inputs[index]
    reason = camera_unavailable_reason(device, lid_closed())
    if reason:
        raise ValueError(
            f"camera index {index} ({device.localizedName()}) unavailable: {reason}"
        )
    return selected_index, device


def select_capture_device_by_id(
    devices: Sequence[Any], device_id: str
) -> tuple[int, Any]:
    """Retain the same selected input across backend/enumeration changes."""
    for index, device in enumerate(devices):
        if str(device.uniqueID()) == device_id:
            if is_obs_output_device(device):
                raise ValueError("selected camera is OBS output, not an input")
            reason = camera_unavailable_reason(device, lid_closed())
            if reason:
                raise ValueError(
                    f"selected camera ({device.localizedName()}) unavailable: {reason}"
                )
            return index, device
    raise ValueError("selected camera is no longer available; run list-cameras")


def select_capture_format(
    device: Any, core_media: Any, width: int, height: int, fps: float, index: int
) -> Any:
    """Require an exact format; never silently switch to another input device."""
    available: set[tuple[int, int, float, float]] = set()
    selected = None
    for fmt, w, h, minimum, maximum in _format_ranges(device, core_media):
        available.add((w, h, minimum, maximum))
        if selected is None and (w, h) == (width, height) and minimum <= fps <= maximum:
            selected = fmt
    if selected is not None:
        return selected
    choices = (
        ", ".join(
            f"{w}x{h} at {low:g}-{high:g} fps" for w, h, low, high in sorted(available)
        )
        or "none"
    )
    raise ValueError(
        f"AVFoundation camera {index} ({device.localizedName()}) cannot deliver "
        f"{width}x{height} at {fps:g} fps. Supported formats: {choices}. "
        "Choose another camera with --input-device or VIDEO_IN; "
        "AVFoundation device indices may differ from OpenCV. Run list-cameras to inspect inputs."
    )


@dataclass(frozen=True)
class CameraInfo:
    input_index: int | None
    name: str
    formats: tuple[str, ...]
    excluded_reason: str | None = None


def _format_ranges(
    device: Any, core_media: Any
) -> Iterator[tuple[Any, int, int, float, float]]:
    for fmt in device.formats():
        dims = core_media.CMVideoFormatDescriptionGetDimensions(fmt.formatDescription())
        for rate in fmt.videoSupportedFrameRateRanges():
            yield fmt, dims.width, dims.height, rate.minFrameRate(), rate.maxFrameRate()


def camera_inventory(backend: str = "avfoundation") -> list[CameraInfo]:
    """Enumerate formats without opening devices or requesting camera permission."""
    if backend not in ("auto", "avfoundation", "opencv"):
        raise ValueError(f"unknown camera backend: {backend}")
    import AVFoundation as av
    import CoreMedia as cm
    from webcam_mods.capture import resolve_backend

    devices = list(av.AVCaptureDevice.devicesWithMediaType_(av.AVMediaTypeVideo))
    video_ids = {str(device.uniqueID()) for device in devices}
    native_auto = backend == "auto" and resolve_backend("auto") == "avfoundation"
    if backend in ("auto", "opencv"):
        # match OpenCV's video + muxed devices sorted by uniqueID, including OBS
        devices += list(av.AVCaptureDevice.devicesWithMediaType_(av.AVMediaTypeMuxed))
        devices.sort(key=lambda device: str(device.uniqueID()))
    closed = lid_closed()
    cameras = []
    input_index = 0
    for device in devices:
        excluded_reason = (
            "OBS output"
            if is_obs_output_device(device)
            else (
                "not a native video input; use --capture-backend opencv"
                if native_auto and str(device.uniqueID()) not in video_ids
                else None
            )
        )
        excluded = excluded_reason is not None
        formats = sorted(
            {(w, h, low, high) for _, w, h, low, high in _format_ranges(device, cm)}
        )
        cameras.append(
            CameraInfo(
                input_index=None if excluded else input_index,
                name=str(device.localizedName()),
                formats=tuple(
                    f"{w}x{h} at {low:g}-{high:g} fps" for w, h, low, high in formats
                ),
                excluded_reason=(
                    excluded_reason or camera_unavailable_reason(device, closed)
                ),
            )
        )
        if not excluded or backend in ("auto", "opencv"):
            input_index += 1
    return cameras


class AVFoundationCamera(FrameInput):
    """Copy BGRA callback buffers before returning them to AVFoundation.

    The existing loop receives owned BGR arrays. Native pixel buffers never escape
    their callback lifetime; this adapter does not yet offer zero-copy processing.
    """

    def __init__(
        self,
        device_index: int | None = None,
        *,
        timeout: float = 10.0,
        device_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        if timeout <= 0 or not np.isfinite(timeout):
            raise ValueError("capture timeout must be finite and positive")
        if (
            self.width <= 0
            or self.height <= 0
            or self.fps <= 0
            or not np.isfinite(self.fps)
        ):
            raise ValueError("camera dimensions and fps must be positive")
        self.device_index = (
            load_settings().video_in if device_index is None else device_index
        )
        self.timeout = timeout
        self._device_id = device_id
        self.timestamp: float | None = None
        self._condition = Condition()
        self._pending: tuple[NDArray[np.uint8], float] | None = None
        self._error: BaseException | None = None
        self._running = False
        self._stop = Event()
        self._worker: Thread | None = None
        self._locked_device: Any = None
        self._session: Any = None
        self._output: Any = None
        self._delegate: Any = None
        self._queue: Any = None

    def _publish(self, frame: NDArray[np.uint8], timestamp: float) -> None:
        with self._condition:
            if self._running:
                self._pending = (frame, timestamp)
                self._condition.notify_all()

    def _fail(self, error: BaseException) -> None:
        with self._condition:
            self._error = error
            self._condition.notify_all()

    def _receive(self, sample: Any, core_media: Any, quartz: Any) -> None:
        pixel = core_media.CMSampleBufferGetImageBuffer(sample)
        if pixel is None:
            raise RuntimeError("AVFoundation delivered a sample without an image")
        flags = quartz.kCVPixelBufferLock_ReadOnly
        status = quartz.CVPixelBufferLockBaseAddress(pixel, flags)
        if status != 0:
            raise RuntimeError(f"could not lock camera pixel buffer: {status}")
        try:
            width = quartz.CVPixelBufferGetWidth(pixel)
            height = quartz.CVPixelBufferGetHeight(pixel)
            stride = quartz.CVPixelBufferGetBytesPerRow(pixel)
            if (
                quartz.CVPixelBufferGetPixelFormatType(pixel)
                != quartz.kCVPixelFormatType_32BGRA
            ):
                raise RuntimeError("camera output did not negotiate BGRA pixels")
            memory = quartz.CVPixelBufferGetBaseAddress(pixel).as_buffer(
                height * stride
            )
            rows = np.frombuffer(memory, dtype=np.uint8).reshape(height, stride)
            bgr = rows[:, : width * 4].reshape(height, width, 4)[..., :3].copy()
            timestamp = core_media.CMTimeGetSeconds(
                core_media.CMSampleBufferGetPresentationTimeStamp(sample)
            )
        finally:
            quartz.CVPixelBufferUnlockBaseAddress(pixel, flags)
        self._publish(bgr, timestamp)

    def setup(self) -> AdapterMetadata:
        global _delegate_class
        if self._running:
            return {"width": self.width, "height": self.height, "fps": self.fps}
        if self._worker is not None and self._worker.is_alive():
            raise RuntimeError("previous camera session is still stopping")
        try:
            import AVFoundation as av
            import CoreMedia as cm
            import Quartz as q
            import libdispatch
            import objc
            from Foundation import NSObject
        except ImportError as exc:
            raise RuntimeError(
                "AVFoundation capture requires macOS and the webcam-mods macos extra"
            ) from exc

        status = av.AVCaptureDevice.authorizationStatusForMediaType_(
            av.AVMediaTypeVideo
        )
        if status == av.AVAuthorizationStatusNotDetermined:
            granted = Event()
            result: list[bool] = []

            def permission(allowed: bool) -> None:
                result.append(allowed)
                granted.set()

            av.AVCaptureDevice.requestAccessForMediaType_completionHandler_(
                av.AVMediaTypeVideo, permission
            )
            if not granted.wait(self.timeout):
                raise TimeoutError(
                    "camera permission timed out; allow Camera access for the terminal/app"
                )
            status = (
                av.AVAuthorizationStatusAuthorized
                if result[0]
                else av.AVAuthorizationStatusDenied
            )
        if status != av.AVAuthorizationStatusAuthorized:
            raise PermissionError(
                "camera access denied; enable this terminal/app in System Settings > Privacy & Security > Camera"
            )

        if _delegate_class is None:

            # PyObjC registers this dynamic base and protocol outside Python's type model
            class WebcamModsCaptureDelegate(  # type: ignore[call-arg]
                NSObject,  # type: ignore[misc]
                protocols=[
                    objc.protocolNamed("AVCaptureVideoDataOutputSampleBufferDelegate")
                ],
            ):
                owner: "AVFoundationCamera | None"

                @objc.python_method  # type: ignore[untyped-decorator]
                def receive(self, sample: Any) -> None:
                    owner = self.owner
                    if owner is None:
                        return
                    try:
                        owner._receive(sample, cm, q)
                    except Exception as exc:
                        owner._fail(exc)

                def captureOutput_didOutputSampleBuffer_fromConnection_(
                    self, output: Any, sample: Any, connection: Any
                ) -> None:
                    self.receive(sample)

            _delegate_class = WebcamModsCaptureDelegate

        self._stop = Event()
        self._pending = None
        self._error = None
        self.timestamp = None
        try:
            devices = av.AVCaptureDevice.devicesWithMediaType_(av.AVMediaTypeVideo)
            selected_index, device = (
                select_capture_device_by_id(devices, self._device_id)
                if self._device_id is not None
                else select_capture_device(devices, self.device_index)
            )
            selected_format = select_capture_format(
                device, cm, self.width, self.height, self.fps, selected_index
            )
            camera_input, error = av.AVCaptureDeviceInput.deviceInputWithDevice_error_(
                device, None
            )
            if camera_input is None:
                raise RuntimeError(f"could not open camera: {error}")
            self._session = av.AVCaptureSession.alloc().init()
            self._output = av.AVCaptureVideoDataOutput.alloc().init()
            self._output.setVideoSettings_(
                {q.kCVPixelBufferPixelFormatTypeKey: q.kCVPixelFormatType_32BGRA}
            )
            self._output.setAlwaysDiscardsLateVideoFrames_(True)
            self._delegate = _delegate_class.alloc().init()
            self._delegate.owner = self
            self._queue = libdispatch.dispatch_queue_create(
                b"webcam-mods.capture", None
            )
            self._output.setSampleBufferDelegate_queue_(self._delegate, self._queue)
            self._session.beginConfiguration()
            try:
                if not self._session.canAddInput_(camera_input):
                    raise RuntimeError("could not attach camera input")
                self._session.addInput_(camera_input)
                if not self._session.canAddOutput_(self._output):
                    raise RuntimeError("could not attach camera output")
                self._session.addOutput_(self._output)
                locked, error = device.lockForConfiguration_(None)
                if not locked:
                    raise RuntimeError(f"could not configure camera: {error}")
                # macOS may override the format at commit/start unless this lock is retained
                self._locked_device = device
                device.setActiveFormat_(selected_format)
                duration = cm.CMTimeMake(1000, round(self.fps * 1000))
                device.setActiveVideoMinFrameDuration_(duration)
                device.setActiveVideoMaxFrameDuration_(duration)
            finally:
                self._session.commitConfiguration()
            self._running = True
            session, output, stop = self._session, self._output, self._stop

            def run() -> None:
                try:
                    with objc.autorelease_pool():
                        session.startRunning()
                        stop.wait()
                except Exception as exc:
                    self._fail(exc)
                finally:
                    try:
                        with objc.autorelease_pool():
                            session.stopRunning()
                    except Exception as exc:
                        self._fail(exc)
                    finally:
                        output.setSampleBufferDelegate_queue_(None, None)
                        if self._delegate is not None:
                            self._delegate.owner = None

            self._worker = Thread(
                target=run, name="webcam-mods-avfoundation", daemon=True
            )
            self._worker.start()
            with self._condition:
                ready = self._condition.wait_for(
                    lambda: self._pending is not None or self._error is not None,
                    self.timeout,
                )
                if self._error is not None:
                    raise RuntimeError("AVFoundation startup failed") from self._error
                if not ready or self._pending is None:
                    raise TimeoutError(
                        "camera produced no frame before startup timeout"
                    )
                first, _ = self._pending
                height, width = first.shape[:2]
                if (width, height) != (self.width, self.height):
                    raise RuntimeError(
                        f"camera returned {width}x{height}; requested {self.width}x{self.height}"
                    )
            duration = device.activeVideoMinFrameDuration()
            negotiated_fps = 1.0 / cm.CMTimeGetSeconds(duration)
            if not np.isclose(negotiated_fps, self.fps, rtol=0.01, atol=0.1):
                raise RuntimeError(
                    f"AVFoundation returned {negotiated_fps:g} FPS; "
                    f"requested {self.fps:g} FPS"
                )
            self.fps = negotiated_fps
            return {"width": self.width, "height": self.height, "fps": self.fps}
        except BaseException:
            try:
                self.teardown()
            except TimeoutError:
                pass
            raise

    def frame(self) -> NDArray[np.uint8] | None:
        with self._condition:
            if not self._running:
                return None
            ready = self._condition.wait_for(
                lambda: self._pending is not None
                or self._error is not None
                or not self._running,
                self.timeout,
            )
            if self._error is not None:
                raise RuntimeError("AVFoundation frame capture failed") from self._error
            if not self._running:
                return None
            if not ready or self._pending is None:
                raise TimeoutError("camera frame timeout")
            frame, self.timestamp = self._pending
            self._pending = None
            height, width = frame.shape[:2]
            if (width, height) != (self.width, self.height):
                raise RuntimeError(
                    "AVFoundation changed resolution during capture: "
                    f"{self.width}x{self.height} -> {width}x{height}"
                )
            return frame

    def is_setup(self) -> bool:
        return self._running

    def teardown(self, *args: Any, **kwargs: Any) -> None:
        with self._condition:
            self._running = False
            self._pending = None
            self._condition.notify_all()
        self._stop.set()
        if self._worker is not None:
            self._worker.join(self.timeout)
            if self._worker.is_alive():
                raise TimeoutError("native camera session is still stopping")
            self._worker = None
        try:
            if self._output is not None:
                self._output.setSampleBufferDelegate_queue_(None, None)
            if self._delegate is not None:
                self._delegate.owner = None
        finally:
            device, self._locked_device = self._locked_device, None
            try:
                if device is not None:
                    device.unlockForConfiguration()
            finally:
                self._session = self._output = self._delegate = self._queue = None
