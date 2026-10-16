"""Small numerical and integration checks for anatomical slice refinement."""

import csv
import json
from types import SimpleNamespace

import numpy as np
import pytest
from tifffile import imread, imwrite

from brain_section_pipeline import apply_slice_registration_transform
from brain_section_pipeline import registration_refinement as refinement
from brain_section_pipeline import slice_registration as registration
from brain_section_pipeline.slice_registration import SliceRegistrationConfig


def _structure(shape=(64, 80)):
    yy, xx = np.indices(shape, dtype=float)
    return (10 + 130 * np.exp(-((yy-23)**2/40 + (xx-28)**2/60))
            + 80 * np.exp(-((yy-42)**2/60 + (xx-53)**2/30))).astype(np.float32)


def test_preparation_preserves_dim_tissue_outside_bright_bbox():
    image = np.zeros((96, 96), dtype=np.float32)
    image[20:80, 20:80] = 20
    image[40:64, 40:64] = 200
    prepared = registration._prepare_section_registration_input(image, SliceRegistrationConfig())
    y0, x0 = prepared.crop_origin_yx
    assert y0 <= 20 and x0 <= 20
    assert y0 + prepared.section_crop.shape[0] >= 80
    assert x0 + prepared.section_crop.shape[1] >= 80
    assert prepared.section_envelope_mask_crop[25-y0, 25-x0]
    assert not prepared.section_bright_mask_crop[25-y0, 25-x0]
    assert prepared.section_crop[25-y0, 25-x0] == 20


def test_direct_affine_inverse_matches_homogeneous_identity():
    matrix = np.asarray([[1.2, 0.3, 7], [-0.2, 0.9, -4], [0, 0, 1]])
    inverse = refinement._inverse_affine(matrix)
    np.testing.assert_allclose(np.einsum("ij,jk->ik", matrix, inverse, optimize=False), np.eye(3), atol=1e-12)
    np.testing.assert_allclose(np.einsum("ij,jk->ik", inverse, matrix, optimize=False), np.eye(3), atol=1e-12)
    np.testing.assert_allclose(refinement._compose_affines(matrix, inverse), np.eye(3), atol=1e-12)


def test_mutual_information_gradient_matches_finite_difference():
    fixed = np.linspace(0.05, 0.95, 101)
    moving = 0.13 + 0.73 * (np.sin(np.arange(101) * 0.37) + 1) / 2
    _, gradient = refinement._mutual_information_loss(fixed, moving, 16)
    direction = np.cos(np.arange(101) * 0.19)
    epsilon = 1e-6
    plus = refinement._mutual_information_loss(fixed, moving + epsilon * direction, 16)[0]
    minus = refinement._mutual_information_loss(fixed, moving - epsilon * direction, 16)[0]
    assert np.dot(gradient, direction) == pytest.approx((plus-minus)/(2*epsilon), rel=1e-5, abs=1e-7)


def test_bending_energy_gradient_and_affine_nullspace():
    yy, xx = np.indices((6, 7), dtype=float)
    coefficients = np.asarray([np.sin(yy + xx*0.3), np.cos(xx + yy*0.4)])
    direction = np.cos(np.arange(coefficients.size).reshape(coefficients.shape) * 0.17)
    _, gradient = refinement._bending_energy(coefficients)
    epsilon = 1e-6
    plus = refinement._bending_energy(coefficients + epsilon*direction)[0]
    minus = refinement._bending_energy(coefficients - epsilon*direction)[0]
    assert np.sum(gradient*direction) == pytest.approx((plus-minus)/(2*epsilon), rel=1e-6, abs=1e-8)
    energy, affine_gradient = refinement._bending_energy(np.asarray([yy+2*xx, 3*yy-xx]))
    assert energy == pytest.approx(0)
    np.testing.assert_allclose(affine_gradient, 0, atol=1e-12)


def test_cubic_basis_matches_dense_field_and_physical_displacement_bound():
    shape = (60, 70)
    spacing = np.asarray([13.0, 17.0])
    grid_shape = tuple((np.ceil((np.asarray(shape)-1)/spacing).astype(int)+4).tolist())
    points = np.asarray([[0, 0], [5.3, 14.7], [23, 42], [59, 69]])
    basis = refinement._bspline_basis(points, spacing, grid_shape)
    np.testing.assert_allclose(np.asarray(basis.sum(axis=1)).ravel(), 1, atol=1e-12)
    pixel_sizes = np.asarray([20.0, 40.0])
    limit_um = 200
    limits = limit_um/(np.sqrt(2)*pixel_sizes)
    coefficients = np.asarray([np.full(grid_shape, limit) for limit in limits])
    field = refinement.bspline_displacement(coefficients, shape, spacing)
    for axis in range(2):
        np.testing.assert_allclose(basis @ coefficients[axis].ravel(), limits[axis], atol=1e-12)
        np.testing.assert_allclose(field[axis], limits[axis], atol=1e-12)
    assert np.sqrt(np.sum((field*pixel_sizes[:, None, None])**2, axis=0)).max() <= limit_um*(1+1e-12)
    np.testing.assert_allclose(refinement.displacement_jacobian(field), 1, atol=1e-12)


def test_affine_refinement_uses_internal_intensities_with_identical_masks():
    fixed = _structure()
    moving = np.roll(fixed, 4, axis=1)
    mask = np.ones(fixed.shape, dtype=bool)
    params = np.asarray([1.0, 0.0, (fixed.shape[0]-1)/2, (fixed.shape[1]-1)/2])
    matrix = registration._similarity_matrix(*params, fixed.shape)
    metadata = registration._similarity_transform_metadata(matrix, params, transform_model="affine")
    config = SliceRegistrationConfig(min_scale_factor=1, max_scale_factor=1,
                                    max_affine_anisotropy=0, max_affine_shear=0,
                                    intensity_pyramid_max_dims=(32, 64), intensity_max_evaluations=180)
    fitted, _, diagnostics = refinement.refine_affine_intensity(
        moving, mask, mask, fixed, mask, matrix, tuple(params), params, metadata, config,
    )
    assert diagnostics["intensity_refinement_status"] == "accepted"
    assert diagnostics["intensity_nmi_after"] > diagnostics["intensity_nmi_before"]
    assert fitted[1, 2] < -0.5
    assert diagnostics["intensity_evaluations"] <= 2*config.intensity_max_evaluations


def test_bspline_improves_internal_alignment_and_respects_constraints():
    fixed = _structure()
    moving = np.roll(fixed, 2, axis=1)
    mask = np.ones(fixed.shape, dtype=bool)
    config = SliceRegistrationConfig(nonlinear_refinement_model="bspline", atlas_pixel_size_um=(39, 39))
    field, diagnostics, grid = refinement.refine_bspline_intensity(moving, mask, fixed, mask, config)
    assert diagnostics["bspline_status"] == "accepted"
    assert diagnostics["bspline_nmi_after"] > diagnostics["bspline_nmi_before"]
    assert diagnostics["bspline_max_displacement_um"] <= config.bspline_max_displacement_um
    assert refinement.displacement_jacobian(field).min() >= config.bspline_min_jacobian
    np.testing.assert_allclose(field, refinement.bspline_displacement(grid["bspline_coefficients"], fixed.shape,
                                                                      grid["bspline_spacing_yx_px"]), atol=1e-12)


def test_bspline_rejects_folding_candidate(monkeypatch):
    fixed = _structure()
    mask = np.ones(fixed.shape, dtype=bool)
    config = SliceRegistrationConfig(nonlinear_refinement_model="bspline", atlas_pixel_size_um=(1, 1),
                                    bspline_control_point_spacing_um=8, bspline_max_displacement_um=200)

    def folded_result(fun, initial, **kwargs):
        grid_shape = (int(np.ceil((fixed.shape[0]-1)/8))+4, int(np.ceil((fixed.shape[1]-1)/8))+4)
        coefficients = np.zeros((2, *grid_shape))
        coefficients[0] = -16*np.arange(grid_shape[0])[:, None]
        return SimpleNamespace(x=coefficients.ravel(), fun=-1.0, nit=1, success=True)

    monkeypatch.setattr(refinement.optimize, "minimize", folded_result)
    monkeypatch.setattr(refinement, "_mutual_information_loss",
                        lambda fixed_values, values, bins: (0.01 if np.std(values) == 0 else 0.5, np.zeros_like(values)))
    field, diagnostics, _ = refinement.refine_bspline_intensity(np.roll(fixed, 2, axis=1), mask, fixed, mask, config)
    assert diagnostics["bspline_status"] == "rejected_folding"
    np.testing.assert_array_equal(field, 0)


def test_low_contrast_refinement_and_missing_physical_calibration():
    constant = np.ones((40, 50), dtype=np.float32)
    mask = np.ones(constant.shape, dtype=bool)
    config = SliceRegistrationConfig(nonlinear_refinement_model="bspline")
    with pytest.raises(ValueError, match="atlas_pixel_size_um"):
        refinement.refine_bspline_intensity(constant, mask, constant, mask, config)
    field, diagnostics, _ = refinement.refine_bspline_intensity(
        constant, mask, constant, mask, SliceRegistrationConfig(atlas_pixel_size_um=(39, 39)),
    )
    assert diagnostics["bspline_status"] == "insufficient_contrast"
    np.testing.assert_array_equal(field, 0)


def test_uninformative_bspline_preserves_affine_image_and_masks():
    image = np.zeros((60, 80), dtype=np.float32)
    image[12:48, 18:62] = 100
    mask = image > 0
    common = dict(section_image=image, atlas_reference=image, atlas_mask=mask)
    affine_image, affine_metadata = registration._register_section_to_atlas(
        **common, config=SliceRegistrationConfig(nonlinear_refinement_model="none"),
    )
    refined_image, refined_metadata = registration._register_section_to_atlas(
        **common, config=SliceRegistrationConfig(nonlinear_refinement_model="bspline", atlas_pixel_size_um=(39, 39)),
    )
    assert refined_metadata["bspline_status"] == "insufficient_contrast"
    np.testing.assert_array_equal(refined_image, affine_image)
    np.testing.assert_array_equal(refined_metadata["_warped_mask"], affine_metadata["_warped_mask"])


@pytest.mark.parametrize("nonlinear_model", ["none", "bspline"])
def test_saved_transform_replays_channels_and_handles_mixed_empty_rows(tmp_path, nonlinear_model):
    fixed = _structure((80, 96))
    fixed[:8] = fixed[-8:] = 0
    fixed[:, :8] = fixed[:, -8:] = 0
    moving = np.roll(fixed, 2, axis=1)
    imwrite(tmp_path/"reference.tif", fixed)
    imwrite(tmp_path/"annotation.tif", (fixed > 0).astype(np.uint16))
    imwrite(tmp_path/"section.tif", moving)
    imwrite(tmp_path/"blank.tif", np.zeros_like(fixed))
    rows = [{"section_index": index, "section_source_path": str(tmp_path/name),
             "atlas_reference_path": str(tmp_path/"reference.tif"),
             "atlas_annotation_path": str(tmp_path/"annotation.tif"),
             "atlas_pixel_size_y_um": 39, "atlas_pixel_size_x_um": 39}
            for index, name in ((1, "blank.tif"), (2, "section.tif"))]
    manifest = tmp_path/"pairing.csv"
    with manifest.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    result = registration.register_slices_to_atlas(
        manifest, config=None if nonlinear_model == "bspline" else SliceRegistrationConfig(nonlinear_refinement_model="none"),
    )
    with result.manifest_path.open(newline="", encoding="utf-8") as handle:
        registered = list(csv.DictReader(handle))
    assert registered[1]["registration_nonlinear_refinement_model"] == nonlinear_model
    replayed = apply_slice_registration_transform(moving, registered[1]["registration_transform_path"])
    original = imread(registered[1]["warped_section_path"])
    np.testing.assert_allclose(replayed, original, rtol=1e-5, atol=1e-4)
    second_channel = apply_slice_registration_transform(moving*3, registered[1]["registration_transform_path"])
    np.testing.assert_allclose(second_channel, original*3, rtol=1e-5, atol=3e-4)
    blank_replay = apply_slice_registration_transform(np.zeros_like(fixed), registered[0]["registration_transform_path"])
    np.testing.assert_array_equal(blank_replay, 0)
    assert json.loads(result.metadata_path.read_text())["rows"][1]["registration_transform_path"]
    with pytest.raises(ValueError, match="shape"):
        apply_slice_registration_transform(moving[:-1], registered[1]["registration_transform_path"])
