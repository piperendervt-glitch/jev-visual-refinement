"""Preserve every instance mask in original keyframe pixel-edge coordinates."""
from __future__ import annotations

from io import BytesIO
import numpy as np
from PIL import Image


def normalize_masks(raw: np.ndarray, width: int, height: int) -> np.ndarray:
    """Validate retina-size binary instance masks without merging overlaps.

    Ultralytics ``retina_masks=True`` promises masks at the input image's
    original size. A size mismatch is an adapter failure, not a license to
    stretch an unknown crop or padding transform into plausible pixels.
    """
    array = np.asarray(raw)
    if array.ndim != 3 or array.shape[1:] != (height, width):
        raise ValueError("mask_original_shape_mismatch")
    if array.shape[0] > 20:
        raise ValueError("mask_count_limit")
    if not np.isfinite(array).all():
        raise ValueError("mask_nonfinite")
    return (array > 0.5).astype(np.uint8, copy=True)


def pixel_edge_bbox(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    """Return an exclusive right/bottom bbox in original pixel-edge units."""
    if mask.ndim != 2:
        raise ValueError("mask_rank")
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def png_rgb(rgb: np.ndarray) -> bytes:
    if rgb.ndim != 3 or rgb.shape[2] != 3 or rgb.dtype != np.uint8:
        raise ValueError("rgb8_required")
    stream = BytesIO()
    Image.fromarray(rgb, "RGB").save(stream, format="PNG")
    return stream.getvalue()


def png_mask(mask: np.ndarray) -> bytes:
    if mask.ndim != 2 or mask.dtype != np.uint8:
        raise ValueError("binary_mask_required")
    stream = BytesIO()
    Image.fromarray(mask * 255, "L").save(stream, format="PNG")
    return stream.getvalue()


def overlay_png(rgb: np.ndarray, masks: np.ndarray, alpha: float = 0.38) -> bytes:
    """Render one preview while keeping the independent masks in storage."""
    if not 0 <= alpha <= 1:
        raise ValueError("alpha_range")
    output = rgb.astype(np.float32, copy=True)
    palette = np.array(((20, 235, 173), (64, 176, 255), (218, 115, 255),
                        (255, 190, 68), (255, 107, 126)), dtype=np.float32)
    for ordinal, mask in enumerate(masks):
        active = mask.astype(bool)
        color = palette[ordinal % len(palette)]
        output[active] = output[active] * (1 - alpha) + color * alpha
    return png_rgb(np.clip(output, 0, 255).astype(np.uint8))
