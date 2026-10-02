"""Optional AVFoundation capture with a single newest-frame mailbox."""

from threading import Condition, Event, Thread
from typing import Any

import numpy as np
from numpy.typing import NDArray

from webcam_mods import config
from webcam_mods.input.input import FrameInput

_delegate_class: Any = None


class AVFoundationCamera(FrameInput):
    """Copy BGRA callback buffers before returning them to AVFoundation.

    The existing loop receives owned BGR arrays. Native pixel buffers never escape
    their callback lifetime; this adapter does not yet offer zero-copy processing.
    """

    def __init__(
        self,
        device_index: int = config.VIDEO_IN,
        *,
        timeout: float = 10.0,
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
        self.device_index = device_index
        self.timeout = timeout
        self.timestamp: float | None = None
        self._condition = Condition()
        self._pending: tuple[NDArray[np.uint8], float] | None = None
        self._error: BaseException | None = None
        self._running = False
        self._stop = Event()
        self._worker: Thread | None = None
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

    def setup(self) -> dict[str, Any]:
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

            class WebcamModsCaptureDelegate(
                NSObject,
                protocols=[
                    objc.protocolNamed("AVCaptureVideoDataOutputSampleBufferDelegate")
                ],
            ):
                @objc.python_method
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
            if not isinstance(
                self.device_index, int
            ) or not 0 <= self.device_index < len(devices):
                raise ValueError(
                    f"camera index {self.device_index} unavailable ({len(devices)} devices)"
                )
            device = devices[self.device_index]
            formats = []
            for fmt in device.formats():
                dimensions = cm.CMVideoFormatDescriptionGetDimensions(
                    fmt.formatDescription()
                )
                if (dimensions.width, dimensions.height) == (self.width, self.height):
                    for rate in fmt.videoSupportedFrameRateRanges():
                        if rate.minFrameRate() <= self.fps <= rate.maxFrameRate():
                            formats.append(fmt)
                            break
            if not formats:
                raise ValueError(
                    f"camera cannot deliver {self.width}x{self.height} at {self.fps} fps"
                )
            locked, error = device.lockForConfiguration_(None)
            if not locked:
                raise RuntimeError(f"could not configure camera: {error}")
            try:
                device.setActiveFormat_(formats[0])
                duration = cm.CMTimeMake(1000, round(self.fps * 1000))
                device.setActiveVideoMinFrameDuration_(duration)
                device.setActiveVideoMaxFrameDuration_(duration)
            finally:
                device.unlockForConfiguration()
            camera_input, error = av.AVCaptureDeviceInput.deviceInputWithDevice_error_(
                device, None
            )
            if camera_input is None:
                raise RuntimeError(f"could not open camera: {error}")
            self._session = av.AVCaptureSession.alloc().init()
            if not self._session.canSetSessionPreset_(
                av.AVCaptureSessionPresetInputPriority
            ):
                raise RuntimeError(
                    "camera session cannot honor explicit capture format"
                )
            self._session.setSessionPreset_(av.AVCaptureSessionPresetInputPriority)
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
            if not self._session.canAddInput_(camera_input):
                raise RuntimeError("could not attach camera input")
            self._session.addInput_(camera_input)
            if not self._session.canAddOutput_(self._output):
                raise RuntimeError("could not attach camera output")
            self._session.addOutput_(self._output)
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
                if not ready:
                    raise TimeoutError(
                        "camera produced no frame before startup timeout"
                    )
                first, _ = self._pending
                self.height, self.width = first.shape[:2]
            duration = device.activeVideoMinFrameDuration()
            self.fps = 1.0 / cm.CMTimeGetSeconds(duration)
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
            if not ready:
                raise TimeoutError("camera frame timeout")
            frame, self.timestamp = self._pending
            self._pending = None
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
        elif self._output is not None:
            self._output.setSampleBufferDelegate_queue_(None, None)
        if self._delegate is not None:
            self._delegate.owner = None
        self._session = self._output = self._delegate = self._queue = None
