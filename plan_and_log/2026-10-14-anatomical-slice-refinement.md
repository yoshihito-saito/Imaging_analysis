# Anatomical slice refinement

## Goal and scope

Improve section-to-atlas fitting using complete-tissue crops, multiresolution
intensity-guided affine refinement, and optional constrained 2D cubic B-splines.
Use existing NumPy/SciPy dependencies and atlas-resolution work images. Preserve
the separate atlas-plane assignment and legacy boundary refinement paths.

## Implementation steps

1. Preserve dim tissue when preparing source crops and record crop offsets.
2. Add bounded affine refinement using sampled mutual information and mask
   constraints at multiple resolutions.
3. Add sampled, regularized cubic B-spline refinement with displacement and
   folding constraints; persist its complete transform for reuse.
4. Expose controls in registration and workflow scripts and document usage.
5. Run scoped registration tests in the available environment and review the diff.

## Decisions and results

- Registration calculations stay in `src/`; no dense 3D reconstruction is added.
- Crops use the union of full-source bright, boundary, and display masks plus
  padding; transforms record crop coordinates and a full-source affine map.
- Constrained affine refinement is enabled by default. Sampled normalized MI
  uses a Gaussian-smoothed partial-volume histogram; smoothing resolved an
  ill-conditioned gradient check without changing test tolerances or inputs.
- Optional `bspline` fits cubic control points with analytic gradients, mask
  coverage and bending penalties, physical displacement bounds, and a full-grid
  Jacobian acceptance check. Rejected/low-contrast fits retain the affine output.
- No new dependencies. Small affine maps use direct scalar formulas. B-spline
  optimization uses SciPy L-BFGS-B. Atlas-index searches skip intensity refinement.
- Both CLI wrappers expose controls. New pairing manifests record atlas-plane
  spacing; older manifests require explicit spacing for B-splines. Saved affine
  and B-spline transforms can be replayed on another channel with one resampling.
- The user explicitly authorized adding/running focused synthetic tests. The
  final scoped run passed **17 tests**: the new refinement module's 12 cases
  plus five existing registration tests. Pytest reported 3.39 seconds; this is
  synthetic test timing, not a production benchmark. Cache was disabled and
  temporary roots were unique and outside the repository.
- Initial pytest plugin startup exceeded a ten-minute deadline and was stopped.
  Direct Python execution also crashed in native NumPy/SciPy routines with
  Windows code `0xc06d007f`. Running through `conda run --no-capture-output -n
  histology` with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` completed successfully. The
  installed environment uses NumPy 2.4.6 / SciPy 1.17.1, differing from YAML pins.
- Source/diff review completed. No slides, notebooks, full suite, atlas downloads,
  or production benchmarks were run. Anatomical accuracy on real tissue and batch
  cost still require review on representative sections; defaults are starting
  settings, not experimentally validated biological parameters.
- Follow-up: enabled B-splines by default in the Python configuration and both
  registration/workflow CLIs. Explicit `none` disables them. Candidate atlas
  searches keep B-splines off; affine-only and diagnostic tests now select `none`
  explicitly. The existing transform-replay test passed both cases (default
  B-splines and explicit opt-out): **2 passed in 2.45 seconds**, through Conda
  with external pytest plugins/cache disabled. Reviewed the scoped default and
  documentation changes; no further test runs were made for this small change.
