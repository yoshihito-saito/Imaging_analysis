# Registration Tissue Envelope and Mask Comparison

Date: 2026-10-02  
Commit: uncommitted

Plan: [2026-10-02-registration-envelope-mask](../implementation_plan/2026-10-02-registration-envelope-mask.md)

## Changes

- The default registration/scoring mask now uses the existing permissive
  boundary-derived tissue envelope (0.35 quantile, small-radius closing and
  speck cleanup). The old bright mask still anchors the source crop. Use
  `tissue_mask_mode="bright"` for legacy fitting/scoring.
- Added opt-in `save_mask_diagnostics`: bright and envelope masks are measured
  at the same fitted transform, producing one comparison CSV and one contact
  sheet. Routine runs do not write these extra artifacts. The overlay display
  mask and the 2D transform matrix semantics are unchanged.
- Exposed both controls in the CLI, documented them in the README, and added
  focused mask, metric, empty-input, and artifact tests.

## Verification

Run with `PYTHONPATH=src` and the `histology` Miniforge environment's
`Library\bin`, `Scripts`, and root on `PATH`:

- `python -m pytest tests\test_merge_and_crop.py -k 'registration or mask_comparison or register_slices' -q`: 10 passed before the final guard test.
- `python -m pytest -q`: 82 passed, 1 failed before the final guard test. The
  unchanged failure is
  `test_detect_section_crops_merges_moderately_smaller_fragment_companion`,
  outside the registration code.
- `python -m pytest -q -k 'not test_detect_section_crops_merges_moderately_smaller_fragment_companion'`:
  83 passed, 1 deselected after the final guard test.
- `git diff --check` on affected tracked files: clean.

Real Slide 4 comparison used the existing four paired atlas planes in new
`slice_registration_bright_diagnostic/` and
`slice_registration_envelope_validation/` folders, leaving the original
registration folder unchanged. Bright-mode scores reproduced the old
0.464/0.440/0.451/0.455 Dice values exactly. On those same transforms,
the envelope scored 0.859/0.837/0.838/0.833. Refit envelope Dice was
0.863/0.838/0.848/0.839. The diagnostic sheet and final contact sheet were
visually reviewed: envelope masks track the broad tissue and the overlays
remain broadly aligned.

## Limitations and Next Steps

The large score increase is primarily a more representative mask, not a
comparably large geometric improvement. Validate the envelope visually on
other staining patterns before treating 0.80 Dice as an automatic pass.
The stable bright-mask crop can still clip tissue outside its bounds.
Mask diagnostics are currently affine/similarity-only and reject optional
nonlinear refinement because a nonlinear displacement field is not persisted.
