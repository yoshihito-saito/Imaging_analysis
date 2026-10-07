"""Prepare slice-wise atlas inputs for sparse BrainGlobe workflows."""

from __future__ import annotations

import csv
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
from tifffile import imread, imwrite


SectionSource = Literal["registration", "rgb", "channel"]
AxisName = Literal["ap", "si", "dv", "rl", "ml"]

_WHS_SOURCE_AP_ORIGIN_VOXEL = 623
_WHS_SOURCE_VOXEL_SIZE_MM = 0.0390625
_WHS_AP_AXIS_LENGTH = 1024


@dataclass(frozen=True)
class SliceAtlasConfig:
    """Configuration for pairing sections with BrainGlobe atlas planes."""

    atlas_name: str = "whs_sd_rat_39um"
    anatomical_axis: AxisName = "ap"
    section_source: SectionSource = "registration"
    channel: int | None = None
    start_slice_index: int = 0
    slice_index_step: int = 1
    sample_id: str | None = None
    allowed_qc_statuses: tuple[str, ...] | None = None
    require_include_in_stack: bool = True
    copy_section_source: bool = False
    output_name: str = "slice_atlas_manifest.csv"
    metadata_name: str = "slice_atlas_metadata.json"


@dataclass(frozen=True)
class SliceAtlasResult:
    """Artifacts produced while preparing slice-wise atlas inputs."""

    output_dir: Path
    manifest_path: Path
    metadata_path: Path
    atlas_reference_dir: Path
    atlas_annotation_dir: Path
    section_source_dir: Path | None
    section_indices: list[int]


def prepare_slice_atlas_inputs(
    manifest_path: str | Path,
    output_dir: str | Path | None = None,
    *,
    config: SliceAtlasConfig | None = None,
) -> SliceAtlasResult:
    """Export atlas planes, accepting WHS-native AP millimetres on selected rows."""

    cfg = config or SliceAtlasConfig()
    manifest = Path(manifest_path)
    rows = _selected_rows(_read_manifest_rows(manifest), cfg)
    if not rows:
        raise ValueError("No section rows were selected for slice-wise atlas preparation.")

    atlas = _load_atlas(cfg.atlas_name)
    atlas_reference = np.asarray(atlas.reference)
    atlas_annotation = np.asarray(atlas.annotation)
    atlas_orientation = str(getattr(atlas, "orientation", "")).lower()
    atlas_resolution = list(getattr(atlas, "resolution", []))
    atlas_version = str(getattr(atlas, "metadata", {}).get("version", ""))
    slice_axis = _axis_index_from_orientation(atlas_orientation, cfg.anatomical_axis)

    assignments = [
        _slice_assignment_for_row(
            row,
            ordinal,
            cfg,
            atlas_reference.shape,
            atlas_orientation,
            atlas_resolution,
            atlas_version,
            slice_axis,
        )
        for ordinal, row in enumerate(rows)
    ]

    target_dir = Path(output_dir) if output_dir is not None else manifest.parent / "slice_atlas"
    atlas_reference_dir = target_dir / "atlas_reference"
    atlas_annotation_dir = target_dir / "atlas_annotation"
    section_source_dir = target_dir / "sections" if cfg.copy_section_source else None
    atlas_reference_dir.mkdir(parents=True, exist_ok=True)
    atlas_annotation_dir.mkdir(parents=True, exist_ok=True)
    if section_source_dir is not None:
        section_source_dir.mkdir(parents=True, exist_ok=True)

    pairing_rows: list[dict[str, Any]] = []
    selected_indices: list[int] = []
    for row, (atlas_slice_index, atlas_plane_whs_ap_mm) in zip(rows, assignments):
        section_index = int(row["section_index"])
        reference_slice = _extract_slice(atlas_reference, slice_axis, atlas_slice_index)
        annotation_slice = _extract_slice(atlas_annotation, slice_axis, atlas_slice_index)
        section_path = _section_source_path(row, cfg)

        reference_path = atlas_reference_dir / f"section{section_index:03d}_atlas_reference.tif"
        annotation_path = atlas_annotation_dir / f"section{section_index:03d}_atlas_annotation.tif"
        section_copy_path = (
            section_source_dir / f"section{section_index:03d}_section.tif" if section_source_dir is not None else section_path
        )
        imwrite(reference_path, reference_slice)
        imwrite(annotation_path, annotation_slice)
        if section_source_dir is not None:
            _copy_section_image(section_path, section_copy_path)

        pairing_rows.append(
            {
                **row,
                "atlas_name": cfg.atlas_name,
                "atlas_version": atlas_version,
                "atlas_orientation": atlas_orientation,
                "atlas_axis_name": cfg.anatomical_axis,
                "atlas_axis_index": slice_axis,
                "atlas_slice_index": atlas_slice_index,
                "whs_ap_mm": row.get("whs_ap_mm", ""),
                "atlas_plane_whs_ap_mm": atlas_plane_whs_ap_mm if atlas_plane_whs_ap_mm is not None else "",
                "atlas_reference_path": str(reference_path),
                "atlas_annotation_path": str(annotation_path),
                "section_source_kind": cfg.section_source,
                "section_source_path": str(section_copy_path),
            }
        )
        selected_indices.append(section_index)

    pairing_manifest_path = target_dir / cfg.output_name
    metadata_path = target_dir / cfg.metadata_name
    _write_manifest(pairing_manifest_path, pairing_rows)
    _write_json(
        metadata_path,
        {
            "input_manifest_path": str(manifest),
            "atlas_name": cfg.atlas_name,
            "atlas_version": atlas_version,
            "atlas_orientation": atlas_orientation,
            "atlas_resolution_um": atlas_resolution,
            "atlas_shape": list(atlas_reference.shape),
            "slice_axis_index": slice_axis,
            "slice_axis_name": cfg.anatomical_axis,
            "section_indices": selected_indices,
            "config": asdict(cfg),
            **(
                {
                    "whs_ap_calibration": {
                        "source": "WHS_SD_rat_T2star_v1.01",
                        "source_ap_origin_voxel": _WHS_SOURCE_AP_ORIGIN_VOXEL,
                        "source_voxel_size_mm": _WHS_SOURCE_VOXEL_SIZE_MM,
                        "rounding": "nearest_voxel",
                    }
                }
                if any(plane_mm is not None for _, plane_mm in assignments)
                else {}
            ),
        },
    )

    return SliceAtlasResult(
        output_dir=target_dir,
        manifest_path=pairing_manifest_path,
        metadata_path=metadata_path,
        atlas_reference_dir=atlas_reference_dir,
        atlas_annotation_dir=atlas_annotation_dir,
        section_source_dir=section_source_dir,
        section_indices=selected_indices,
    )


def _selected_rows(rows: list[dict[str, str]], cfg: SliceAtlasConfig) -> list[dict[str, str]]:
    filtered: list[dict[str, str]] = []
    allowed_statuses = {value.strip().lower() for value in cfg.allowed_qc_statuses} if cfg.allowed_qc_statuses else None
    for row in rows:
        if cfg.sample_id and row.get("sample_id") != cfg.sample_id:
            continue
        if cfg.require_include_in_stack and not _parse_bool(row.get("include_in_stack", "true")):
            continue
        if allowed_statuses is not None:
            status = (row.get("qc_status") or "").strip().lower()
            if status not in allowed_statuses:
                continue
        filtered.append(row)
    return sorted(filtered, key=lambda row: int(row["section_index"]))


def _load_atlas(atlas_name: str):
    try:
        from brainglobe_atlasapi.bg_atlas import BrainGlobeAtlas
    except ImportError as exc:
        raise ImportError(
            "brainglobe-atlasapi is required for slice-wise atlas preparation."
        ) from exc
    return BrainGlobeAtlas(atlas_name)


def _axis_index_from_orientation(orientation: str, axis_name: AxisName) -> int:
    mapping = {
        "ap": {"a", "p"},
        "si": {"s", "i"},
        "dv": {"d", "v", "s", "i"},
        "rl": {"r", "l"},
        "ml": {"m", "l", "r"},
    }
    allowed = mapping[axis_name]
    for index, char in enumerate(orientation):
        if char.lower() in allowed:
            return index
    raise ValueError(f"Could not find anatomical axis {axis_name!r} in atlas orientation {orientation!r}.")


def _slice_assignment_for_row(
    row: dict[str, str],
    ordinal: int,
    cfg: SliceAtlasConfig,
    atlas_shape: tuple[int, ...],
    atlas_orientation: str,
    atlas_resolution: list[float],
    atlas_version: str,
    axis: int,
) -> tuple[int, float | None]:
    axis_length = atlas_shape[axis]
    explicit_value = row.get("atlas_slice_index")
    whs_ap_value = row.get("whs_ap_mm")
    if whs_ap_value is not None and whs_ap_value.strip():
        if explicit_value is not None and explicit_value.strip():
            raise ValueError(
                f"Section {row['section_index']} has both whs_ap_mm and atlas_slice_index; specify only one."
            )
        _validate_whs_ap_atlas(cfg, atlas_shape, atlas_orientation, atlas_resolution, atlas_version, axis)
        try:
            requested_ap_mm = float(whs_ap_value)
        except ValueError as exc:
            raise ValueError(f"Section {row['section_index']} has invalid whs_ap_mm={whs_ap_value!r}.") from exc
        if not math.isfinite(requested_ap_mm):
            raise ValueError(f"Section {row['section_index']} requires a finite whs_ap_mm.")
        source_voxel = _WHS_SOURCE_AP_ORIGIN_VOXEL + requested_ap_mm / _WHS_SOURCE_VOXEL_SIZE_MM
        # BrainGlobe's ASR array reverses the source volume's posterior-origin AP axis.
        continuous_index = axis_length - 1 - source_voxel
        if not 0 <= continuous_index <= axis_length - 1:
            raise ValueError(f"Section {row['section_index']} WHS AP coordinate is outside the atlas AP range.")
        index = round(continuous_index)
        selected_source_voxel = axis_length - 1 - index
        selected_ap_mm = (selected_source_voxel - _WHS_SOURCE_AP_ORIGIN_VOXEL) * _WHS_SOURCE_VOXEL_SIZE_MM
        return index, selected_ap_mm
    if explicit_value is not None and explicit_value.strip():
        index = int(explicit_value)
    else:
        index = cfg.start_slice_index + ordinal * cfg.slice_index_step
    if index < 0 or index >= axis_length:
        raise ValueError(f"Atlas slice index {index} is outside the available range 0..{axis_length - 1}.")
    return index, None


def _validate_whs_ap_atlas(
    cfg: SliceAtlasConfig,
    atlas_shape: tuple[int, ...],
    atlas_orientation: str,
    atlas_resolution: list[float],
    atlas_version: str,
    axis: int,
) -> None:
    if cfg.atlas_name != "whs_sd_rat_39um" or cfg.anatomical_axis != "ap":
        raise ValueError("whs_ap_mm requires the AP axis of the whs_sd_rat_39um atlas.")
    if (
        atlas_version != "3.0"
        or atlas_orientation != "asr"
        or tuple(atlas_shape) != (_WHS_AP_AXIS_LENGTH, 512, 512)
        or axis != 0
        or len(atlas_resolution) != 3
        or not math.isfinite(float(atlas_resolution[axis]))
        or abs(float(atlas_resolution[axis]) - 39.0) > 0.5
    ):
        raise ValueError("whs_ap_mm requires the validated BrainGlobe v3.0 WHS rat atlas (asr, 1024 AP planes, 39 um).")


def _extract_slice(volume: np.ndarray, axis: int, index: int) -> np.ndarray:
    return np.take(volume, index, axis=axis)


def _section_source_path(row: dict[str, str], cfg: SliceAtlasConfig) -> Path:
    if cfg.section_source == "registration":
        return Path(row["crop_path_registration"])
    if cfg.section_source == "rgb":
        return Path(row["crop_path_rgb"])
    if cfg.section_source == "channel":
        if cfg.channel is None:
            raise ValueError("SliceAtlasConfig.channel is required when section_source='channel'.")
        channel_paths = json.loads(row["channel_paths"])
        key = f"ch{cfg.channel}"
        if key not in channel_paths:
            raise ValueError(f"Manifest row does not contain a path for {key}.")
        return Path(channel_paths[key])
    raise ValueError("section_source must be one of: 'registration', 'rgb', 'channel'.")


def _copy_section_image(source_path: Path, target_path: Path) -> None:
    image = np.asarray(imread(source_path))
    imwrite(target_path, image)


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y"}


def _read_manifest_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_manifest(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        if not rows:
            handle.write("section_index,atlas_slice_index,atlas_reference_path,atlas_annotation_path,section_source_path\n")
            return
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
