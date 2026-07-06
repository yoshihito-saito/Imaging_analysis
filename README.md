# Brain Section Pipeline

This repository is being shaped into a workflow for reconstructing 3D rat
brain histology data from 2D slide sections and registering the result to a
BrainGlobe rat atlas. The implementation is not finalized yet. This README
summarizes the planned direction and the expected implementation boundaries.

## Current Status

The current code can process Nikon ND2 slide images, merge channels, detect
individual tissue sections, save section crops, and write basic crop metadata.
The next planned stage is to turn those cropped 2D sections into an organized
dataset that can be aligned section-to-section and then registered to a rat
atlas with BrainGlobe tools.

BrainGlobe should be treated as the atlas and registration backend, especially
through `brainreg` and `brainglobe-atlasapi`. The custom code in this repository
should handle slide-specific preparation, section ordering, channel export,
metadata, quality control, and post-registration quantification.

## Planned Workflow

### 1. Inspect The Raw Slide Data

Input data are expected to be ND2 slide scanner files with multiple color
channels and multiple physical tissue sections per slide. For each acquisition,
record:

- sample ID;
- slide ID;
- channel names and biological meaning;
- pixel size in microns;
- section thickness in microns;
- section interval in microns;
- physical section order;
- anterior-posterior direction;
- any missing, folded, torn, or duplicated sections.

The section interval is critical for 3D reconstruction. If 40 um sections were
cut but only every fifth section was imaged, the z spacing for reconstruction is
200 um, not 40 um.

### 2. Extract Individual Sections From Slides

Use the existing ND2 pipeline to detect tissue pieces and export one image per
section. The current reusable entry points are:

- `find_nd2_files` for locating ND2 files;
- `read_nd2_image` for reading channel-first image data;
- `detect_section_crops` for tissue section detection;
- `merge_channels` for RGB preview images;
- `process_nd2_file` and `process_selected_files` for end-to-end crop export.

Expected outputs for this stage:

```text
sample_id/
  sections_rgb/
    section001.tif
    section002.tif
  sections_channels/
    ch0/
    ch1/
    ch2/
  qc/
    slide_crop_overlays/
  section_manifest.csv
```

The section manifest should become the central handoff file. It should preserve
the source ND2 file, crop box, channel mapping, section index, slide position,
z position, pixel size, section thickness, section interval, and QC notes.

### 3. Select The Registration Channel

For BrainGlobe registration, use a structural or background-like channel when
possible. A strong sparse signal channel is usually a poor registration target.

Recommended channel roles:

- registration channel: autofluorescence, counterstain, or broad tissue signal;
- signal channels: marker channels used for downstream quantification;
- RGB preview: human QC only, not the primary registration input.

If no clean background channel exists, build a registration image from a robust
combination of channels and validate it visually before running atlas
registration.

### 4. Order And Align 2D Sections

Before using BrainGlobe, the section images must be placed in biological order
and aligned to each other. This is the main custom part of the workflow.

Planned alignment stages:

1. Sort sections by slide and physical position.
2. Manually correct the order if slide layout does not match biological order.
3. Normalize orientation so every section has the same left-right and
   dorsal-ventral convention.
4. Perform rigid or affine section-to-section alignment.
5. Optionally apply non-rigid correction for local tissue distortion.
6. Export a coherent 3D image stack for the registration channel.
7. Apply the same transforms to all signal channels.

For sparse datasets, such as only a small number of widely spaced sections,
full 3D reconstruction may be unreliable. In that case, the safer path is
slice-wise atlas-plane matching followed by section-level atlas summaries.

### 5. Register The Stack To A Rat Atlas With BrainGlobe

Once a coherent 3D stack exists, run `brainreg` with a rat atlas. Candidate
atlases include:

- `whs_sd_rat_39um`: Waxholm Space Sprague Dawley rat atlas;
- `swc_female_rat_50um`: SWC female rat atlas;
- `whs_sd_swc_female_rat_39um`: SWC female rat template aligned to Waxholm
  Space annotations.

The command shape is expected to be:

```powershell
brainreg path\to\registration_channel path\to\brainreg_output `
  -v Z_UM Y_UM X_UM `
  --orientation ORIENTATION `
  --atlas whs_sd_rat_39um `
  -a path\to\signal_channel_1 path\to\signal_channel_2
```

The exact `-v` order and `--orientation` value must be verified against the
prepared stack before production use.

Expected `brainreg` outputs include:

- `registered_atlas.tiff`;
- `registered_hemispheres.tiff`;
- `boundaries.tiff`;
- `downsampled.tiff`;
- `downsampled_standard_*.tiff`;
- deformation fields;
- `volumes.csv`;
- `brainreg.json`.

### 6. Quantify Signals By Atlas Region

After registration, use the warped atlas annotation image to summarize signal
or detected objects by anatomical region.

Planned measurements:

- mean, median, max, and integrated intensity per region and channel;
- labelled cell or object counts per region;
- normalized density per atlas volume or sampled section area;
- hemisphere-specific summaries when relevant;
- QC flags for regions affected by missing or damaged sections.

BrainGlobe Atlas API should provide atlas metadata and structure lookup, while
the repository code should perform dataset-specific table generation.

### 7. Quality Control And Review

Every sample should have QC outputs before downstream interpretation:

- slide crop overlays;
- section order preview;
- aligned stack preview;
- atlas boundary overlay on registered data;
- region summary sanity checks;
- notes for missing, folded, torn, or low-signal sections.

Registration should be rejected or repeated if major landmarks, ventricles,
cortex outline, hippocampus, striatum, or cerebellar boundaries are visibly
misaligned for the target analysis.

## Implementation Overview

### Existing Components

The current package already contains the first stage of the workflow:

```text
src/brain_section_pipeline/
  io.py        ND2 discovery and reading
  crop.py      tissue section detection and crop export
  merge.py     channel scaling and RGB merging
  pipeline.py  end-to-end ND2 crop processing
```

Existing scripts:

```text
scripts/
  preview_nd2.py  downsampled section preview and crop QC
```

These components should remain responsible for raw ND2 ingestion and section
crop generation.

### Planned Source Modules

The next implementation should be added as small reusable modules under
`src/brain_section_pipeline/`, not embedded directly in notebooks.

Proposed modules:

```text
src/brain_section_pipeline/
  export.py              prepare BrainGlobe-ready section folders
  section_manifest.py    validate and edit section metadata
  stack.py               build ordered channel stacks from section images
  alignment.py           run or wrap section-to-section registration
  brainglobe_api.py      small BrainGlobe Atlas API helper layer
  brainreg_runner.py     construct and run brainreg commands
  atlas_summary.py       summarize intensity or objects by atlas region
  qc.py                  generate preview images and QC tables
```

The first implementation milestone should focus on export and metadata, because
registration quality depends on reliable section order, channel mapping, and
voxel spacing.

### Planned Command-Line Entry Points

Proposed scripts:

```text
scripts/
  export_sections.py       export per-section, per-channel image folders
  build_stack.py           build an ordered 3D stack from the manifest
  run_brainreg.py          run brainreg with recorded voxel size/orientation
  summarize_atlas.py       produce region-level signal summaries
```

The scripts should be thin clients around package functions. They should not
contain the core image-processing logic.

### BrainGlobe API Usage

Use `brainglobe-atlasapi` for atlas inspection and structure metadata:

```python
from brainglobe_atlasapi.bg_atlas import BrainGlobeAtlas

atlas = BrainGlobeAtlas("whs_sd_rat_39um")
reference = atlas.reference
annotation = atlas.annotation
structures = atlas.lookup_df
resolution = atlas.resolution
orientation = atlas.orientation
mask = atlas.get_structure_mask("HIP")
```

Expected uses in this repository:

- verify the selected rat atlas exists locally;
- record atlas name, version, orientation, resolution, and shape;
- map structure IDs to acronyms and names;
- create region masks for analysis or QC;
- summarize registered data by atlas annotations.

Use `brainreg` itself as the registration engine through its command-line
interface unless a stable internal Python API is needed later.

### Metadata Contract

The pipeline should produce and preserve a machine-readable manifest. A minimal
manifest row should include:

```text
sample_id
slide_id
source_file
section_index
section_label
crop_x
crop_y
crop_width
crop_height
pixel_size_x_um
pixel_size_y_um
section_thickness_um
section_interval_um
z_position_um
registration_channel
channel_0_name
channel_1_name
channel_2_name
include_in_stack
qc_status
qc_notes
```

This contract is more important than the exact file layout, because it defines
how raw slide sections become a reproducible 3D reconstruction input.

### Recommended First Milestone

Implement a BrainGlobe preparation export without performing registration yet:

1. Read all ND2 files for a sample.
2. Detect and crop sections.
3. Export RGB previews and raw per-channel TIFF crops.
4. Write a sample-level `section_manifest.csv`.
5. Include physical metadata fields for pixel size, section thickness, section
   interval, and z position.
6. Generate QC overlays and a section order contact sheet.
7. Optionally load `BrainGlobeAtlas` to write atlas metadata.

This milestone would make the dataset inspectable and ready for deciding
whether to pursue full 3D `brainreg` registration or slice-wise atlas matching.

## References

- [BrainGlobe documentation](https://brainglobe.info/documentation/)
- [brainreg documentation](https://brainglobe.info/documentation/brainreg/index.html)
- [brainreg command-line tool](https://brainglobe.info/documentation/brainreg/user-guide/brainreg-cli.html)
- [BrainGlobeAtlas API](https://brainglobe.info/documentation/brainglobe-atlasapi/api/brainglobe_atlasapi.bg_atlas.BrainGlobeAtlas.html)
- [BrainGlobe histology segmentation guide](reference/brainglobe-histology-segmentation-guide.md)
- [Paperflow reconstruction review](paperflow/2d-rat-slice-3d-reconstruction/reviews/brainj-vs-brainglobe-workflows.md)
