# Two-Pass Section Detection

Date: 2026-09-28  
Git state: uncommitted

Implementation plan: [Two-Pass Section Detection](../implementation_plan/2026-09-28-two-pass-section-detection.md)

## What Changed

- Added `PipelineConfig.detection_downsample`, default `4`, for a coarse ND2
  detection pass. Set it to `1` to use the prior full-resolution-only path.
- Added `PipelineConfig.detection_refinement_padding`, default `128` full
  resolution pixels.
- The pipeline now reads a coarse representation first, scales its detected
  candidates into full-resolution coordinates, and reruns the existing section
  detector only inside padded candidate windows before applying final crop
  padding and ordering.
- Retained full-resolution image data for crop export. ROI-based final ND2
  reads are intentionally not included.
- Added full-workflow CLI options `--detection-downsample` and
  `--detection-refinement-padding`.
- Added tests for coarse-first reading, exact box recovery on a clean
  multi-section layout, and greater than 0.99 box IoU with morphology enabled.

## Why

Full-slide thresholding, morphology, and connected-component labeling are the
largest compute cost in section isolation. Coarse candidate detection reduces
the image area used by these global operations while retaining full-resolution
measurements for exported crops.

## Verification

Focused command:

```powershell
& 'C:\Users\Cornell\miniforge3\envs\histology\python.exe' -m pytest tests/test_merge_and_crop.py -k "two_pass_detection or process_nd2_file_can_keep_review_data or export_sections_for_brainglobe or export_section_review"
```

Result: 5 passed.

Full module command:

```powershell
& 'C:\Users\Cornell\miniforge3\envs\histology\python.exe' -m pytest tests/test_merge_and_crop.py
```

Result: 62 passed, 1 failed. The remaining failure is the existing
`test_detect_section_crops_merges_moderately_smaller_fragment_companion`
expectation; this change does not modify `crop.py` or its fragment-merging
logic.

Synthetic 4096 by 4096 timing results for detection computation only:

- a smaller refinement-window case: 1.081 seconds full resolution versus
  0.458 seconds two-pass, 2.36x faster;
- a default-like morphology case with four sections covering much of the
  slide: 1.059 seconds full resolution versus 0.972 seconds two-pass, 1.09x
  faster, with minimum final-box IoU of 1.0.

These measurements exclude ND2 decoding, full-resolution crop export, and
disk I/O. Representative ND2 data is required for a production estimate.

Representative RM014 sample-data validation:

- The five supplied ND2s range from 3.9 GB to 7.0 GB and have 4 channels.
- On the 3.9 GB Slide 05, the factor-8 path completed in 24.68 seconds and
  factor 4 completed in 28.06 seconds. Both found two sections, but factor 8
  shifted one final crop boundary by about 2,500 full-resolution pixels.
- Slide 05 factor-2 and factor-4 coarse candidates agree closely, so factor 4
  replaced factor 8 as the default.
- On the crowded Slide 01, factors 2 and 4 both found six coarse candidates.
  Factor 4 completed coarse detection in 3.06 seconds compared with 12.00
  seconds for factor 2 after similarly sized reads. One coarse candidate edge
  differed by approximately 700 full-resolution pixels, so that slide still
  needs final-overlay review once memory-safe final reads are available.
- The legacy factor-1 full-slide morphology was terminated during detection on
  Slide 05, even when only the mask channel was loaded. A full factor-4
  no-output run on the 5.7 GB Slide 01 also terminated without a Python
  exception after reaching approximately 10 GB working set. This is consistent
  with system memory pressure while the full ND2 array and refinement windows
  coexist.

## Known Limitations And Next Steps

- The full-resolution ND2 array is still read after coarse detection because
  current export code writes full-resolution crops from it.
- Factor 4 is a materially safer coarse detector than factor 8 for the tested
  data, but it does not resolve the full-array memory ceiling on the largest
  slides. ROI-based final ND2 reads remain the required next step for those
  slides.
- Local morphology can vary by a few pixels if the refinement window is too
  small for unusually large defects. Increase
  `detection_refinement_padding` for such slides.
- Benchmark two or three representative ND2s against
  `detection_downsample=1`, inspect paired overlays, and compare section count
  and final box IoU before processing a 50-slide batch.
