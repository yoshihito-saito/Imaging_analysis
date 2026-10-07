# Output Surface Reduction

Date: 2026-09-28

## Goal And Motivation

Reduce default on-disk outputs to the artifacts required for review, direct
slice-wise atlas registration, and atlas-region summaries, while retaining
opt-in diagnostics and compatibility artifacts for troubleshooting.

## Current Problem

The default sparse workflow persists several duplicate or diagnostic-only image
sets: full-resolution RGB crops, per-slide merged previews and local crop
overlays, per-slide metadata/manifests, copied section images in `slice_atlas`,
and coarse atlas QC overlays that are superseded by final registration
overlays. The largest duplicates are `sections_rgb/` and
`slice_atlas/sections/`.

## Why This Is Needed Now

The planned 20 to 50 slide datasets make output volume, file-count overhead,
and user-facing clutter significant. The user has confirmed that only the
essential review, registration, and analysis outputs should be routine.

## Affected Files

- `src/brain_section_pipeline/pipeline.py`
- `src/brain_section_pipeline/export.py`
- `src/brain_section_pipeline/slice_atlas.py`
- `src/brain_section_pipeline/workflow.py`
- `scripts/run_slicewise_workflow.py`
- `tests/test_merge_and_crop.py`
- `README.md`
- `implementation_plan/README.md`
- `change_log/2026-09-28-output-surface-reduction.md`
- `change_log/README.md`

## Public API Changes

- BrainGlobe export defaults to no persisted full-resolution RGB crops and no
  per-slide diagnostic artifacts. Add opt-in configuration flags for either.
- Slice-atlas preparation defaults to referencing the existing registration or
  signal image instead of copying it into `slice_atlas/sections/`.
- `run_slicewise_atlas_workflow(...)` defaults to skipping coarse atlas QC.
  The standalone QC function and CLI remain available.

## Implementation

- Build the five-column review montage from bounded in-memory RGB thumbnails;
  do not require `sections_rgb/` for default review.
- Retain full-resolution detection, registration crops, selected signal crops,
  atlas reference/annotation planes, final warped sections, final overlays,
  registration manifest, and atlas summaries.
- Make per-slide pipeline diagnostics optional while retaining their existing
  behavior for direct `process_nd2_file(...)` callers.
- Keep manifest fields stable: optional omitted artifact paths are empty.

## Expected Behavior

The normal full workflow writes one per-slide detection overlay and one montage
for export review, but no `sections_rgb/`, `slide_outputs/`,
`slice_atlas/sections/`, or `slice_atlas/qc_overlays/` directory. Existing
users can restore each omitted class of output with explicit configuration or
the existing standalone QC tool.

## Verification

- Add tests for default omission and opt-in restoration of RGB crops and
  diagnostics.
- Add tests for direct slice-atlas source references without duplicated files.
- Verify coarse QC is skipped by default and runs when explicitly requested.
- Run focused tests and the full module using the `histology` interpreter.

## Non-Goals

- Do not alter tissue detection, crop boxes, registration algorithms, atlas
  reference/annotation exports, final registration overlays, or summaries.
- Do not remove public standalone diagnostic/QC functions.
