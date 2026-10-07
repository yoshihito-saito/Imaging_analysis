# Waxholm AP Millimetres for Slice-Atlas Pairing

Date: 2026-10-02  
Commit: uncommitted

Plan: [2026-10-02-whs-ap-plane-input](../implementation_plan/2026-10-02-whs-ap-plane-input.md)

## Changes

- `prepare_slice_atlas_inputs` accepts a per-row `whs_ap_mm` value in the
  section manifest. Rows without it retain explicit-index or sequential
  behavior. Simultaneous AP mm and index values are rejected.
- Conversion uses the published v1.01 source AP origin (voxel 623), exact
  0.0390625 mm source spacing, and BrainGlobe's reversed ASR AP array axis.
  It is gated to the verified v3.0 `whs_sd_rat_39um` layout.
- The pairing manifest records the requested AP coordinate, selected index,
  actual selected-plane AP coordinate, and atlas version. Metadata records
  the calibration. The CLI help and README describe the input.
- Added conversion, rejection, and end-to-end pairing tests, including an
  independent synthetic `brainglobe_space` reorientation check.

## Verification

- Commands below ran with `PYTHONPATH=src` and the `histology` Miniforge
  environment's `Library\bin`, `Scripts`, and environment root prepended
  to `PATH`, using that environment's `python.exe`.
- Installed atlas manifest: version 3.0, orientation `asr`, shape
  `(1024, 512, 512)`, nominal resolution `(39, 39, 39)` um.
- Published WHS coordinates give `0 -> 400`, `3.9 -> 300`, `4.9 -> 275`,
  and `5.8 -> 252` for the atlas's zero-based AP index. Actual selected
  plane coordinates for the latter three are 3.90625, 4.8828125, and
  5.78125 mm.
- `python -m pytest tests\test_merge_and_crop.py -k 'prepare_slice_atlas_inputs or whs_ap_mm or whs_ap_index_reversal' -q`: 18 passed.
- `python -m pytest -q`: 80 passed, 1 failed. The failure is the unchanged
  `test_detect_section_crops_merges_moderately_smaller_fragment_companion`
  in the untouched crop module, outside this change.
- `python -m pytest -q -k 'not test_detect_section_crops_merges_moderately_smaller_fragment_companion'`:
  80 passed, 1 deselected.
- `git diff --check` on changed code/docs: clean.

## Limitations

The physical-coordinate conversion is validated only for BrainGlobe v3.0
`whs_sd_rat_39um` and Waxholm-native AP positions, not Bregma-referenced
coordinates. The optional atlas-index suggestion helper still uses its old
volume-centre approximation and was not changed here. The fragment-merging
test failure needs separate investigation.
