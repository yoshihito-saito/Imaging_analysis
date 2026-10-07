"""Preparation helpers for BrainGlobe atlas registration workflows."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageOps
from tifffile import imread, imwrite

from .pipeline import PipelineConfig, ProcessingResult, process_nd2_file


@dataclass(frozen=True)
class BrainGlobeExportConfig:
    """Configuration for exporting isolated sections for BrainGlobe workflows."""

    sample_id: str = "sample"
    atlas_name: str = "whs_sd_rat_39um"
    orientation: str | None = None
    registration_channel: int = 0
    signal_channels: Sequence[int] | None = None
    section_thickness_um: float | None = None
    section_interval_um: float | None = None
    start_z_um: float = 0.0
    pixel_size_x_um: float | None = None
    pixel_size_y_um: float | None = None
    include_in_stack: bool = True
    default_qc_status: str = "pending"
    default_qc_notes: str = ""
    capture_atlas_metadata: bool = True
    preview_max_dim: int | None = 4096
    keep_raw_channel_crops: bool = False
    write_rgb_crops: bool = False
    write_slide_diagnostics: bool = False
    review_thumbnail_max_dim: int = 320


@dataclass(frozen=True)
class BrainGlobeExportResult:
    """Paths produced by a BrainGlobe-preparation export run."""

    sample_dir: Path
    manifest_path: Path
    metadata_path: Path
    sections_rgb_dir: Path
    sections_registration_dir: Path
    sections_channels_dir: Path
    qc_dir: Path
    review_dir: Path
    slide_overlay_paths: list[Path]
    section_montage_path: Path
    processing_results: list[ProcessingResult]


def export_sections_for_brainglobe(
    paths: Sequence[str | Path],
    output_dir: str | Path,
    *,
    pipeline_config: PipelineConfig | None = None,
    export_config: BrainGlobeExportConfig | None = None,
) -> BrainGlobeExportResult:
    """Run section isolation and export a BrainGlobe-ready sample layout."""

    if not paths:
        raise ValueError("At least one ND2 path is required for BrainGlobe export.")

    export_cfg = export_config or BrainGlobeExportConfig()
    sample_dir = Path(output_dir) / export_cfg.sample_id
    sections_rgb_dir = sample_dir / "sections_rgb"
    sections_registration_dir = sample_dir / "sections_registration"
    sections_channels_dir = sample_dir / "sections_channels"
    review_dir = sample_dir / "qc" / "section_review"
    qc_dir = review_dir
    slide_outputs_dir = sample_dir / "slide_outputs"
    manifest_path = sample_dir / "section_manifest.csv"
    metadata_path = sample_dir / "sample_metadata.json"

    output_directories = [sections_registration_dir, sections_channels_dir, review_dir]
    if export_cfg.write_rgb_crops:
        output_directories.append(sections_rgb_dir)
    if export_cfg.write_slide_diagnostics or export_cfg.keep_raw_channel_crops:
        output_directories.append(slide_outputs_dir)
    for directory in output_directories:
        directory.mkdir(parents=True, exist_ok=True)

    # Slide order and within-slide left-to-right order define the global section sequence.
    pipeline_cfg = replace(
        pipeline_config or PipelineConfig(),
        save_raw_channel_crops=export_cfg.keep_raw_channel_crops,
        sort_mode="row_left_to_right",
        preview_max_dim=(
            pipeline_config.preview_max_dim
            if pipeline_config is not None and pipeline_config.preview_max_dim is not None
            else export_cfg.preview_max_dim
        ),
        write_rgb_crops=export_cfg.write_rgb_crops,
        collect_rgb_review_thumbnails=not export_cfg.write_rgb_crops,
        review_thumbnail_max_dim=export_cfg.review_thumbnail_max_dim,
    )
    processing_results: list[ProcessingResult] = []
    manifest_rows: list[dict[str, Any]] = []
    slide_overlay_paths: list[Path] = []
    review_items: list[Path | np.ndarray] = []
    next_index = 1

    ordered_paths = _numeric_slide_order(paths)
    for slide_number, path in enumerate(ordered_paths, start=1):
        result = process_nd2_file(
            path,
            slide_outputs_dir,
            config=pipeline_cfg,
            crop_output_dir=sections_rgb_dir,
            crop_start_index=next_index,
            crop_stem="section",
            crop_filename_template="{stem}{index:03d}.{extension}",
            channel_output_dir=sections_channels_dir,
            channel_export_channels=export_cfg.signal_channels,
            registration_output_dir=sections_registration_dir,
            registration_channel=export_cfg.registration_channel,
            write_diagnostics=export_cfg.write_slide_diagnostics,
        )
        processing_results.append(result)

        review_overlay_path = review_dir / f"slide{slide_number:03d}_detected_sections.png"
        review_preview = result.review_preview if result.review_preview is not None else result.merged_path
        if review_preview is None:
            raise RuntimeError("Export requires either an in-memory review preview or a saved merged preview.")
        _write_numbered_slide_overlay(
            review_preview,
            result.boxes,
            review_overlay_path,
            first_section_index=next_index,
            source_shape=result.detection_shape,
        )
        slide_overlay_paths.append(review_overlay_path)
        review_items.extend(result.review_thumbnails or result.crop_paths)

        manifest_rows.extend(
            _build_manifest_rows(
                result,
                global_start_index=next_index,
                slide_number=slide_number,
                sections_channels_dir=sections_channels_dir,
                sections_registration_dir=sections_registration_dir,
                export_config=export_cfg,
            )
        )
        next_index += len(result.boxes)

    section_montage_path = review_dir / "all_detected_sections.png"
    _write_section_montage(review_items, section_montage_path)
    _write_manifest(manifest_path, manifest_rows)
    _write_json(
        metadata_path,
        {
            "sample_id": export_cfg.sample_id,
            "atlas_name": export_cfg.atlas_name,
            "atlas_metadata": _capture_atlas_metadata(export_cfg.atlas_name) if export_cfg.capture_atlas_metadata else None,
            "orientation": export_cfg.orientation,
            "pipeline_config": asdict(pipeline_cfg),
            "export_config": asdict(export_cfg),
            "source_paths": [str(path) for path in ordered_paths],
            "slide_outputs": [str(result.output_dir) for result in processing_results]
            if export_cfg.write_slide_diagnostics or export_cfg.keep_raw_channel_crops
            else [],
            "review_outputs": {
                "slide_overlays": [str(path) for path in slide_overlay_paths],
                "section_montage": str(section_montage_path),
            },
        },
    )

    return BrainGlobeExportResult(
        sample_dir=sample_dir,
        manifest_path=manifest_path,
        metadata_path=metadata_path,
        sections_rgb_dir=sections_rgb_dir,
        sections_registration_dir=sections_registration_dir,
        sections_channels_dir=sections_channels_dir,
        qc_dir=qc_dir,
        review_dir=review_dir,
        slide_overlay_paths=slide_overlay_paths,
        section_montage_path=section_montage_path,
        processing_results=processing_results,
    )


def _numeric_slide_order(paths: Sequence[str | Path]) -> list[Path]:
    """Sort input slides naturally so 2.nd2 precedes 10.nd2."""

    def natural_key(path: str | Path) -> list[int | str]:
        return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", Path(path).name)]

    return sorted((Path(path) for path in paths), key=natural_key)


def _write_numbered_slide_overlay(
    merged_image: Path | np.ndarray,
    boxes: Sequence[Any],
    output_path: Path,
    *,
    first_section_index: int,
    source_shape: tuple[int, int] | None,
) -> None:
    source = imread(merged_image) if isinstance(merged_image, Path) else merged_image
    image = Image.fromarray(_rgb_uint8(source), mode="RGB")
    draw = ImageDraw.Draw(image)
    source_height, source_width = source_shape or (image.height, image.width)
    scale_y = image.height / max(1.0, float(source_height))
    scale_x = image.width / max(1.0, float(source_width))
    line_width = max(1, int(round(4 * max(scale_x, scale_y))))
    for offset, box in enumerate(boxes):
        x0 = int(round(box.x0 * scale_x))
        x1 = int(round(box.x1 * scale_x))
        y0 = int(round(box.y0 * scale_y))
        y1 = int(round(box.y1 * scale_y))
        draw.rectangle((x0, y0, x1, y1), outline=(255, 64, 64), width=line_width)
        draw.text((x0 + 8, y0 + 8), str(first_section_index + offset), fill=(255, 255, 0))
    image.save(output_path)


def _write_section_montage(crops: Sequence[Path | np.ndarray], output_path: Path) -> None:
    """Write a compact five-column visual review sheet without distorting crops."""

    columns = 5
    tile_width = 320
    tile_height = 240
    label_height = 28
    padding = 12
    rows = max(1, int(np.ceil(len(crops) / columns)))
    montage = Image.new(
        "RGB",
        (columns * (tile_width + padding) + padding, rows * (tile_height + label_height + padding) + padding),
        color=(28, 28, 28),
    )
    draw = ImageDraw.Draw(montage)

    for section_index, crop_source in enumerate(crops, start=1):
        tile_column = (section_index - 1) % columns
        tile_row = (section_index - 1) // columns
        x0 = padding + tile_column * (tile_width + padding)
        y0 = padding + tile_row * (tile_height + label_height + padding)
        crop_array = imread(crop_source) if isinstance(crop_source, Path) else crop_source
        crop = Image.fromarray(_rgb_uint8(crop_array), mode="RGB")
        preview = ImageOps.contain(crop, (tile_width, tile_height), method=Image.Resampling.LANCZOS)
        image_x = x0 + (tile_width - preview.width) // 2
        image_y = y0 + label_height + (tile_height - preview.height) // 2
        draw.text((x0, y0 + 5), str(section_index), fill=(255, 255, 0))
        montage.paste(preview, (image_x, image_y))

    montage.save(output_path)


def _rgb_uint8(image: Any) -> np.ndarray:
    array = np.asarray(image)
    if array.ndim == 2:
        array = np.repeat(array[..., None], 3, axis=-1)
    elif array.ndim == 3 and array.shape[-1] >= 3:
        array = array[..., :3]
    elif array.ndim == 3 and array.shape[0] >= 3:
        array = np.moveaxis(array[:3], 0, -1)
    else:
        raise ValueError("Review images must be grayscale or RGB-like arrays.")
    if array.dtype == np.uint8:
        return array
    finite = np.nan_to_num(array.astype(np.float32), nan=0.0, posinf=0.0, neginf=0.0)
    upper = float(np.percentile(finite, 99.8)) if finite.size else 0.0
    if upper <= 0:
        return np.zeros(finite.shape, dtype=np.uint8)
    return np.clip(finite / upper * 255.0, 0, 255).astype(np.uint8)


def _build_manifest_rows(
    result: ProcessingResult,
    *,
    global_start_index: int,
    slide_number: int,
    sections_channels_dir: Path,
    sections_registration_dir: Path,
    export_config: BrainGlobeExportConfig,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for offset, (box, channel_paths, registration_path) in enumerate(
        zip(result.boxes, result.channel_crop_paths, result.registration_crop_paths)
    ):
        section_index = global_start_index + offset
        rgb_path = result.crop_paths[offset] if offset < len(result.crop_paths) else ""
        channel_count = result.channel_count
        registration_channel = export_config.registration_channel
        if registration_channel < 0 or registration_channel >= channel_count:
            raise ValueError(
                f"registration_channel={registration_channel} is outside the available range 0..{channel_count - 1}."
            )

        raw_crop_path = result.raw_crop_paths[offset] if offset < len(result.raw_crop_paths) else ""

        pixel_size = _pixel_size_um(result, export_config)
        z_position_um = _z_position_um(section_index, export_config)
        rows.append(
            {
                "sample_id": export_config.sample_id,
                "atlas_name": export_config.atlas_name,
                "orientation": export_config.orientation,
                "source_file": str(result.input_path),
                "slide_number": slide_number,
                "slide_id": result.input_path.stem,
                "section_index": section_index,
                "slide_section_label": box.label,
                "crop_path_rgb": str(rgb_path),
                "crop_path_registration": str(registration_path),
                "raw_crop_path": str(raw_crop_path),
                "channel_count": channel_count,
                "channel_paths": json.dumps({f"ch{channel}": str(path) for channel, path in channel_paths.items()}),
                "registration_channel": registration_channel,
                "pixel_size_x_um": pixel_size["x"],
                "pixel_size_y_um": pixel_size["y"],
                "section_thickness_um": export_config.section_thickness_um,
                "section_interval_um": export_config.section_interval_um,
                "z_position_um": z_position_um,
                "include_in_stack": export_config.include_in_stack,
                "qc_status": export_config.default_qc_status,
                "qc_notes": export_config.default_qc_notes,
                **box.to_dict(),
            }
        )
    return rows


def _pixel_size_um(result: ProcessingResult, export_config: BrainGlobeExportConfig) -> dict[str, float | None]:
    voxel = result_metadata_value(result, "voxel_size_um") or {}
    return {
        "x": export_config.pixel_size_x_um if export_config.pixel_size_x_um is not None else voxel.get("x"),
        "y": export_config.pixel_size_y_um if export_config.pixel_size_y_um is not None else voxel.get("y"),
    }


def _z_position_um(section_index: int, export_config: BrainGlobeExportConfig) -> float | None:
    if export_config.section_interval_um is None:
        return None
    return export_config.start_z_um + (section_index - 1) * export_config.section_interval_um


def result_metadata_value(result: ProcessingResult, key: str) -> Any:
    if key in result.nd2_metadata:
        return result.nd2_metadata[key]
    if result.metadata_path is None or not result.metadata_path.exists():
        return None
    with result.metadata_path.open("r", encoding="utf-8") as handle:
        metadata = json.load(handle)
    nd2_metadata = metadata.get("nd2", {})
    return nd2_metadata.get(key)


def _capture_atlas_metadata(atlas_name: str) -> dict[str, Any] | None:
    try:
        from brainglobe_atlasapi.bg_atlas import BrainGlobeAtlas
    except ImportError:
        return None

    try:
        atlas = BrainGlobeAtlas(atlas_name)
    except Exception:
        return None

    return {
        "name": atlas_name,
        "resolution_um": list(getattr(atlas, "resolution", [])),
        "shape": list(getattr(atlas, "shape", [])),
        "orientation": getattr(atlas, "orientation", None),
    }


def _write_manifest(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        if not rows:
            handle.write(
                "sample_id,atlas_name,orientation,source_file,slide_number,slide_id,section_index,"
                "slide_section_label,crop_path_rgb,crop_path_registration,raw_crop_path,channel_count,"
                "channel_paths,registration_channel,pixel_size_x_um,pixel_size_y_um,section_thickness_um,"
                "section_interval_um,z_position_um,include_in_stack,qc_status,qc_notes,label,y0,y1,x0,x1,"
                "height,width,area,centroid_y,centroid_x\n"
            )
            return
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
