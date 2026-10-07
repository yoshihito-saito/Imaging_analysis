import subprocess

import csv
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image
from tifffile import imread
from tifffile import imwrite

from brain_section_pipeline import select_nd2_files_dialog
from brain_section_pipeline.crop import CropBox, crop_sections, detect_section_crops, save_crops, sort_crop_boxes
from brain_section_pipeline.io import Nd2Image, Nd2RegionReader
from brain_section_pipeline.export import (
    BrainGlobeExportConfig,
    BrainGlobeExportResult,
    _capture_atlas_metadata,
    export_sections_for_brainglobe,
)
from brain_section_pipeline.merge import merge_channels, robust_scale
from brain_section_pipeline.pipeline import (
    PipelineConfig,
    ProcessingResult,
    _preview_source_image,
    _raw_channels_to_rgb,
    _save_direct_channel_crops,
    _save_rgb_direct_crops,
    process_nd2_file,
)
from brain_section_pipeline.brainreg_runner import BrainRegConfig, prepare_brainreg_run, run_prepared_brainreg
from brain_section_pipeline.stack import StackBuildConfig, build_stack_from_manifest
from brain_section_pipeline.atlas_summary import AtlasSummaryConfig, summarize_registered_slices_by_region
from brain_section_pipeline.atlas_indexing import (
    AtlasIndexSuggestionConfig,
    ap_mm_to_atlas_index,
    atlas_native_ap_mm_to_coordinate_ap_mm,
    atlas_index_to_ap_mm,
    coordinate_ap_mm_to_atlas_native_ap_mm,
    export_selected_atlas_previews,
    suggest_atlas_indices,
)
from brain_section_pipeline.qc import SliceAtlasQcConfig, generate_slice_atlas_qc
import brain_section_pipeline.atlas_indexing as atlas_indexing_module
import brain_section_pipeline.pipeline as pipeline_module
import brain_section_pipeline.slice_registration as slice_registration_module
import brain_section_pipeline.slice_atlas as slice_atlas_module
import brain_section_pipeline.workflow as workflow_module
from brain_section_pipeline.slice_registration import SliceRegistrationConfig, register_slices_to_atlas
from brain_section_pipeline.slice_atlas import SliceAtlasConfig, prepare_slice_atlas_inputs


def test_file_dialog_helper_is_exported_without_opening_gui():
    assert callable(select_nd2_files_dialog)


def test_robust_scale_handles_nan_and_inf():
    image = np.array([[0.0, 1.0], [np.nan, np.inf]], dtype=np.float32)

    scaled = robust_scale(image, percentiles=(0, 100))

    assert np.isfinite(scaled).all()
    assert scaled.min() >= 0.0
    assert scaled.max() <= 1.0


def test_merge_channels_returns_rgb_uint8_with_invalid_values():
    image = np.zeros((2, 20, 30), dtype=np.float32)
    image[0, 2:10, 3:12] = 100
    image[1, 8:15, 10:22] = 200
    image[0, 0, 0] = np.nan
    image[1, 1, 1] = np.inf

    rgb = merge_channels(image, percentiles=(0, 99))

    assert rgb.shape == (20, 30, 3)
    assert rgb.dtype == np.uint8
    assert np.isfinite(rgb).all()
    assert rgb.max() > 0


def test_detect_section_crops_finds_and_orders_sections():
    image = np.zeros((1, 220, 420), dtype=np.float32)
    image[0, 20:90, 30:120] = 1.0
    image[0, 110:190, 240:360] = 1.0
    image[0, 0, 0] = np.nan

    result = detect_section_crops(
        image,
        min_area=1_000,
        margin=5,
        opening_radius=0,
        closing_iterations=0,
        sort_mode="row",
    )

    assert len(result.boxes) == 2
    assert result.boxes[0].centroid_y < result.boxes[1].centroid_y
    crops = crop_sections(image[0], result.boxes)
    assert crops[0].shape == (80, 100)
    assert crops[1].shape == (90, 130)


def test_detection_plane_sanitizes_selected_channel_only(monkeypatch):
    import brain_section_pipeline.crop as crop_module

    seen_shapes = []

    def fake_sanitize(array, fill_value=0.0):
        seen_shapes.append(np.asarray(array).shape)
        return np.asarray(array, dtype=np.float32)

    monkeypatch.setattr(crop_module, "sanitize_array", fake_sanitize)

    image = np.zeros((4, 20, 30), dtype=np.uint16)
    plane = crop_module._detection_plane(image, mask_channel=2)

    assert plane.shape == (20, 30)
    assert seen_shapes == [(20, 30)]


def test_detect_section_crops_drops_nested_components_after_margin():
    image = np.zeros((1, 220, 260), dtype=np.float32)
    image[0, 20:180, 20:220] = 1.0
    image[0, 80:120, 80:140] = 0.0
    image[0, 85:115, 90:130] = 2.0

    result = detect_section_crops(
        image,
        min_area=100,
        margin=20,
        opening_radius=0,
        closing_iterations=0,
        threshold_method="quantile",
        threshold_quantile=0.10,
    )

    assert len(result.boxes) == 1


def test_detect_section_crops_merges_close_split_fragments():
    image = np.zeros((1, 180, 260), dtype=np.float32)
    image[0, 30:140, 60:170] = 1.0
    image[0, 55:120, 35:55] = 1.0

    result = detect_section_crops(
        image,
        min_area=200,
        margin=0,
        opening_radius=0,
        closing_iterations=0,
        threshold_method="quantile",
        threshold_quantile=0.5,
        merge_box_gap=8,
    )

    assert len(result.boxes) == 1
    box = result.boxes[0]
    assert box.x0 == 35
    assert box.x1 == 170


def test_detect_section_crops_does_not_merge_clearly_separate_sections():
    image = np.zeros((1, 180, 320), dtype=np.float32)
    image[0, 30:140, 20:120] = 1.0
    image[0, 30:140, 180:280] = 1.0

    result = detect_section_crops(
        image,
        min_area=200,
        margin=0,
        opening_radius=0,
        closing_iterations=0,
        threshold_method="quantile",
        threshold_quantile=0.5,
        merge_box_gap=8,
    )

    assert len(result.boxes) == 2


def test_detect_section_crops_does_not_merge_similar_sections_after_margin_expansion():
    image = np.zeros((1, 220, 320), dtype=np.float32)
    image[0, 40:140, 30:120] = 1.0
    image[0, 40:140, 145:235] = 1.0

    result = detect_section_crops(
        image,
        min_area=200,
        margin=20,
        opening_radius=0,
        closing_iterations=0,
        threshold_method="quantile",
        threshold_quantile=0.5,
        merge_box_gap=10,
    )

    assert len(result.boxes) == 2


def test_detect_section_crops_can_keep_margin_overlap_without_merging_equal_slices():
    image = np.zeros((1, 240, 360), dtype=np.float32)
    image[0, 40:140, 25:105] = 1.0
    image[0, 45:145, 115:195] = 1.0

    result = detect_section_crops(
        image,
        min_area=200,
        margin=12,
        opening_radius=0,
        closing_iterations=0,
        threshold_method="quantile",
        threshold_quantile=0.5,
        merge_box_gap=8,
    )

    assert len(result.boxes) == 2


def test_detect_section_crops_merges_moderately_smaller_fragment_companion():
    image = np.zeros((1, 220, 320), dtype=np.float32)
    image[0, 40:145, 90:180] = 1.0
    image[0, 45:140, 182:245] = 1.0

    result = detect_section_crops(
        image,
        min_area=200,
        margin=0,
        opening_radius=0,
        closing_iterations=0,
        threshold_method="quantile",
        threshold_quantile=0.5,
        merge_box_gap=6,
    )

    assert len(result.boxes) == 1


def test_detect_section_crops_final_padding_expands_and_clamps_boxes():
    image = np.zeros((1, 80, 100), dtype=np.float32)
    image[0, 5:20, 6:18] = 1.0

    result = detect_section_crops(
        image,
        min_area=10,
        margin=0,
        opening_radius=0,
        closing_iterations=0,
        threshold_method="quantile",
        threshold_quantile=0.5,
        merge_box_fragments=False,
        final_box_padding=8,
    )

    assert len(result.boxes) == 1
    box = result.boxes[0]
    assert box.y0 == 0
    assert box.x0 == 0
    assert box.y1 == 28
    assert box.x1 == 26


def test_sort_crop_boxes_supports_row_right_to_left_order():
    boxes = [
        CropBox(10, 30, 10, 30, label=1, area=100, centroid_y=20, centroid_x=20),
        CropBox(10, 30, 110, 130, label=2, area=100, centroid_y=20, centroid_x=120),
        CropBox(10, 30, 210, 230, label=3, area=100, centroid_y=20, centroid_x=220),
        CropBox(110, 130, 10, 30, label=4, area=100, centroid_y=120, centroid_x=20),
        CropBox(110, 130, 110, 130, label=5, area=100, centroid_y=120, centroid_x=120),
        CropBox(110, 130, 210, 230, label=6, area=100, centroid_y=120, centroid_x=220),
    ]

    ordered = sort_crop_boxes(boxes, image_shape=(160, 260), mode="row_right_to_left", row_tolerance=40)

    assert [box.label for box in ordered] == [3, 2, 1, 6, 5, 4]


def test_save_crops_supports_continuous_numbered_names(tmp_path):
    image = np.ones((20, 30, 3), dtype=np.uint8)
    boxes = [
        CropBox(0, 10, 0, 10, label=1, area=100, centroid_y=5, centroid_x=5),
        CropBox(10, 20, 10, 30, label=2, area=200, centroid_y=15, centroid_x=20),
    ]

    paths = save_crops(
        image,
        boxes,
        tmp_path,
        stem="section",
        start_index=7,
        filename_template="{stem}{index:03d}.{extension}",
    )

    assert [path.name for path in paths] == ["section007.tif", "section008.tif"]
    assert all(path.exists() for path in paths)


def test_save_crops_preserves_channel_first_stack(tmp_path):
    image = np.zeros((3, 20, 30), dtype=np.uint16)
    image[0, 2:12, 3:13] = 100
    image[1, 2:12, 3:13] = 200
    image[2, 2:12, 3:13] = 300
    boxes = [CropBox(2, 12, 3, 13, label=1, area=100, centroid_y=7, centroid_x=8)]

    paths = save_crops(
        image,
        boxes,
        tmp_path,
        stem="section",
        filename_template="{stem}{index:03d}.{extension}",
    )

    saved = imread(paths[0])
    assert saved.shape == (3, 10, 10)
    assert int(saved[0].max()) == 100
    assert int(saved[1].max()) == 200
    assert int(saved[2].max()) == 300


def test_raw_channels_to_rgb_direct_mapping_is_demixable():
    raw = np.zeros((3, 5, 6), dtype=np.uint16)
    raw[0, 1, 1] = 100
    raw[1, 2, 2] = 200
    raw[2, 3, 3] = 300

    rgb = _raw_channels_to_rgb(raw, rgb_channels=(2, 1, 0))

    assert rgb.shape == (5, 6, 3)
    assert int(rgb[..., 0].max()) == 300
    assert int(rgb[..., 1].max()) == 200
    assert int(rgb[..., 2].max()) == 100
    np.testing.assert_array_equal(rgb[..., 0], raw[2])
    np.testing.assert_array_equal(rgb[..., 1], raw[1])
    np.testing.assert_array_equal(rgb[..., 2], raw[0])


def test_preview_source_image_downsamples_large_channel_first_arrays():
    image = np.zeros((4, 100, 220), dtype=np.uint16)

    preview = _preview_source_image(image, preview_max_dim=50)

    assert preview.shape == (4, 20, 44)


def test_save_rgb_direct_crops_writes_each_crop_without_full_rgb_canvas(tmp_path):
    image = np.zeros((4, 20, 30), dtype=np.uint16)
    image[0] = 10
    image[1] = 20
    image[2] = 30
    boxes = [
        CropBox(y0=2, y1=8, x0=3, x1=13, label=1, area=60, centroid_y=5.0, centroid_x=8.0),
        CropBox(y0=10, y1=18, x0=15, x1=25, label=2, area=80, centroid_y=14.0, centroid_x=20.0),
    ]

    paths = _save_rgb_direct_crops(
        image,
        boxes,
        tmp_path,
        stem="section",
        extension="tif",
        start_index=1,
        filename_template="{stem}{index:03d}.{extension}",
        rgb_channels=(2, 1, 0),
    )

    assert [path.name for path in paths] == ["section001.tif", "section002.tif"]
    first = imread(paths[0])
    assert first.shape == (6, 10, 3)
    assert np.all(first[..., 0] == 30)
    assert np.all(first[..., 1] == 20)
    assert np.all(first[..., 2] == 10)


def test_save_direct_channel_crops_writes_final_outputs_without_raw_stack(tmp_path):
    image = np.zeros((3, 20, 30), dtype=np.uint16)
    image[0, 2:12, 3:13] = 10
    image[1, 2:12, 3:13] = 20
    image[2, 2:12, 3:13] = 30
    boxes = [CropBox(2, 12, 3, 13, label=1, area=100, centroid_y=7, centroid_x=8)]

    channel_paths, registration_paths = _save_direct_channel_crops(
        image,
        boxes,
        channel_output_dir=tmp_path / "channels",
        channel_export_channels=(0, 2),
        registration_output_dir=tmp_path / "registration",
        registration_channel=2,
        extension="tif",
        start_index=7,
    )

    assert set(channel_paths[0]) == {0, 2}
    np.testing.assert_array_equal(imread(channel_paths[0][0]), np.full((10, 10), 10, dtype=np.uint16))
    np.testing.assert_array_equal(imread(channel_paths[0][2]), np.full((10, 10), 30, dtype=np.uint16))
    np.testing.assert_array_equal(imread(registration_paths[0]), np.full((10, 10), 30, dtype=np.uint16))


def test_process_nd2_file_can_keep_review_data_in_memory_without_diagnostics(tmp_path, monkeypatch):
    image = np.zeros((3, 40, 60), dtype=np.uint16)
    image[:, 5:20, 5:20] = np.asarray([10, 20, 30])[:, None, None]
    image[:, 5:20, 35:50] = np.asarray([10, 20, 30])[:, None, None]
    input_path = tmp_path / "slide_01.nd2"

    read_downsamples = []

    def fake_read_nd2(path, **kwargs):
        downsample = kwargs["downsample"]
        read_downsamples.append(downsample)
        return Nd2Image(
            data=image[..., ::downsample, ::downsample],
            path=Path(path),
            dims=("C", "Y", "X"),
            sizes={"C": 3, "Y": 40, "X": 60},
            metadata={"voxel_size_um": {"x": 1.0, "y": 1.0}},
        )

    monkeypatch.setattr("brain_section_pipeline.pipeline.read_nd2_image", fake_read_nd2)

    class FakeRegionReader:
        def __init__(self, path, **kwargs):
            self.image_shape = image.shape[-2:]
            self.channel_count = image.shape[0]
            self.sizes = {"C": 3, "Y": 40, "X": 60}
            self.metadata = {"voxel_size_um": {"x": 1.0, "y": 1.0}}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return None

        def read_region(self, y0, y1, x0, x1, *, channel):
            return image[channel, y0:y1, x0:x1]

    monkeypatch.setattr("brain_section_pipeline.pipeline.Nd2RegionReader", FakeRegionReader)

    result = process_nd2_file(
        input_path,
        tmp_path / "slide_outputs",
        config=PipelineConfig(
            min_area=50,
            margin=0,
            opening_radius=0,
            closing_iterations=0,
            final_box_padding=0,
            write_rgb_crops=False,
            collect_rgb_review_thumbnails=True,
        ),
        channel_output_dir=tmp_path / "channels",
        channel_export_channels=(1,),
        registration_output_dir=tmp_path / "registration",
        registration_channel=0,
        write_diagnostics=False,
    )

    assert result.crop_paths == []
    assert result.merged_path is None
    assert result.metadata_path is None
    assert not result.output_dir.exists()
    assert len(result.review_thumbnails) == 2
    assert all(path.exists() for path in result.registration_crop_paths)
    assert all(paths[1].exists() for paths in result.channel_crop_paths)
    assert read_downsamples == [4]
    for box, paths, registration_path in zip(result.boxes, result.channel_crop_paths, result.registration_crop_paths):
        np.testing.assert_array_equal(imread(paths[1]), image[1, box.y0 : box.y1, box.x0 : box.x1])
        np.testing.assert_array_equal(imread(registration_path), image[0, box.y0 : box.y1, box.x0 : box.x1])


def test_nd2_region_reader_selects_channel_and_projects_z(monkeypatch):
    import dask.array as da
    import brain_section_pipeline.io as io_module

    pixels = np.arange(2 * 3 * 12 * 16, dtype=np.uint16).reshape(2, 3, 12, 16)

    class FakeHandle:
        sizes = {"Z": 2, "C": 3, "Y": 12, "X": 16}
        metadata = None

        def to_dask(self):
            return da.from_array(pixels, chunks=(1, 1, 6, 8))

        def close(self):
            pass

    monkeypatch.setattr(io_module, "_import_nd2", lambda: SimpleNamespace(ND2File=lambda path: FakeHandle()))
    with Nd2RegionReader("synthetic.nd2", z_projection="max") as reader:
        assert reader.image_shape == (12, 16)
        assert reader.channel_count == 3
        result = reader.read_region(2, 9, 4, 13, channel=1)

    np.testing.assert_array_equal(result, pixels[:, 1, 2:9, 4:13].max(axis=0))


def test_roi_rgb_only_export_uses_requested_channels(tmp_path, monkeypatch):
    image = np.zeros((4, 40, 60), dtype=np.uint16)
    image[:, 5:25, 10:30] = np.asarray([10, 20, 30, 40])[:, None, None]

    def fake_read(path, **kwargs):
        step = kwargs["downsample"]
        return Nd2Image(image[:, ::step, ::step], Path(path), ("C", "Y", "X"), {"C": 4, "Y": 40, "X": 60}, {})

    class FakeReader:
        image_shape = (40, 60)
        channel_count = 4
        sizes = {"C": 4, "Y": 40, "X": 60}
        metadata = {}

        def __init__(self, path, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return None

        def read_region(self, y0, y1, x0, x1, *, channel):
            return image[channel, y0:y1, x0:x1]

    monkeypatch.setattr(pipeline_module, "read_nd2_image", fake_read)
    monkeypatch.setattr(pipeline_module, "Nd2RegionReader", FakeReader)
    result = process_nd2_file(
        tmp_path / "slide.nd2",
        tmp_path / "output",
        config=PipelineConfig(
            min_area=20,
            margin=0,
            opening_radius=0,
            closing_iterations=0,
            final_box_padding=0,
            rgb_direct_channels=(2, 1, 0),
        ),
        write_diagnostics=False,
    )

    assert len(result.crop_paths) == 1
    crop = imread(result.crop_paths[0])
    box = result.boxes[0]
    np.testing.assert_array_equal(crop[..., 0], image[2, box.y0:box.y1, box.x0:box.x1])
    np.testing.assert_array_equal(crop[..., 2], image[0, box.y0:box.y1, box.x0:box.x1])


def test_two_pass_detection_refines_to_full_resolution_baseline_boxes():
    image = np.zeros((1, 400, 640), dtype=np.uint16)
    image[0, 51:159, 67:197] = 100
    image[0, 78:188, 333:487] = 120
    image[0, 240:356, 122:274] = 90

    config = PipelineConfig(
        min_area=100,
        margin=16,
        opening_radius=0,
        closing_iterations=0,
        threshold_method="quantile",
        threshold_quantile=0.5,
        sort_mode="row_left_to_right",
        final_box_padding=12,
        detection_downsample=8,
        detection_refinement_padding=64,
    )
    baseline = pipeline_module._detect_sections(image, config)
    coarse = pipeline_module._detect_sections(image[..., ::8, ::8], config, downsample=8)
    refined = pipeline_module._refine_coarse_boxes(
        image,
        coarse.boxes,
        config=config,
        downsample=8,
    )

    assert [(box.y0, box.y1, box.x0, box.x1) for box in refined] == [
        (box.y0, box.y1, box.x0, box.x1) for box in baseline.boxes
    ]


def test_two_pass_detection_preserves_high_box_overlap_with_morphology():
    image = np.zeros((1, 1024, 1024), dtype=np.uint16)
    image[0, 120:520, 120:500] = 100
    image[0, 530:900, 480:880] = 100
    config = PipelineConfig(
        min_area=10_000,
        margin=40,
        opening_radius=2,
        closing_iterations=32,
        threshold_method="quantile",
        threshold_quantile=0.5,
        final_box_padding=16,
        detection_downsample=8,
        detection_refinement_padding=128,
    )
    baseline = pipeline_module._detect_sections(image, config)
    coarse = pipeline_module._detect_sections(image[..., ::8, ::8], config, downsample=8)
    refined = pipeline_module._refine_coarse_boxes(
        image,
        coarse.boxes,
        config=config,
        downsample=8,
    )

    assert len(refined) == len(baseline.boxes)
    for full_box, two_pass_box in zip(baseline.boxes, refined):
        intersection = pipeline_module._box_intersection_area(full_box, two_pass_box)
        union = full_box.height * full_box.width + two_pass_box.height * two_pass_box.width - intersection
        assert intersection / union > 0.99


def test_export_sections_for_brainglobe_writes_manifest_and_channel_exports(tmp_path, monkeypatch):
    observed_configs = []

    def fake_process_nd2_file(
        path,
        output_dir,
        config=None,
        *,
        crop_output_dir=None,
        crop_start_index=1,
        crop_stem=None,
        crop_filename_template="{stem}_section{index:03d}.{extension}",
        **kwargs,
    ):
        observed_configs.append(config)
        input_path = Path(path)
        slide_dir = Path(output_dir) / input_path.stem
        slide_dir.mkdir(parents=True, exist_ok=True)
        raw_dir = slide_dir / "raw_channel_crops"
        raw_dir.mkdir(parents=True, exist_ok=True)

        overlay_path = slide_dir / f"{input_path.stem}_crops_overlay.png"
        Image.new("RGB", (10, 10), color=(32, 32, 32)).save(overlay_path)
        merged_path = slide_dir / f"{input_path.stem}_merged.tif"
        imwrite(merged_path, np.zeros((10, 10, 3), dtype=np.uint8))
        metadata_path = slide_dir / f"{input_path.stem}_metadata.json"
        metadata_path.write_text(json.dumps({"nd2": {"voxel_size_um": {"x": 4.0, "y": 5.0, "z": 40.0}}}), encoding="utf-8")
        manifest_path = slide_dir / f"{input_path.stem}_crop_manifest.csv"
        manifest_path.write_text("section_index\n", encoding="utf-8")

        boxes = []
        crop_paths = []
        raw_crop_paths = []
        channel_crop_paths = []
        registration_crop_paths = []
        for offset in range(2):
            section_index = crop_start_index + offset
            box = CropBox(
                y0=offset,
                y1=offset + 4,
                x0=offset + 1,
                x1=offset + 6,
                label=offset + 1,
                area=20,
                centroid_y=offset + 2.0,
                centroid_x=offset + 3.5,
            )
            boxes.append(box)

            rgb_path = Path(crop_output_dir) / f"section{section_index:03d}.tif"
            rgb_path.parent.mkdir(parents=True, exist_ok=True)
            imwrite(rgb_path, np.full((4, 5, 3), section_index, dtype=np.uint8))
            crop_paths.append(rgb_path)

            raw = np.zeros((3, 4, 5), dtype=np.uint16)
            raw[0] = section_index
            raw[1] = section_index + 100
            raw[2] = section_index + 200
            if config.save_raw_channel_crops:
                raw_path = raw_dir / f"{input_path.stem}_section{offset + 1:03d}.tif"
                imwrite(raw_path, raw, imagej=True, metadata={"axes": "CYX", "mode": "composite"})
                raw_crop_paths.append(raw_path)

            channel_paths = {}
            for channel in range(3):
                channel_path = Path(kwargs["channel_output_dir"]) / f"ch{channel}" / f"section{section_index:03d}.tif"
                channel_path.parent.mkdir(parents=True, exist_ok=True)
                imwrite(channel_path, raw[channel])
                channel_paths[channel] = channel_path
            channel_crop_paths.append(channel_paths)
            registration_path = Path(kwargs["registration_output_dir"]) / f"section{section_index:03d}.tif"
            registration_path.parent.mkdir(parents=True, exist_ok=True)
            imwrite(registration_path, raw[kwargs["registration_channel"]])
            registration_crop_paths.append(registration_path)

        return ProcessingResult(
            input_path=input_path,
            output_dir=slide_dir,
            merged_path=merged_path,
            overlay_path=overlay_path,
            manifest_path=manifest_path,
            metadata_path=metadata_path,
            crop_paths=[],
            raw_crop_paths=raw_crop_paths,
            boxes=boxes,
            detection_shape=(10, 10),
            channel_count=3,
            channel_crop_paths=channel_crop_paths,
            registration_crop_paths=registration_crop_paths,
            review_thumbnails=[np.full((4, 5, 3), 60, dtype=np.uint8) for _ in boxes],
        )

    monkeypatch.setattr("brain_section_pipeline.export.process_nd2_file", fake_process_nd2_file)
    monkeypatch.setattr("brain_section_pipeline.export._capture_atlas_metadata", lambda atlas_name: {"name": atlas_name})

    result = export_sections_for_brainglobe(
        ["slide_a.nd2", "slide_b.nd2"],
        tmp_path,
        export_config=BrainGlobeExportConfig(
            sample_id="rat_01",
            atlas_name="whs_sd_rat_39um",
            registration_channel=1,
            section_thickness_um=40.0,
            section_interval_um=120.0,
        ),
    )

    with result.manifest_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 4
    assert [row["section_index"] for row in rows] == ["1", "2", "3", "4"]
    assert [float(row["z_position_um"]) for row in rows] == [0.0, 120.0, 240.0, 360.0]
    assert all(row["atlas_name"] == "whs_sd_rat_39um" for row in rows)
    assert all(row["registration_channel"] == "1" for row in rows)
    assert rows[0]["pixel_size_x_um"] == "4.0"
    assert rows[0]["pixel_size_y_um"] == "5.0"
    assert rows[0]["raw_crop_path"] == ""
    assert observed_configs[0].preview_max_dim == 4096
    assert not observed_configs[0].save_raw_channel_crops
    assert not observed_configs[0].write_rgb_crops
    assert observed_configs[0].collect_rgb_review_thumbnails

    registration = imread(result.sections_registration_dir / "section001.tif")
    np.testing.assert_array_equal(registration, np.full((4, 5), 101, dtype=np.uint16))

    channel_zero = imread(result.sections_channels_dir / "ch0" / "section001.tif")
    channel_two = imread(result.sections_channels_dir / "ch2" / "section004.tif")
    np.testing.assert_array_equal(channel_zero, np.full((4, 5), 1, dtype=np.uint16))
    np.testing.assert_array_equal(channel_two, np.full((4, 5), 204, dtype=np.uint16))

    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    assert metadata["atlas_metadata"] == {"name": "whs_sd_rat_39um"}
    assert len(result.slide_overlay_paths) == 2
    assert all(path.exists() for path in result.slide_overlay_paths)
    assert result.section_montage_path.exists()
    assert Image.open(result.section_montage_path).size == (1672, 292)


def test_export_section_review_uses_numeric_slide_and_global_left_to_right_order(tmp_path, monkeypatch):
    processed_paths = []
    overlay_indices = []

    def fake_process_nd2_file(path, output_dir, config=None, **kwargs):
        input_path = Path(path)
        processed_paths.append((input_path.name, config.sort_mode, kwargs["crop_start_index"]))
        slide_dir = Path(output_dir) / input_path.stem
        slide_dir.mkdir(parents=True, exist_ok=True)
        raw_dir = slide_dir / "raw_channel_crops"
        raw_dir.mkdir(exist_ok=True)
        merged_path = slide_dir / "merged.tif"
        overlay_path = slide_dir / "overlay.png"
        metadata_path = slide_dir / "metadata.json"
        manifest_path = slide_dir / "manifest.csv"
        imwrite(merged_path, np.zeros((20, 30, 3), dtype=np.uint8))
        Image.new("RGB", (20, 30)).save(overlay_path)
        metadata_path.write_text(json.dumps({"nd2": {}}), encoding="utf-8")
        manifest_path.write_text("section_index\n", encoding="utf-8")
        start = kwargs["crop_start_index"]
        boxes = [
            CropBox(1, 8, 2, 10, label=1, area=48, centroid_y=4.5, centroid_x=6.0),
            CropBox(1, 8, 12, 20, label=2, area=48, centroid_y=4.5, centroid_x=16.0),
        ]
        crop_paths = []
        raw_paths = []
        channel_crop_paths = []
        registration_crop_paths = []
        for offset in range(2):
            crop_path = Path(kwargs["crop_output_dir"]) / f"section{start + offset:03d}.tif"
            crop_path.parent.mkdir(parents=True, exist_ok=True)
            imwrite(crop_path, np.full((4, 5, 3), start + offset, dtype=np.uint8))
            crop_paths.append(crop_path)
            raw_path = raw_dir / f"raw{offset}.tif"
            imwrite(raw_path, np.full((3, 4, 5), start + offset, dtype=np.uint16))
            if config.save_raw_channel_crops:
                raw_paths.append(raw_path)
            channel_paths = {}
            for channel in range(3):
                channel_path = Path(kwargs["channel_output_dir"]) / f"ch{channel}" / f"section{start + offset:03d}.tif"
                channel_path.parent.mkdir(parents=True, exist_ok=True)
                imwrite(channel_path, np.full((4, 5), start + offset + channel, dtype=np.uint16))
                channel_paths[channel] = channel_path
            channel_crop_paths.append(channel_paths)
            registration_path = Path(kwargs["registration_output_dir"]) / f"section{start + offset:03d}.tif"
            registration_path.parent.mkdir(parents=True, exist_ok=True)
            imwrite(registration_path, np.full((4, 5), start + offset, dtype=np.uint16))
            registration_crop_paths.append(registration_path)
        return ProcessingResult(
            input_path=input_path,
            output_dir=slide_dir,
            merged_path=merged_path,
            overlay_path=overlay_path,
            manifest_path=manifest_path,
            metadata_path=metadata_path,
            crop_paths=crop_paths,
            raw_crop_paths=raw_paths,
            boxes=boxes,
            detection_shape=(20, 30),
            channel_count=3,
            channel_crop_paths=channel_crop_paths,
            registration_crop_paths=registration_crop_paths,
        )

    def fake_overlay(merged_path, boxes, output_path, *, first_section_index, source_shape):
        overlay_indices.append((Path(merged_path).parent.name, first_section_index))
        Image.new("RGB", (20, 30)).save(output_path)

    monkeypatch.setattr("brain_section_pipeline.export.process_nd2_file", fake_process_nd2_file)
    monkeypatch.setattr("brain_section_pipeline.export._write_numbered_slide_overlay", fake_overlay)
    monkeypatch.setattr("brain_section_pipeline.export._capture_atlas_metadata", lambda atlas_name: None)

    result = export_sections_for_brainglobe(
        ["slide_10.nd2", "slide_2.nd2", "slide_1.nd2"],
        tmp_path,
        export_config=BrainGlobeExportConfig(sample_id="rat_01"),
    )

    assert processed_paths == [
        ("slide_1.nd2", "row_left_to_right", 1),
        ("slide_2.nd2", "row_left_to_right", 3),
        ("slide_10.nd2", "row_left_to_right", 5),
    ]
    assert overlay_indices == [("slide_1", 1), ("slide_2", 3), ("slide_10", 5)]
    assert Image.open(result.section_montage_path).size == (1672, 572)


def test_capture_atlas_metadata_returns_none_without_brainglobe(monkeypatch):
    import builtins

    original_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "brainglobe_atlasapi.bg_atlas":
            raise ImportError("brainglobe unavailable")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    assert _capture_atlas_metadata("whs_sd_rat_39um") is None


def test_build_stack_from_manifest_filters_and_centers_sections(tmp_path):
    sample_dir = tmp_path / "rat_01"
    registration_dir = sample_dir / "sections_registration"
    registration_dir.mkdir(parents=True)
    channel_dir = sample_dir / "sections_channels" / "ch0"
    channel_dir.mkdir(parents=True)

    first = np.full((2, 3), 10, dtype=np.uint16)
    second = np.full((4, 5), 20, dtype=np.uint16)
    third = np.full((3, 2), 30, dtype=np.uint16)
    imwrite(registration_dir / "section001.tif", first)
    imwrite(registration_dir / "section002.tif", second)
    imwrite(registration_dir / "section003.tif", third)
    imwrite(channel_dir / "section001.tif", first + 1)
    imwrite(channel_dir / "section002.tif", second + 1)
    imwrite(channel_dir / "section003.tif", third + 1)

    manifest_path = sample_dir / "section_manifest.csv"
    rows = [
        {
            "sample_id": "rat_01",
            "source_file": "slide_01.nd2",
            "slide_id": "slide_01",
            "section_index": "1",
            "crop_path_registration": str(registration_dir / "section001.tif"),
            "crop_path_rgb": str(registration_dir / "section001.tif"),
            "channel_paths": json.dumps({"ch0": str(channel_dir / "section001.tif")}),
            "pixel_size_x_um": "4.0",
            "pixel_size_y_um": "5.0",
            "section_thickness_um": "40.0",
            "section_interval_um": "120.0",
            "z_position_um": "0.0",
            "include_in_stack": "true",
            "qc_status": "approved",
            "y0": "2",
            "y1": "4",
            "x0": "1",
            "x1": "4",
        },
        {
            "sample_id": "rat_01",
            "source_file": "slide_01.nd2",
            "slide_id": "slide_01",
            "section_index": "2",
            "crop_path_registration": str(registration_dir / "section002.tif"),
            "crop_path_rgb": str(registration_dir / "section002.tif"),
            "channel_paths": json.dumps({"ch0": str(channel_dir / "section002.tif")}),
            "pixel_size_x_um": "4.0",
            "pixel_size_y_um": "5.0",
            "section_thickness_um": "40.0",
            "section_interval_um": "120.0",
            "z_position_um": "120.0",
            "include_in_stack": "false",
            "qc_status": "approved",
            "y0": "0",
            "y1": "4",
            "x0": "0",
            "x1": "5",
        },
        {
            "sample_id": "rat_01",
            "source_file": "slide_02.nd2",
            "slide_id": "slide_02",
            "section_index": "3",
            "crop_path_registration": str(registration_dir / "section003.tif"),
            "crop_path_rgb": str(registration_dir / "section003.tif"),
            "channel_paths": json.dumps({"ch0": str(channel_dir / "section003.tif")}),
            "pixel_size_x_um": "4.0",
            "pixel_size_y_um": "5.0",
            "section_thickness_um": "40.0",
            "section_interval_um": "120.0",
            "z_position_um": "240.0",
            "include_in_stack": "true",
            "qc_status": "pending",
            "y0": "1",
            "y1": "4",
            "x0": "3",
            "x1": "5",
        },
    ]
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    result = build_stack_from_manifest(
        manifest_path,
        config=StackBuildConfig(allowed_qc_statuses=("approved",), placement_mode="center"),
    )

    stack = imread(result.stack_path)
    assert result.section_indices == [1]
    assert stack.shape == (1, 2, 3)
    np.testing.assert_array_equal(stack[0], first)

    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    assert metadata["voxel_size_um"] == {"z": 120.0, "y": 5.0, "x": 4.0}


def test_build_stack_from_manifest_supports_original_coordinates_and_channel_source(tmp_path):
    sample_dir = tmp_path / "rat_02"
    channel_dir = sample_dir / "sections_channels" / "ch2"
    channel_dir.mkdir(parents=True)

    first = np.full((2, 2), 7, dtype=np.uint16)
    second = np.full((3, 3), 9, dtype=np.uint16)
    imwrite(channel_dir / "section001.tif", first)
    imwrite(channel_dir / "section002.tif", second)

    manifest_path = sample_dir / "section_manifest.csv"
    rows = [
        {
            "sample_id": "rat_02",
            "source_file": "slide_a.nd2",
            "slide_id": "slide_a",
            "section_index": "1",
            "crop_path_registration": str(channel_dir / "section001.tif"),
            "crop_path_rgb": str(channel_dir / "section001.tif"),
            "channel_paths": json.dumps({"ch2": str(channel_dir / "section001.tif")}),
            "pixel_size_x_um": "3.0",
            "pixel_size_y_um": "3.0",
            "section_thickness_um": "25.0",
            "section_interval_um": "",
            "z_position_um": "0.0",
            "include_in_stack": "true",
            "qc_status": "approved",
            "y0": "1",
            "y1": "3",
            "x0": "2",
            "x1": "4",
        },
        {
            "sample_id": "rat_02",
            "source_file": "slide_b.nd2",
            "slide_id": "slide_b",
            "section_index": "2",
            "crop_path_registration": str(channel_dir / "section002.tif"),
            "crop_path_rgb": str(channel_dir / "section002.tif"),
            "channel_paths": json.dumps({"ch2": str(channel_dir / "section002.tif")}),
            "pixel_size_x_um": "3.0",
            "pixel_size_y_um": "3.0",
            "section_thickness_um": "25.0",
            "section_interval_um": "",
            "z_position_um": "25.0",
            "include_in_stack": "true",
            "qc_status": "approved",
            "y0": "0",
            "y1": "3",
            "x0": "0",
            "x1": "3",
        },
    ]
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    result = build_stack_from_manifest(
        manifest_path,
        config=StackBuildConfig(source_kind="channel", channel=2, placement_mode="original_coords", output_name="custom.tif"),
    )

    stack = imread(result.stack_path)
    assert result.stack_path.name == "custom.tif"
    assert stack.shape == (2, 3, 4)
    np.testing.assert_array_equal(stack[0, 1:3, 2:4], first)
    np.testing.assert_array_equal(stack[1, 0:3, 0:3], second)
    assert result.voxel_size_um == {"z": 25.0, "y": 3.0, "x": 3.0}


def test_prepare_brainreg_run_writes_slice_directories_and_command(tmp_path):
    sample_dir = tmp_path / "rat_03"
    registration_dir = sample_dir / "sections_registration"
    registration_dir.mkdir(parents=True)
    channel_dir = sample_dir / "sections_channels" / "ch2"
    channel_dir.mkdir(parents=True)

    reg_first = np.full((2, 2), 11, dtype=np.uint16)
    reg_second = np.full((2, 3), 22, dtype=np.uint16)
    ch_first = np.full((2, 2), 111, dtype=np.uint16)
    ch_second = np.full((2, 3), 222, dtype=np.uint16)
    imwrite(registration_dir / "section001.tif", reg_first)
    imwrite(registration_dir / "section002.tif", reg_second)
    imwrite(channel_dir / "section001.tif", ch_first)
    imwrite(channel_dir / "section002.tif", ch_second)

    manifest_path = sample_dir / "section_manifest.csv"
    rows = [
        {
            "sample_id": "rat_03",
            "atlas_name": "whs_sd_rat_39um",
            "orientation": "asl",
            "source_file": "slide_01.nd2",
            "slide_id": "slide_01",
            "section_index": "1",
            "crop_path_registration": str(registration_dir / "section001.tif"),
            "crop_path_rgb": str(registration_dir / "section001.tif"),
            "channel_paths": json.dumps({"ch2": str(channel_dir / "section001.tif")}),
            "pixel_size_x_um": "4.0",
            "pixel_size_y_um": "5.0",
            "section_thickness_um": "40.0",
            "section_interval_um": "120.0",
            "z_position_um": "0.0",
            "include_in_stack": "true",
            "qc_status": "approved",
            "y0": "0",
            "y1": "2",
            "x0": "0",
            "x1": "2",
        },
        {
            "sample_id": "rat_03",
            "atlas_name": "whs_sd_rat_39um",
            "orientation": "asl",
            "source_file": "slide_02.nd2",
            "slide_id": "slide_02",
            "section_index": "2",
            "crop_path_registration": str(registration_dir / "section002.tif"),
            "crop_path_rgb": str(registration_dir / "section002.tif"),
            "channel_paths": json.dumps({"ch2": str(channel_dir / "section002.tif")}),
            "pixel_size_x_um": "4.0",
            "pixel_size_y_um": "5.0",
            "section_thickness_um": "40.0",
            "section_interval_um": "120.0",
            "z_position_um": "120.0",
            "include_in_stack": "true",
            "qc_status": "approved",
            "y0": "0",
            "y1": "2",
            "x0": "0",
            "x1": "3",
        },
    ]
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    stack_result = build_stack_from_manifest(
        manifest_path,
        config=StackBuildConfig(source_kind="registration", placement_mode="center", allowed_qc_statuses=("approved",)),
    )

    prep = prepare_brainreg_run(
        stack_result.metadata_path,
        config=BrainRegConfig(additional_channels=(2,), debug=True, save_original_orientation=True),
    )

    registration_slices = sorted(prep.registration_input_dir.glob("slice_*.tif"))
    additional_slices = sorted(prep.additional_input_dirs[0].glob("slice_*.tif"))
    assert len(registration_slices) == 2
    assert len(additional_slices) == 2
    np.testing.assert_array_equal(imread(registration_slices[0]), np.array([[11, 11, 0], [11, 11, 0]], dtype=np.uint16))
    np.testing.assert_array_equal(imread(additional_slices[1]), np.array([[222, 222, 222], [222, 222, 222]], dtype=np.uint16))

    assert prep.command[:3] == ["brainreg", str(prep.registration_input_dir), str(prep.brainreg_output_dir)]
    assert "-v" in prep.command
    assert prep.command[prep.command.index("--orientation") + 1] == "asl"
    assert prep.command[prep.command.index("--atlas") + 1] == "whs_sd_rat_39um"
    assert "--debug" in prep.command
    assert "--save-original-orientation" in prep.command
    assert "-a" in prep.command

    prep_metadata = json.loads(prep.metadata_path.read_text(encoding="utf-8"))
    assert prep_metadata["voxel_size_um"] == {"z": 120.0, "y": 5.0, "x": 4.0}


def test_run_prepared_brainreg_uses_saved_command(tmp_path, monkeypatch):
    metadata_path = tmp_path / "brainreg_preparation.json"
    payload = {
        "prepared_dir": str(tmp_path),
        "registration_input_dir": str(tmp_path / "registration"),
        "additional_input_dirs": [],
        "brainreg_output_dir": str(tmp_path / "brainreg_output"),
        "command_script_path": str(tmp_path / "run_brainreg.ps1"),
        "stack_metadata_path": str(tmp_path / "stack.json"),
        "manifest_path": str(tmp_path / "section_manifest.csv"),
        "command": ["brainreg", "input", "output", "-v", "10", "5", "5", "--orientation", "asl", "--atlas", "whs_sd_rat_39um"],
    }
    metadata_path.write_text(json.dumps(payload), encoding="utf-8")

    called = {}

    def fake_run(command, check, text, capture_output):
        called["command"] = command
        called["check"] = check
        called["text"] = text
        called["capture_output"] = capture_output
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr("brain_section_pipeline.brainreg_runner.subprocess.run", fake_run)

    result = run_prepared_brainreg(metadata_path)

    assert called["command"] == payload["command"]
    assert called["check"] is True
    assert result.stdout == "ok"


def test_prepare_slice_atlas_inputs_exports_reference_and_annotation_planes(tmp_path, monkeypatch):
    sample_dir = tmp_path / "rat_04"
    registration_dir = sample_dir / "sections_registration"
    registration_dir.mkdir(parents=True)
    imwrite(registration_dir / "section001.tif", np.full((3, 4), 10, dtype=np.uint16))
    imwrite(registration_dir / "section002.tif", np.full((3, 4), 20, dtype=np.uint16))

    manifest_path = sample_dir / "section_manifest.csv"
    rows = [
        {
            "sample_id": "rat_04",
            "atlas_name": "whs_sd_rat_39um",
            "orientation": "asl",
            "section_index": "1",
            "crop_path_registration": str(registration_dir / "section001.tif"),
            "crop_path_rgb": str(registration_dir / "section001.tif"),
            "channel_paths": "{}",
            "include_in_stack": "true",
            "qc_status": "approved",
        },
        {
            "sample_id": "rat_04",
            "atlas_name": "whs_sd_rat_39um",
            "orientation": "asl",
            "section_index": "2",
            "crop_path_registration": str(registration_dir / "section002.tif"),
            "crop_path_rgb": str(registration_dir / "section002.tif"),
            "channel_paths": "{}",
            "include_in_stack": "true",
            "qc_status": "approved",
        },
    ]
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    class FakeAtlas:
        orientation = "asl"
        resolution = (39.0, 39.0, 39.0)

        def __init__(self):
            self.reference = np.arange(4 * 5 * 6, dtype=np.uint16).reshape(4, 5, 6)
            self.annotation = (np.arange(4 * 5 * 6, dtype=np.uint16).reshape(4, 5, 6) % 7).astype(np.uint16)

    monkeypatch.setattr("brain_section_pipeline.slice_atlas._load_atlas", lambda atlas_name: FakeAtlas())

    result = prepare_slice_atlas_inputs(
        manifest_path,
        config=SliceAtlasConfig(start_slice_index=1, slice_index_step=2, allowed_qc_statuses=("approved",)),
    )

    with result.manifest_path.open("r", encoding="utf-8", newline="") as handle:
        pairing_rows = list(csv.DictReader(handle))

    assert [row["atlas_slice_index"] for row in pairing_rows] == ["1", "3"]
    assert result.section_indices == [1, 2]
    exported_reference = imread(result.atlas_reference_dir / "section001_atlas_reference.tif")
    exported_annotation = imread(result.atlas_annotation_dir / "section002_atlas_annotation.tif")
    assert exported_reference.shape == (5, 6)
    assert exported_annotation.shape == (5, 6)
    assert result.section_source_dir is None
    assert pairing_rows[0]["section_source_path"] == str(registration_dir / "section001.tif")


def test_prepare_slice_atlas_inputs_raises_without_brainglobe(monkeypatch, tmp_path):
    manifest_path = tmp_path / "section_manifest.csv"
    manifest_path.write_text(
        "sample_id,section_index,crop_path_registration,crop_path_rgb,channel_paths,include_in_stack,qc_status\n"
        "rat,1,a.tif,a.tif,{},true,approved\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "brain_section_pipeline.slice_atlas._load_atlas",
        lambda atlas_name: (_ for _ in ()).throw(ImportError("missing atlasapi")),
    )

    try:
        prepare_slice_atlas_inputs(manifest_path)
    except ImportError as exc:
        assert "atlasapi" in str(exc)
    else:
        raise AssertionError("Expected prepare_slice_atlas_inputs to raise ImportError.")


@pytest.mark.parametrize(
    ("requested_ap_mm", "source_voxel", "expected_index"),
    [
        (0.0, 623, 400),
        (3.9, 723, 300),
        (4.9, 748, 275),
        (5.8, 771, 252),
    ],
)
def test_whs_ap_mm_uses_published_origin_and_source_voxel_spacing(requested_ap_mm, source_voxel, expected_index):
    index, actual_ap_mm = slice_atlas_module._slice_assignment_for_row(
        {"section_index": "1", "whs_ap_mm": str(requested_ap_mm)},
        0,
        SliceAtlasConfig(),
        (1024, 512, 512),
        "asr",
        [39.0, 39.0, 39.0],
        "3.0",
        0,
    )
    assert expected_index == 1023 - source_voxel
    assert index == expected_index
    assert actual_ap_mm == pytest.approx((source_voxel - 623) * 0.0390625)


def test_whs_ap_index_reversal_matches_brainglobe_space_stack_mapping():
    brainglobe_space = pytest.importorskip("brainglobe_space")
    source = np.zeros((4, 7, 5), dtype=np.uint8)
    source[2, 3, 1] = 1
    mapped = brainglobe_space.AnatomicalSpace("lpi", shape=source.shape).map_stack_to(
        brainglobe_space.AnatomicalSpace("asr", shape=(7, 5, 4)), source
    )
    mapped_ap_index = int(np.argwhere(mapped == 1)[0, 0])
    assert mapped_ap_index == 7 - 1 - 3


@pytest.mark.parametrize(
    ("row", "config", "shape", "orientation", "resolution", "version", "error"),
    [
        ({"whs_ap_mm": "3.9", "atlas_slice_index": "300"}, SliceAtlasConfig(), (1024, 512, 512), "asr", [39.0] * 3, "3.0", "both"),
        ({"whs_ap_mm": "unknown"}, SliceAtlasConfig(), (1024, 512, 512), "asr", [39.0] * 3, "3.0", "invalid"),
        ({"whs_ap_mm": "nan"}, SliceAtlasConfig(), (1024, 512, 512), "asr", [39.0] * 3, "3.0", "finite"),
        ({"whs_ap_mm": "100"}, SliceAtlasConfig(), (1024, 512, 512), "asr", [39.0] * 3, "3.0", "outside"),
        ({"whs_ap_mm": "3.9"}, SliceAtlasConfig(atlas_name="other_atlas"), (1024, 512, 512), "asr", [39.0] * 3, "3.0", "requires"),
        ({"whs_ap_mm": "3.9"}, SliceAtlasConfig(), (1000, 512, 512), "asr", [39.0] * 3, "3.0", "validated"),
        ({"whs_ap_mm": "3.9"}, SliceAtlasConfig(), (1024, 512, 512), "asr", [50.0] * 3, "3.0", "validated"),
        ({"whs_ap_mm": "3.9"}, SliceAtlasConfig(), (1024, 512, 512), "asr", [39.0] * 3, "3.1", "validated"),
        ({"whs_ap_mm": "3.9"}, SliceAtlasConfig(), (512, 1024, 512), "lpi", [39.0] * 3, "3.0", "validated"),
    ],
)
def test_whs_ap_mm_rejects_ambiguous_or_incompatible_inputs(row, config, shape, orientation, resolution, version, error):
    with pytest.raises(ValueError, match=error):
        slice_atlas_module._slice_assignment_for_row(
            {"section_index": "1", **row}, 0, config, shape, orientation, resolution, version, 0
        )


def test_prepare_slice_atlas_inputs_accepts_whs_ap_mm_per_section(tmp_path, monkeypatch):
    registration_dir = tmp_path / "sections_registration"
    registration_dir.mkdir()
    rows = []
    for section_index, ap_mm in enumerate((3.9, 4.9, 5.8), start=1):
        section_path = registration_dir / f"section{section_index:03d}.tif"
        imwrite(section_path, np.ones((4, 4), dtype=np.uint16))
        rows.append(
            {
                "section_index": section_index,
                "crop_path_registration": str(section_path),
                "include_in_stack": "true",
                "whs_ap_mm": ap_mm,
            }
        )
    manifest_path = tmp_path / "section_manifest.csv"
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    class FakeAtlas:
        orientation = "asr"
        resolution = (39.0, 39.0, 39.0)
        metadata = {"version": "3.0"}
        reference = np.broadcast_to(np.arange(1024, dtype=np.uint16)[:, None, None], (1024, 512, 512))
        annotation = np.broadcast_to(np.arange(1024, dtype=np.uint16)[:, None, None], (1024, 512, 512))

    monkeypatch.setattr("brain_section_pipeline.slice_atlas._load_atlas", lambda atlas_name: FakeAtlas())
    result = prepare_slice_atlas_inputs(manifest_path)
    with result.manifest_path.open("r", encoding="utf-8", newline="") as handle:
        paired = list(csv.DictReader(handle))

    assert [int(row["atlas_slice_index"]) for row in paired] == [300, 275, 252]
    assert [float(row["whs_ap_mm"]) for row in paired] == [3.9, 4.9, 5.8]
    assert [float(row["atlas_plane_whs_ap_mm"]) for row in paired] == pytest.approx(
        [3.90625, 4.8828125, 5.78125]
    )
    for row in paired:
        assert np.all(imread(row["atlas_reference_path"]) == int(row["atlas_slice_index"]))
        assert np.all(imread(row["atlas_annotation_path"]) == int(row["atlas_slice_index"]))
    with result.metadata_path.open("r", encoding="utf-8") as handle:
        metadata = json.load(handle)
    assert metadata["whs_ap_calibration"]["source_ap_origin_voxel"] == 623
    assert metadata["whs_ap_calibration"]["source_voxel_size_mm"] == 0.0390625


def test_blank_whs_ap_mm_preserves_explicit_atlas_index():
    index, plane_ap_mm = slice_atlas_module._slice_assignment_for_row(
        {"section_index": "1", "whs_ap_mm": "", "atlas_slice_index": "321"},
        0,
        SliceAtlasConfig(),
        (1024, 512, 512),
        "asr",
        [39.0, 39.0, 39.0],
        "3.0",
        0,
    )
    assert index == 321
    assert plane_ap_mm is None


def test_atlas_index_ap_conversion_matches_whs_axis_convention():
    shape = (1024, 512, 512)
    resolution = (39.0, 39.0, 39.0)

    assert ap_mm_to_atlas_index(-7.30, shape=shape, resolution_um=resolution, orientation="asr") == 699
    assert atlas_index_to_ap_mm(699, shape=shape, resolution_um=resolution, orientation="asr") == pytest.approx(-7.293)


def test_atlas_index_ap_conversion_supports_paxinos_offset():
    shape = (1024, 512, 512)
    resolution = (39.0, 39.0, 39.0)

    assert coordinate_ap_mm_to_atlas_native_ap_mm(
        -7.80,
        coordinate_system="paxinos",
        ap_coordinate_offset_mm=0.50,
    ) == pytest.approx(-7.30)
    assert atlas_native_ap_mm_to_coordinate_ap_mm(
        -7.30,
        coordinate_system="paxinos",
        ap_coordinate_offset_mm=0.50,
    ) == pytest.approx(-7.80)
    assert (
        ap_mm_to_atlas_index(
            -7.80,
            shape=shape,
            resolution_um=resolution,
            orientation="asr",
            coordinate_system="paxinos",
            ap_coordinate_offset_mm=0.50,
        )
        == 699
    )
    assert atlas_index_to_ap_mm(
        699,
        shape=shape,
        resolution_um=resolution,
        orientation="asr",
        coordinate_system="paxinos",
        ap_coordinate_offset_mm=0.50,
    ) == pytest.approx(-7.793)


def test_atlas_candidate_score_penalizes_oversized_visible_boundary():
    base_registration = {
        "status": "ok",
        "dice": 0.55,
        "iou": 0.38,
        "loss": 0.95,
        "warped_area_ratio": 1.0,
        "warped_extent_y_ratio": 1.0,
        "warped_extent_x_ratio": 1.0,
        "warped_center_y_offset": 0.0,
        "warped_center_x_offset": 0.0,
        "boundary_area_ratio": 1.0,
        "boundary_extent_y_ratio": 1.0,
        "boundary_extent_x_ratio": 1.0,
        "boundary_outside_fraction": 0.02,
    }
    oversized_boundary = {
        **base_registration,
        "boundary_area_ratio": 1.3,
        "boundary_extent_y_ratio": 1.15,
        "boundary_extent_x_ratio": 1.12,
        "boundary_outside_fraction": 0.25,
    }

    assert atlas_indexing_module._candidate_score(base_registration) > atlas_indexing_module._candidate_score(
        oversized_boundary
    )


def test_atlas_candidate_score_penalizes_boundary_distance_and_dorsal_anchor_mismatch():
    base_registration = {
        "status": "ok",
        "dice": 0.55,
        "iou": 0.38,
        "loss": 0.95,
        "warped_area_ratio": 1.0,
        "warped_extent_y_ratio": 1.0,
        "warped_extent_x_ratio": 1.0,
        "warped_center_y_offset": 0.0,
        "warped_center_x_offset": 0.0,
        "boundary_area_ratio": 1.0,
        "boundary_extent_y_ratio": 1.0,
        "boundary_extent_x_ratio": 1.0,
        "boundary_outside_fraction": 0.02,
        "boundary_distance_norm": 0.02,
        "dorsal_midline_distance": 0.01,
    }
    mismatched = {
        **base_registration,
        "boundary_distance_norm": 0.20,
        "dorsal_midline_distance": 0.30,
    }

    assert atlas_indexing_module._candidate_score(base_registration) > atlas_indexing_module._candidate_score(mismatched)


def test_dorsal_midline_anchor_detects_central_notch():
    mask = np.zeros((70, 100), dtype=bool)
    for x in range(20, 81):
        top = 10
        if 45 <= x <= 55:
            top = 20
        mask[top:55, x] = True

    anchor = atlas_indexing_module._dorsal_midline_anchor(mask)

    assert anchor is not None
    assert anchor["detected"]
    assert anchor["x"] == pytest.approx(50, abs=6)
    assert anchor["y"] >= 18


def test_anatomical_alignment_metrics_penalize_shifted_boundary_and_notch():
    atlas_mask = np.zeros((80, 120), dtype=bool)
    section_mask = np.zeros_like(atlas_mask)
    shifted_section_mask = np.zeros_like(atlas_mask)
    for x in range(25, 96):
        top = 12 if not 54 <= x <= 66 else 22
        atlas_mask[top:64, x] = True
        section_mask[top:64, x] = True
    shifted_section_mask[16:68, 31:102] = section_mask[12:64, 25:96]

    aligned = atlas_indexing_module._anatomical_alignment_metrics({"_warped_boundary_mask": section_mask}, atlas_mask)
    shifted = atlas_indexing_module._anatomical_alignment_metrics(
        {"_warped_boundary_mask": shifted_section_mask},
        atlas_mask,
    )

    assert aligned["boundary_distance_norm"] < shifted["boundary_distance_norm"]
    assert aligned["dorsal_midline_distance"] < shifted["dorsal_midline_distance"]


def test_suggest_atlas_indices_writes_selected_manifest_and_review_candidates(tmp_path, monkeypatch):
    class FakeAtlas:
        orientation = "asr"
        resolution = (39.0, 39.0, 39.0)

        def __init__(self):
            self.reference = np.zeros((7, 40, 50), dtype=np.float32)
            self.annotation = np.zeros((7, 40, 50), dtype=np.uint16)
            self.reference[2, 11:29, 16:34] = 80
            self.annotation[2, 11:29, 16:34] = 1
            self.reference[3, 10:30, 14:36] = 120
            self.annotation[3, 10:30, 14:36] = 1
            self.reference[4, 8:34, 10:42] = 60
            self.annotation[4, 8:34, 10:42] = 1

    monkeypatch.setattr("brain_section_pipeline.atlas_indexing._load_atlas", lambda atlas_name: FakeAtlas())

    section_path = tmp_path / "section001.tif"
    section = np.zeros((40, 50), dtype=np.float32)
    section[10:30, 14:36] = 500
    imwrite(section_path, section)

    manifest_path = tmp_path / "section_manifest.csv"
    rows = [
        {
            "sample_id": "rat_01",
            "atlas_name": "fake",
            "source_file": "slide.nd2",
            "slide_number": "1",
            "slide_id": "slide",
            "section_index": "1",
            "crop_path_rgb": str(section_path),
            "crop_path_registration": str(section_path),
            "raw_crop_path": str(section_path),
            "channel_count": "1",
            "channel_paths": "{}",
            "registration_channel": "0",
            "include_in_stack": "True",
            "qc_status": "pending",
        }
    ]
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    result = suggest_atlas_indices(
        manifest_path,
        config=AtlasIndexSuggestionConfig(
            atlas_name="fake",
            start_slice_index=3,
            search_radius_slices=1,
            top_n=2,
        ),
    )

    candidate_rows = list(csv.DictReader(result.candidate_manifest_path.open(newline="", encoding="utf-8")))
    selected_rows = list(csv.DictReader(result.selected_manifest_path.open(newline="", encoding="utf-8")))
    choices = list(csv.DictReader(result.selected_choices_path.open(newline="", encoding="utf-8")))

    assert len(candidate_rows) == 2
    assert len(result.review_grid_paths) == 1
    assert result.review_grid_paths[0].exists()
    assert len(result.atlas_preview_paths) == 1
    assert result.atlas_preview_paths[0].exists()
    assert result.atlas_preview_contact_sheet_path is not None
    assert result.atlas_preview_contact_sheet_path.exists()
    assert selected_rows[0]["atlas_slice_index"] == choices[0]["selected_atlas_slice_index"]
    assert Path(selected_rows[0]["atlas_reference_path"]).exists()
    assert Path(selected_rows[0]["atlas_annotation_path"]).exists()
    assert Path(selected_rows[0]["atlas_index_selected_atlas_preview_path"]).exists()
    assert Path(choices[0]["selected_atlas_preview_path"]).exists()
    assert Path(candidate_rows[0]["overlay_path"]).exists()


def test_oblique_atlas_plane_extraction_preserves_zero_angle_slice():
    volume = np.arange(7 * 9 * 11, dtype=np.float32).reshape((7, 9, 11))

    exact = atlas_indexing_module._extract_slice(volume, 0, 3)
    zero_angle = atlas_indexing_module._extract_atlas_plane(
        volume,
        0,
        3,
        pitch_degrees=0.0,
        yaw_degrees=0.0,
        resolution_um=(39.0, 39.0, 39.0),
        order=1,
    )
    oblique = atlas_indexing_module._extract_atlas_plane(
        volume,
        0,
        3,
        pitch_degrees=20.0,
        yaw_degrees=0.0,
        resolution_um=(39.0, 39.0, 39.0),
        order=1,
    )

    np.testing.assert_array_equal(zero_angle, exact)
    assert oblique.shape == exact.shape
    assert not np.allclose(oblique, exact)


def test_suggest_atlas_indices_records_oblique_plane_angle_candidates(tmp_path, monkeypatch):
    class FakeAtlas:
        orientation = "asr"
        resolution = (39.0, 39.0, 39.0)

        def __init__(self):
            self.reference = np.zeros((7, 40, 50), dtype=np.float32)
            self.annotation = np.zeros((7, 40, 50), dtype=np.uint16)
            self.reference[3, 10:30, 14:36] = 120
            self.annotation[3, 10:30, 14:36] = 1

    monkeypatch.setattr("brain_section_pipeline.atlas_indexing._load_atlas", lambda atlas_name: FakeAtlas())

    section_path = tmp_path / "section001.tif"
    section = np.zeros((40, 50), dtype=np.float32)
    section[10:30, 14:36] = 500
    imwrite(section_path, section)

    manifest_path = tmp_path / "section_manifest.csv"
    rows = [
        {
            "sample_id": "rat_01",
            "atlas_name": "fake",
            "source_file": "slide.nd2",
            "slide_number": "1",
            "slide_id": "slide",
            "section_index": "1",
            "crop_path_rgb": str(section_path),
            "crop_path_registration": str(section_path),
            "raw_crop_path": str(section_path),
            "channel_count": "1",
            "channel_paths": "{}",
            "registration_channel": "0",
            "include_in_stack": "True",
            "qc_status": "pending",
        }
    ]
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    result = suggest_atlas_indices(
        manifest_path,
        config=AtlasIndexSuggestionConfig(
            atlas_name="fake",
            start_slice_index=3,
            search_radius_slices=0,
            top_n=2,
            atlas_plane_angle_search=True,
            atlas_plane_pitch_degrees=(0.0, 5.0),
            atlas_plane_yaw_degrees=(0.0,),
        ),
    )

    candidate_rows = list(csv.DictReader(result.candidate_manifest_path.open(newline="", encoding="utf-8")))
    selected_rows = list(csv.DictReader(result.selected_manifest_path.open(newline="", encoding="utf-8")))
    choices = list(csv.DictReader(result.selected_choices_path.open(newline="", encoding="utf-8")))

    assert len(candidate_rows) == 2
    assert {float(row["atlas_plane_pitch_degrees"]) for row in candidate_rows} == {0.0, 5.0}
    assert all(float(row["atlas_plane_yaw_degrees"]) == 0.0 for row in candidate_rows)
    assert "atlas_plane_pitch_degrees" in selected_rows[0]
    assert "selected_atlas_plane_pitch_degrees" in choices[0]
    assert "pitch" in Path(candidate_rows[0]["overlay_path"]).name


def test_suggest_atlas_indices_supports_independent_coarse_to_fine_search(tmp_path, monkeypatch):
    class FakeAtlas:
        orientation = "asr"
        resolution = (39.0, 39.0, 39.0)

        def __init__(self):
            self.reference = np.zeros((11, 40, 50), dtype=np.float32)
            self.annotation = np.zeros((11, 40, 50), dtype=np.uint16)
            self.reference[4, 12:28, 18:32] = 80
            self.annotation[4, 12:28, 18:32] = 1
            self.reference[8, 10:30, 14:36] = 120
            self.annotation[8, 10:30, 14:36] = 1

    monkeypatch.setattr("brain_section_pipeline.atlas_indexing._load_atlas", lambda atlas_name: FakeAtlas())

    section_path = tmp_path / "section001.tif"
    section = np.zeros((40, 50), dtype=np.float32)
    section[10:30, 14:36] = 500
    imwrite(section_path, section)

    manifest_path = tmp_path / "section_manifest.csv"
    rows = [
        {
            "sample_id": "rat_01",
            "atlas_name": "fake",
            "source_file": "slide.nd2",
            "slide_number": "1",
            "slide_id": "slide",
            "section_index": "1",
            "crop_path_rgb": str(section_path),
            "crop_path_registration": str(section_path),
            "raw_crop_path": str(section_path),
            "channel_count": "1",
            "channel_paths": "{}",
            "registration_channel": "0",
            "include_in_stack": "True",
            "qc_status": "pending",
        }
    ]
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    result = suggest_atlas_indices(
        manifest_path,
        config=AtlasIndexSuggestionConfig(
            atlas_name="fake",
            start_slice_index=5,
            search_radius_slices=5,
            search_stride_slices=4,
            search_refine_radius_slices=1,
            top_n=3,
        ),
    )

    selected_rows = list(csv.DictReader(result.selected_manifest_path.open(newline="", encoding="utf-8")))
    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))

    assert selected_rows[0]["atlas_slice_index"]
    assert Path(selected_rows[0]["atlas_reference_path"]).exists()
    assert Path(selected_rows[0]["atlas_annotation_path"]).exists()
    assert metadata["config"]["search_stride_slices"] == 4
    assert metadata["config"]["search_refine_radius_slices"] == 1


def test_export_selected_atlas_previews_from_existing_selected_manifest(tmp_path):
    reference_path = tmp_path / "atlas_reference.tif"
    annotation_path = tmp_path / "atlas_annotation.tif"
    reference = np.zeros((32, 40), dtype=np.float32)
    reference[8:26, 9:31] = 100.0
    annotation = np.zeros((32, 40), dtype=np.uint16)
    annotation[10:24, 12:28] = 1
    imwrite(reference_path, reference)
    imwrite(annotation_path, annotation)

    manifest_path = tmp_path / "selected_slice_atlas_manifest.csv"
    rows = [
        {
            "section_index": "1",
            "atlas_slice_index": "439",
            "atlas_ap_mm": "2.847",
            "atlas_native_ap_mm": "2.847",
            "ap_coordinate_system": "paxinos",
            "atlas_reference_path": str(reference_path),
            "atlas_annotation_path": str(annotation_path),
        }
    ]
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    result = export_selected_atlas_previews(manifest_path)

    assert len(result.preview_paths) == 1
    assert result.preview_paths[0].exists()
    assert result.contact_sheet_path is not None
    assert result.contact_sheet_path.exists()
    preview = Image.open(result.preview_paths[0]).convert("RGB")
    assert preview.width > 0
    assert preview.height > reference.shape[0]


def test_suggest_atlas_indices_can_lock_later_sections_to_first_selected_spacing(tmp_path, monkeypatch):
    class FakeAtlas:
        orientation = "asr"
        resolution = (39.0, 39.0, 39.0)

        def __init__(self):
            self.reference = np.zeros((7, 40, 50), dtype=np.float32)
            self.annotation = np.zeros((7, 40, 50), dtype=np.uint16)
            self.reference[2, 10:30, 14:36] = 120
            self.annotation[2, 10:30, 14:36] = 1
            self.reference[3, 12:28, 18:32] = 90
            self.annotation[3, 12:28, 18:32] = 1
            self.reference[4, 5:34, 9:43] = 120
            self.annotation[4, 5:34, 9:43] = 1

    monkeypatch.setattr("brain_section_pipeline.atlas_indexing._load_atlas", lambda atlas_name: FakeAtlas())

    section_dir = tmp_path / "sections"
    section_dir.mkdir()
    section_one_path = section_dir / "section001.tif"
    section_two_path = section_dir / "section002.tif"

    section_one = np.zeros((40, 50), dtype=np.float32)
    section_one[10:30, 14:36] = 500
    imwrite(section_one_path, section_one)

    section_two = np.zeros((40, 50), dtype=np.float32)
    section_two[5:34, 9:43] = 500
    imwrite(section_two_path, section_two)

    manifest_path = tmp_path / "section_manifest.csv"
    rows = [
        {
            "sample_id": "rat_01",
            "atlas_name": "fake",
            "source_file": "slide.nd2",
            "slide_number": "1",
            "slide_id": "slide",
            "section_index": str(section_index),
            "crop_path_rgb": str(section_path),
            "crop_path_registration": str(section_path),
            "raw_crop_path": str(section_path),
            "channel_count": "1",
            "channel_paths": "{}",
            "registration_channel": "0",
            "include_in_stack": "True",
            "qc_status": "pending",
        }
        for section_index, section_path in ((1, section_one_path), (2, section_two_path))
    ]
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    result = suggest_atlas_indices(
        manifest_path,
        config=AtlasIndexSuggestionConfig(
            atlas_name="fake",
            start_slice_index=6,
            section_interval_um=39.0,
            direction="posterior",
            selection_strategy="spacing_locked",
            search_radius_slices=1,
            anchor_search_radius_slices=4,
            anchor_search_stride_slices=2,
            anchor_refine_radius_slices=0,
            top_n=3,
        ),
    )

    choices = list(csv.DictReader(result.selected_choices_path.open(newline="", encoding="utf-8")))
    candidate_rows = list(csv.DictReader(result.candidate_manifest_path.open(newline="", encoding="utf-8")))
    selected_section_one = [
        row for row in candidate_rows if row["section_index"] == "1" and row["is_selected"] == "True"
    ][0]
    selected_section_two = [
        row for row in candidate_rows if row["section_index"] == "2" and row["is_selected"] == "True"
    ][0]

    assert [row["selected_atlas_slice_index"] for row in choices] == ["2", "3"]
    assert choices[1]["selection_strategy"] == "spacing_locked"
    assert selected_section_one["search_radius_slices"] == "4"
    assert selected_section_two["search_radius_slices"] == "1"
    assert selected_section_two["atlas_slice_index"] == "3"


def test_suggest_atlas_indices_respects_ap_bounds(tmp_path, monkeypatch):
    class FakeAtlas:
        orientation = "asr"
        resolution = (39.0, 39.0, 39.0)

        def __init__(self):
            self.reference = np.zeros((7, 40, 50), dtype=np.float32)
            self.annotation = np.zeros((7, 40, 50), dtype=np.uint16)
            self.reference[1, 6:35, 8:42] = 90
            self.annotation[1, 6:35, 8:42] = 1
            self.reference[2, 10:30, 14:36] = 120
            self.annotation[2, 10:30, 14:36] = 1
            self.reference[3, 12:28, 18:32] = 90
            self.annotation[3, 12:28, 18:32] = 1

    monkeypatch.setattr("brain_section_pipeline.atlas_indexing._load_atlas", lambda atlas_name: FakeAtlas())

    section_path = tmp_path / "section001.tif"
    section = np.zeros((40, 50), dtype=np.float32)
    section[10:30, 14:36] = 500
    imwrite(section_path, section)

    manifest_path = tmp_path / "section_manifest.csv"
    rows = [
        {
            "sample_id": "rat_01",
            "atlas_name": "fake",
            "source_file": "slide.nd2",
            "slide_number": "1",
            "slide_id": "slide",
            "section_index": "1",
            "crop_path_rgb": str(section_path),
            "crop_path_registration": str(section_path),
            "raw_crop_path": str(section_path),
            "channel_count": "1",
            "channel_paths": "{}",
            "registration_channel": "0",
            "include_in_stack": "True",
            "qc_status": "pending",
        }
    ]
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    result = suggest_atlas_indices(
        manifest_path,
        config=AtlasIndexSuggestionConfig(
            atlas_name="fake",
            start_slice_index=6,
            search_radius_slices=6,
            min_ap_mm=0.04,
            max_ap_mm=0.07,
            top_n=3,
        ),
    )

    choices = list(csv.DictReader(result.selected_choices_path.open(newline="", encoding="utf-8")))
    candidate_rows = list(csv.DictReader(result.candidate_manifest_path.open(newline="", encoding="utf-8")))

    assert choices[0]["selected_atlas_slice_index"] == "2"
    assert {row["atlas_slice_index"] for row in candidate_rows} == {"2"}
    assert "base_score" in candidate_rows[0]
    assert "ap_prior_penalty" in candidate_rows[0]


def test_suggest_atlas_indices_respects_paxinos_ap_bounds_with_offset(tmp_path, monkeypatch):
    class FakeAtlas:
        orientation = "asr"
        resolution = (39.0, 39.0, 39.0)

        def __init__(self):
            self.reference = np.zeros((7, 40, 50), dtype=np.float32)
            self.annotation = np.zeros((7, 40, 50), dtype=np.uint16)
            self.reference[1, 6:35, 8:42] = 90
            self.annotation[1, 6:35, 8:42] = 1
            self.reference[2, 10:30, 14:36] = 120
            self.annotation[2, 10:30, 14:36] = 1
            self.reference[3, 12:28, 18:32] = 90
            self.annotation[3, 12:28, 18:32] = 1

    monkeypatch.setattr("brain_section_pipeline.atlas_indexing._load_atlas", lambda atlas_name: FakeAtlas())

    section_path = tmp_path / "section001.tif"
    section = np.zeros((40, 50), dtype=np.float32)
    section[10:30, 14:36] = 500
    imwrite(section_path, section)

    manifest_path = tmp_path / "section_manifest.csv"
    rows = [
        {
            "sample_id": "rat_01",
            "atlas_name": "fake",
            "source_file": "slide.nd2",
            "slide_number": "1",
            "slide_id": "slide",
            "section_index": "1",
            "crop_path_rgb": str(section_path),
            "crop_path_registration": str(section_path),
            "raw_crop_path": str(section_path),
            "channel_count": "1",
            "channel_paths": "{}",
            "registration_channel": "0",
            "include_in_stack": "True",
            "qc_status": "pending",
        }
    ]
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    result = suggest_atlas_indices(
        manifest_path,
        config=AtlasIndexSuggestionConfig(
            atlas_name="fake",
            start_slice_index=6,
            search_radius_slices=6,
            ap_coordinate_system="paxinos",
            ap_coordinate_offset_mm=0.5,
            min_ap_mm=-0.45,
            max_ap_mm=-0.43,
            top_n=3,
        ),
    )

    choices = list(csv.DictReader(result.selected_choices_path.open(newline="", encoding="utf-8")))
    candidate_rows = list(csv.DictReader(result.candidate_manifest_path.open(newline="", encoding="utf-8")))
    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))

    assert choices[0]["selected_atlas_slice_index"] == "2"
    assert {row["atlas_slice_index"] for row in candidate_rows} == {"2"}
    assert choices[0]["ap_coordinate_system"] == "paxinos"
    assert float(choices[0]["selected_ap_mm"]) == pytest.approx(-0.4415)
    assert float(choices[0]["selected_native_ap_mm"]) == pytest.approx(0.0585)
    assert float(candidate_rows[0]["atlas_ap_mm"]) == pytest.approx(-0.4415)
    assert float(candidate_rows[0]["atlas_native_ap_mm"]) == pytest.approx(0.0585)
    assert metadata["ap_coordinate_system"] == "paxinos"
    assert metadata["ap_coordinate_offset_mm"] == pytest.approx(0.5)


def test_suggest_atlas_indices_can_estimate_ap_bounds_from_first_section(tmp_path, monkeypatch):
    class FakeAtlas:
        orientation = "asr"
        resolution = (39.0, 39.0, 39.0)

        def __init__(self):
            self.reference = np.zeros((7, 40, 50), dtype=np.float32)
            self.annotation = np.zeros((7, 40, 50), dtype=np.uint16)
            self.reference[1, 6:35, 8:42] = 90
            self.annotation[1, 6:35, 8:42] = 1
            self.reference[2, 10:30, 14:36] = 120
            self.annotation[2, 10:30, 14:36] = 1
            self.reference[3, 12:28, 18:32] = 90
            self.annotation[3, 12:28, 18:32] = 1

    monkeypatch.setattr("brain_section_pipeline.atlas_indexing._load_atlas", lambda atlas_name: FakeAtlas())

    section_path = tmp_path / "section001.tif"
    section = np.zeros((40, 50), dtype=np.float32)
    section[10:30, 14:36] = 500
    imwrite(section_path, section)

    manifest_path = tmp_path / "section_manifest.csv"
    rows = [
        {
            "sample_id": "rat_01",
            "atlas_name": "fake",
            "source_file": "slide.nd2",
            "slide_number": "1",
            "slide_id": "slide",
            "section_index": "1",
            "crop_path_rgb": str(section_path),
            "crop_path_registration": str(section_path),
            "raw_crop_path": str(section_path),
            "channel_count": "1",
            "channel_paths": "{}",
            "registration_channel": "0",
            "include_in_stack": "True",
            "qc_status": "pending",
        }
    ]
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    result = suggest_atlas_indices(
        manifest_path,
        config=AtlasIndexSuggestionConfig(
            atlas_name="fake",
            start_slice_index=6,
            search_radius_slices=6,
            auto_ap_range=True,
            auto_ap_range_stride_slices=1,
            auto_ap_range_top_n=1,
            auto_ap_range_padding_mm=0.001,
            top_n=3,
        ),
    )

    choices = list(csv.DictReader(result.selected_choices_path.open(newline="", encoding="utf-8")))
    candidate_rows = list(csv.DictReader(result.candidate_manifest_path.open(newline="", encoding="utf-8")))
    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))

    assert choices[0]["selected_atlas_slice_index"] == "2"
    assert {row["atlas_slice_index"] for row in candidate_rows} == {"2"}
    assert metadata["auto_ap_range"]["best_atlas_slice_index"] == 2
    assert float(choices[0]["effective_min_ap_mm"]) < float(choices[0]["effective_max_ap_mm"])


def test_generate_slice_atlas_qc_writes_overlay_images(tmp_path):
    pairing_dir = tmp_path / "slice_atlas"
    section_dir = pairing_dir / "sections"
    reference_dir = pairing_dir / "atlas_reference"
    annotation_dir = pairing_dir / "atlas_annotation"
    section_dir.mkdir(parents=True)
    reference_dir.mkdir(parents=True)
    annotation_dir.mkdir(parents=True)

    section = np.zeros((20, 30), dtype=np.uint16)
    section[5:15, 8:22] = 200
    atlas_reference = np.zeros((40, 50), dtype=np.uint16)
    atlas_reference[8:32, 10:40] = 150
    atlas_annotation = np.zeros((40, 50), dtype=np.uint16)
    atlas_annotation[10:30, 15:35] = 1

    imwrite(section_dir / "section001_section.tif", section)
    imwrite(reference_dir / "section001_atlas_reference.tif", atlas_reference)
    imwrite(annotation_dir / "section001_atlas_annotation.tif", atlas_annotation)

    manifest_path = pairing_dir / "slice_atlas_manifest.csv"
    rows = [
        {
            "section_index": "1",
            "atlas_slice_index": "12",
            "atlas_reference_path": str(reference_dir / "section001_atlas_reference.tif"),
            "atlas_annotation_path": str(annotation_dir / "section001_atlas_annotation.tif"),
            "section_source_path": str(section_dir / "section001_section.tif"),
        }
    ]
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    result = generate_slice_atlas_qc(manifest_path, config=SliceAtlasQcConfig())

    assert len(result.overlay_paths) == 1
    overlay = np.asarray(Image.open(result.overlay_paths[0]))
    assert overlay.shape == (40, 50, 3)
    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    assert metadata["rows"][0]["atlas_slice_index"] == 12


def test_register_slices_to_atlas_writes_warped_outputs_and_metrics(tmp_path):
    pairing_dir = tmp_path / "slice_atlas"
    section_dir = pairing_dir / "sections"
    reference_dir = pairing_dir / "atlas_reference"
    annotation_dir = pairing_dir / "atlas_annotation"
    section_dir.mkdir(parents=True)
    reference_dir.mkdir(parents=True)
    annotation_dir.mkdir(parents=True)

    atlas_reference = np.zeros((80, 100), dtype=np.float32)
    atlas_reference[18:62, 24:78] = 80
    atlas_reference[26:56, 34:68] = 180
    atlas_annotation = np.zeros((80, 100), dtype=np.uint16)
    atlas_annotation[20:60, 28:74] = 1

    true_transform = slice_registration_module._similarity_matrix(
        scale=0.84,
        rotation_radians=np.deg2rad(14.0),
        translation_y=34.0,
        translation_x=56.0,
        source_shape=atlas_reference.shape,
    )
    section = slice_registration_module._warp_image(
        atlas_reference,
        true_transform,
        atlas_reference.shape,
        order=1,
        fill_value=0.0,
    ).astype(np.float32)

    imwrite(section_dir / "section001_section.tif", section)
    imwrite(reference_dir / "section001_atlas_reference.tif", atlas_reference.astype(np.float32))
    imwrite(annotation_dir / "section001_atlas_annotation.tif", atlas_annotation)

    manifest_path = pairing_dir / "slice_atlas_manifest.csv"
    rows = [
        {
            "section_index": "1",
            "atlas_slice_index": "12",
            "atlas_reference_path": str(reference_dir / "section001_atlas_reference.tif"),
            "atlas_annotation_path": str(annotation_dir / "section001_atlas_annotation.tif"),
            "section_source_path": str(section_dir / "section001_section.tif"),
        }
    ]
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    result = register_slices_to_atlas(
        manifest_path,
        config=SliceRegistrationConfig(max_rotation_degrees=30.0, save_individual_overlays=True),
    )

    with result.manifest_path.open("r", encoding="utf-8", newline="") as handle:
        registered_rows = list(csv.DictReader(handle))

    assert len(result.section_indices) == 1
    assert Path(registered_rows[0]["warped_section_path"]).exists()
    assert Path(registered_rows[0]["registration_overlay_path"]).exists()
    assert result.contact_sheet_path is not None
    assert result.contact_sheet_path.exists()
    assert float(registered_rows[0]["registration_dice"]) > 0.75

    warped = imread(registered_rows[0]["warped_section_path"])
    assert warped.shape == atlas_reference.shape

    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    assert metadata["rows"][0]["registration_dice"] > 0.75

    compact_result = register_slices_to_atlas(
        manifest_path,
        pairing_dir / "compact_registration",
        config=SliceRegistrationConfig(max_rotation_degrees=30.0, low_quality_dice_threshold=0.0, save_mask_diagnostics=True),
    )
    compact_rows = list(csv.DictReader(compact_result.manifest_path.open(encoding="utf-8", newline="")))
    assert compact_rows[0]["registration_overlay_path"] == ""
    assert compact_result.contact_sheet_path is not None
    assert compact_result.contact_sheet_path.exists()
    assert not compact_result.overlay_dir.exists()
    assert compact_result.mask_diagnostics_path is not None
    assert compact_result.mask_diagnostics_sheet_path is not None
    assert compact_result.mask_diagnostics_sheet_path.exists()
    comparison = list(csv.DictReader(compact_result.mask_diagnostics_path.open(encoding="utf-8", newline="")))
    assert len(comparison) == 1
    assert 0.0 <= float(comparison[0]["bright_dice"]) <= 1.0
    assert 0.0 <= float(comparison[0]["envelope_dice"]) <= 1.0
    assert result.mask_diagnostics_path is None
    assert result.mask_diagnostics_sheet_path is None


def test_slice_registration_initial_scale_uses_bbox_fit_by_default():
    section_mask = np.zeros((100, 220), dtype=bool)
    section_mask[10:90, 20:180] = True
    atlas_mask = np.zeros((80, 100), dtype=bool)
    atlas_mask[20:60, 30:70] = True
    atlas_bbox = slice_registration_module._bbox(atlas_mask)

    bbox_fit = slice_registration_module._initial_similarity_parameters(
        section_mask,
        atlas_mask,
        atlas_bbox,
        SliceRegistrationConfig(),
    )
    area_based = slice_registration_module._initial_similarity_parameters(
        section_mask,
        atlas_mask,
        atlas_bbox,
        SliceRegistrationConfig(scale_initialization="area", initial_rotation_degrees=None),
    )

    assert bbox_fit[0] == pytest.approx(0.25)
    assert bbox_fit[1] == pytest.approx(0.0)
    assert bbox_fit[0] < area_based[0]


def test_slice_registration_tissue_centroid_initialization_maps_tissue_to_atlas_centroid():
    section_mask = np.zeros((20, 30), dtype=bool)
    section_mask[5:15, 3:13] = True
    atlas_mask = np.zeros((40, 50), dtype=bool)
    atlas_mask[10:30, 15:35] = True
    atlas_bbox = slice_registration_module._bbox(atlas_mask)

    params = slice_registration_module._initial_similarity_parameters(
        section_mask,
        atlas_mask,
        atlas_bbox,
        SliceRegistrationConfig(
            translation_initialization="tissue_centroid",
            initial_rotation_degrees=0.0,
        ),
    )
    matrix = slice_registration_module._similarity_matrix(params[0], params[1], params[2], params[3], section_mask.shape)
    section_centroid = np.asarray(slice_registration_module._mask_centroid(section_mask))
    atlas_centroid = np.asarray(slice_registration_module._mask_centroid(atlas_mask))
    mapped_section_centroid = matrix[:2, :2] @ section_centroid + matrix[:2, 2]

    assert mapped_section_centroid == pytest.approx(atlas_centroid)


def test_compose_overlay_can_hide_crop_background_outside_tissue_mask():
    warped_section = np.full((20, 30), 25.0, dtype=np.float32)
    warped_section[5:15, 8:22] = 200.0
    atlas_reference = np.full((20, 30), 100.0, dtype=np.float32)
    atlas_mask = np.zeros((20, 30), dtype=bool)
    atlas_mask[4:16, 7:23] = True
    section_mask = np.zeros((20, 30), dtype=bool)
    section_mask[5:15, 8:22] = True
    config = SliceRegistrationConfig(
        atlas_color=(180, 180, 180),
        section_color=(255, 96, 96),
        boundary_color=(0, 255, 0),
        overlay_alpha=0.5,
        mask_overlay_to_tissue=True,
    )

    overlay = slice_registration_module._compose_overlay(
        warped_section,
        atlas_reference,
        atlas_mask,
        config,
        section_mask=section_mask,
    )
    atlas_gray = slice_registration_module._normalize_uint8(atlas_reference)
    expected_background = np.asarray(
        [(1.0 - config.overlay_alpha) * atlas_gray[1, 1] * (channel / 255.0) for channel in config.atlas_color],
        dtype=np.uint8,
    )

    assert overlay[1, 1] == pytest.approx(expected_background)
    assert overlay[10, 15, 0] > overlay[1, 1, 0]


def test_display_tissue_mask_is_more_permissive_than_registration_mask():
    image = np.zeros((40, 60), dtype=np.float32)
    image[8:32, 10:50] = 20.0
    image[14:26, 22:38] = 100.0
    config = SliceRegistrationConfig(
        tissue_threshold_quantile=0.8,
        overlay_mask_threshold_quantile=0.3,
        overlay_mask_dilation_px=0,
    )

    registration_mask = slice_registration_module._tissue_mask(image, quantile=config.tissue_threshold_quantile)
    display_mask = slice_registration_module._display_tissue_mask(image, config)

    assert display_mask.sum() > registration_mask.sum()
    assert display_mask[10, 12]
    assert not registration_mask[10, 12]


def test_registration_envelope_uses_dim_tissue_with_bright_crop_and_preserves_bright_mode():
    image = np.zeros((80, 120), dtype=np.float32)
    image[15:65, 20:35] = 20.0
    image[15:65, 85:100] = 20.0
    image[50:65, 20:100] = 20.0
    image[15:25, 20:35] = 100.0
    image[15:25, 85:100] = 100.0
    image[55:65, 50:70] = 100.0

    envelope = slice_registration_module._prepare_section_registration_input(image, SliceRegistrationConfig())
    bright = slice_registration_module._prepare_section_registration_input(
        image, SliceRegistrationConfig(tissue_mask_mode="bright")
    )

    assert envelope is not None
    assert bright is not None
    assert np.array_equal(envelope.section_crop, bright.section_crop)
    assert np.array_equal(bright.section_mask_crop, bright.section_bright_mask_crop)
    assert envelope.section_mask_crop.sum() > bright.section_mask_crop.sum()
    assert envelope.section_mask_crop[30, 5]
    assert not bright.section_mask_crop[30, 5]


def test_mask_comparison_metrics_use_the_same_atlas_area_for_both_masks():
    atlas = np.zeros((10, 10), dtype=bool)
    atlas[2:8, 2:8] = True
    bright = np.zeros_like(atlas)
    bright[3:7, 3:7] = True
    envelope = np.zeros_like(atlas)
    envelope[2:8, 2:8] = True
    envelope[2, 1] = True

    bright_metrics = slice_registration_module._mask_comparison_metrics(bright, atlas)
    envelope_metrics = slice_registration_module._mask_comparison_metrics(envelope, atlas)

    assert bright_metrics["dice"] == pytest.approx(32 / 52)
    assert bright_metrics["inside_fraction"] == pytest.approx(1.0)
    assert envelope_metrics["area_ratio"] == pytest.approx(37 / 36)
    assert envelope_metrics["inside_fraction"] == pytest.approx(36 / 37)
    assert envelope_metrics["dice"] == pytest.approx(72 / 73)


def test_mask_diagnostics_reject_nonlinear_refinement_before_creating_outputs(tmp_path):
    output_dir = tmp_path / "registration"
    manifest_path = tmp_path / "pairing.csv"
    manifest_path.write_text("section_index\n1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="nonlinear_refinement_model"):
        register_slices_to_atlas(
            manifest_path,
            output_dir,
            config=SliceRegistrationConfig(save_mask_diagnostics=True, nonlinear_refinement_model="boundary_spline"),
        )
    assert not output_dir.exists()


def test_slice_registration_loss_penalizes_oversized_warped_masks():
    section_mask = np.ones((20, 20), dtype=np.float32)
    atlas_mask = np.zeros((60, 60), dtype=np.float32)
    atlas_mask[20:40, 20:40] = 1.0
    config = SliceRegistrationConfig(area_loss_weight=0.2, extent_loss_weight=0.6)

    fit_params = np.array([1.0, 0.0, 29.5, 29.5], dtype=np.float64)
    oversized_params = np.array([2.0, 0.0, 29.5, 29.5], dtype=np.float64)

    fit_loss = slice_registration_module._registration_loss(fit_params, section_mask, atlas_mask, atlas_mask.shape, config)
    oversized_loss = slice_registration_module._registration_loss(
        oversized_params,
        section_mask,
        atlas_mask,
        atlas_mask.shape,
        config,
    )

    assert fit_loss < oversized_loss


def test_boundary_fit_loss_penalizes_visible_boundary_outside_atlas():
    section_mask = np.ones((20, 20), dtype=np.float32)
    boundary_mask = np.ones((28, 28), dtype=np.float32)
    atlas_mask = np.zeros((60, 60), dtype=np.float32)
    atlas_mask[16:44, 16:44] = 1.0
    config = SliceRegistrationConfig(
        area_loss_weight=0.0,
        extent_loss_weight=0.0,
        center_loss_weight=0.0,
        boundary_fit_weight=0.3,
        boundary_containment_weight=1.5,
    )

    contained_params = np.array([1.0, 0.0, 29.5, 29.5], dtype=np.float64)
    oversized_params = np.array([1.4, 0.0, 29.5, 29.5], dtype=np.float64)

    contained_loss = slice_registration_module._registration_loss(
        contained_params,
        section_mask,
        atlas_mask,
        atlas_mask.shape,
        config,
        section_boundary_mask=boundary_mask,
    )
    oversized_loss = slice_registration_module._registration_loss(
        oversized_params,
        section_mask,
        atlas_mask,
        atlas_mask.shape,
        config,
        section_boundary_mask=boundary_mask,
    )

    assert contained_loss < oversized_loss


def test_affine_regularization_penalizes_anisotropy_and_shear():
    config = SliceRegistrationConfig(
        max_affine_anisotropy=0.10,
        max_affine_shear=0.04,
        affine_regularization_weight=0.08,
    )

    no_affine = slice_registration_module._affine_regularization_penalty(0.0, 0.0, config)
    moderate_affine = slice_registration_module._affine_regularization_penalty(0.05, 0.02, config)
    max_affine = slice_registration_module._affine_regularization_penalty(0.10, 0.04, config)

    assert no_affine == pytest.approx(0.0)
    assert 0.0 < moderate_affine < max_affine


def test_slice_registration_affine_model_reports_bounded_affine_metadata():
    section_image = np.zeros((60, 80), dtype=np.float32)
    section_image[14:48, 18:58] = 200.0
    atlas_reference = np.zeros((60, 80), dtype=np.float32)
    atlas_reference[12:50, 20:56] = 100.0
    atlas_mask = np.zeros((60, 80), dtype=bool)
    atlas_mask[12:50, 20:56] = True
    config = SliceRegistrationConfig(
        transform_model="affine",
        tissue_threshold_quantile=0.5,
        max_rotation_degrees=0.0,
        min_scale_factor=0.9,
        max_scale_factor=1.05,
        max_affine_anisotropy=0.10,
        max_affine_shear=0.04,
        affine_regularization_weight=0.08,
    )

    _, registration = slice_registration_module._register_section_to_atlas(
        section_image=section_image,
        atlas_reference=atlas_reference,
        atlas_mask=atlas_mask,
        config=config,
    )

    assert registration["status"] == "ok"
    assert registration["transform_model"] == "affine"
    assert abs(registration["affine_anisotropy"]) <= config.max_affine_anisotropy
    assert abs(registration["affine_shear"]) <= config.max_affine_shear
    assert registration["affine_regularization_penalty"] >= 0.0
    assert registration["scale_y"] > 0.0
    assert registration["scale_x"] > 0.0


def test_boundary_spline_refinement_reduces_shifted_boundary_distance():
    atlas_mask = np.zeros((80, 90), dtype=bool)
    atlas_mask[24:56, 28:62] = True
    shifted_mask = np.zeros_like(atlas_mask)
    shifted_mask[27:59, 32:66] = True
    config = SliceRegistrationConfig(
        nonlinear_refinement_model="boundary_spline",
        nonlinear_max_displacement_px=6.0,
        nonlinear_control_point_spacing_px=8.0,
        nonlinear_iterations=1,
        nonlinear_boundary_sample_step=1,
    )

    before = slice_registration_module._boundary_distance_metric_value(shifted_mask, atlas_mask)
    _, refined_mask, _, refined_boundary, metadata = slice_registration_module._apply_boundary_spline_refinement(
        warped_section=shifted_mask.astype(np.float32),
        warped_mask=shifted_mask,
        warped_display_mask=shifted_mask,
        warped_boundary_mask=shifted_mask,
        atlas_mask=atlas_mask,
        config=config,
    )
    after = slice_registration_module._boundary_distance_metric_value(refined_boundary, atlas_mask)

    assert metadata["nonlinear_refinement_model"] == "boundary_spline"
    assert metadata["nonlinear_iterations_completed"] == 1
    assert 0.0 < metadata["nonlinear_max_displacement_px"] <= config.nonlinear_max_displacement_px
    assert refined_mask.shape == atlas_mask.shape
    assert after < before


def test_slice_registration_respects_zero_rotation_search_bound():
    section_mask = np.zeros((30, 50), dtype=np.float32)
    section_mask[5:25, 8:42] = 1.0
    atlas_mask = np.zeros((40, 60), dtype=np.float32)
    atlas_mask[10:30, 13:47] = 1.0

    params, _ = slice_registration_module._estimate_similarity_parameters(
        section_mask_crop=section_mask,
        section_boundary_mask_crop=section_mask,
        atlas_mask=atlas_mask,
        initial=(1.0, 0.0, 20.0, 30.0),
        config=SliceRegistrationConfig(max_rotation_degrees=0.0),
    )

    assert np.rad2deg(params[1]) == pytest.approx(0.0)


def test_register_slices_to_atlas_handles_empty_masks(tmp_path):
    pairing_dir = tmp_path / "slice_atlas"
    section_dir = pairing_dir / "sections"
    reference_dir = pairing_dir / "atlas_reference"
    annotation_dir = pairing_dir / "atlas_annotation"
    section_dir.mkdir(parents=True)
    reference_dir.mkdir(parents=True)
    annotation_dir.mkdir(parents=True)

    blank = np.zeros((30, 40), dtype=np.uint16)
    imwrite(section_dir / "section001_section.tif", blank)
    imwrite(reference_dir / "section001_atlas_reference.tif", blank)
    imwrite(annotation_dir / "section001_atlas_annotation.tif", blank)

    manifest_path = pairing_dir / "slice_atlas_manifest.csv"
    rows = [
        {
            "section_index": "1",
            "atlas_slice_index": "0",
            "atlas_reference_path": str(reference_dir / "section001_atlas_reference.tif"),
            "atlas_annotation_path": str(annotation_dir / "section001_atlas_annotation.tif"),
            "section_source_path": str(section_dir / "section001_section.tif"),
        }
    ]
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    result = register_slices_to_atlas(manifest_path, config=SliceRegistrationConfig(save_mask_diagnostics=True))

    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    assert metadata["rows"][0]["registration_status"] == "empty_mask"
    diagnostic_rows = list(csv.DictReader(result.mask_diagnostics_path.open(encoding="utf-8", newline="")))
    assert float(diagnostic_rows[0]["bright_dice"]) == 0.0
    assert float(diagnostic_rows[0]["envelope_dice"]) == 0.0


def test_summarize_registered_slices_by_region_writes_section_and_aggregate_rows(tmp_path, monkeypatch):
    registration_dir = tmp_path / "slice_registration"
    warped_dir = registration_dir / "warped_sections"
    annotation_dir = registration_dir / "atlas_annotation"
    warped_dir.mkdir(parents=True)
    annotation_dir.mkdir(parents=True)

    section_one = np.array(
        [
            [0, 0, 0, 0],
            [0, 2, 4, 0],
            [0, 6, 8, 0],
            [0, 0, 0, 0],
        ],
        dtype=np.float32,
    )
    section_two = np.array(
        [
            [0, 0, 0, 0],
            [0, 1, 3, 0],
            [0, 5, 7, 0],
            [0, 0, 0, 0],
        ],
        dtype=np.float32,
    )
    annotation = np.array(
        [
            [0, 0, 0, 0],
            [0, 1, 1, 0],
            [0, 2, 2, 0],
            [0, 0, 0, 0],
        ],
        dtype=np.uint16,
    )

    warped_one_path = warped_dir / "section001_warped.tif"
    warped_two_path = warped_dir / "section002_warped.tif"
    annotation_one_path = annotation_dir / "section001_atlas_annotation.tif"
    annotation_two_path = annotation_dir / "section002_atlas_annotation.tif"
    imwrite(warped_one_path, section_one)
    imwrite(warped_two_path, section_two)
    imwrite(annotation_one_path, annotation)
    imwrite(annotation_two_path, annotation)

    manifest_path = registration_dir / "slice_registration_manifest.csv"
    rows = [
        {
            "section_index": "1",
            "atlas_name": "whs_sd_rat_39um",
            "atlas_slice_index": "12",
            "atlas_annotation_path": str(annotation_one_path),
            "warped_section_path": str(warped_one_path),
        },
        {
            "section_index": "2",
            "atlas_name": "whs_sd_rat_39um",
            "atlas_slice_index": "13",
            "atlas_annotation_path": str(annotation_two_path),
            "warped_section_path": str(warped_two_path),
        },
    ]
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    monkeypatch.setattr(
        "brain_section_pipeline.atlas_summary._load_structure_lookup",
        lambda atlas_name: {
            1: {"acronym": "REG1", "name": "Region 1"},
            2: {"acronym": "REG2", "name": "Region 2"},
        },
    )

    result = summarize_registered_slices_by_region(
        manifest_path,
        config=AtlasSummaryConfig(),
    )

    with result.per_section_summary_path.open("r", encoding="utf-8", newline="") as handle:
        section_rows = list(csv.DictReader(handle))
    with result.aggregate_summary_path.open("r", encoding="utf-8", newline="") as handle:
        aggregate_rows = list(csv.DictReader(handle))

    assert result.section_count == 2
    assert result.region_row_count == 4
    assert len(section_rows) == 4
    assert section_rows[0]["region_acronym"] == "REG1"
    assert float(section_rows[0]["intensity_sum"]) == 6.0
    assert float(section_rows[1]["intensity_sum"]) == 14.0

    aggregate_by_region = {int(row["region_id"]): row for row in aggregate_rows}
    assert aggregate_by_region[1]["region_name"] == "Region 1"
    assert int(aggregate_by_region[1]["section_count"]) == 2
    assert float(aggregate_by_region[1]["intensity_sum"]) == 10.0
    assert float(aggregate_by_region[1]["intensity_mean"]) == 2.5
    assert float(aggregate_by_region[2]["intensity_sum"]) == 26.0

    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    assert metadata["structure_metadata_attached"] is True


def test_summarize_registered_slices_by_region_handles_missing_structure_lookup(tmp_path, monkeypatch):
    registration_dir = tmp_path / "slice_registration"
    warped_dir = registration_dir / "warped_sections"
    annotation_dir = registration_dir / "atlas_annotation"
    warped_dir.mkdir(parents=True)
    annotation_dir.mkdir(parents=True)

    warped_path = warped_dir / "section001_warped.tif"
    annotation_path = annotation_dir / "section001_atlas_annotation.tif"
    imwrite(warped_path, np.array([[0, 1], [2, 3]], dtype=np.float32))
    imwrite(annotation_path, np.array([[0, 1], [1, 1]], dtype=np.uint16))

    manifest_path = registration_dir / "slice_registration_manifest.csv"
    rows = [
        {
            "section_index": "1",
            "atlas_name": "whs_sd_rat_39um",
            "atlas_slice_index": "1",
            "atlas_annotation_path": str(annotation_path),
            "warped_section_path": str(warped_path),
        }
    ]
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    monkeypatch.setattr("brain_section_pipeline.atlas_summary._load_structure_lookup", lambda atlas_name: {})

    result = summarize_registered_slices_by_region(manifest_path)

    with result.per_section_summary_path.open("r", encoding="utf-8", newline="") as handle:
        section_rows = list(csv.DictReader(handle))

    assert len(section_rows) == 1
    assert section_rows[0]["region_acronym"] == ""
    assert section_rows[0]["region_name"] == ""


def test_run_slicewise_atlas_workflow_orchestrates_all_sparse_stages(tmp_path, monkeypatch):
    input_path = tmp_path / "slide_01.nd2"
    input_path.write_text("placeholder", encoding="utf-8")

    call_order = []
    sample_dir = tmp_path / "outputs" / "rat_01"
    sample_dir.mkdir(parents=True)
    manifest_path = sample_dir / "section_manifest.csv"
    manifest_path.write_text("section_index\n1\n", encoding="utf-8")
    slice_dir = sample_dir / "slice_atlas"
    slice_dir.mkdir(parents=True)
    pairing_manifest = slice_dir / "slice_atlas_manifest.csv"
    pairing_manifest.write_text("section_index\n1\n", encoding="utf-8")
    registration_dir = slice_dir / "slice_registration"
    registration_dir.mkdir(parents=True)
    registration_manifest = registration_dir / "slice_registration_manifest.csv"
    registration_manifest.write_text("section_index\n1\n", encoding="utf-8")
    summary_dir = registration_dir / "atlas_summary"
    summary_dir.mkdir(parents=True)

    export_result = BrainGlobeExportResult(
        sample_dir=sample_dir,
        manifest_path=manifest_path,
        metadata_path=sample_dir / "sample_metadata.json",
        sections_rgb_dir=sample_dir / "sections_rgb",
        sections_registration_dir=sample_dir / "sections_registration",
        sections_channels_dir=sample_dir / "sections_channels",
        qc_dir=sample_dir / "qc",
        review_dir=sample_dir / "qc" / "section_review",
        slide_overlay_paths=[],
        section_montage_path=sample_dir / "qc" / "section_review" / "all_detected_sections.png",
        processing_results=[],
    )
    slice_result = workflow_module.SliceAtlasResult(
        output_dir=slice_dir,
        manifest_path=pairing_manifest,
        metadata_path=slice_dir / "slice_atlas_metadata.json",
        atlas_reference_dir=slice_dir / "atlas_reference",
        atlas_annotation_dir=slice_dir / "atlas_annotation",
        section_source_dir=slice_dir / "sections",
        section_indices=[1],
    )
    qc_result = workflow_module.SliceAtlasQcResult(
        output_dir=slice_dir / "qc_overlays",
        metadata_path=slice_dir / "qc_overlays" / "slice_atlas_qc.json",
        overlay_paths=[slice_dir / "qc_overlays" / "section001_overlay.png"],
    )
    registration_result = workflow_module.SliceRegistrationResult(
        output_dir=registration_dir,
        manifest_path=registration_manifest,
        metadata_path=registration_dir / "slice_registration_metadata.json",
        warped_sections_dir=registration_dir / "warped_sections",
        overlay_dir=registration_dir / "overlays",
        section_indices=[1],
    )
    summary_result = workflow_module.AtlasSummaryResult(
        output_dir=summary_dir,
        per_section_summary_path=summary_dir / "atlas_region_summary.csv",
        aggregate_summary_path=summary_dir / "atlas_region_aggregate.csv",
        metadata_path=summary_dir / "atlas_region_summary.json",
        section_count=1,
        region_row_count=2,
    )

    monkeypatch.setattr(
        workflow_module,
        "export_sections_for_brainglobe",
        lambda paths, output_dir, pipeline_config=None, export_config=None: call_order.append(("export", [Path(path) for path in paths])) or export_result,
    )
    monkeypatch.setattr(
        workflow_module,
        "prepare_slice_atlas_inputs",
        lambda manifest_path, config=None: call_order.append(("slice_atlas", Path(manifest_path))) or slice_result,
    )
    monkeypatch.setattr(
        workflow_module,
        "generate_slice_atlas_qc",
        lambda pairing_manifest_path, config=None: call_order.append(("qc", Path(pairing_manifest_path))) or qc_result,
    )
    monkeypatch.setattr(
        workflow_module,
        "register_slices_to_atlas",
        lambda pairing_manifest_path, config=None: call_order.append(("registration", Path(pairing_manifest_path))) or registration_result,
    )
    monkeypatch.setattr(
        workflow_module,
        "summarize_registered_slices_by_region",
        lambda registration_manifest_path, config=None: call_order.append(("summary", Path(registration_manifest_path))) or summary_result,
    )

    result = workflow_module.run_slicewise_atlas_workflow(
        input_path,
        tmp_path / "outputs",
        generate_qc=True,
    )

    assert result.export_result is export_result
    assert result.slice_atlas_result is slice_result
    assert result.qc_result is qc_result
    assert result.registration_result is registration_result
    assert result.summary_result is summary_result
    assert call_order == [
        ("export", [input_path]),
        ("slice_atlas", manifest_path),
        ("qc", pairing_manifest),
        ("registration", pairing_manifest),
        ("summary", registration_manifest),
    ]


def test_run_slicewise_atlas_workflow_can_skip_qc_and_summary(tmp_path, monkeypatch):
    input_path = tmp_path / "slide_01.nd2"
    input_path.write_text("placeholder", encoding="utf-8")

    sample_dir = tmp_path / "outputs" / "rat_01"
    sample_dir.mkdir(parents=True)
    manifest_path = sample_dir / "section_manifest.csv"
    manifest_path.write_text("section_index\n1\n", encoding="utf-8")
    slice_dir = sample_dir / "slice_atlas"
    slice_dir.mkdir(parents=True)
    pairing_manifest = slice_dir / "slice_atlas_manifest.csv"
    pairing_manifest.write_text("section_index\n1\n", encoding="utf-8")
    registration_dir = slice_dir / "slice_registration"
    registration_dir.mkdir(parents=True)
    registration_manifest = registration_dir / "slice_registration_manifest.csv"
    registration_manifest.write_text("section_index\n1\n", encoding="utf-8")

    export_result = BrainGlobeExportResult(
        sample_dir=sample_dir,
        manifest_path=manifest_path,
        metadata_path=sample_dir / "sample_metadata.json",
        sections_rgb_dir=sample_dir / "sections_rgb",
        sections_registration_dir=sample_dir / "sections_registration",
        sections_channels_dir=sample_dir / "sections_channels",
        qc_dir=sample_dir / "qc",
        review_dir=sample_dir / "qc" / "section_review",
        slide_overlay_paths=[],
        section_montage_path=sample_dir / "qc" / "section_review" / "all_detected_sections.png",
        processing_results=[],
    )
    slice_result = workflow_module.SliceAtlasResult(
        output_dir=slice_dir,
        manifest_path=pairing_manifest,
        metadata_path=slice_dir / "slice_atlas_metadata.json",
        atlas_reference_dir=slice_dir / "atlas_reference",
        atlas_annotation_dir=slice_dir / "atlas_annotation",
        section_source_dir=slice_dir / "sections",
        section_indices=[1],
    )
    registration_result = workflow_module.SliceRegistrationResult(
        output_dir=registration_dir,
        manifest_path=registration_manifest,
        metadata_path=registration_dir / "slice_registration_metadata.json",
        warped_sections_dir=registration_dir / "warped_sections",
        overlay_dir=registration_dir / "overlays",
        section_indices=[1],
    )

    monkeypatch.setattr(workflow_module, "export_sections_for_brainglobe", lambda *args, **kwargs: export_result)
    monkeypatch.setattr(workflow_module, "prepare_slice_atlas_inputs", lambda *args, **kwargs: slice_result)
    monkeypatch.setattr(workflow_module, "register_slices_to_atlas", lambda *args, **kwargs: registration_result)

    qc_called = {"value": False}
    summary_called = {"value": False}

    def _unexpected_qc(*args, **kwargs):
        qc_called["value"] = True
        raise AssertionError("QC stage should have been skipped.")

    def _unexpected_summary(*args, **kwargs):
        summary_called["value"] = True
        raise AssertionError("Summary stage should have been skipped.")

    monkeypatch.setattr(workflow_module, "generate_slice_atlas_qc", _unexpected_qc)
    monkeypatch.setattr(workflow_module, "summarize_registered_slices_by_region", _unexpected_summary)

    result = workflow_module.run_slicewise_atlas_workflow(
        input_path,
        tmp_path / "outputs",
        generate_qc=False,
        generate_summary=False,
    )

    assert result.qc_result is None
    assert result.summary_result is None
    assert qc_called["value"] is False
    assert summary_called["value"] is False
