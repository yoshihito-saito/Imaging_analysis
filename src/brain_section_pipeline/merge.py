"""Channel scaling and RGB merge utilities."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

DEFAULT_CHANNEL_COLORS: tuple[tuple[float, float, float], ...] = (
    (3 / 255, 81 / 255, 1.0),
    (91 / 255, 1.0, 0.0),
    (1.0, 160 / 255, 0.0),
    (1.0, 1.0, 1.0),
)


def sanitize_array(array: np.ndarray, fill_value: float = 0.0) -> np.ndarray:
    """Return a finite floating-point copy of an image array."""

    return np.nan_to_num(np.asarray(array, dtype=np.float32), nan=fill_value, posinf=fill_value, neginf=fill_value)


def robust_scale(
    image: np.ndarray,
    percentiles: tuple[float, float] = (0.5, 99.8),
) -> np.ndarray:
    """Scale one image plane to 0..1 with finite percentile limits."""

    plane = sanitize_array(image)
    finite = plane[np.isfinite(plane)]
    if finite.size == 0:
        return np.zeros_like(plane, dtype=np.float32)

    low, high = np.percentile(finite, percentiles)
    if high <= low:
        high = float(finite.max())
        low = float(finite.min())
    if high <= low:
        return np.zeros_like(plane, dtype=np.float32)

    scaled = (plane - low) / (high - low)
    return np.clip(scaled, 0.0, 1.0).astype(np.float32)


def merge_channels(
    image: np.ndarray,
    *,
    channel_colors: Sequence[Sequence[float]] | None = None,
    percentiles: tuple[float, float] = (0.5, 99.8),
    channels: Sequence[int] | None = None,
    output_dtype: np.dtype = np.uint8,
) -> np.ndarray:
    """Merge channel-first data into RGB."""

    channel_first = ensure_channel_first(image)
    selected_channels = list(range(channel_first.shape[0])) if channels is None else list(channels)
    colors = channel_colors or DEFAULT_CHANNEL_COLORS
    rgb = np.zeros(channel_first.shape[1:] + (3,), dtype=np.float32)

    for order, channel_index in enumerate(selected_channels):
        if channel_index >= channel_first.shape[0]:
            continue
        color = np.asarray(colors[order % len(colors)], dtype=np.float32)
        if color.shape != (3,):
            raise ValueError("Each channel color must contain exactly 3 RGB values.")
        scaled = robust_scale(channel_first[channel_index], percentiles)
        rgb += scaled[..., np.newaxis] * color

    rgb = np.clip(rgb, 0.0, 1.0)
    if output_dtype == np.uint8:
        return (rgb * 255.0).round().astype(np.uint8)
    if output_dtype == np.uint16:
        return (rgb * 65535.0).round().astype(np.uint16)
    return rgb.astype(output_dtype)


def ensure_channel_first(image: np.ndarray) -> np.ndarray:
    """Normalize common image layouts to ``(channels, y, x)``."""

    array = np.asarray(image)
    if array.ndim == 2:
        return array[np.newaxis, ...]
    if array.ndim != 3:
        raise ValueError("Expected a 2D image or a 3D channel image.")
    if array.shape[0] <= 8 and array.shape[1] > 8 and array.shape[2] > 8:
        return array
    if array.shape[-1] <= 8:
        return np.moveaxis(array, -1, 0)
    raise ValueError("Could not infer channel axis. Pass channel-first data.")
