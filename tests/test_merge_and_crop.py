import numpy as np
from tifffile import imread

from brain_section_pipeline import select_nd2_files_dialog
from brain_section_pipeline.crop import CropBox, crop_sections, detect_section_crops, save_crops, sort_crop_boxes
from brain_section_pipeline.merge import merge_channels, robust_scale
from brain_section_pipeline.pipeline import _raw_channels_to_rgb


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
