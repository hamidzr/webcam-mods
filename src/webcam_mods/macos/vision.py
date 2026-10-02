"""Instance-owned Apple Vision person segmentation for BGR frames."""

import sys
from typing import Any, Literal

import cv2
import numpy as np
from numpy.typing import NDArray

Quality = Literal["fast", "balanced", "accurate"]


class VisionSegmenter:
    """Synchronous segmenter; one instance belongs to one frame-processing thread."""

    def __init__(self, quality: Quality = "balanced") -> None:
        if quality not in ("fast", "balanced", "accurate"):
            raise ValueError("Vision quality must be fast, balanced, or accurate")
        self.quality = quality
        self._request: Any = None
        self._buffer: Any = None
        self._shape: tuple[int, int] | None = None
        self._quartz: Any = None
        self._vision: Any = None
        self._objc: Any = None
        self._closed = False

    def _initialize(self) -> None:
        if self._request is not None:
            return
        if sys.platform != "darwin":
            raise RuntimeError("Vision segmentation requires macOS 12 or newer")
        try:
            import objc
            import Quartz
            import Vision
        except ImportError as exc:
            raise RuntimeError(
                "Vision segmentation requires the macos extra: "
                "install webcam-mods[macos]"
            ) from exc
        if not hasattr(Vision, "VNGeneratePersonSegmentationRequest"):
            raise RuntimeError("Vision segmentation requires macOS 12 or newer")
        request = Vision.VNGeneratePersonSegmentationRequest.alloc().initWithCompletionHandler_(
            None
        )
        request.setQualityLevel_(
            getattr(
                Vision,
                "VNGeneratePersonSegmentationRequestQualityLevel"
                + self.quality.title(),
            )
        )
        request.setOutputPixelFormat_(Quartz.kCVPixelFormatType_OneComponent32Float)
        self._quartz, self._vision, self._objc = Quartz, Vision, objc
        self._request = request

    def _copy_input(self, frame: NDArray[np.uint8]) -> Any:
        q = self._quartz
        height, width = frame.shape[:2]
        if self._shape != (height, width):
            status, buffer = q.CVPixelBufferCreate(
                None, width, height, q.kCVPixelFormatType_32BGRA, None, None
            )
            if status != 0 or buffer is None:
                raise RuntimeError(f"Vision input allocation failed: {status}")
            self._buffer, self._shape = buffer, (height, width)
        status = q.CVPixelBufferLockBaseAddress(self._buffer, 0)
        if status != 0:
            raise RuntimeError(f"Vision input buffer lock failed: {status}")
        try:
            stride = q.CVPixelBufferGetBytesPerRow(self._buffer)
            memory = q.CVPixelBufferGetBaseAddress(self._buffer).as_buffer(
                stride * height
            )
            pixels = np.ndarray(
                (height, width, 4),
                dtype=np.uint8,
                buffer=memory,
                strides=(stride, 4, 1),
            )
            pixels[:, :, :3] = frame
            pixels[:, :, 3] = 255
        finally:
            q.CVPixelBufferUnlockBaseAddress(self._buffer, 0)
        return self._buffer

    def _copy_mask(self, buffer: Any) -> NDArray[np.float32]:
        q = self._quartz
        flags = q.kCVPixelBufferLock_ReadOnly
        status = q.CVPixelBufferLockBaseAddress(buffer, flags)
        if status != 0:
            raise RuntimeError(f"Vision mask buffer lock failed: {status}")
        try:
            if (
                q.CVPixelBufferGetPixelFormatType(buffer)
                != q.kCVPixelFormatType_OneComponent32Float
            ):
                raise RuntimeError("Vision returned an unexpected mask pixel format")
            height = q.CVPixelBufferGetHeight(buffer)
            width = q.CVPixelBufferGetWidth(buffer)
            stride = q.CVPixelBufferGetBytesPerRow(buffer)
            memory = q.CVPixelBufferGetBaseAddress(buffer).as_buffer(stride * height)
            # copy while locked: returned arrays must outlive the native observation
            return np.ndarray(
                (height, width), dtype=np.float32, buffer=memory, strides=(stride, 4)
            ).copy()
        finally:
            q.CVPixelBufferUnlockBaseAddress(buffer, flags)

    def predict(self, frame: NDArray[np.uint8]) -> NDArray[np.float32]:
        """Return foreground confidence in [0, 1], preserving input orientation."""
        if self._closed:
            raise RuntimeError("Vision segmenter is closed")
        if (
            not isinstance(frame, np.ndarray)
            or frame.dtype != np.uint8
            or frame.ndim != 3
            or frame.shape[2] != 3
            or min(frame.shape[:2]) == 0
        ):
            raise ValueError("Vision input must be a nonempty HxWx3 uint8 BGR array")
        self._initialize()
        with self._objc.autorelease_pool():
            buffer = self._copy_input(frame)
            # orientation 1 is upright; BGR rows already have top-left origin
            handler = self._vision.VNImageRequestHandler.alloc().initWithCVPixelBuffer_orientation_options_(
                buffer, 1, None
            )
            success, error = handler.performRequests_error_([self._request], None)
            if not success:
                raise RuntimeError(f"Vision segmentation failed: {error}")
            results = self._request.results()
            if not results:
                raise RuntimeError("Vision segmentation returned no mask")
            mask = self._copy_mask(results[0].pixelBuffer())
        height, width = frame.shape[:2]
        if mask.shape != (height, width):
            mask = cv2.resize(mask, (width, height), interpolation=cv2.INTER_LINEAR)
        return np.clip(mask, 0, 1, out=mask)

    def close(self) -> None:
        """Release native references after the owning run completes."""
        if self._request is not None:
            self._request.cancel()
        self._request = self._buffer = None
        self._shape = None
        self._closed = True
