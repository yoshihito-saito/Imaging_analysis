# Output Surface Reduction

Date: 2026-09-28  
Git state: uncommitted

Implementation plan: [Output Surface Reduction](../implementation_plan/2026-09-28-output-surface-reduction.md)

## What Changed

- Disabled full-resolution `sections_rgb/` and per-slide diagnostic outputs by
  default for BrainGlobe export. The review montage now uses bounded in-memory
  thumbnails.
- Kept per-slide numbered section-review overlays and the combined five-column
  montage as the normal export-review artifacts.
- Made legacy RGB crops, per-slide diagnostics, and raw crop stacks explicit
  opt-ins in the workflow script and Python configuration.
- Changed slice-atlas preparation to reference existing registration/channel
  images by default instead of duplicating them in `slice_atlas/sections/`.
  The copy remains available as an explicit option.
- Skipped coarse `slice_atlas/qc_overlays/` by default in the combined workflow.
- Replaced default per-section final registration overlays with a five-column
  contact sheet. Full-resolution individual overlays are retained only for
  failed or low-Dice fits unless explicitly requested for every section.
- Updated the README and command-line wrappers to expose the compact defaults
  and diagnostic opt-ins.

## Why

Large ND2 batches produce many duplicate images and diagnostics that are not
needed for normal review or downstream registration. The most expensive
duplicates were full-resolution RGB section crops and copied section sources in
the slice-atlas directory.

## Verification

Focused command:

```powershell
& 'C:\Users\Cornell\miniforge3\envs\histology\python.exe' -m pytest tests/test_merge_and_crop.py -k "register_slices_to_atlas_writes_warped_outputs or export_sections_for_brainglobe or export_section_review or direct_channel_crops or prepare_slice_atlas_inputs or run_slicewise_atlas_workflow"
```

Result: 8 passed.

Full module command:

```powershell
& 'C:\Users\Cornell\miniforge3\envs\histology\python.exe' -m pytest tests/test_merge_and_crop.py
```

Result: 60 passed, 1 failed. The remaining failure is the pre-existing
`test_detect_section_crops_merges_moderately_smaller_fragment_companion` crop
expectation. This work does not modify `crop.py` or crop-detection settings.

## Known Limitations And Next Steps

- The retained manifests and small JSON metadata files remain intentionally;
  they provide provenance and downstream paths without material storage cost.
- Detection remains full resolution. Downsampled detection with local
  full-resolution box refinement remains deferred to protect crop accuracy.
