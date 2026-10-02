"""Optional Core Image compositing at the existing BGR frame boundary."""

from typing import Any

import numpy as np
from numpy.typing import NDArray


class CoreImageProcessor:
    """Reuse one native context; blur uses Gaussian rather than OpenCV box blur."""

    def __init__(self) -> None:
        self._quartz: Any = None
        self._context: Any = None
        self._color_space: Any = None
        self._closed = False

    def _setup(self) -> None:
        if self._closed:
            raise RuntimeError("Core Image processor is closed")
        if self._context is not None:
            return
        try:
            import Quartz
        except ImportError as exc:
            raise RuntimeError(
                "Core Image requires macOS and the webcam-mods macos extra"
            ) from exc
        self._quartz = Quartz
        self._color_space = Quartz.CGColorSpaceCreateDeviceRGB()
        from Foundation import NSNull

        self._context = Quartz.CIContext.contextWithOptions_(
            {
                Quartz.kCIContextWorkingColorSpace: NSNull.null(),
                Quartz.kCIContextOutputColorSpace: NSNull.null(),
                Quartz.kCIContextCacheIntermediates: False,
            }
        )

    def close(self) -> None:
        self._closed = True
        if self._context is not None:
            self._context.clearCaches()
        self._context = None
        self._color_space = None
        self._quartz = None

    def _image(self, bgr: NDArray[np.uint8]) -> Any:
        from Foundation import NSData

        height, width = bgr.shape[:2]
        rgba = np.empty((height, width, 4), dtype=np.uint8)
        rgba[..., :3] = bgr[..., ::-1]
        rgba[..., 3] = 255
        data = NSData.dataWithBytes_length_(rgba.tobytes(), rgba.nbytes)
        return self._quartz.CIImage.imageWithBitmapData_bytesPerRow_size_format_colorSpace_(
            data,
            width * 4,
            (width, height),
            self._quartz.kCIFormatRGBA8,
            self._color_space,
        )

    def process(
        self,
        frame: NDArray[np.uint8],
        mask: NDArray[np.floating],
        *,
        background: NDArray[np.uint8] | None = None,
        color: tuple[int, int, int] | None = None,
        blur_radius: float | None = None,
    ) -> NDArray[np.uint8]:
        self._setup()
        import objc

        with objc.autorelease_pool():
            return self._process(
                frame, mask, background=background, color=color, blur_radius=blur_radius
            )

    def _process(
        self,
        frame: NDArray[np.uint8],
        mask: NDArray[np.floating],
        *,
        background: NDArray[np.uint8] | None = None,
        color: tuple[int, int, int] | None = None,
        blur_radius: float | None = None,
    ) -> NDArray[np.uint8]:
        """Composite foreground over exactly one BGR background, color, or blur.

        Mask must match frame dimensions and have foreground values in [0, 1].
        Background images are stretched to the frame dimensions.
        """
        if frame.dtype != np.uint8 or frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError("frame must be a uint8 HxWx3 BGR image")
        if not frame.shape[0] or not frame.shape[1]:
            raise ValueError("frame must not be empty")
        if mask.shape != frame.shape[:2] or not np.isfinite(mask).all():
            raise ValueError("mask must be finite and match frame dimensions")
        if sum(value is not None for value in (background, color, blur_radius)) != 1:
            raise ValueError("choose exactly one background, color, or blur_radius")
        if color is not None and (
            len(color) != 3 or any(v < 0 or v > 255 for v in color)
        ):
            raise ValueError("color must contain three BGR values in [0, 255]")
        if blur_radius is not None and (
            not np.isfinite(blur_radius) or blur_radius < 0
        ):
            raise ValueError("blur_radius must be finite and nonnegative")
        if background is not None and (
            background.dtype != np.uint8
            or background.ndim != 3
            or background.shape[2] != 3
            or not all(background.shape[:2])
        ):
            raise ValueError("background must be a nonempty uint8 HxWx3 BGR image")
        self._setup()
        q = self._quartz
        height, width = frame.shape[:2]
        bounds = ((0, 0), (width, height))
        image = self._image(frame)
        if background is not None:
            backdrop = (
                self._image(background)
                .imageByApplyingTransform_(
                    q.CGAffineTransformMakeScale(
                        width / background.shape[1], height / background.shape[0]
                    )
                )
                .imageByCroppingToRect_(bounds)
            )
        elif color is not None:
            backdrop = q.CIImage.imageWithColor_(
                q.CIColor.colorWithRed_green_blue_alpha_(
                    color[2] / 255, color[1] / 255, color[0] / 255, 1.0
                )
            ).imageByCroppingToRect_(bounds)
        else:
            backdrop = (
                image.imageByClampingToExtent()
                .imageByApplyingFilter_withInputParameters_(
                    "CIGaussianBlur", {"inputRadius": float(blur_radius)}
                )
                .imageByCroppingToRect_(bounds)
            )
        from Foundation import NSData

        gray = np.ascontiguousarray(np.clip(mask, 0, 1), dtype=np.float32)
        data = NSData.dataWithBytes_length_(gray.tobytes(), gray.nbytes)
        mask_image = q.CIImage.imageWithBitmapData_bytesPerRow_size_format_colorSpace_(
            data, width * 4, (width, height), q.kCIFormatRf, None
        )
        composite = image.imageByApplyingFilter_withInputParameters_(
            "CIBlendWithRedMask",
            {"inputBackgroundImage": backdrop, "inputMaskImage": mask_image},
        )
        pixels = bytearray(height * width * 4)
        self._context.render_toBitmap_rowBytes_bounds_format_colorSpace_(
            composite, pixels, width * 4, bounds, q.kCIFormatRGBA8, self._color_space
        )
        return (
            np.frombuffer(pixels, dtype=np.uint8)
            .reshape(height, width, 4)[..., 2::-1]
            .copy()
        )
