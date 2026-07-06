# BrainGlobe Rat Workflow Summary

Source checked: 2026-07-06

Primary sources:

- https://github.com/brainglobe
- https://brainglobe.info/documentation/brainreg/index.html
- https://brainglobe.info/documentation/brainglobe-atlasapi/usage/atlas-details.html
- https://brainglobe.info/documentation/brainglobe-workflows/brainmapper/data-requirements.html
- https://brainglobe.info/documentation/brainglobe-segmentation/index.html

Read status: documentation-level.

## What BrainGlobe Is

BrainGlobe is an ecosystem of interoperable Python tools for computational
neuroanatomy. The core pieces relevant here are:

- `brainglobe-atlasapi`: standard access to atlases;
- `brainreg`: atlas-to-sample registration;
- `brainglobe-segmentation`: napari plugin for manual/imported object or region
  segmentation after registration;
- `brainmapper`/`cellfinder`: whole-brain cell detection/registration workflows
  for supported volumetric datasets.

## Rat Atlas Support

BrainGlobe Atlas API currently lists rat atlases:

- `whs_sd_rat_39um`: Waxholm Space Sprague Dawley rat atlas, 39 um MRI template,
  222 annotated structures.
- `swc_female_rat_50um`: SWC female rat atlas, 50 um STPT-derived template.
- `whs_sd_swc_female_rat_39um`: SWC female rat template aligned to Waxholm
  Space, 39 um, with Waxholm annotations.

This is the strongest reason to use BrainGlobe as the atlas layer for this
project.

## brainreg Workflow

`brainreg` registers a template brain to the sample image. The documentation
describes the process as:

1. filter template and sample images;
2. reorient the sample;
3. run affine registration;
4. run freeform registration;
5. apply the resulting transform to atlas annotations;
6. optionally invert/apply transforms to move sample data into common atlas
   space.

The only registration backend currently documented is NiftyReg.

## Orientation And Voxel Size

BrainGlobe uses explicit image-space definitions. The napari plugin can
interactively check orientation by comparing atlas projections to input data
projections. For this project, orientation is a first-class metadata field, not
an afterthought.

The key manifest fields are:

- AP/ML/DV orientation for the final stack;
- x/y pixel size in micrometers;
- section thickness;
- section interval;
- z-spacing used in the reconstructed volume;
- any flips or rotations applied to each section.

## Channel Handling

BrainGlobe's brainmapper documentation is very clear about channel roles:

- registration needs a single channel;
- the registration channel should ideally be a background/autofluorescence
  channel without strong labelled signal;
- cell detection needs a signal channel plus a background channel;
- different channels should be stored in different directories or text files.

The documentation also warns that brainmapper expects planes already registered
to each other, which is often not true for slide scanners or manual acquisition.
That warning matters here: raw ND2 slide crops should not be fed directly to
brainmapper as if they were a pre-registered volume.

## Output Files

`brainreg` outputs include:

- `brainreg.json`: input parameters for downstream tools;
- `downsampled.tiff`: raw data reoriented/downsampled to atlas resolution;
- `downsampled_standard_*.tiff`: raw data transformed to atlas space;
- `registered_atlas.tiff`: atlas annotations warped to raw-data space;
- `registered_hemispheres.tiff`: hemisphere labels in registered space;
- `boundaries.tiff`: atlas boundaries transformed to raw-data space;
- deformation fields;
- `volumes.csv`: atlas-region volume summary.

These files make BrainGlobe attractive for reproducible downstream analysis.

## Segmentation And Downstream Analysis

`brainglobe-segmentation` is a napari plugin companion to `brainreg`. It allows
manual or imported segmentation of regions/objects such as injection sites,
probes, or other labelled structures, then analyses their brain-region
distribution and supports visualization in tools such as brainrender.

For this project, expected analyses include:

- injection/lesion/implant localization;
- labelled projection density per rat atlas region;
- cell counts per rat atlas region if a robust detector is added;
- atlas-space visualization and QC overlays.

## Relevance To This Repository

BrainGlobe is the right atlas-analysis target, but it needs well-formed inputs:

- either a dense reconstructed 3D stack;
- or a slice-wise registration bridge that maps individual sections to the rat
  atlas.

The current `demo/` data are 2D slide mosaics. The repository should therefore
produce a BrainGlobe-ready intermediate dataset rather than trying to pass raw
ND2 slides directly into `brainreg`.
