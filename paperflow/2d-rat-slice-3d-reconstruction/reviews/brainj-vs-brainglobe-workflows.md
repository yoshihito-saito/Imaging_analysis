# BrainJ And BrainGlobe Workflow Comparison

Created: 2026-07-06

## 1. Overall Overview

For this rat histology project, the best overall strategy is to use BrainGlobe
as the atlas and registration backend, while using BrainJ as a design reference
for a slide-section-first workflow.

BrainJ has strong practical value for serial tissue sections and has worked
well for mouse brain sections. However, the public README is primarily framed
around mouse atlas workflows, and rat atlas support is not documented there. In
contrast, BrainGlobe currently provides rat atlas options, including
`whs_sd_rat_39um`, `swc_female_rat_50um`, and
`whs_sd_swc_female_rat_39um`. Because this project needs a rat brain atlas,
BrainGlobe is the more natural production atlas layer.

The important caveat is that BrainGlobe's `brainreg` registers an already
well-formed 3D sample volume to an atlas. It does not, by itself, solve the
earlier slide-processing problem of extracting each physical section from raw
slide images, ordering the sections, separating channels, and constructing a
registration-ready image series or volume. That makes this repository's
preprocessing role central.

## BrainJ And BrainGlobe Roles

| Item | BrainJ | BrainGlobe |
| --- | --- | --- |
| Main target | Serial tissue sections | 3D volumes and atlas-aware neuroanatomy |
| Software base | Fiji/ImageJ | Python, napari, BrainGlobe Atlas API |
| Registration style | Slide-section workflow using tools such as MultiStackReg, TurboReg, and Elastix | Atlas-to-sample registration with `brainreg` |
| Machine-learning analysis | Ilastik pixel classification | `cellfinder`, `brainmapper`, and related BrainGlobe workflows |
| Atlas fit | Strong mouse atlas orientation | Rat atlases are available |
| Recommended role here | Workflow reference | Production atlas backend |

## 2. Step-By-Step Details

### Step 0: Organize Input Slide Images

The current demo data are Nikon ND2 slide mosaics. Each file is a large 2D
multichannel image containing multiple physical tissue sections. The first task
is therefore to crop each physical section from each slide and store one image
per section.

The current repository already supports:

- reading ND2 files;
- converting data into channel-first arrays;
- generating RGB previews;
- detecting tissue sections;
- creating crop overlays;
- writing crop manifests.

For both BrainJ-style and BrainGlobe-style workflows, the critical unit is not
the location on the scanned slide, but the physical section and its serial
position in the brain. Therefore `section_manifest.csv` should become the
central table. It should record `section_index`, `slide_id`, `crop_path`,
`pixel_size_um`, `section_thickness_um`, `section_interval_um`, `orientation`,
and `qc_status`.

### Step 1: Handle Color Channels Explicitly

BrainJ and BrainGlobe both benefit from separating the registration channel from
the signal-analysis channels.

BrainGlobe's brainmapper documentation states that registration only requires
one channel, and that this channel should ideally be a background or
autofluorescence channel without strong labelled signal. Cell detection requires
a signal channel and a background channel. The documentation also expects
channels to be organized in separate directories or text files.

The current demo metadata include three channels:

| Channel | Metadata name | Emission nm | Likely role |
| --- | --- | ---: | --- |
| 0 | `TRITC` | 457.5 | Registration/background candidate |
| 1 | `TRITC_1` | 535.0 | Signal or structural support candidate |
| 2 | `TRITC_2` | 603.5 | Signal or structural support candidate |

The metadata names are not biologically descriptive enough to decide the final
roles. The actual images must be inspected. A conservative pipeline should
export a single `reg_channel.tif` for registration and keep raw channel crops
for downstream signal analysis.

Recommended output structure:

```text
processed/sample_id/
  sections_registration/
    section001_reg.tif
    section002_reg.tif
  sections_channels/
    ch0/section001_ch0.tif
    ch1/section001_ch1.tif
    ch2/section001_ch2.tif
  sections_rgb/
    section001_rgb.tif
  qc_overlays/
  section_manifest.csv
```

### Step 2: Track Section Order And AP Coverage

BrainJ's README directly states that sections should span at least 2-3 mm in
the anterior-posterior axis. The same principle matters for BrainGlobe. With
only 17 demo sections, the dataset is useful for prototyping but may be too
sparse to validate a whole-brain 3D reconstruction.

The pipeline should explicitly record:

- whether slide layout order matches true anterior-posterior order;
- whether the slide sequence starts from top-left, top-right, or another rule;
- whether sections are missing;
- the section interval in micrometers;
- any left-right flips or rotations;
- which sections should be excluded or flagged for review.

### Step 3A: BrainJ-Style Workflow

A BrainJ-style workflow can be summarized as:

1. Import the section image series into Fiji/ImageJ.
2. Align serial sections using tools such as MultiStackReg and TurboReg.
3. Use Elastix for atlas alignment or deformable registration.
4. Use an Ilastik project to classify cells, projections, or labelled signal.
5. Quantify and visualize signal in mouse atlas space.

The strength of BrainJ is that it starts from serial slide sections. The
weakness for this project is that rat atlas support is not documented as a
standard path. Using BrainJ directly for rat would require checking whether its
atlas files, ontology assumptions, and macros can be replaced or adapted.

The BrainJ ideas worth preserving are:

- treat serial section images as first-class data;
- perform section-level GUI/QC for tissue damage and ordering;
- keep registration and signal channels separate;
- assume pixel classification must be retrained or validated for each staining
  protocol;
- record damaged tissue as a major registration-failure risk.

### Step 3B: BrainGlobe-Style Workflow

BrainGlobe is strongest once the input is already a coherent 3D image volume.

A BrainGlobe-oriented workflow is:

1. Build a registration-channel stack from section crops.
2. Specify x/y/z spacing and image orientation.
3. Register the sample volume to a rat atlas with `brainreg`.
4. Save `registered_atlas.tiff`, `boundaries.tiff`, `brainreg.json`, and
   deformation fields.
5. Inspect registration quality in napari.
6. Use `brainglobe-segmentation` to segment injection sites, lesions, implants,
   projection regions, or other labelled objects.
7. Summarize volume, count, or intensity by atlas region.

Candidate rat atlases:

- `whs_sd_rat_39um`: first-choice candidate when Waxholm Space / Sprague Dawley
  compatibility is desired.
- `swc_female_rat_50um`: useful if the data are closer to the SWC female
  Lister Hooded STPT template.
- `whs_sd_swc_female_rat_39um`: useful when both Waxholm interoperability and
  SWC template detail are relevant.

The key warning from BrainGlobe brainmapper documentation is that image planes
are expected to already be registered to each other. The documentation notes
that this is often not true for slide scanner or manual acquisition data. Raw
slide crops should therefore not be passed directly into BrainGlobe as if they
were already a clean volume.

### Step 4: Registration Design

The realistic registration design has two stages:

| Stage | Purpose | Recommended approach |
| --- | --- | --- |
| Section-to-section | Make the section series coherent as a volume | Start with rigid/affine alignment; add local or nonlinear correction only if needed |
| Volume-to-atlas | Map the reconstructed sample to a rat atlas | Use BrainGlobe `brainreg` |

For sparse datasets, it is safer to avoid forcing a 3D volume. Instead, treat
each section as an independent atlas-plane registration target. Even in this
case, the final ontology and region summary should still be based on a
BrainGlobe rat atlas where possible.

### Step 5: Downstream Analysis

Analysis should happen after registration, not before.

BrainJ-style analysis:

- classify cell or projection signal with Ilastik;
- summarize positive pixels, cells, or projection density inside atlas regions;
- verify probe, GRIN lens, lesion, or implant placement in atlas space.

BrainGlobe-style analysis:

- analyse manual or imported labels with `brainglobe-segmentation`;
- combine `registered_atlas.tiff` with signal masks for region-wise summaries;
- use `cellfinder` or `brainmapper` only if the data meet their requirements;
- generate CSV summaries, QC plots, and atlas-region reports in this repository.

## 3. How This Should Enter The Current Pipeline

### Recommended Architecture

The production pipeline should look like:

```text
ND2 slide mosaics
  -> section crop extraction
  -> channel-preserving section dataset
  -> section_manifest.csv
  -> registration channel stack or slice-wise atlas inputs
  -> BrainGlobe rat atlas registration/annotation
  -> segmentation or signal detection
  -> atlas-region summary CSV + QC plots
```

### What To Implement In This Repository

The first concrete implementation should be `scripts/export_sections.py`. This
script is needed before either BrainJ-style or BrainGlobe-style processing.

It should output:

- `sections_rgb/`: images for visual QC;
- `sections_registration/`: the single registration channel or weighted
  structural image;
- `sections_channels/ch0-ch2/`: raw channel crops;
- `qc_overlays/`: crop boxes and section indices;
- `section_manifest.csv`: the reference table for every downstream tool.

### QC Before BrainGlobe

Before passing data to BrainGlobe, confirm:

- the registration channel is not dominated by the experimental signal;
- section order follows anterior-posterior order;
- left-right orientation is correct;
- torn, folded, or missing tissue is excluded or flagged;
- z-spacing is derived from the experimental section interval;
- the selected rat atlas matches the strain, sex, and imaging modality as well
  as possible.

### Dense Dataset Mode

If there are enough serial sections:

1. Sort crops in anterior-posterior order.
2. Build a registration-channel stack.
3. Run rigid/affine section-to-section alignment.
4. Add nonlinear correction only if required and validated.
5. Export a 3D TIFF or Zarr volume with voxel spacing metadata.
6. Register to `whs_sd_rat_39um` or another rat atlas with `brainreg`.
7. Analyse with `brainglobe-segmentation` and repository-level summary code.

### Sparse Dataset Mode

For a sparse dataset such as the current demo:

1. Treat each section as an independent atlas-plane registration target.
2. Determine the approximate anterior-posterior level manually or
   semi-automatically.
3. Reslice the rat atlas annotation to the corresponding plane.
4. Register the 2D section to that atlas plane.
5. Assign signal masks or cell coordinates to atlas regions.
6. Summarize results section-by-section rather than as a full reconstructed 3D
   volume.

### Final Recommendation

Use BrainGlobe's rat atlas support as the production atlas backend. Before
BrainGlobe, implement a BrainJ-inspired section-first workflow inside this
repository.

In short:

```text
Use BrainJ's workflow logic to organize slide sections.
Use BrainGlobe's rat atlases for registration and region ontology.
Keep analysis and QC reproducible in this repository.
```

## Sources

- BrainJ repository: https://github.com/lahammond/BrainJ
- BrainGlobe organization: https://github.com/brainglobe
- BrainGlobe Atlas API atlas details: https://brainglobe.info/documentation/brainglobe-atlasapi/usage/atlas-details.html
- brainreg documentation: https://brainglobe.info/documentation/brainreg/index.html
- brainreg output files: https://brainglobe.info/documentation/brainreg/user-guide/output-files.html
- brainreg orientation checking: https://brainglobe.info/documentation/brainreg/user-guide/checking-orientation.html
- BrainGlobe brainmapper data requirements: https://brainglobe.info/documentation/brainglobe-workflows/brainmapper/data-requirements.html
- brainglobe-segmentation documentation: https://brainglobe.info/documentation/brainglobe-segmentation/index.html
