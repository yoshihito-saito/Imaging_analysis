"""Input helpers for Nikon ND2 microscopy files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import warnings

import numpy as np


@dataclass(frozen=True)
class Nd2Image:
    """A loaded ND2 image normalized to channel-first layout."""

    data: np.ndarray
    path: Path
    dims: tuple[str, ...]
    sizes: dict[str, int]
    metadata: dict[str, Any]


def find_nd2_files(folder: str | Path, recursive: bool = False) -> list[Path]:
    """Return sorted ND2 files in a folder."""

    root = Path(folder).expanduser()
    pattern = "**/*.nd2" if recursive else "*.nd2"
    return sorted(path for path in root.glob(pattern) if path.is_file())


def select_nd2_files_dialog(
    initial_dir: str | Path | None = None,
    *,
    title: str = "Select ND2 files",
) -> list[Path]:
    """Open a local file dialog and return selected ND2 files.

    This helper is intended for local Jupyter sessions. If the GUI dialog is
    unavailable, it returns an empty list so notebooks can fall back to a manual
    folder path.
    """

    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError as exc:
        warnings.warn(f"tkinter is unavailable: {exc}", RuntimeWarning, stacklevel=2)
        return []

    root: Any | None = None
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        root.update()
    except tk.TclError as exc:
        warnings.warn(f"File dialog is unavailable: {exc}", RuntimeWarning, stacklevel=2)
        return []

    try:
        selected = filedialog.askopenfilenames(
            parent=root,
            title=title,
            initialdir=str(Path(initial_dir).expanduser()) if initial_dir is not None else None,
            filetypes=(("Nikon ND2 files", "*.nd2"), ("All files", "*.*")),
        )
    except tk.TclError as exc:
        warnings.warn(f"File dialog is unavailable: {exc}", RuntimeWarning, stacklevel=2)
        return []
    finally:
        if root is not None:
            root.destroy()

    return [Path(path) for path in selected]


def summarize_nd2(path: str | Path) -> dict[str, Any]:
    """Read lightweight ND2 metadata without loading the image pixels."""

    nd2 = _import_nd2()
    nd2_path = Path(path)
    with nd2.ND2File(nd2_path) as handle:
        summary: dict[str, Any] = {
            "path": str(nd2_path),
            "sizes": dict(getattr(handle, "sizes", {})),
            "channels": _channel_metadata(handle),
            "voxel_size_um": _voxel_size_metadata(handle),
        }
        for attr in ("shape", "dtype", "is_rgb", "attributes"):
            try:
                value = getattr(handle, attr)
            except Exception:
                continue
            summary[attr] = _json_safe(value)
        return summary


def read_nd2_image(
    path: str | Path,
    *,
    scene_index: int = 0,
    position_index: int | None = None,
    time_index: int = 0,
    z_index: int | None = None,
    z_projection: str = "max",
    downsample: int = 1,
) -> Nd2Image:
    """Load an ND2 file as a finite ``(channels, y, x)`` array.

    Extra axes are selected by index. If a Z axis is present and ``z_index`` is
    None, the stack is projected with ``z_projection``. ``downsample`` applies a
    spatial stride to Y/X axes before computing the returned array.
    """

    if downsample < 1:
        raise ValueError("downsample must be >= 1.")

    nd2 = _import_nd2()
    nd2_path = Path(path)
    with nd2.ND2File(nd2_path) as handle:
        sizes = dict(getattr(handle, "sizes", {}))
        array, dims = _read_with_dims(handle, downsample=downsample)
        metadata = {
            "sizes": sizes,
            "channels": _channel_metadata(handle),
            "voxel_size_um": _voxel_size_metadata(handle),
            "source_dims": dims,
            "scene_index": scene_index,
            "position_index": position_index,
            "time_index": time_index,
            "z_index": z_index,
            "z_projection": z_projection,
            "downsample": downsample,
        }

    array, dims = _select_axis(array, dims, ("S", "Scene"), scene_index)
    array, dims = _select_axis(array, dims, ("P", "Position"), position_index)
    array, dims = _select_axis(array, dims, ("T", "Time"), time_index)
    array, dims = _project_or_select_z(array, dims, z_index, z_projection)
    array, dims = _drop_singleton_non_image_axes(array, dims)
    channel_first = _to_channel_first(array, dims)
    channel_first = np.nan_to_num(channel_first, nan=0.0, posinf=0.0, neginf=0.0)

    return Nd2Image(
        data=channel_first,
        path=nd2_path,
        dims=("C", "Y", "X"),
        sizes=sizes,
        metadata=metadata,
    )


class Nd2RegionReader:
    """Read bounded single-channel regions while keeping one ND2 handle open."""

    def __init__(
        self,
        path: str | Path,
        *,
        scene_index: int = 0,
        position_index: int | None = None,
        time_index: int = 0,
        z_index: int | None = None,
        z_projection: str = "max",
    ) -> None:
        self.path = Path(path)
        self.scene_index = scene_index
        self.position_index = position_index
        self.time_index = time_index
        self.z_index = z_index
        self.z_projection = z_projection
        self._handle: Any = None
        self._array: Any = None
        self.dims: tuple[str, ...] = ()
        self.sizes: dict[str, int] = {}
        self.metadata: dict[str, Any] = {}

    def __enter__(self) -> Nd2RegionReader:
        self._handle = _import_nd2().ND2File(self.path)
        try:
            self.sizes = dict(getattr(self._handle, "sizes", {}))
            self._array = self._handle.to_dask()
            self.dims = tuple(str(dim).upper() for dim in self.sizes)
            if len(self.dims) != self._array.ndim:
                self.dims = _guess_dims(np.empty(self._array.shape))
            self.metadata = {
                "sizes": self.sizes,
                "channels": _channel_metadata(self._handle),
                "voxel_size_um": _voxel_size_metadata(self._handle),
                "source_dims": self.dims,
                "scene_index": self.scene_index,
                "position_index": self.position_index,
                "time_index": self.time_index,
                "z_index": self.z_index,
                "z_projection": self.z_projection,
                "downsample": 1,
            }
            return self
        except Exception:
            self._handle.close()
            self._handle = None
            raise

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        if self._handle is not None:
            self._handle.close()
        self._handle = None
        self._array = None

    @property
    def image_shape(self) -> tuple[int, int]:
        return (int(self._array.shape[self.dims.index("Y")]), int(self._array.shape[self.dims.index("X")]))

    @property
    def channel_count(self) -> int:
        return int(self._array.shape[self.dims.index("C")]) if "C" in self.dims else 1

    def read_region(self, y0: int, y1: int, x0: int, x1: int, *, channel: int) -> np.ndarray:
        """Return one projected channel as a full-resolution 2D array."""

        if self._array is None:
            raise RuntimeError("ND2 region reader is not open.")
        height, width = self.image_shape
        if not (0 <= y0 < y1 <= height and 0 <= x0 < x1 <= width):
            raise ValueError("Region bounds must lie within the ND2 image.")
        if not 0 <= channel < self.channel_count:
            raise ValueError(f"Channel {channel} is outside the available range.")

        selectors: list[int | slice] = []
        remaining_dims: list[str] = []
        for dim in self.dims:
            if dim == "Y":
                selector: int | slice = slice(y0, y1)
            elif dim == "X":
                selector = slice(x0, x1)
            elif dim == "C":
                selector = channel
            elif dim in {"S", "SCENE"}:
                selector = self.scene_index
            elif dim in {"P", "POSITION"}:
                selector = 0 if self.position_index is None else self.position_index
            elif dim in {"T", "TIME"}:
                selector = self.time_index
            elif dim == "Z" and self.z_index is not None:
                selector = self.z_index
            else:
                selector = slice(None) if dim == "Z" else 0
            selectors.append(selector)
            if isinstance(selector, slice):
                remaining_dims.append(dim)

        array = np.asarray(self._array[tuple(selectors)].compute())
        array, dims = _project_or_select_z(array, tuple(remaining_dims), self.z_index, self.z_projection)
        array = np.moveaxis(array, (dims.index("Y"), dims.index("X")), (0, 1))
        return np.nan_to_num(array, nan=0.0, posinf=0.0, neginf=0.0)


def _import_nd2():
    try:
        import nd2  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ImportError(
            "The 'nd2' package is required. Create the conda environment with "
            "'conda env create -f environment.yml'."
        ) from exc
    return nd2


def _read_with_dims(handle: Any, *, downsample: int) -> tuple[np.ndarray, tuple[str, ...]]:
    if downsample > 1:
        return _read_downsampled_with_dask(handle, downsample=downsample)

    try:
        data_array = handle.to_xarray(delayed=False)
        return np.asarray(data_array), tuple(str(dim).upper() for dim in data_array.dims)
    except Exception:
        array = np.asarray(handle.asarray())
        dims = tuple(str(dim).upper() for dim in getattr(handle, "sizes", {}).keys())
        if len(dims) != array.ndim:
            dims = _guess_dims(array)
        return array, dims


def _read_downsampled_with_dask(handle: Any, *, downsample: int) -> tuple[np.ndarray, tuple[str, ...]]:
    dask_array = handle.to_dask()
    dims = tuple(str(dim).upper() for dim in getattr(handle, "sizes", {}).keys())
    if len(dims) != dask_array.ndim:
        dims = _guess_dims(np.empty(dask_array.shape))

    selectors: list[slice] = []
    for dim in dims:
        if dim in {"Y", "X"}:
            selectors.append(slice(None, None, downsample))
        else:
            selectors.append(slice(None))
    return np.asarray(dask_array[tuple(selectors)].compute()), dims


def _guess_dims(array: np.ndarray) -> tuple[str, ...]:
    if array.ndim == 2:
        return ("Y", "X")
    if array.ndim == 3:
        if array.shape[-1] <= 4:
            return ("Y", "X", "C")
        return ("C", "Y", "X")
    suffix = ("C", "Y", "X") if array.shape[-3] <= 8 else ("Z", "Y", "X")
    prefix = tuple(f"A{i}" for i in range(array.ndim - len(suffix)))
    return prefix + suffix


def _select_axis(
    array: np.ndarray,
    dims: tuple[str, ...],
    names: tuple[str, ...],
    index: int | None,
) -> tuple[np.ndarray, tuple[str, ...]]:
    axis = _find_axis(dims, names)
    if axis is None:
        return array, dims
    selected_index = 0 if index is None else index
    array = np.take(array, selected_index, axis=axis)
    dims = dims[:axis] + dims[axis + 1 :]
    return array, dims


def _project_or_select_z(
    array: np.ndarray,
    dims: tuple[str, ...],
    z_index: int | None,
    z_projection: str,
) -> tuple[np.ndarray, tuple[str, ...]]:
    axis = _find_axis(dims, ("Z",))
    if axis is None:
        return array, dims
    if z_index is not None:
        array = np.take(array, z_index, axis=axis)
    elif z_projection == "max":
        array = np.nanmax(array, axis=axis)
    elif z_projection == "mean":
        array = np.nanmean(array, axis=axis)
    elif z_projection == "first":
        array = np.take(array, 0, axis=axis)
    else:
        raise ValueError("z_projection must be one of: 'max', 'mean', 'first'.")
    dims = dims[:axis] + dims[axis + 1 :]
    return array, dims


def _drop_singleton_non_image_axes(
    array: np.ndarray,
    dims: tuple[str, ...],
) -> tuple[np.ndarray, tuple[str, ...]]:
    current_dims = list(dims)
    axis = 0
    while axis < len(current_dims):
        dim = current_dims[axis]
        if dim in {"C", "Y", "X"}:
            axis += 1
            continue
        if array.shape[axis] == 1:
            array = np.squeeze(array, axis=axis)
        else:
            array = np.take(array, 0, axis=axis)
        current_dims.pop(axis)

    final_dims = tuple(current_dims)
    if len(final_dims) != array.ndim:
        final_dims = _guess_dims(array)
    return array, final_dims


def _to_channel_first(array: np.ndarray, dims: tuple[str, ...]) -> np.ndarray:
    if "Y" not in dims or "X" not in dims:
        dims = _guess_dims(array)
    if "C" not in dims:
        y_axis = dims.index("Y")
        x_axis = dims.index("X")
        moved = np.moveaxis(array, (y_axis, x_axis), (-2, -1))
        return moved[np.newaxis, ...]

    order = [dims.index("C"), dims.index("Y"), dims.index("X")]
    return np.transpose(array, order)


def _find_axis(dims: tuple[str, ...], names: tuple[str, ...]) -> int | None:
    normalized = {name.upper() for name in names}
    for axis, dim in enumerate(dims):
        if dim.upper() in normalized:
            return axis
    return None


def _json_safe(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)


def _channel_metadata(handle: Any) -> list[dict[str, Any]]:
    metadata = getattr(handle, "metadata", None)
    channels = getattr(metadata, "channels", None)
    if not channels:
        return []

    result: list[dict[str, Any]] = []
    for item in channels:
        channel = getattr(item, "channel", None)
        color = getattr(channel, "color", None)
        result.append(
            {
                "index": getattr(channel, "index", None),
                "name": getattr(channel, "name", None),
                "color_rgb": (
                    [getattr(color, "r", None), getattr(color, "g", None), getattr(color, "b", None)]
                    if color is not None
                    else None
                ),
                "emission_lambda_nm": getattr(channel, "emissionLambdaNm", None),
                "excitation_lambda_nm": getattr(channel, "excitationLambdaNm", None),
            }
        )
    return result


def _voxel_size_metadata(handle: Any) -> dict[str, float | None] | None:
    voxel_size = getattr(handle, "voxel_size", None)
    if voxel_size is None:
        return None

    try:
        voxel = voxel_size() if callable(voxel_size) else voxel_size
    except Exception:
        return None

    def _read_component(names: tuple[str, ...]) -> float | None:
        for name in names:
            if hasattr(voxel, name):
                value = getattr(voxel, name)
                return float(value) if value is not None else None
        return None

    return {
        "x": _read_component(("x",)),
        "y": _read_component(("y",)),
        "z": _read_component(("z",)),
    }
