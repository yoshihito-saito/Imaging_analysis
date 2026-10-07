# Waxholm AP Millimetres for Slice-Atlas Pairing

Date: 2026-10-02

## Goal and Motivation

Allow users to specify a Waxholm-native AP coordinate in millimetres for each
selected section instead of having to derive a BrainGlobe array index manually.
Preserve the existing integer-index workflow.

## Current Problem

`prepare_slice_atlas_inputs` accepts only `atlas_slice_index` or a sequential
start/step. The optional atlas-suggestion helper estimates AP zero at the
volume centre, but the published WHS rat v1.01 origin is at source AP voxel
623. For the BrainGlobe v3 `whs_sd_rat_39um` atlas, that volume is reoriented
from `lpi` to `asr`, making the zero-based AP array origin `1023 - 623 = 400`.
Using the midpoint approximation would misassign planes by about 112 voxels.

## Why Now

The user has selected sections by WHS-native AP millimetres and wants the
program to do the conversion reliably, without repeating the manual
publication-to-BrainGlobe calculation.

## Worktree and Scope

The worktree already contains unrelated uncommitted edits, including recent
changes to slice-atlas source, CLI, tests, and README. Preserve them.

Affected files: `src/brain_section_pipeline/slice_atlas.py`, focused tests in
`tests/test_merge_and_crop.py`, notebook/API-facing guidance in `README.md`,
and the plan/change-log indexes. No changes to the registration optimizer,
slice export, or optional atlas-index suggestion algorithm.

## Public Input and Conversion

- Accept an optional `whs_ap_mm` column on each selected row of the input
  section manifest. If present, reject a simultaneous `atlas_slice_index`.
- Support only the validated BrainGlobe v3.0 `whs_sd_rat_39um` layout
  (`asr`, shape `1024 x 512 x 512`, nominal 39 um); reject other versions or
  layouts rather than guessing.
- Use the published v1.01 source origin and physical spacing:
  `source_ap_voxel = 623 + whs_ap_mm / 0.0390625`.
- For the anterior-origin BrainGlobe array, use
  `atlas_index = round(1023 - source_ap_voxel)`.
- Reject non-finite or out-of-volume coordinates. Record the requested AP mm,
  chosen index, and the exact AP mm represented by that chosen voxel.
- Rows without `whs_ap_mm` keep the current explicit-index or sequential
  behavior. Registration consumes the resulting pairing manifest unchanged.

## Verification

- Unit tests for WHS 0 mm -> ASR index 400 and +3.9/+4.9/+5.8 mm ->
  300/275/252, with an explicit source-to-ASR index reversal check.
- Test round-trip plane positions, unsupported atlas layout, non-finite and
  out-of-range values, and conflicting AP/index inputs.
- Verify the source-to-BrainGlobe voxel flip independently with a synthetic
  `brainglobe_space` mapped stack (not point coordinates), and check loaded
  atlas metadata (`shape`, `orientation`, `resolution`).
- Run the focused pytest cases and relevant existing slice-atlas tests.

## Non-Goals

Do not alter existing crop outputs, registration masks or transforms, or the
legacy optional atlas-index suggestion helper in this change.
