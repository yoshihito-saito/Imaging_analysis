# BrainGlobe Histology Segmentation Guide

Source checked: 2026-07-06

Primary source: [BrainGlobe tutorial: Segmenting 2/3D structures](https://brainglobe.info/tutorials/segmenting-3d-structures.html)

Related sources:

- [brainreg documentation](https://brainglobe.info/documentation/brainreg/index.html)
- [brainglobe-segmentation documentation](https://brainglobe.info/documentation/brainglobe-segmentation/index.html)
- [Analysing segmentation from other napari plugins](https://brainglobe.info/documentation/brainglobe-segmentation/user-guide/analysing-external-segmentation.html)

## Goal

Use BrainGlobe to place histology data into a reference atlas space, segment
2D or 3D regions of interest, and quantify where those segmented structures
fall relative to atlas-defined brain areas.

The tutorial is most directly useful for objects such as injection sites,
lesions, labelled projections, implant tracks, or other spatial features that
can be drawn manually or produced as a napari labels layer.

## Big Picture Workflow

1. Prepare a clean Python or conda environment with napari and BrainGlobe tools.
2. Register the histology volume to a BrainGlobe atlas with `brainreg`.
3. Open napari and load the `brainreg` output with `brainglobe-segmentation`.
4. Draw, import, or generate segmentation labels for the feature of interest.
5. Analyse the segmented region against atlas annotations.
6. Save region volumes, centers, summaries, and segmentation outputs in the
   `brainreg` output directory.

## What Each Tool Does

| Tool | Purpose in this workflow |
| --- | --- |
| `brainreg` | Registers the atlas/template brain to the sample image, then allows the sample and atlas annotations to be represented in a shared coordinate space. |
| `napari` | Interactive viewer used to inspect histology, atlas-aligned data, and segmentation layers. |
| `brainglobe-segmentation` | napari plugin for manual or imported segmentation of regions/tracks and atlas-aware analysis of those segmented features. |
| `brainglobe-atlasapi` | Provides access to supported anatomical atlases used by BrainGlobe tools. |

## Installation Notes

BrainGlobe's tutorial expects napari to be installed, preferably in a conda
environment. A typical setup is:

```powershell
conda create -n brainglobe-histology python=3.11 napari -c conda-forge
conda activate brainglobe-histology
pip install brainreg brainglobe-segmentation
```

Alternatively, install `brainglobe-segmentation` from inside napari:

1. Open napari.
2. Go to `Plugins > Install/Uninstall plugins`.
3. Search for `brainglobe-segmentation`.
4. Click `Install` if it is not already installed.

On Apple Silicon Macs, the tutorial notes that `conda install hdf5` may be
needed before installing the plugin. This is not usually relevant on this
Windows workstation, but it is worth remembering when moving the workflow
between machines.

## Required Input

For the 2D/3D segmentation tutorial, the required prerequisite is a completed
`brainreg` registration. You need to know the `brainreg` output directory
because `brainglobe-segmentation` loads the registered data from that folder
and saves analysis outputs back into it.

At minimum, plan to keep:

- the original histology image stack or volume;
- voxel size and image orientation notes;
- the selected atlas name and resolution;
- the `brainreg` output directory;
- any segmentation layers saved from napari;
- analysis summaries exported by `brainglobe-segmentation`.

## Step 1: Register Histology To An Atlas

Before segmentation, use `brainreg` to align the sample with a reference atlas.
The exact registration command depends on the dataset, atlas, orientation, and
voxel spacing. The important concept is that `brainreg` creates an output
folder containing the registered image, atlas annotations, and transforms
needed for atlas-aware downstream analysis.

Quality control matters here. Before segmenting, inspect the registration and
confirm that major anatomical boundaries line up well enough for the intended
quantification. If the registration is poor, segmentation summaries by atlas
region will also be poor.

## Step 2: Load The Registered Project In Napari

1. Start napari from the BrainGlobe environment:

```powershell
conda activate brainglobe-histology
napari
```

2. Open the plugin:

```text
Plugins > Region/track segmentation (brainglobe-segmentation)
```

3. In the widget, click `Load project (atlas space)`.
4. Select the `brainreg` output directory.
5. If the registered image is dim or saturated, select the `Registered Image`
   layer and use `Autocontrast: once`.

## Step 3: Manually Segment A 2D Or 3D Region

Use this path for objects you can reliably draw by eye, such as an injection
site or localized labelled region.

1. In the `Segmentation` panel, click `Region Segmentation`.
2. Click `Add new region`.
3. A labels layer such as `region_0` appears in the napari layer list.
4. Rename the layer to something meaningful, for example
   `mouse01_injection_site`.
5. Navigate to the target structure in the registered image.
6. Choose a brush size.
7. Activate paint mode with the paintbrush icon.
8. Paint a solid object over the region of interest.
9. For 3D structures, either:
   - set `n edit dim` to `3` to paint a sphere; or
   - paint across consecutive slices using the slice slider.
10. Repeat for additional regions as needed.

Practical advice: keep each biological object as a clearly named region layer.
Avoid vague names such as `region_0` in saved projects because they make later
comparisons across animals unnecessarily painful.

## Step 4: Analyse The Segmented Region

When the segmentation is ready, click `Analyse regions`.

Useful options:

- `Calculate volumes`: calculates the volume of each atlas brain area included
  in the segmented region.
- `Summarise volumes`: exports summary information such as centers and volumes.
- `Save segmentation`: saves the segmentation while running the analysis. This
  can take longer, but it is useful for reproducibility.

The BrainGlobe tutorial notes that outputs are saved into the `brainreg` output
directory.

## Step 5: Use Automated Or External Segmentation When Needed

Manual segmentation is fine for simple or sparse structures, but automated
segmentation is better when the feature is large, repetitive, faint, or
requires consistent thresholds across many samples.

BrainGlobe can analyse layers produced by other napari plugins if the external
plugin returns one of these layer types:

- a 3D labels layer containing a 2D or 3D labelled region;
- a 3D points layer representing a trajectory through 3D space.

Recommended pattern:

1. Load the registered data through `brainglobe-segmentation` first.
2. Run the external napari segmentation plugin on the loaded image.
3. Confirm the result is a compatible labels or points layer.
4. Select the generated layer in napari.
5. In `brainglobe-segmentation`, choose `Region segmentation` or
   `Track tracing`.
6. Click `Add region from selected layer` or `Add track from selected layer`.
7. Run the corresponding analysis.

Loading data through `brainglobe-segmentation` before using third-party plugins
helps keep the image, segmentation, and atlas coordinate spaces consistent.

## Recommended Dataset Organization

For each animal or sample, keep a folder like:

```text
sample_id/
  raw/
    histology_stack.tif
  brainreg/
    ...
  segmentation/
    notes.md
    exported_layers/
  qc/
    registration_screenshots/
    segmentation_screenshots/
```

If the BrainGlobe outputs already live inside the `brainreg` directory, avoid
duplicating large files. Use the `segmentation/notes.md` file to record what was
drawn, who drew it, and which analysis options were selected.

## Quality Control Checklist

- Confirm the histology stack orientation before registration.
- Confirm the voxel spacing used by `brainreg`.
- Inspect registration alignment in several anatomical regions, not just near
  the feature of interest.
- Save screenshots of the registered image with atlas overlays.
- Use consistent names for regions across samples.
- Save the segmentation layer, not only the numerical summary.
- Record whether segmentation was manual, threshold-based, or generated by a
  specific napari plugin.
- For group analysis, check whether left/right hemisphere handling matters for
  your biological question.

## Outputs To Expect

The tutorial states that all analysis data are saved into the `brainreg` output
directory. Depending on selected options, expect saved segmentation data and
tables summarizing:

- segmented region volume;
- overlap with atlas brain areas;
- centers or summary coordinates;
- per-region measurements for each segmented object.

The exact filenames can vary with BrainGlobe version, so after the first run,
inspect the `brainreg` output directory and document the filenames used by the
installed version in the sample's notes.

## How This Fits This Repository

This repository already contains histology-oriented environment files and
section-isolation notebooks. A sensible next implementation step would be to
add a reproducible notebook or script that:

1. records sample metadata and raw image paths;
2. points to the `brainreg` output directory for each sample;
3. reads BrainGlobe summary tables after segmentation;
4. combines per-sample region measurements into a project-level CSV;
5. generates QC plots for atlas-region distribution across samples.

Keep reusable parsing and plotting helpers in `src/`, and keep notebooks focused
on orchestration, parameters, visualization, and sample-specific commentary.

## Common Pitfalls

- Starting segmentation before checking registration quality.
- Drawing in the wrong coordinate space.
- Forgetting to save segmentation layers.
- Reusing default names like `region_0` across many samples.
- Mixing manual and automated segmentation without recording the method.
- Comparing samples registered to different atlas versions or resolutions
  without documenting that difference.

## Citation Reminder

If the workflow is used in a publication, cite the relevant BrainGlobe tools,
the atlas used, and the underlying `brainreg` or `brainglobe-segmentation`
papers listed in the BrainGlobe documentation.
