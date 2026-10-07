# Export Throughput Improvements

Date: 2026-09-28  
Git state: uncommitted

Implementation plan: [Export Throughput Improvements](../implementation_plan/2026-09-28-export-throughput.md)

## What Changed

- Added direct final channel and registration TIFF export from the loaded ND2
  array in `process_nd2_file(...)`.
- Updated `export_sections_for_brainglobe(...)` to use that direct path instead
  of writing, rereading, and splitting temporary raw multi-channel crop stacks.
- Added `BrainGlobeExportConfig.preview_max_dim`, defaulting to `4096` for
  review images without changing full-resolution detection or crop output.
- Added `BrainGlobeExportConfig.keep_raw_channel_crops`, defaulting to `False`.
  Setting it to `True` retains the former raw-stack compatibility artifact.
- Preserved the existing channel TIFFs, registration TIFFs, crop paths, and
  manifest schema. `raw_crop_path` is an empty string when raw-stack retention
  is disabled.
- Added focused tests for direct channel/registration output and the new export
  defaults.
- Updated the README with large-slide defaults and the raw-stack compatibility
  option.

## Why

Large ND2 batches were paying for an unnecessary raw-stack write-read-write
cycle. The new direct path retains the same final data products while reducing
temporary storage and disk I/O. Downsampled review images avoid expensive
full-slide preview generation; tissue detection remains full resolution.

## Verification

Focused command:

```powershell
& 'C:\Users\Cornell\miniforge3\envs\histology\python.exe' -m pytest tests/test_merge_and_crop.py -k "direct_channel_crops or export_sections_for_brainglobe or export_section_review or run_slicewise_atlas_workflow"
```

Result: 5 passed.

Full module command:

```powershell
& 'C:\Users\Cornell\miniforge3\envs\histology\python.exe' -m pytest tests/test_merge_and_crop.py
```

Result: 59 passed, 1 failed. The remaining failure is the pre-existing
`test_detect_section_crops_merges_moderately_smaller_fragment_companion` crop
expectation. This work does not modify `crop.py` or detection configuration.

## Known Limitations And Next Steps

- ND2 loading and tissue detection still run at full resolution.
- Actual speed and storage gains should be measured on representative ND2 files
  before changing detection resolution.
- Downsampled detection with local full-resolution box refinement remains
  intentionally deferred because it can affect section identification.
