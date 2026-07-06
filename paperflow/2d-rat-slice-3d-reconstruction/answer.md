# Answer: 3D Reconstruction From 2D Rat Histology Slices

## Direct Answer

For your current demo dataset, I would not start with full BrainGlobe
`brainreg` reconstruction. The demo ND2s are sparse 2D slide mosaics: three
slides, three channels, and 17 detected tissue sections total. `brainreg` is
excellent after you have a 3D sample volume, but it does not solve the hard
first step of reconstructing sparse serial 2D histology sections into a
physically plausible rat brain volume.

The best practical plan is:

1. Use this repository to extract ordered, QC'd section crops from ND2.
2. Build a manifest with section order, spacing, orientation, pixel size, and QC
   flags.
3. For the demo/sparse dataset, use per-section 2D-to-atlas registration and
   aggregate atlas-region measurements.
4. For a complete dense serial dataset, reconstruct a 3D stack with global
   constraints, then use BrainGlobe/`brainreg` for atlas registration and
   `brainglobe-segmentation` for downstream quantification.

## Best-Fit Methods

| Situation | Recommended method |
| --- | --- |
| Only sparse sections, like the demo | 2D slice-to-atlas registration, then per-section atlas quantification |
| Complete serial rat brain with many sections | Dense serial reconstruction with rigid/affine/nonrigid alignment plus global reference constraints |
| Already reconstructed 3D volume | BrainGlobe `brainreg` then `brainglobe-segmentation` |
| Need GUI correction and whole-slide compatibility | Fiji/ImageJ/ABBA/Slice2Volume-style workflow |

## Literature Evidence

- Ali et al. 2018 reconstructed a Wistar rat brain from 278 high-resolution
  histological 3D-PLI sections using feature-based and nonrigid registration.
  This supports dense rat 3D reconstruction, but your demo has far fewer
  sections.
- Agarwal et al. 2017 show a useful atlas-reslicing strategy for conventional
  brain slices with artifacts: create matching atlas slices, contour-align the
  histology, remove artifacts, then apply nonlinear correction.
- Piluso et al. 2021 supports the sparse-section alternative: register single
  2D coronal sections to a 3D atlas-derived plane for atlas-based segmentation.
- Casamitjana et al. 2021 explains why simple neighboring-slice alignment can
  fail through drift, z-shift, and banana-shaped deformation. A full 3D
  reconstruction needs global constraints.
- BrainGlobe documentation says `brainreg` registers a template brain to a
  sample image via reorientation, affine registration, and freeform
  registration; the companion segmentation plugin analyses segmented regions
  after registration.

## Recommended Pipeline For This Repo

### Phase 1: Preprocess ND2 slides

Use the existing pipeline to generate:

- full-resolution section crops;
- downsampled registration crops;
- RGB previews;
- crop overlays;
- a manifest CSV.

### Phase 2: Decide sparse vs dense

Use sparse mode if the dataset has tens of sections or large spacing:

- register each section to an atlas plane;
- save transforms;
- quantify labels per atlas region.

Use dense mode if the dataset has enough serial sections to represent the whole
brain:

- build a 3D stack;
- align neighboring slices;
- regularize with atlas/MRI/blockface/landmarks;
- register final volume with BrainGlobe.

### Phase 3: Atlas analysis

After registration:

- segment injection sites, labelled regions, or cells;
- transform labels/points to atlas coordinates;
- summarize by rat atlas region;
- export CSV tables and QC figures.

## Confidence And Scope

Confidence is high that BrainGlobe is a downstream registration/analysis tool
here, not the first reconstruction step. Confidence is moderate on the exact
best slice-registration software until rat atlas support, full dataset size,
and desired GUI-vs-code workflow are confirmed.

## Supporting Files

- `request.md`
- `reviews/review.md`
- `proposals/2026-07-06-3d-reconstruction-pipeline.md`
- `summaries/2018-ali-ultra-high-resolution-rat-pli.md`
- `summaries/2017-agarwal-geometry-processing-mouse-slices.md`
- `summaries/2021-casamitjana-robust-joint-registration.md`
- `summaries/2021-piluso-automated-atlas-segmentation.md`
- `summaries/2022-tyson-brainreg.md`
- `summaries/local-brain-slice-registration-spreadsheet.md`
