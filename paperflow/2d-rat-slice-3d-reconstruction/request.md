# 2D Rat Slice 3D Reconstruction Literature Request

Date: 2026-07-06

## Question

What methods and software are suitable for reconstructing a 3D rat brain volume
from serial 2D histology slices, and how do published workflows handle slice
ordering, damaged or missing sections, nonlinear slice-to-slice deformation,
atlas registration, and downstream atlas-based quantification?

## Source Repository

`D:\Imaging_analysis`

## Source Context

The repository contains a current preprocessing pipeline for large Nikon ND2
slide mosaics. The `demo/` folder contains three 2D, 3-channel ND2 slide
mosaics:

- `Slide_01_x4.nd2`: 3 channels, 19800 x 38700 pixels, six detected sections.
- `Slide_02_x4.nd2`: 3 channels, 19800 x 44775 pixels, six detected sections.
- `Slide_03_x4.nd2`: 3 channels, 26280 x 46800 pixels, five detected sections.

The existing package can detect individual tissue sections, generate RGB
previews, save crop manifests, and export ordered crops. The desired next stage
is 3D reconstruction and atlas-aware analysis.

## Source Files To Read

- `src/brain_section_pipeline/pipeline.py`
- `src/brain_section_pipeline/io.py`
- `src/brain_section_pipeline/crop.py`
- `scripts/preview_nd2.py`
- `reference/brainglobe-histology-segmentation-guide.md`

## Literature Scope

Prioritize:

- rat brain serial histology 3D reconstruction;
- 2D-to-3D histology-to-atlas registration;
- serial section reconstruction with missing/damaged slices;
- nonlinear slice-to-slice alignment;
- BrainGlobe, brainreg/aMAP, QuickNII/VisuAlign, SHARCQ, AMaSiNe, STPT/serial
  two-photon alignment, and related open software;
- atlas-based quantification after reconstruction.

Include mouse methods when they are transferable to rat histology or when rat
software is sparse.

## Library Search Terms

- rat brain histology reconstruction
- serial section reconstruction brain atlas registration
- 2D histology 3D reconstruction brain
- QuickNII VisuAlign rat
- AMaSiNe histology reconstruction
- SHARCQ brain histology registration
- brainreg aMAP histology atlas registration
- Waxholm rat atlas histology registration

## Desired Output

Create paperflow artifacts that summarize relevant papers and methods, then
provide a recommendation for this repository's pipeline:

1. candidate software/workflows;
2. method comparison table;
3. recommended staged pipeline for the demo ND2 dataset;
4. risks and validation checks;
5. papers that should be added to the user's library if missing.

## Claim Boundaries

Separate methods actually read from metadata-only candidate papers. Distinguish
rat-specific workflows from mouse workflows that may transfer conceptually but
require atlas/tool changes.
