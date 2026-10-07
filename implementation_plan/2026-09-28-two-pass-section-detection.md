# Two-Pass Section Detection

Date: 2026-09-28

## Goal And Motivation

Reduce the compute cost of identifying isolated brain sections in very large
ND2 slides without changing the full-resolution output crops used by the
BrainGlobe and atlas-registration workflow.

## Current Problem

`process_nd2_file(...)` loads full-resolution ND2 data and runs thresholding,
morphology, connected-component labeling, and box construction across the
entire full-resolution detection plane. These operations scale with slide
pixel count and dominate the section-isolation stage for large slides.

## Why This Is Needed Now

The planned 20 to 50 slide batches make full-resolution detection a material
runtime cost. Recent output cleanup reduced I/O but intentionally left
detection unchanged; a separate, conservative change is now needed to improve
the computational bottleneck while preserving crop accuracy.

## Affected Files

- `src/brain_section_pipeline/pipeline.py`
- `scripts/run_slicewise_workflow.py`
- `README.md`
- `tests/test_merge_and_crop.py`
- `implementation_plan/README.md`
- `change_log/2026-09-28-two-pass-section-detection.md`
- `change_log/README.md`

## Public API Changes

- Add `PipelineConfig.detection_downsample`, defaulting to `4`; `1` restores
  the existing full-resolution detection behavior.
- Add a full-resolution refinement padding parameter for each mapped coarse
  candidate.
- Expose the detection downsampling factor in the full-workflow CLI.

## Algorithm

1. Read a downsampled ND2 representation using the existing ND2 reader.
2. Detect coarse components with geometry-sensitive parameters converted to
   downsampled pixels: area by `s^2`, linear distances by `s`.
3. Read the full-resolution ND2 data needed by current export code.
4. Map each coarse box to full-resolution coordinates, expand it by a
   conservative full-resolution refinement padding, and rerun the existing
   detector only in that local window.
5. Select the local component that best overlaps the mapped coarse candidate,
   translate it back to slide coordinates, then apply final full-resolution
   crop padding and normal ordering.

## Expected Behavior

Final crop boxes should agree with normal full-resolution detection for clean
sections while retaining a full-resolution recovery path around each coarse
candidate. The normal output files and downstream manifest contract must not
change. The method does not perform ROI-based ND2 reads; a full-resolution ND2
array is still loaded after coarse detection for crop export.

## Verification

- Add synthetic layout tests comparing two-pass boxes with full-resolution
  baseline boxes, including multiple rows and a fragmented companion.
- Test that two-pass processing reads downsampled data first and retains
  full-resolution crop outputs.
- Benchmark the detection stage on a synthetic large slide and report that it
  is a relative estimate only; request a representative ND2 for real
  end-to-end timing and accuracy measurement.
- Run the focused tests and the full test module in the `histology`
  interpreter.
- Compare factors 2, 4, and 8 on representative ND2 files before setting the
  production default. Factor 8 must not be retained when it changes a final
  section candidate materially relative to factors 2 and 4.

## Validation Update

Representative Slide 05 testing found that factor 8 shifted one final crop
boundary by approximately 2,500 full-resolution pixels relative to factor 4.
The factor-2 and factor-4 coarse candidates agreed closely. The default is
therefore revised from 8 to 4 before further representative-slide testing.

## Non-Goals

- Do not introduce ROI-based final ND2 reads.
- Do not change default crop ordering, exported channel images, registration,
  atlas-plane selection, or scoring.
- Do not change the underlying detection heuristic outside the new coarse and
  local-refinement orchestration.
