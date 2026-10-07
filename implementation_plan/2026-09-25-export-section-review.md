# Export Section Review Outputs

Date: 2026-09-25

## Goal And Motivation

Make the initial ND2 section-isolation review concise and easy to inspect while
preserving the existing manifest and per-section TIFF exports required by the
later sparse atlas-registration workflow.

## Current Problem

`export_sections_for_brainglobe(...)` writes the useful per-slide crop overlays
inside a broad export tree and does not create a single visual review of all
detected sections. Its default crop order is also configurable rather than
explicitly enforcing the requested left-to-right order across numerically
ordered slide files. The optional atlas-index search is already outside the
main workflow, but its large set of review outputs can distract from the
intended export-first user experience.

## Why This Is Needed Now

The desired workflow starts with a compact, human-reviewable confirmation that
all sections were detected and globally ordered correctly before atlas-plane
assignment and registration begin.

## Affected Files

- `src/brain_section_pipeline/export.py`
- `tests/test_merge_and_crop.py`
- `README.md`
- `implementation_plan/README.md`
- `change_log/2026-09-25-export-section-review.md`
- `change_log/README.md`

## Implementation

- Add a dedicated `qc/section_review/` directory to the BrainGlobe export.
- Copy one numbered crop-box overlay per input slide into that directory.
  Numbering will be global, based on natural numeric slide-file order and
  left-to-right detection order within each slide.
- Render one RGB contact sheet from the exported section crops, with five
  columns per row, stable tile dimensions, visible global section labels, and
  preserved crop aspect ratios.
- Add paths for these review outputs to `BrainGlobeExportResult` and sample
  metadata while leaving the manifest and machine-readable crop exports in
  place.
- Keep `suggest_atlas_indices(...)` public and unchanged, but do not add it to
  the main `run_slicewise_atlas_workflow(...)` path.

## Expected Behavior

For input slides named in numeric order, e.g. `1.nd2`, `2.nd2`, each slide
overlay labels its detected boxes with the global sequence. The combined
contact sheet presents those same numbered sections left-to-right, five tiles
per row, continuing onto later rows as needed.

## Verification

- Add focused export tests using synthetic/fake slide processing to assert
  natural slide ordering, global labels in slide overlays, contact-sheet
  creation, and expected five-column layout dimensions.
- Run the focused export tests and syntax checks.

## Non-Goals

- Do not remove section TIFFs, channel exports, or `section_manifest.csv`.
- Do not alter atlas-plane selection or registration algorithms.
- Do not remove the optional atlas-index suggestion feature.
