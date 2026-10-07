# Registration Tissue Envelope and Mask Comparison

Date: 2026-10-02

## Goal and Motivation

Make the registration mask represent the gross slice envelope rather than only
the brightest tissue, and expose a fixed-transform comparison so improvements
in Dice can be distinguished from improvements in geometry.

## Current Problem

Slide 4's four registered slices have Dice 0.44-0.46, while the bright scoring
mask occupies only 29-31% of atlas tissue and nearly all of that mask lies
inside the atlas. The already-computed 0.35-quantile boundary mask occupies
73-78% and mostly lies inside. Thus the reported score is dominated by mask
underfill, not necessarily a bad transform. The 0.8-quantile mask is used for
the optimizer and reported Dice; the lower-threshold mask affects only a
boundary term.

## Why Now

The user reviewed the first two workflow stages and asked to implement the
low-cost diagnostic and fuller-mask correction before changing the optimizer.

## Worktree and Scope

The worktree contains user/recent uncommitted changes. Preserve them. Change
`src/brain_section_pipeline/slice_registration.py`, the CLI, focused tests,
and registration-facing README guidance. Do not edit ND2 export or atlas
pairing. Do not overwrite existing Slide 4 registration outputs.

## Public Behavior

- Add a `tissue_mask_mode` setting: `envelope` by default, `bright` for the
  previous 0.8-quantile behavior. Keep `tissue_threshold_quantile` as the
  bright-mask threshold and use the existing `boundary_fit_threshold_quantile`
  (0.35 default) for the envelope, to minimize new parameter surface.
- The envelope uses the existing small-radius binary closing and small-object
  cleanup. Do not fill large anatomical holes or introduce full-resolution
  connected-component passes beyond those already in the mask path.
- For a requested mask diagnostic, compute bright and envelope Dice at the
  *same selected transform*, record each mask's area ratio and atlas
  containment, and write one small comparison contact sheet. Keep the normal
  overlay display mask separate. The diagnostic is opt-in to avoid work and
  outputs in routine large-batch runs.
- Preserve matrix semantics and the existing registration/overlay manifests.

## Algorithm and Checks

For candidate mask area A, atlas area B, and intersection I, compute
`Dice = 2I/(A+B)`, `area_ratio = A/B`, and `inside_fraction = I/A`.
Compare the candidates using the identical transform matrix; do not claim a
mask-driven Dice increase is itself a geometric improvement.

Verify with unit tests for mask coverage, empty masks, same-transform
diagnostic metrics, opt-in contact sheet, and bright-mode compatibility.
Run the focused and full test suite. Run Slide 4 into a new output directory,
inspect diagnostic imagery and compare old/new overlays and scores.

## Non-Goals

No rotation/affine tuning, nonlinear refinement, AP-plane changes, or new
per-slice diagnostic image files by default.
