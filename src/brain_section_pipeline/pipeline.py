"""End-to-end ND2 processing pipeline."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from PIL import Image, ImageDraw
from tifffile import imwrite

from .crop import CropBox, detect_section_crops, save_crops, sort_crop_boxes
from .io import Nd2RegionReader, read_nd2_image
from .merge import DEFAULT_CHANNEL_COLORS, merge_channels


@dataclass
class PipelineConfig:
    """Configurable parameters for ND2 section cropping."""

    channel_colors: Sequence[Sequence[float]] = field(default_factory=lambda: DEFAULT_CHANNEL_COLORS)
    merge_channels: Sequence[int] | None = None
    percentiles: tuple[float, float] = (0.5, 99.8)
    mask_channel: int | None = 0
    min_area: int = 1_000_000
    margin: int = 250
    opening_radius: int = 2
    closing_iterations: int = 160
    threshold_method: str = "otsu"
    threshold_quantile: float = 0.90
    sort_mode: str = "row"
    row_tolerance: float | None = None
    final_box_padding: int = 32
    scene_index: int = 0
    position_index: int | None = None
    time_index: int = 0
    z_index: int | None = None
    z_projection: str = "max"
    output_extension: str = "tif"
    crop_output_mode: str = "rgb_direct"
    rgb_direct_channels: Sequence[int | None] = (2, 1, 0)
    write_rgb_crops: bool = True
    collect_rgb_review_thumbnails: bool = False
    review_thumbnail_max_dim: int = 320
    save_raw_channel_crops: bool = False
    preview_max_dim: int | None = None
    detection_downsample: int = 4
    detection_refinement_padding: int = 128


@dataclass(frozen=True)
class ProcessingResult:
    """Paths and crop boxes produced for one ND2 file."""

    input_path: Path
    output_dir: Path
    merged_path: Path | None
    overlay_path: Path | None
    manifest_path: Path | None
    metadata_path: Path | None
    crop_paths: list[Path]
    raw_crop_paths: list[Path]
    boxes: list[CropBox]
    detection_shape: tuple[int, int] | None = None
    channel_count: int = 0
    channel_crop_paths: list[dict[int, Path]] = field(default_factory=list)
    registration_crop_paths: list[Path] = field(default_factory=list)
    review_thumbnails: list[np.ndarray] = field(default_factory=list)
    review_preview: np.ndarray | None = None
    nd2_metadata: dict[str, Any] = field(default_factory=dict)


def process_nd2_file(
    path: str | Path,
    output_dir: str | Path,
    config: PipelineConfig | None = None,
    *,
    crop_output_dir: str | Path | None = None,
    crop_start_index: int = 1,
    crop_stem: str | None = None,
    crop_filename_template: str = "{stem}_section{index:03d}.{extension}",
    channel_output_dir: str | Path | None = None,
    channel_export_channels: Sequence[int] | None = None,
    registration_output_dir: str | Path | None = None,
    registration_channel: int | None = None,
    write_diagnostics: bool = True,
) -> ProcessingResult:
    """Read one ND2 file, merge channels, detect sections, and save crops."""

    cfg = config or PipelineConfig()
    input_path = Path(path)
    file_output_dir = Path(output_dir) / input_path.stem
    if write_diagnostics or cfg.save_raw_channel_crops:
        file_output_dir.mkdir(parents=True, exist_ok=True)

    if cfg.detection_downsample < 1:
        raise ValueError("detection_downsample must be >= 1.")

    if cfg.detection_downsample > 1:
        return _process_nd2_file_with_regions(
            input_path,
            file_output_dir,
            cfg,
            crop_output_dir=crop_output_dir,
            crop_start_index=crop_start_index,
            crop_stem=crop_stem,
            crop_filename_template=crop_filename_template,
            channel_output_dir=channel_output_dir,
            channel_export_channels=channel_export_channels,
            registration_output_dir=registration_output_dir,
            registration_channel=registration_channel,
            write_diagnostics=write_diagnostics,
        )

    nd2_image = _read_nd2(input_path, cfg)

    preview_source = _preview_source_image(nd2_image.data, cfg.preview_max_dim)
    rgb = merge_channels(
        preview_source,
        channel_colors=cfg.channel_colors,
        percentiles=cfg.percentiles,
        channels=cfg.merge_channels,
    )
    detection = _detect_sections(
        nd2_image.data if cfg.mask_channel is not None else rgb,
        cfg,
        image_is_rgb=cfg.mask_channel is None,
    )
    boxes = detection.boxes
    detection_threshold = detection.threshold

    merged_path = file_output_dir / f"{input_path.stem}_merged.tif"
    overlay_path = file_output_dir / f"{input_path.stem}_crops_overlay.png"
    metadata_path = file_output_dir / f"{input_path.stem}_metadata.json"
    manifest_path = file_output_dir / f"{input_path.stem}_crop_manifest.csv"
    crop_dir = Path(crop_output_dir) if crop_output_dir is not None else file_output_dir

    if write_diagnostics:
        imwrite(merged_path, rgb)
        _save_overlay(rgb, boxes, overlay_path, source_shape=nd2_image.data.shape[-2:])
    if cfg.write_rgb_crops and cfg.crop_output_mode == "rgb_direct":
        crop_paths = _save_rgb_direct_crops(
            nd2_image.data,
            boxes,
            crop_dir,
            stem=crop_stem or input_path.stem,
            extension=cfg.output_extension,
            start_index=crop_start_index,
            filename_template=crop_filename_template,
            rgb_channels=cfg.rgb_direct_channels,
        )
    elif cfg.write_rgb_crops:
        crop_source = _crop_output_image(nd2_image.data, rgb, cfg)
        crop_paths = save_crops(
            crop_source,
            boxes,
            crop_dir,
            stem=crop_stem or input_path.stem,
            extension=cfg.output_extension,
            start_index=crop_start_index,
            filename_template=crop_filename_template,
        )

    else:
        crop_paths = []

    raw_crop_paths: list[Path] = []
    if cfg.save_raw_channel_crops:
        raw_dir = file_output_dir / "raw_channel_crops"
        raw_crop_paths = save_crops(
            nd2_image.data,
            boxes,
            raw_dir,
            stem=input_path.stem,
            extension=cfg.output_extension,
        )

    channel_crop_paths, registration_crop_paths = _save_direct_channel_crops(
        nd2_image.data,
        boxes,
        channel_output_dir=channel_output_dir,
        channel_export_channels=channel_export_channels,
        registration_output_dir=registration_output_dir,
        registration_channel=registration_channel,
        extension=cfg.output_extension,
        start_index=crop_start_index,
    )

    review_thumbnails = (
        _collect_rgb_review_thumbnails(
            nd2_image.data,
            boxes,
            rgb_channels=cfg.rgb_direct_channels,
            max_dim=cfg.review_thumbnail_max_dim,
        )
        if cfg.collect_rgb_review_thumbnails
        else []
    )

    if write_diagnostics:
        _write_manifest(manifest_path, input_path, crop_paths, boxes, start_index=crop_start_index)
        _write_json(
            metadata_path,
            {
                "input_path": str(input_path),
                "config": asdict(cfg),
                "nd2": nd2_image.metadata,
                "sizes": nd2_image.sizes,
                "threshold": detection_threshold,
                "section_count": len(boxes),
            },
        )

    return ProcessingResult(
        input_path=input_path,
        output_dir=file_output_dir,
        merged_path=merged_path if write_diagnostics else None,
        overlay_path=overlay_path if write_diagnostics else None,
        manifest_path=manifest_path if write_diagnostics else None,
        metadata_path=metadata_path if write_diagnostics else None,
        crop_paths=crop_paths,
        raw_crop_paths=raw_crop_paths,
        boxes=boxes,
        detection_shape=tuple(int(value) for value in nd2_image.data.shape[-2:]),
        channel_count=int(nd2_image.data.shape[0]),
        channel_crop_paths=channel_crop_paths,
        registration_crop_paths=registration_crop_paths,
        review_thumbnails=review_thumbnails,
        review_preview=rgb if cfg.collect_rgb_review_thumbnails else None,
        nd2_metadata=nd2_image.metadata,
    )


def _read_nd2(input_path: Path, cfg: PipelineConfig, *, downsample: int = 1):
    return read_nd2_image(
        input_path,
        scene_index=cfg.scene_index,
        position_index=cfg.position_index,
        time_index=cfg.time_index,
        z_index=cfg.z_index,
        z_projection=cfg.z_projection,
        downsample=downsample,
    )


def _process_nd2_file_with_regions(
    input_path: Path,
    file_output_dir: Path,
    cfg: PipelineConfig,
    *,
    crop_output_dir: str | Path | None,
    crop_start_index: int,
    crop_stem: str | None,
    crop_filename_template: str,
    channel_output_dir: str | Path | None,
    channel_export_channels: Sequence[int] | None,
    registration_output_dir: str | Path | None,
    registration_channel: int | None,
    write_diagnostics: bool,
) -> ProcessingResult:
    coarse_image = _read_nd2(input_path, cfg, downsample=cfg.detection_downsample)
    coarse_detection = _detect_sections(coarse_image.data, cfg, downsample=cfg.detection_downsample)
    preview_source = _preview_source_image(coarse_image.data, cfg.preview_max_dim)
    rgb_preview = merge_channels(
        preview_source,
        channel_colors=cfg.channel_colors,
        percentiles=cfg.percentiles,
        channels=cfg.merge_channels,
    )
    merged_path = file_output_dir / f"{input_path.stem}_merged.tif"
    overlay_path = file_output_dir / f"{input_path.stem}_crops_overlay.png"
    metadata_path = file_output_dir / f"{input_path.stem}_metadata.json"
    manifest_path = file_output_dir / f"{input_path.stem}_crop_manifest.csv"
    crop_dir = Path(crop_output_dir) if crop_output_dir is not None else file_output_dir
    channel_root = Path(channel_output_dir) if channel_output_dir is not None else None
    registration_root = Path(registration_output_dir) if registration_output_dir is not None else None
    crop_paths: list[Path] = []
    raw_crop_paths: list[Path] = []
    channel_crop_paths: list[dict[int, Path]] = []
    registration_crop_paths: list[Path] = []
    review_thumbnails: list[np.ndarray] = []

    with Nd2RegionReader(
        input_path,
        scene_index=cfg.scene_index,
        position_index=cfg.position_index,
        time_index=cfg.time_index,
        z_index=cfg.z_index,
        z_projection=cfg.z_projection,
    ) as reader:
        image_shape = reader.image_shape
        channel_count = reader.channel_count
        if cfg.mask_channel is not None and not 0 <= cfg.mask_channel < channel_count:
            raise ValueError(f"mask_channel={cfg.mask_channel} is outside the available channel range.")
        channels = list(range(channel_count)) if channel_export_channels is None else sorted(set(channel_export_channels))
        if channel_root is not None and any(channel < 0 or channel >= channel_count for channel in channels):
            raise ValueError("channel_export_channels contains out-of-range channels.")
        if registration_root is not None and registration_channel is None:
            raise ValueError("registration_channel is required when registration_output_dir is provided.")
        if registration_channel is not None and not 0 <= registration_channel < channel_count:
            raise ValueError(f"registration_channel={registration_channel} is outside the available channel range.")

        boxes = _refine_coarse_boxes_from_reader(reader, coarse_detection.boxes, config=cfg)
        if write_diagnostics:
            imwrite(merged_path, rgb_preview)
            _save_overlay(rgb_preview, boxes, overlay_path, source_shape=image_shape)

        for section_index, box in enumerate(boxes, start=crop_start_index):
            output_channels = set(channels if channel_root is not None else ())
            if registration_root is not None and registration_channel is not None:
                output_channels.add(registration_channel)
            if cfg.write_rgb_crops:
                output_channels.add(0)
                output_channels.update(channel for channel in cfg.rgb_direct_channels if channel is not None)
            if cfg.save_raw_channel_crops or (cfg.write_rgb_crops and cfg.crop_output_mode != "rgb_direct"):
                output_channels.update(range(channel_count))
            if any(channel < 0 or channel >= channel_count for channel in output_channels):
                raise ValueError("RGB channel selection contains out-of-range channels.")

            retained: dict[int, np.ndarray] = {}
            section_channel_paths: dict[int, Path] = {}
            for channel in sorted(output_channels):
                plane = reader.read_region(box.y0, box.y1, box.x0, box.x1, channel=channel)
                if channel_root is not None and channel in channels:
                    channel_path = channel_root / f"ch{channel}" / f"section{section_index:03d}.{cfg.output_extension}"
                    channel_path.parent.mkdir(parents=True, exist_ok=True)
                    imwrite(channel_path, plane)
                    section_channel_paths[channel] = channel_path
                if registration_root is not None and channel == registration_channel:
                    registration_path = registration_root / f"section{section_index:03d}.{cfg.output_extension}"
                    registration_path.parent.mkdir(parents=True, exist_ok=True)
                    imwrite(registration_path, plane)
                    registration_crop_paths.append(registration_path)
                if cfg.write_rgb_crops or cfg.save_raw_channel_crops:
                    retained[channel] = plane
            channel_crop_paths.append(section_channel_paths)

            if cfg.write_rgb_crops:
                if cfg.crop_output_mode == "rgb_direct":
                    if len(cfg.rgb_direct_channels) != 3:
                        raise ValueError("rgb_direct_channels must contain exactly 3 channel indices.")
                    reference = next(iter(retained.values()))
                    crop_image = np.zeros(reference.shape + (3,), dtype=reference.dtype)
                    for rgb_index, channel in enumerate(cfg.rgb_direct_channels):
                        if channel is not None:
                            crop_image[..., rgb_index] = retained[channel]
                elif cfg.crop_output_mode == "raw_stack":
                    crop_image = np.stack([retained[channel] for channel in range(channel_count)])
                elif cfg.crop_output_mode == "merged_rgb":
                    crop_image = merge_channels(
                        np.stack([retained[channel] for channel in range(channel_count)]),
                        channel_colors=cfg.channel_colors,
                        percentiles=cfg.percentiles,
                        channels=cfg.merge_channels,
                    )
                else:
                    raise ValueError("crop_output_mode must be one of: 'rgb_direct', 'raw_stack', 'merged_rgb'.")
                crop_path = crop_dir / crop_filename_template.format(
                    stem=crop_stem or input_path.stem,
                    index=section_index,
                    extension=cfg.output_extension,
                )
                crop_path.parent.mkdir(parents=True, exist_ok=True)
                imwrite(crop_path, crop_image)
                crop_paths.append(crop_path)

            if cfg.save_raw_channel_crops:
                raw_dir = file_output_dir / "raw_channel_crops"
                raw_dir.mkdir(parents=True, exist_ok=True)
                raw_path = raw_dir / f"{input_path.stem}_section{section_index - crop_start_index + 1:03d}.{cfg.output_extension}"
                imwrite(raw_path, np.stack([retained[channel] for channel in range(channel_count)]))
                raw_crop_paths.append(raw_path)

            if cfg.collect_rgb_review_thumbnails:
                coarse_box = _box_to_coarse(box, cfg.detection_downsample, coarse_image.data.shape[-2:])
                y_slice, x_slice = coarse_box.as_slices()
                review_rgb = _raw_channels_to_rgb(coarse_image.data[:, y_slice, x_slice], cfg.rgb_direct_channels)
                review_thumbnails.append(_thumbnail_uint8(review_rgb, max_dim=cfg.review_thumbnail_max_dim))

        if write_diagnostics:
            _write_manifest(manifest_path, input_path, crop_paths, boxes, start_index=crop_start_index)
            _write_json(
                metadata_path,
                {
                    "input_path": str(input_path),
                    "config": asdict(cfg),
                    "nd2": reader.metadata,
                    "sizes": reader.sizes,
                    "threshold": coarse_detection.threshold,
                    "section_count": len(boxes),
                },
            )
        metadata = reader.metadata

    return ProcessingResult(
        input_path=input_path,
        output_dir=file_output_dir,
        merged_path=merged_path if write_diagnostics else None,
        overlay_path=overlay_path if write_diagnostics else None,
        manifest_path=manifest_path if write_diagnostics else None,
        metadata_path=metadata_path if write_diagnostics else None,
        crop_paths=crop_paths,
        raw_crop_paths=raw_crop_paths,
        boxes=boxes,
        detection_shape=image_shape,
        channel_count=channel_count,
        channel_crop_paths=channel_crop_paths,
        registration_crop_paths=registration_crop_paths,
        review_thumbnails=review_thumbnails,
        review_preview=rgb_preview if cfg.collect_rgb_review_thumbnails else None,
        nd2_metadata=metadata,
    )


def _box_to_coarse(box: CropBox, scale: int, coarse_shape: tuple[int, int]) -> CropBox:
    height, width = coarse_shape
    return CropBox(
        y0=max(0, box.y0 // scale),
        y1=min(height, int(np.ceil(box.y1 / scale))),
        x0=max(0, box.x0 // scale),
        x1=min(width, int(np.ceil(box.x1 / scale))),
        label=box.label,
        area=box.area,
        centroid_y=box.centroid_y / scale,
        centroid_x=box.centroid_x / scale,
    )


def _refine_coarse_boxes_from_reader(
    reader: Nd2RegionReader,
    coarse_boxes: Sequence[CropBox],
    *,
    config: PipelineConfig,
) -> list[CropBox]:
    image_shape = reader.image_shape
    refined: list[CropBox] = []
    for coarse_box in coarse_boxes:
        mapped_box = _scale_box(coarse_box, downsample=config.detection_downsample, image_shape=image_shape)
        search_box = _expand_box(mapped_box, padding=config.detection_refinement_padding, image_shape=image_shape)
        if config.mask_channel is None:
            local_image = np.stack(
                [
                    reader.read_region(search_box.y0, search_box.y1, search_box.x0, search_box.x1, channel=channel)
                    for channel in range(reader.channel_count)
                ]
            )
        else:
            local_image = reader.read_region(
                search_box.y0,
                search_box.y1,
                search_box.x0,
                search_box.x1,
                channel=config.mask_channel,
            )
        local_detection = _detect_sections(local_image, config, apply_final_padding=False)
        local_boxes = [_translate_box(box, y_offset=search_box.y0, x_offset=search_box.x0) for box in local_detection.boxes]
        refined.append(_best_refinement_box(local_boxes, mapped_box))

    padded = [_expand_box(box, padding=config.final_box_padding, image_shape=image_shape) for box in refined]
    return sort_crop_boxes(
        padded,
        image_shape=image_shape,
        mode=config.sort_mode,  # type: ignore[arg-type]
        row_tolerance=config.row_tolerance,
    )


def _detect_sections(
    image: np.ndarray,
    cfg: PipelineConfig,
    *,
    downsample: int = 1,
    image_is_rgb: bool = False,
    apply_final_padding: bool = True,
):
    scale = max(1, int(downsample))
    if cfg.mask_channel is None and not image_is_rgb:
        detection_input = merge_channels(
            image,
            channel_colors=cfg.channel_colors,
            percentiles=cfg.percentiles,
            channels=cfg.merge_channels,
        )
    else:
        detection_input = image
    return detect_section_crops(
        detection_input,
        mask_channel=cfg.mask_channel,
        min_area=max(1, int(np.ceil(cfg.min_area / float(scale * scale)))),
        margin=int(np.ceil(cfg.margin / float(scale))),
        opening_radius=max(0, int(np.ceil(cfg.opening_radius / float(scale)))),
        closing_iterations=max(0, int(np.ceil(cfg.closing_iterations / float(scale)))),
        threshold_method=cfg.threshold_method,  # type: ignore[arg-type]
        threshold_quantile=cfg.threshold_quantile,
        sort_mode=cfg.sort_mode,  # type: ignore[arg-type]
        row_tolerance=None if cfg.row_tolerance is None else cfg.row_tolerance / float(scale),
        final_box_padding=cfg.final_box_padding if apply_final_padding and scale == 1 else 0,
    )


def _refine_coarse_boxes(
    full_image: np.ndarray,
    coarse_boxes: Sequence[CropBox],
    *,
    config: PipelineConfig,
    downsample: int,
) -> list[CropBox]:
    """Recover full-resolution section bounds around coarse detection candidates."""

    image_shape = tuple(int(value) for value in full_image.shape[-2:])
    refined: list[CropBox] = []
    for coarse_box in coarse_boxes:
        mapped_box = _scale_box(coarse_box, downsample=downsample, image_shape=image_shape)
        search_box = _expand_box(mapped_box, padding=config.detection_refinement_padding, image_shape=image_shape)
        local_image = full_image[..., search_box.y0 : search_box.y1, search_box.x0 : search_box.x1]
        local_detection = _detect_sections(local_image, config, apply_final_padding=False)
        local_boxes = [_translate_box(box, y_offset=search_box.y0, x_offset=search_box.x0) for box in local_detection.boxes]
        refined.append(_best_refinement_box(local_boxes, mapped_box))

    padded = [_expand_box(box, padding=config.final_box_padding, image_shape=image_shape) for box in refined]
    return sort_crop_boxes(
        padded,
        image_shape=image_shape,
        mode=config.sort_mode,  # type: ignore[arg-type]
        row_tolerance=config.row_tolerance,
    )


def _scale_box(box: CropBox, *, downsample: int, image_shape: tuple[int, int]) -> CropBox:
    scale = int(downsample)
    height, width = image_shape
    return CropBox(
        y0=max(0, box.y0 * scale),
        y1=min(height, box.y1 * scale),
        x0=max(0, box.x0 * scale),
        x1=min(width, box.x1 * scale),
        label=box.label,
        area=box.area * scale * scale,
        centroid_y=box.centroid_y * scale,
        centroid_x=box.centroid_x * scale,
    )


def _expand_box(box: CropBox, *, padding: int, image_shape: tuple[int, int]) -> CropBox:
    height, width = image_shape
    return CropBox(
        y0=max(0, box.y0 - padding),
        y1=min(height, box.y1 + padding),
        x0=max(0, box.x0 - padding),
        x1=min(width, box.x1 + padding),
        label=box.label,
        area=box.area,
        centroid_y=box.centroid_y,
        centroid_x=box.centroid_x,
    )


def _translate_box(box: CropBox, *, y_offset: int, x_offset: int) -> CropBox:
    return CropBox(
        y0=box.y0 + y_offset,
        y1=box.y1 + y_offset,
        x0=box.x0 + x_offset,
        x1=box.x1 + x_offset,
        label=box.label,
        area=box.area,
        centroid_y=box.centroid_y + y_offset,
        centroid_x=box.centroid_x + x_offset,
    )


def _best_refinement_box(candidates: Sequence[CropBox], mapped_box: CropBox) -> CropBox:
    if not candidates:
        return mapped_box

    def score(candidate: CropBox) -> tuple[float, float]:
        intersection = _box_intersection_area(candidate, mapped_box)
        union = candidate.height * candidate.width + mapped_box.height * mapped_box.width - intersection
        iou = intersection / max(1, union)
        center_distance = float(np.hypot(candidate.centroid_y - mapped_box.centroid_y, candidate.centroid_x - mapped_box.centroid_x))
        return iou, -center_distance

    return max(candidates, key=score)


def _box_intersection_area(first: CropBox, second: CropBox) -> int:
    y0 = max(first.y0, second.y0)
    y1 = min(first.y1, second.y1)
    x0 = max(first.x0, second.x0)
    x1 = min(first.x1, second.x1)
    return max(0, y1 - y0) * max(0, x1 - x0)


def process_selected_files(
    paths: Sequence[str | Path],
    output_dir: str | Path,
    config: PipelineConfig | None = None,
    *,
    continuous_crop_numbering: bool = True,
) -> list[ProcessingResult]:
    """Run the pipeline for selected ND2 files."""

    results: list[ProcessingResult] = []
    next_index = 1
    for path in paths:
        if continuous_crop_numbering:
            result = process_nd2_file(
                path,
                output_dir,
                config=config,
                crop_output_dir=output_dir,
                crop_start_index=next_index,
                crop_stem="section",
                crop_filename_template="{stem}{index:03d}.{extension}",
            )
        else:
            result = process_nd2_file(path, output_dir, config=config)
        results.append(result)
        next_index += len(result.boxes)
    return results


def _crop_output_image(raw_channels: np.ndarray, rgb_preview: np.ndarray, cfg: PipelineConfig) -> np.ndarray:
    if cfg.crop_output_mode == "rgb_direct":
        return _raw_channels_to_rgb(raw_channels, cfg.rgb_direct_channels)
    if cfg.crop_output_mode == "raw_stack":
        return raw_channels
    if cfg.crop_output_mode == "merged_rgb":
        return rgb_preview
    raise ValueError("crop_output_mode must be one of: 'rgb_direct', 'raw_stack', 'merged_rgb'.")


def _raw_channels_to_rgb(
    image: np.ndarray,
    rgb_channels: Sequence[int | None] = (2, 1, 0),
) -> np.ndarray:
    if len(rgb_channels) != 3:
        raise ValueError("rgb_direct_channels must contain exactly 3 channel indices for R, G, and B.")

    array = np.asarray(image)
    if array.ndim != 3 or array.shape[0] > 8:
        raise ValueError("rgb_direct crop output requires channel-first image data.")

    rgb = np.zeros(array.shape[1:] + (3,), dtype=array.dtype)
    for rgb_index, channel_index in enumerate(rgb_channels):
        if channel_index is None:
            continue
        if channel_index < 0 or channel_index >= array.shape[0]:
            raise ValueError(f"rgb_direct channel index {channel_index} is outside the available channel range.")
        rgb[..., rgb_index] = array[channel_index]
    return rgb


def _save_rgb_direct_crops(
    raw_channels: np.ndarray,
    boxes: list[CropBox],
    output_dir: str | Path,
    *,
    stem: str,
    extension: str,
    start_index: int,
    filename_template: str,
    rgb_channels: Sequence[int | None],
) -> list[Path]:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for index, box in enumerate(boxes, start=start_index):
        y_slice, x_slice = box.as_slices()
        crop = np.asarray(raw_channels)[..., y_slice, x_slice]
        rgb_crop = _raw_channels_to_rgb(crop, rgb_channels)
        filename = filename_template.format(stem=stem, index=index, extension=extension)
        path = out_dir / filename
        imwrite(path, rgb_crop)
        paths.append(path)
    return paths


def _save_direct_channel_crops(
    raw_channels: np.ndarray,
    boxes: list[CropBox],
    *,
    channel_output_dir: str | Path | None,
    channel_export_channels: Sequence[int] | None,
    registration_output_dir: str | Path | None,
    registration_channel: int | None,
    extension: str,
    start_index: int,
) -> tuple[list[dict[int, Path]], list[Path]]:
    """Write final channel outputs directly from the in-memory ND2 array."""

    if channel_output_dir is None and registration_output_dir is None:
        return [], []

    array = np.asarray(raw_channels)
    if array.ndim != 3 or array.shape[0] > 8:
        raise ValueError("Direct channel export requires channel-first image data.")
    channel_count = int(array.shape[0])
    channels = list(range(channel_count)) if channel_export_channels is None else sorted(set(channel_export_channels))
    invalid_channels = [channel for channel in channels if channel < 0 or channel >= channel_count]
    if invalid_channels:
        raise ValueError(f"channel_export_channels contains out-of-range channels: {invalid_channels}")
    if registration_output_dir is not None and registration_channel is None:
        raise ValueError("registration_channel is required when registration_output_dir is provided.")
    if registration_channel is not None and not 0 <= registration_channel < channel_count:
        raise ValueError(f"registration_channel={registration_channel} is outside the available range 0..{channel_count - 1}.")

    channel_root = Path(channel_output_dir) if channel_output_dir is not None else None
    registration_root = Path(registration_output_dir) if registration_output_dir is not None else None
    if channel_root is not None:
        for channel in channels:
            (channel_root / f"ch{channel}").mkdir(parents=True, exist_ok=True)
    if registration_root is not None:
        registration_root.mkdir(parents=True, exist_ok=True)

    channel_paths: list[dict[int, Path]] = []
    registration_paths: list[Path] = []
    for section_index, box in enumerate(boxes, start=start_index):
        y_slice, x_slice = box.as_slices()
        crop = array[:, y_slice, x_slice]
        section_channel_paths: dict[int, Path] = {}
        if channel_root is not None:
            for channel in channels:
                channel_path = channel_root / f"ch{channel}" / f"section{section_index:03d}.{extension}"
                imwrite(channel_path, crop[channel])
                section_channel_paths[channel] = channel_path
        channel_paths.append(section_channel_paths)
        if registration_root is not None and registration_channel is not None:
            registration_path = registration_root / f"section{section_index:03d}.{extension}"
            imwrite(registration_path, crop[registration_channel])
            registration_paths.append(registration_path)

    return channel_paths, registration_paths


def _collect_rgb_review_thumbnails(
    raw_channels: np.ndarray,
    boxes: list[CropBox],
    *,
    rgb_channels: Sequence[int | None],
    max_dim: int,
) -> list[np.ndarray]:
    thumbnails: list[np.ndarray] = []
    for box in boxes:
        y_slice, x_slice = box.as_slices()
        rgb_crop = _raw_channels_to_rgb(np.asarray(raw_channels)[..., y_slice, x_slice], rgb_channels)
        thumbnails.append(_thumbnail_uint8(rgb_crop, max_dim=max_dim))
    return thumbnails


def _thumbnail_uint8(image: np.ndarray, *, max_dim: int) -> np.ndarray:
    array = np.nan_to_num(np.asarray(image, dtype=np.float32), nan=0.0, posinf=0.0, neginf=0.0)
    high = float(np.percentile(array, 99.8)) if array.size else 0.0
    scaled = np.zeros(array.shape, dtype=np.uint8) if high <= 0 else np.clip(array / high * 255.0, 0, 255).astype(np.uint8)
    if max_dim <= 0 or max(scaled.shape[:2]) <= max_dim:
        return scaled
    thumbnail = Image.fromarray(scaled, mode="RGB")
    thumbnail.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
    return np.asarray(thumbnail)


def _preview_source_image(image: np.ndarray, preview_max_dim: int | None) -> np.ndarray:
    if preview_max_dim is None or preview_max_dim <= 0:
        return image

    array = np.asarray(image)
    if array.ndim == 2:
        height, width = array.shape
    elif array.ndim == 3 and array.shape[0] <= 8:
        height, width = array.shape[1:]
    elif array.ndim == 3 and array.shape[-1] <= 8:
        height, width = array.shape[:2]
    else:
        return image

    max_dim = max(height, width)
    if max_dim <= preview_max_dim:
        return image

    step = int(np.ceil(max_dim / float(preview_max_dim)))
    if array.ndim == 2:
        return array[::step, ::step]
    if array.shape[0] <= 8:
        return array[:, ::step, ::step]
    return array[::step, ::step, :]


def _save_overlay(
    rgb: np.ndarray,
    boxes: list[CropBox],
    output_path: Path,
    *,
    source_shape: tuple[int, int] | None = None,
) -> None:
    image = Image.fromarray(rgb.astype(np.uint8), mode="RGB")
    draw = ImageDraw.Draw(image)
    if source_shape is None:
        scale_y = 1.0
        scale_x = 1.0
    else:
        scale_y = rgb.shape[0] / max(1.0, float(source_shape[0]))
        scale_x = rgb.shape[1] / max(1.0, float(source_shape[1]))
    for index, box in enumerate(boxes, start=1):
        x0 = int(round(box.x0 * scale_x))
        x1 = int(round(box.x1 * scale_x))
        y0 = int(round(box.y0 * scale_y))
        y1 = int(round(box.y1 * scale_y))
        line_width = max(1, int(round(4 * max(scale_x, scale_y))))
        draw.rectangle((x0, y0, x1, y1), outline=(255, 64, 64), width=line_width)
        draw.text((x0 + 8, y0 + 8), str(index), fill=(255, 255, 0))
    image.save(output_path)


def _write_manifest(
    path: Path,
    input_path: Path,
    crop_paths: list[Path],
    boxes: list[CropBox],
    *,
    start_index: int = 1,
) -> None:
    rows = []
    for index, box in enumerate(boxes, start=start_index):
        offset = index - start_index
        crop_path = crop_paths[offset] if offset < len(crop_paths) else ""
        rows.append(
            {
                "input_path": str(input_path),
                "crop_path": str(crop_path),
                **box.to_dict(index=index),
            }
        )
    with path.open("w", newline="", encoding="utf-8") as handle:
        if not rows:
            handle.write("input_path,crop_path,section_index,label,y0,y1,x0,x1,height,width,area,centroid_y,centroid_x\n")
            return
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, default=str)
