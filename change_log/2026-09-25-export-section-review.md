# Export Section Review Outputs

Date: 2026-09-25  
Git state: uncommitted

Implementation plan: [Export Section Review Outputs](../implementation_plan/2026-09-25-export-section-review.md)

## What Changed

- Updated `export_sections_for_brainglobe(...)` to create a focused
  `qc/section_review/` directory containing one numbered detection overlay per
  ND2 slide and `all_detected_sections.png`.
- Enforced natural numeric ordering of input slide filenames and left-to-right
  section ordering within each slide for global section numbering.
- Added a five-column montage renderer that preserves each crop's aspect ratio
  while displaying its global section index.
- Preserved `section_manifest.csv`, per-channel TIFFs, registration TIFFs, and
  existing internal crop overlays for later atlas-registration stages.
- Exposed the review paths through `BrainGlobeExportResult`, sample metadata,
  and `scripts/run_slicewise_workflow.py` output.
- Updated the README to make direct atlas-plane assignment the main path and
  describe atlas-index suggestion as optional advanced functionality.
- Added focused tests for the new review artifacts, numeric slide order, global
  overlay numbering, left-to-right ordering, and five-column montage sizing.

## Why

The export stage previously produced many artifacts without a compact visual
confirmation that all slices had been detected and globally ordered correctly.
The new review outputs provide that confirmation before atlas-plane assignment
while retaining the machine-readable handoff needed by the rest of the
pipeline.

## Verification

Completed with the explicit Miniforge interpreter:

```powershell
& 'C:\Users\Cornell\miniforge3\envs\histology\python.exe' -m pytest tests/test_merge_and_crop.py -k "export_sections_for_brainglobe or export_section_review or run_slicewise_atlas_workflow"
```

Result: 4 passed.

The full current test module was also run:

```powershell
& 'C:\Users\Cornell\miniforge3\envs\histology\python.exe' -m pytest tests/test_merge_and_crop.py
```

Result: 58 passed, 1 failed. The failure is the existing
`test_detect_section_crops_merges_moderately_smaller_fragment_companion` crop
expectation; `crop.py` was not changed in this work. `git diff --check` also
passes for the modified files.

## Known Limitations And Next Steps

- The montage uses fixed 320 by 240 pixel preview tiles, so it is intended for
  review rather than pixel-accurate inspection.
- Real ND2 input still needs a manual visual validation of the generated review
  PNGs.
- `suggest_atlas_indices(...)` remains available but is intentionally not part
  of the default sparse workflow.
