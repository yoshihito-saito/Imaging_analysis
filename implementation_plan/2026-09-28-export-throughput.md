# Export Throughput Improvements

Date: 2026-09-28

## Goal And Motivation

Reduce time, disk traffic, and peak preview-memory pressure in the
BrainGlobe-export path while preserving full-resolution slice detection and
the downstream manifest, channel, and registration-image contract.

## Current Problem

`export_sections_for_brainglobe(...)` currently forces full-resolution preview
generation when callers do not explicitly set `PipelineConfig.preview_max_dim`.
It also writes a full multi-channel raw TIFF crop for every section, rereads
that TIFF, and then writes its individual channel and registration TIFFs. For
large ND2 batches, this duplicates most crop I/O and storage without adding
information used by the normal sparse workflow.

## Why This Is Needed Now

The intended use includes 20 to 50 large ND2 slides. Removing unnecessary
data movement is the safest first performance improvement before considering
the higher-risk proposal to downsample tissue detection.

## Affected Files

- `src/brain_section_pipeline/pipeline.py`
- `src/brain_section_pipeline/export.py`
- `tests/test_merge_and_crop.py`
- `README.md`
- `implementation_plan/README.md`
- `change_log/2026-09-28-export-throughput.md`
- `change_log/README.md`

## Public API Changes

- `BrainGlobeExportConfig.preview_max_dim` defaults to `4096` for the
  BrainGlobe export's review images. A supplied `PipelineConfig.preview_max_dim`
  takes precedence.
- `BrainGlobeExportConfig.keep_raw_channel_crops` defaults to `False`. Setting
  it to `True` retains the prior intermediate raw-stack TIFF behavior.
- `process_nd2_file(...)` gains optional direct channel and registration export
  destinations. Existing callers remain unchanged when they do not supply
  those arguments.

## Implementation

- Keep ND2 loading, full-resolution detection, crop boxes, and RGB crop output
  unchanged.
- Export selected signal channels and the registration channel directly from
  the already loaded channel-first ND2 array.
- Keep `raw_crop_path` in the export manifest for compatibility; leave it empty
  when raw intermediate stacks are disabled.
- Preserve full-resolution crop values and filenames.

## Expected Behavior

Normal BrainGlobe export writes each requested channel crop and registration
crop once, with no `raw_channel_crops/` directory. Preview and review images
are capped at 4,096 pixels on their longest side by default. Detection remains
full-resolution and produces the same crop boxes for a fixed configuration.

## Verification

- Extend export tests to verify direct channel/registration output, an empty
  raw-stack path by default, and optional raw-stack compatibility mode.
- Verify 4,096-pixel preview default and explicit caller override.
- Run focused export/workflow tests and the full test module with the
  `histology` interpreter.

## Non-Goals

- Do not downsample or otherwise alter section detection.
- Do not change crop morphology, ordering, atlas fitting, or registration.
- Do not introduce multi-slide parallelism.
