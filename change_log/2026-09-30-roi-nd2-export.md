# ROI-Based ND2 Export

Date: 2026-09-30  
Git state: uncommitted

Implementation plan: [ROI-Based ND2 Export](../implementation_plan/2026-09-30-roi-nd2-export.md)

## What Changed

- Added `Nd2RegionReader`, which keeps one ND2 handle open and computes bounded
  single-channel Dask slices. It respects scene, position, time and Z settings.
- The default two-pass pipeline now refines candidates using mask-channel
  regions and writes final channel and registration TIFFs one channel at a
  time from each final box. It no longer loads the full-resolution slide array.
- Bounded review thumbnails use the coarse image already in memory.
- Corrected section numbering and crop manifests when optional RGB crops are
  disabled, including numbering across multiple slides.
- Preserved the explicit `detection_downsample=1` full-resolution path and
  optional RGB/raw-stack outputs.
- Updated the README and regression tests.

## Why

The earlier two-pass detector still loaded all full-resolution ND2 channels
before local refinement and crop export. That exceeded available memory on
large RM014 slides. Compact export also left the RGB crop list empty, causing
duplicate section numbers on later slides.

## Verification

- Real `Slide_01_x4.nd2`: a 400 by 500 channel-2 ROI matched direct ND2/Dask
  pixels exactly. All six factor-four refinement boxes completed in 59.6 s
  without writing output crops.
- Real `Slide_05_x4.nd2`: two registration TIFFs were exported in 37.72 s;
  both TIFF dimensions matched their final box dimensions. Temporary output
  was removed after inspection.
- The real BrainGlobe export entry point completed Slide 05 in 34.32 s with
  registration output only. Its manifest contained unique indices 1 and 2,
  both registration TIFFs existed, and the slide overlay and montage existed.
  Temporary output was removed after inspection.
- Real `Slide_04_x4.nd2` (the widest, 7.0 GB sample): all four factor-four
  refinement boxes completed in 74.18 s without writing output crops.
- Focused unit tests: region channel/Z selection, ROI crop pixels, and
  numbering with RGB crops disabled passed. RGB-only export without channel
  TIFFs also passed.

Full test command:

```powershell
& 'C:\Users\Cornell\miniforge3\envs\histology\python.exe' -m pytest tests/test_merge_and_crop.py -q
```

Result: 64 passed, 1 failed. The failure is the pre-existing
`test_detect_section_crops_merges_moderately_smaller_fragment_companion`
expectation in the unchanged crop-fragment merge logic.

## Known Limitations

- Full output export still writes large TIFFs and therefore takes additional
  time and disk space beyond refinement-only measurements.
- `detection_downsample=1` retains the older whole-slide memory behavior.
- Optional full-resolution RGB or raw-stack outputs can require large
  per-section allocations; the compact default leaves them disabled.
- Factor-four candidate boundaries on Slide 01 should still be visually
  reviewed against the detection overlays before a large production batch.
