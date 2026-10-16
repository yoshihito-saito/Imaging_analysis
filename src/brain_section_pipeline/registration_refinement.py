"""Sampled mutual-information affine and cubic B-spline slice refinement.

All displacements are pullbacks: an atlas point q samples the affine-warped
section at q + displacement(q). B-spline coefficients are in atlas pixels;
configuration distances are converted from micrometres before optimization.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
from PIL import Image
from scipy import ndimage, optimize, sparse

if TYPE_CHECKING:
    from .slice_registration import SliceRegistrationConfig


def _affine_determinant(matrix: np.ndarray) -> float:
    return float(matrix[0, 0]*matrix[1, 1] - matrix[0, 1]*matrix[1, 0])


def _inverse_affine(matrix: np.ndarray) -> np.ndarray:
    """Invert a 2D homogeneous affine map directly, without a LAPACK call."""
    determinant = _affine_determinant(matrix)
    if abs(determinant) < 1e-12:
        raise ValueError("The affine transform is singular and cannot be inverted.")
    inverse = np.eye(3)
    inverse[0, 0], inverse[0, 1] = matrix[1, 1]/determinant, -matrix[0, 1]/determinant
    inverse[1, 0], inverse[1, 1] = -matrix[1, 0]/determinant, matrix[0, 0]/determinant
    inverse[0, 2] = -inverse[0, 0]*matrix[0, 2] - inverse[0, 1]*matrix[1, 2]
    inverse[1, 2] = -inverse[1, 0]*matrix[0, 2] - inverse[1, 1]*matrix[1, 2]
    return inverse


def _compose_affines(first: np.ndarray, second: np.ndarray) -> np.ndarray:
    """Compose small 2D affine maps using scalar arithmetic."""
    result = np.eye(3)
    for row in range(2):
        for column in range(2):
            result[row, column] = first[row, 0]*second[0, column] + first[row, 1]*second[1, column]
        result[row, 2] = first[row, 0]*second[0, 2] + first[row, 1]*second[1, 2] + first[row, 2]
    return result


def _transform_points(matrix: np.ndarray, points: np.ndarray) -> np.ndarray:
    y, x = points.T
    return np.column_stack((matrix[0, 0]*y + matrix[0, 1]*x + matrix[0, 2],
                            matrix[1, 0]*y + matrix[1, 1]*x + matrix[1, 2]))


def _normalize(image: np.ndarray, mask: np.ndarray) -> np.ndarray | None:
    values = image[np.asarray(mask, dtype=bool) & np.isfinite(image)]
    if values.size < 32:
        return None
    lo, hi = np.percentile(values, (1.0, 99.0))
    if hi <= lo:
        return None
    clean = np.where(np.isfinite(image), image, lo)
    return np.clip((clean - lo) / (hi - lo), 0.0, 1.0).astype(np.float64)


def _resize(array: np.ndarray, scale: float, *, mask: bool = False) -> tuple[np.ndarray, np.ndarray]:
    shape = tuple(max(2, int(round(size * scale))) for size in array.shape)
    factors = np.asarray(shape, dtype=float) / np.asarray(array.shape)
    # PIL resize maps pixel centres, so coordinates include this half-pixel offset.
    mapping = np.eye(3)
    mapping[:2, :2] = np.diag(factors)
    mapping[:2, 2] = (factors - 1.0) / 2.0
    image = Image.fromarray(np.asarray(array, dtype=np.float32))
    resized = np.asarray(image.resize((shape[1], shape[0]), Image.Resampling.NEAREST if mask else Image.Resampling.BILINEAR))
    return resized.astype(np.float64), mapping


def _points(mask: np.ndarray, maximum: int) -> np.ndarray:
    points = np.argwhere(mask).astype(float)
    if len(points) > maximum:
        points = points[np.linspace(0, len(points) - 1, maximum, dtype=int)]
    return points


def _sample(image: np.ndarray, points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Bilinear samples and exact derivatives with respect to (y, x)."""
    y, x = points.T
    iy, ix = np.floor(y).astype(int), np.floor(x).astype(int)
    fy, fx = y - iy, x - ix

    def corner(dy: int, dx: int) -> np.ndarray:
        yy, xx = iy + dy, ix + dx
        valid = (yy >= 0) & (yy < image.shape[0]) & (xx >= 0) & (xx < image.shape[1])
        values = np.zeros(len(points))
        values[valid] = image[yy[valid], xx[valid]]
        return values

    a, b, c, d = corner(0, 0), corner(0, 1), corner(1, 0), corner(1, 1)
    values = (1 - fy) * ((1 - fx) * a + fx * b) + fy * ((1 - fx) * c + fx * d)
    gradient = np.column_stack(((1 - fx) * (c - a) + fx * (d - b), (1 - fy) * (b - a) + fy * (d - c)))
    return values, gradient


def _mutual_information_loss(fixed: np.ndarray, moving: np.ndarray, bins: int) -> tuple[float, np.ndarray]:
    """One minus normalized MI, with partial-volume histogram derivatives.

    NMI here is 2 * MI / (H_fixed + H_moving). Linear histogram weights and
    half-bin Gaussian Parzen smoothing keep sparse intensity bins from giving
    sharply conditioned entropy gradients as samples cross bin boundaries.
    """
    f = np.clip(fixed, 0, 1) * (bins - 1)
    m = np.clip(moving, 0, 1) * (bins - 1)
    fi = np.minimum(np.floor(f).astype(int), bins - 2)
    mi = np.minimum(np.floor(m).astype(int), bins - 2)
    ff, mf = f - fi, m - mi
    counts = np.zeros((bins, bins))
    for df, wf in ((0, 1 - ff), (1, ff)):
        for dm, wm in ((0, 1 - mf), (1, mf)):
            counts += np.bincount((fi + df) * bins + mi + dm, weights=wf * wm, minlength=bins * bins).reshape(bins, bins)
    counts = ndimage.gaussian_filter(counts, sigma=0.5, mode="reflect")
    counts += 1e-8
    total = counts.sum()
    joint = counts / total
    pf, pm = joint.sum(axis=1), joint.sum(axis=0)
    hf, hm = -np.sum(pf * np.log(pf)), -np.sum(pm * np.log(pm))
    hj = -np.sum(joint * np.log(joint))
    entropy = hf + hm
    information = entropy - hj
    if entropy <= 1e-10:
        return 1.0, np.zeros_like(moving)
    cost = 1.0 - 2.0 * information / entropy
    derivative = (-2 / entropy + 2 * information / entropy**2) * (-np.log(pf[:, None]) - np.log(pm[None, :]) - 2)
    derivative += 2 / entropy * (-np.log(joint) - 1)
    # Reflect-boundary Gaussian convolution is symmetric: apply its adjoint
    # before differentiating the original partial-volume histogram weights.
    derivative = ndimage.gaussian_filter(derivative, sigma=0.5, mode="reflect")
    sample_derivative = np.zeros_like(moving)
    for df, wf in ((0, 1 - ff), (1, ff)):
        sample_derivative += wf * (derivative[fi + df, mi + 1] - derivative[fi + df, mi])
    sample_derivative *= (bins - 1) / total
    sample_derivative[(moving < 0) | (moving > 1)] = 0
    return float(cost), sample_derivative


@dataclass
class _IntensityLevel:
    moving: np.ndarray
    fixed_values: np.ndarray
    points: np.ndarray
    fixed_mapping: np.ndarray
    moving_mapping: np.ndarray

    def loss(self, matrix: np.ndarray, bins: int) -> float:
        mapping = _compose_affines(_compose_affines(self.fixed_mapping, matrix), _inverse_affine(self.moving_mapping))
        inverse = _inverse_affine(mapping)
        source = _transform_points(inverse, self.points)
        values, _ = _sample(self.moving, source)
        return _mutual_information_loss(self.fixed_values, values, bins)[0]


def _intensity_level(section: np.ndarray, section_mask: np.ndarray, reference: np.ndarray, atlas_mask: np.ndarray,
                     matrix: np.ndarray, maximum_dim: int, maximum_samples: int) -> _IntensityLevel | None:
    scale = min(1.0, maximum_dim / max(reference.shape))
    moving_scale = min(1.0, scale * np.sqrt(_affine_determinant(matrix)))
    fixed, fm = _resize(reference, scale)
    fixed_mask, _ = _resize(atlas_mask, scale, mask=True)
    moving, mm = _resize(section, moving_scale)
    moving_mask, _ = _resize(section_mask, moving_scale, mask=True)
    fixed = _normalize(fixed, fixed_mask > 0.5)
    moving = _normalize(moving, moving_mask > 0.5)
    if fixed is None or moving is None:
        return None
    points = _points(fixed_mask > 0.5, maximum_samples)
    return _IntensityLevel(moving, _sample(fixed, points)[0], points, fm, mm)


def refine_affine_intensity(section: np.ndarray, section_mask: np.ndarray, boundary_mask: np.ndarray,
                            reference: np.ndarray, atlas_mask: np.ndarray, matrix: np.ndarray,
                            initial: tuple[float, float, float, float], similarity: np.ndarray,
                            metadata: dict[str, Any], config: SliceRegistrationConfig,
                            ) -> tuple[np.ndarray, dict[str, Any], dict[str, Any]]:
    """Refine bounded global parameters using MI at successively finer levels."""
    from .slice_registration import (
        _affine_metadata_from_matrix, _affine_regularization_penalty,
        _refined_affine_matrix, _registration_loss_for_matrix, _similarity_matrix,
    )

    diagnostics: dict[str, Any] = {"intensity_refinement_status": "disabled", "intensity_nmi_before": 0.0,
                                   "intensity_nmi_after": 0.0, "intensity_evaluations": 0, "intensity_levels": []}
    if not config.intensity_refinement or config.intensity_weight == 0:
        return matrix, metadata, diagnostics
    if (not config.intensity_pyramid_max_dims or any(n < 16 for n in config.intensity_pyramid_max_dims)
            or config.intensity_max_samples < 32 or config.intensity_histogram_bins < 4
            or config.intensity_max_evaluations < 1 or config.intensity_weight < 0):
        raise ValueError("Intensity refinement requires positive budgets, >=32 samples, >=4 bins and pyramid dimensions >=16.")
    shape = section.shape
    anisotropy = config.max_affine_anisotropy if config.transform_model == "affine" else 0.0
    shear = config.max_affine_shear if config.transform_model == "affine" else 0.0
    lower_scale = max(1e-3, initial[0] * config.min_scale_factor)
    upper_scale = max(lower_scale, initial[0] * config.max_scale_factor)
    rotation_range = np.deg2rad(config.max_rotation_degrees)
    bounds = np.asarray([
        (np.log(lower_scale), np.log(upper_scale)),
        (initial[1] - rotation_range, initial[1] + rotation_range),
        (initial[2] - atlas_mask.shape[0] * config.translation_search_fraction,
         initial[2] + atlas_mask.shape[0] * config.translation_search_fraction),
        (initial[3] - atlas_mask.shape[1] * config.translation_search_fraction,
         initial[3] + atlas_mask.shape[1] * config.translation_search_fraction),
        (-anisotropy, anisotropy), (-shear, shear),
    ])
    parameters = np.asarray([np.log(similarity[0]), similarity[1], metadata["translation_y"], metadata["translation_x"],
                             metadata["affine_anisotropy"], metadata["affine_shear"]])
    parameters = np.clip(parameters, bounds[:, 0], bounds[:, 1])
    active = bounds[:, 1] > bounds[:, 0]
    original_matrix = matrix.copy()
    coarse_scale = min(1.0, 96 / max(atlas_mask.shape))
    coarse_source_scale = min(1.0, coarse_scale * np.sqrt(_affine_determinant(matrix)))
    coarse_mask, source_mapping = _resize(section_mask, coarse_source_scale, mask=True)
    coarse_boundary, _ = _resize(boundary_mask, coarse_source_scale, mask=True)
    coarse_atlas, atlas_mapping = _resize(atlas_mask, coarse_scale, mask=True)

    def make_matrix(p: np.ndarray) -> np.ndarray:
        base = _similarity_matrix(np.exp(p[0]), p[1], p[2], p[3], shape)
        return _refined_affine_matrix(base, shape, anisotropy=p[4], shear=p[5], delta_y=0, delta_x=0)

    def objective(p: np.ndarray, level: _IntensityLevel) -> float:
        candidate = make_matrix(p)
        coarse_matrix = _compose_affines(_compose_affines(atlas_mapping, candidate), _inverse_affine(source_mapping))
        mask_loss = _registration_loss_for_matrix(
            coarse_matrix, coarse_mask, coarse_atlas, coarse_atlas.shape, config,
            section_boundary_mask=coarse_boundary,
            transform_regularization=_affine_regularization_penalty(p[4], p[5], config),
        )
        return mask_loss + config.intensity_weight * level.loss(candidate, config.intensity_histogram_bins)

    last_level = None
    dimensions = sorted({min(n, max(reference.shape)) for n in config.intensity_pyramid_max_dims})
    for dimension in dimensions:
        level = _intensity_level(section, section_mask, reference, atlas_mask, original_matrix, dimension, config.intensity_max_samples)
        if level is None:
            continue
        last_level = level
        diagnostics["intensity_levels"].append(dimension)
        baseline = objective(parameters, level)
        best = parameters.copy()
        best_cost = baseline

        def evaluate(values: np.ndarray) -> float:
            nonlocal best, best_cost
            candidate = parameters.copy()
            candidate[active] = values
            cost = objective(candidate, level)
            if np.isfinite(cost) and cost < best_cost:
                best, best_cost = candidate, cost
            return cost

        if np.any(active):
            result = optimize.minimize(evaluate, parameters[active], method="Powell", bounds=bounds[active],
                                       options={"maxfev": config.intensity_max_evaluations, "xtol": 1e-3, "ftol": 1e-5})
            diagnostics["intensity_evaluations"] += int(result.nfev)
        parameters = best
    if last_level is None:
        diagnostics["intensity_refinement_status"] = "insufficient_contrast"
        return original_matrix, metadata, diagnostics
    candidate = make_matrix(parameters)
    original_regularization = _affine_regularization_penalty(metadata["affine_anisotropy"], metadata["affine_shear"], config)
    original_mask_loss = _registration_loss_for_matrix(
        _compose_affines(_compose_affines(atlas_mapping, original_matrix), _inverse_affine(source_mapping)),
        coarse_mask, coarse_atlas, coarse_atlas.shape,
        config, section_boundary_mask=coarse_boundary, transform_regularization=original_regularization,
    )
    before = last_level.loss(original_matrix, config.intensity_histogram_bins)
    after = last_level.loss(candidate, config.intensity_histogram_bins)
    accepted = (after < before and objective(parameters, last_level) < original_mask_loss + config.intensity_weight * before)
    diagnostics.update(intensity_refinement_status="accepted" if accepted else "no_improvement",
                       intensity_nmi_before=1 - before, intensity_nmi_after=1 - (after if accepted else before))
    if not accepted:
        return original_matrix, metadata, diagnostics
    refined_metadata = _affine_metadata_from_matrix(
        candidate, source_shape=shape, transform_model=config.transform_model, anisotropy=parameters[4], shear=parameters[5],
        regularization_penalty=_affine_regularization_penalty(parameters[4], parameters[5], config),
    )
    return candidate, refined_metadata, diagnostics


def _bspline_basis(points: np.ndarray, spacing_yx: np.ndarray, grid_shape: tuple[int, int]) -> sparse.csr_matrix:
    """Tensor-product cardinal cubic B-splines; sixteen nonzero weights per point."""
    coordinates = points / spacing_yx + 1.0
    integer = np.floor(coordinates).astype(int)
    t = coordinates - integer
    weights = np.stack(((1-t)**3/6, (3*t**3-6*t**2+4)/6,
                        (-3*t**3+3*t**2+3*t+1)/6, t**3/6), axis=2)
    indices, values = [], []
    for iy in range(4):
        for ix in range(4):
            indices.append((integer[:, 0] + iy - 1) * grid_shape[1] + integer[:, 1] + ix - 1)
            values.append(weights[:, 0, iy] * weights[:, 1, ix])
    return sparse.csr_matrix((np.concatenate(values), (np.tile(np.arange(len(points)), 16), np.concatenate(indices))),
                             shape=(len(points), int(np.prod(grid_shape))))


def bspline_displacement(coefficients: np.ndarray, output_shape: tuple[int, int], spacing_yx: np.ndarray) -> np.ndarray:
    """Evaluate cubic coefficients on an atlas grid, returning (2, Y, X)."""
    yy, xx = np.indices(output_shape, dtype=float)
    coordinates = np.asarray([yy / spacing_yx[0] + 1, xx / spacing_yx[1] + 1])
    return np.asarray([ndimage.map_coordinates(component, coordinates, order=3, prefilter=False, mode="nearest")
                       for component in coefficients])


def _bending_energy(coefficients: np.ndarray) -> tuple[float, np.ndarray]:
    """Discrete thin-plate energy and its analytic coefficient gradient."""
    gradient = np.zeros_like(coefficients)
    energy = 0.0
    for axis in (1, 2):
        difference = np.diff(coefficients, n=2, axis=axis)
        energy += float(np.mean(difference**2))
        contribution = 2 * difference / difference.size
        for start, weight in ((0, 1), (1, -2), (2, 1)):
            selection = [slice(None)] * 3
            selection[axis] = slice(start, start + difference.shape[axis])
            gradient[tuple(selection)] += weight * contribution
    mixed = np.diff(np.diff(coefficients, axis=1), axis=2)
    energy += 2 * float(np.mean(mixed**2))
    contribution = 4 * mixed / mixed.size
    gradient[:, :-1, :-1] += contribution
    gradient[:, 1:, :-1] -= contribution
    gradient[:, :-1, 1:] -= contribution
    gradient[:, 1:, 1:] += contribution
    return energy, gradient


def displacement_jacobian(displacement: np.ndarray) -> np.ndarray:
    """Determinant of the atlas pullback q -> q + displacement(q)."""
    dy_y, dy_x = np.gradient(displacement[0])
    dx_y, dx_x = np.gradient(displacement[1])
    return (1 + dy_y) * (1 + dx_x) - dy_x * dx_y


def refine_bspline_intensity(warped: np.ndarray, warped_mask: np.ndarray, reference: np.ndarray,
                             atlas_mask: np.ndarray, config: SliceRegistrationConfig,
                             ) -> tuple[np.ndarray, dict[str, Any], dict[str, np.ndarray]]:
    """Fit bounded cubic coefficients with MI, mask and bending penalties.

    Returns an inverse sampling displacement, diagnostics, and reusable grid.
    Candidates must improve MI and the total objective and retain a positive
    full-grid Jacobian. Exhausting the iteration budget can still yield a valid
    improvement, which is distinguished from optimizer convergence in metadata.
    """
    if config.atlas_pixel_size_um is None:
        raise ValueError("bspline requires atlas_pixel_size_um=(y_um, x_um), or atlas pixel sizes in the pairing manifest.")
    pixel_size = np.asarray(config.atlas_pixel_size_um, dtype=float)
    if (pixel_size.shape != (2,) or not np.all(np.isfinite(pixel_size)) or np.any(pixel_size <= 0)
            or not np.isfinite(config.bspline_control_point_spacing_um) or config.bspline_control_point_spacing_um <= 0
            or not np.isfinite(config.bspline_max_displacement_um) or config.bspline_max_displacement_um <= 0
            or config.bspline_max_iterations < 1 or config.bspline_bending_weight < 0
            or not 0 < config.bspline_min_jacobian <= 1):
        raise ValueError("B-splines require positive physical spacing/displacement, an iteration budget, nonnegative bending weight and 0 < min_jacobian <= 1.")
    if config.intensity_max_samples < 32 or config.intensity_histogram_bins < 4 or config.intensity_weight <= 0:
        raise ValueError("B-splines require positive intensity weight, >=32 samples and >=4 histogram bins.")
    spacing = config.bspline_control_point_spacing_um / pixel_size
    grid_shape = tuple((np.ceil((np.asarray(warped.shape) - 1) / spacing).astype(int) + 4).tolist())
    coefficients = np.zeros((2, *grid_shape))
    zero = np.zeros((2, *warped.shape), dtype=float)
    diagnostics = {"bspline_status": "insufficient_contrast", "bspline_nmi_before": 0.0, "bspline_nmi_after": 0.0,
                   "bspline_min_jacobian": 1.0, "bspline_max_displacement_um": 0.0,
                   "bspline_optimizer_converged": False, "bspline_iterations": 0}
    grid = {"bspline_coefficients": coefficients, "bspline_spacing_yx_px": spacing}
    fixed, moving = _normalize(reference, atlas_mask), _normalize(warped, warped_mask)
    if fixed is None or moving is None:
        return zero, diagnostics, grid
    points = _points(atlas_mask, config.intensity_max_samples)
    fixed_values = _sample(fixed, points)[0]
    basis = _bspline_basis(points, spacing, grid_shape)
    # A second, uniformly sampled grid penalizes both missing and excess tissue.
    mask_points = _points(np.ones_like(atlas_mask, dtype=bool), config.intensity_max_samples)
    mask_values = _sample(atlas_mask.astype(float), mask_points)[0]
    mask_basis = _bspline_basis(mask_points, spacing, grid_shape)
    size = int(np.prod(grid_shape))
    # Cubic weights are nonnegative and sum to one. These component bounds
    # guarantee the interpolated physical displacement norm is <= the limit.
    component_limits = config.bspline_max_displacement_um / (np.sqrt(2) * pixel_size)
    limits = np.repeat(component_limits, size)
    inverse_limits = 1 / component_limits[:, None, None]

    def evaluate(flat: np.ndarray) -> tuple[float, np.ndarray]:
        controls = flat.reshape(2, *grid_shape)
        offset = np.column_stack([basis @ part.ravel() for part in controls])
        values, image_gradient = _sample(moving, points + offset)
        intensity, intensity_derivative = _mutual_information_loss(fixed_values, values, config.intensity_histogram_bins)
        offset_mask = np.column_stack([mask_basis @ part.ravel() for part in controls])
        sampled_mask, mask_gradient = _sample(warped_mask.astype(float), mask_points + offset_mask)
        error = sampled_mask - mask_values
        mask_cost = float(np.mean(error**2))
        derivative_mask = 2 * error / len(error)
        gradient = np.asarray([
            basis.T @ (config.intensity_weight * intensity_derivative * image_gradient[:, axis])
            + mask_basis.T @ (derivative_mask * mask_gradient[:, axis]) for axis in range(2)
        ]).reshape(controls.shape)
        bending, bending_gradient = _bending_energy(controls * inverse_limits)
        gradient += config.bspline_bending_weight * bending_gradient * inverse_limits
        return config.intensity_weight * intensity + mask_cost + config.bspline_bending_weight * bending, gradient.ravel()

    baseline_cost = evaluate(coefficients.ravel())[0]
    baseline_mi = _mutual_information_loss(fixed_values, _sample(moving, points)[0], config.intensity_histogram_bins)[0]
    result = optimize.minimize(evaluate, coefficients.ravel(), jac=True, method="L-BFGS-B",
                               bounds=np.column_stack((-limits, limits)),
                               options={"maxiter": config.bspline_max_iterations, "maxls": 10, "ftol": 1e-7})
    candidate_coefficients = result.x.reshape(coefficients.shape)
    candidate = bspline_displacement(candidate_coefficients, warped.shape, spacing)
    offset = np.column_stack([basis @ part.ravel() for part in candidate_coefficients])
    final_mi = _mutual_information_loss(fixed_values, _sample(moving, points + offset)[0], config.intensity_histogram_bins)[0]
    jacobian = displacement_jacobian(candidate)
    min_jacobian = float(jacobian.min())
    physical_magnitude = np.sqrt(np.sum((candidate * pixel_size[:, None, None])**2, axis=0))
    accepted = (np.all(np.isfinite(candidate)) and np.isfinite(result.fun) and result.fun < baseline_cost
                and final_mi < baseline_mi and min_jacobian >= config.bspline_min_jacobian
                and physical_magnitude.max() <= config.bspline_max_displacement_um * (1 + 1e-12))
    rejected_status = "rejected_folding" if min_jacobian < config.bspline_min_jacobian else "rejected"
    diagnostics.update(bspline_status="accepted" if accepted else rejected_status,
                       bspline_nmi_before=1-baseline_mi, bspline_nmi_after=1-(final_mi if accepted else baseline_mi),
                       bspline_min_jacobian=min_jacobian if accepted else 1.0,
                       bspline_max_displacement_um=float(physical_magnitude.max()) if accepted else 0.0,
                       bspline_optimizer_converged=bool(result.success), bspline_iterations=int(result.nit))
    if accepted:
        grid["bspline_coefficients"] = candidate_coefficients
        return candidate, diagnostics, grid
    return zero, diagnostics, grid
