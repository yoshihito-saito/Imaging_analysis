# ROI-Based ND2 Export

Date: 2026-09-30

## Goal And Motivation

Process large ND2 slides without materializing the full four-channel image.

## Current Problem

Factor-four coarse detection is fast, but `process_nd2_file` loads the entire
full-resolution ND2 before local refinement and crop export. Slide 01 exceeds
practical memory limits during this stage. The compact export also increments
global section numbers by the number of RGB crops, which is zero by default.

## Why Now

The RM014 sample includes 3.9 to 7.0 GB slides. The current whole-slide read
blocks useful testing and batch processing on the available machine.

## Scope And API

- `io.py`: add a context-managed regional ND2 reader using lazy ND2/Dask
  indexing with the same scene, position, time, Z and channel semantics as the
  existing reader.
- `pipeline.py`: use one-channel ROI reads for refinement and channel-at-a-time
  reads for final outputs when downsampling is enabled. Preserve the existing
  full-resolution-only route when `detection_downsample=1`.
- `export.py`: advance global numbering by detected boxes.
- Tests, README and changelog for the new behavior.

## Algorithm

For each coarse box, map to full-resolution coordinates, add the configured
search padding, read the detection channel only, and run the current local
detector. For each refined final box, read each required channel in turn and
write the existing TIFF outputs. Build bounded review previews from the coarse
image. All final box coordinates and TIFF pixels remain full resolution.

## Verification

- Compare regional reads to full-array slices on synthetic ND2-like data.
- Compare ROI pipeline boxes and TIFF contents with the full-array path.
- Verify numbering across slides when RGB crops are disabled.
- Run focused and full unit tests, then process representative RM014 slides.

## Non-Goals

- No changes to atlas registration, detection scoring, or the optional
  full-resolution-only mode.
- No destructive changes to representative ND2 files or unrelated worktree
  changes.
