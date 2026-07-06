# Review: 3D Reconstruction From 2D Rat Histology Slices

## Scope

This is an initial paperflow review for reconstructing a rat brain volume from
serial 2D histology sections in `D:\Imaging_analysis`. It uses the local demo
dataset context, the user's Google Drive/Paperpile search results, a local Drive
spreadsheet on brain slice registration tools, official BrainGlobe
documentation, and open literature sources found on arXiv.

## Current Dataset Constraint

The demo data are three large 2D, 3-channel ND2 slide mosaics, not z-stacks.
The existing repo pipeline detects 17 total sections:

| Slide | Shape | Detected sections |
| --- | --- | ---: |
| `Slide_01_x4.nd2` | `3 x 19800 x 38700` | 6 |
| `Slide_02_x4.nd2` | `3 x 19800 x 44775` | 6 |
| `Slide_03_x4.nd2` | `3 x 26280 x 46800` | 5 |

This is enough for developing the preprocessing and QC machinery, but likely
too sparse for a high-fidelity whole-brain 3D reconstruction unless it is a
small subset of a larger serial section set.

## Main Method Families

| Method family | Representative source | Core idea | Strength | Main risk |
| --- | --- | --- | --- | --- |
| Dense serial-section reconstruction | Ali et al. 2018 | Register hundreds of rat sections with feature-based and nonrigid methods, ideally using blockface/reference images. | Best match for true rat 3D reconstruction. | Needs dense sections, spacing, and preferably blockface/reference images. |
| Atlas-resliced 2D slice registration | Agarwal et al. 2017; Piluso et al. 2021 | Find/reslice a matching atlas plane, then register each histology section to that atlas plane. | Practical for sparse sections and region quantification. | Lower 3D continuity; rat atlas/tool support must be checked. |
| Reference-constrained global reconstruction | Casamitjana et al. 2021 | Estimate transforms jointly with a reference volume to avoid drift and outliers. | Avoids banana effect and z-shift from naive neighbor alignment. | More complex; needs enough data and a reference. |
| BrainGlobe/brainreg 3D registration | Tyson et al. 2022 / BrainGlobe docs | Register a 3D sample volume to atlas space using reorientation, affine, and freeform registration. | Excellent downstream atlas-analysis ecosystem. | Assumes a 3D sample volume already exists. |
| Fiji/ImageJ/QuPath slice workflows | Local Drive spreadsheet: ABBA, Slice2Volume | Use BioFormats, Elastix, BigWarp, and transform export around slice images. | Practical for whole-slide formats and manual correction. | Needs hands-on QC and tool-specific transform management. |

## Synthesis

There are two realistic paths:

1. **If you have or will acquire a dense serial dataset**: build an ordered
   section stack, estimate physical z-spacing, correct slice-to-slice
   deformation, then register the reconstructed volume to a rat atlas. This is
   the closest analogue to Ali et al. 2018 and lets BrainGlobe/brainreg become
   useful downstream.

2. **If you only have sparse sections like the demo**: do not force a full 3D
   volume. Use per-slice 2D-to-atlas registration, ideally with a rat atlas, and
   aggregate region measurements section-by-section. This aligns more with
   Agarwal et al. and Piluso et al. conceptually.

The important warning from Casamitjana et al. is that simple adjacent-section
alignment can drift, producing plausible-looking but anatomically wrong 3D
shapes. Any full reconstruction needs a global constraint: atlas, MRI,
blockface images, landmarks, or a reference volume.

## Recommendation For This Repository

Start with a **slice-first atlas registration pipeline**, then add full 3D
volume reconstruction only if there are enough ordered sections.

Stage 1 should extend the current ND2 crop pipeline:

- export full-resolution section crops;
- write a `section_manifest.csv` with slide, crop path, section index, AP order,
  pixel size, channel names, orientation, and QC flags;
- generate downsampled registration images for fast tools;
- keep raw channel crops for later segmentation.

Stage 2 should choose between:

- **Sparse mode**: register each 2D section to a matching rat atlas plane and
  quantify labels per atlas region.
- **Dense mode**: reconstruct a 3D stack, then pass the volume to
  `brainreg`/BrainGlobe for atlas registration and segmentation.

## Open Questions

- Are the 17 demo sections a complete animal or only a small example?
- What is the section thickness and interval between mounted sections?
- Is the section order known physically, or must it be inferred from anatomy?
- Is a rat atlas available in the local BrainGlobe installation?
- Are there blockface images or low-magnification reference photographs?
- Which channel should drive registration: anatomy/background stain, labelled
  signal, or merged image?
