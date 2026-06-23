# ND2 Brain Section Pipeline

Date: 2026-06-14

## Goal And Motivation

Build a Python-first workflow for Nikon ND2 rat brain section images that can be run from Jupyter Notebook. The workflow should avoid ImageJ, tolerate NaN/Inf pixel values, merge channels into an RGB preview/output, isolate each tissue section, crop each section, and repeat this for selected ND2 files in a folder.

## Current Problem

The current workspace contains the original `section_isolator` notebook logic, which assumes already-merged whole-slide `.tif` inputs. The target data are `.nd2` files, and ImageJ may fail to open them, likely due to invalid numeric pixel values or metadata/data quirks. There is no reusable source package yet for ND2 loading, channel merging, crop detection, or Jupyter-facing batch execution.

## Why This Is Needed Now

The user wants a conda-based, notebook-operated analysis path that starts from a selected folder of `.nd2` files and processes selected files without requiring manual ImageJ conversion.

## Git Or Worktree State

`D:\Imaging_analysis` is not currently a Git repository, so commit hash and branch information are unavailable.

## Affected Modules And Files

- `environment.yml`: conda environment for the notebook pipeline.
- `src/brain_section_pipeline/`: reusable package code.
- `notebooks/nd2_brain_section_pipeline.ipynb`: execution-facing notebook.
- `tests/`: focused tests for channel merge, NaN handling, component detection, and crop saving.
- `change_log/`: post-implementation log.
- `reference/`: preserved copy of the `section_isolator` notebook dump that had been placed at the repository root as `__init__.py`.

Existing `section_isolator` notebook files are treated as reference material. The invalid root-level `__init__.py` notebook dump may be moved intact so it does not make the workspace an importable package.

## Public Parameters Or API Changes

New public functions will include:

- `find_nd2_files(folder)`: discover ND2 files below or inside a folder.
- `select_nd2_files_dialog(initial_dir=None)`: open a local file dialog and return selected ND2 paths for notebook use. The notebook should keep this behind an explicit switch because modal dialogs can be hidden behind VS Code and make a cell appear slow.
- `read_nd2_image(path, scene_index=0, z_index=None, time_index=0)`: load a 2D channel-first image from ND2.
- `read_nd2_image(..., downsample=1)`: optionally load a spatially downsampled image for safe preview/detection on very large ND2 slides.
- `merge_channels(image, channel_colors, percentiles)`: create an RGB image with robust percentile scaling.
- `detect_section_crops(image, ...)`: create tissue mask, connected components, and ordered crop boxes.
- `process_nd2_file(path, output_dir, config)`: read, merge, crop, and save outputs.
- `process_selected_files(paths, output_dir, config)`: repeat processing across selected files and save crop images with continuous numbering across the selected set.

## Algorithm Details

The crop detector follows the `section_isolator` idea:

1. Build a tissue-detection image from selected channels or from RGB intensity.
2. Replace NaN/Inf with finite values.
3. Estimate foreground using Otsu thresholding or a configurable quantile fallback.
4. Apply morphological opening/closing and small-object removal.
5. Label connected components.
6. Filter by minimum area.
7. Create bounding boxes with margin.
8. Sort sections by a selectable order. Supported row-wise modes should include top-to-bottom with either left-to-right or right-to-left order within each row, plus the existing diagonal and area modes.

Channel merging maps each channel to an RGB color vector and uses robust percentiles to scale fluorescence intensity. This prevents a few hot pixels or invalid values from dominating the merged image.

RGB merge products must be treated as visualization outputs only. Because pseudo-color vectors such as `(3, 81, 255)` intentionally place blue-channel signal into multiple RGB components, splitting an RGB merged crop cannot recover the original microscope channels. Analysis crop files should therefore save the raw channel stack `(C, Y, X)` directly, with RGB merged files retained only for previews and overlays.

To reduce downstream friction, raw channel crops should be mergeable into one ordinary RGB image per section when there are three relevant channels. This must be a direct channel-to-RGB packing, not pseudo-color merging: for the demo metadata, channel 2 should fill R, channel 1 should fill G, and channel 0 should fill B. RGB split can then recover the original raw channel planes as long as no percentile scaling, clipping, or color-vector mixing is applied. A raw stack mode can remain available when hyperstack-style output is preferred.

The provided demo ND2 metadata reports channel index 0 with RGB color `(3, 81, 255)`, channel index 1 with `(91, 255, 0)`, and channel index 2 with `(255, 160, 0)`. Defaults should therefore treat channel index 0 as the blue/DAPI-like tissue-detection channel, even though the Nikon channel names are not informative.

Large ND2 files may be previewed by strided spatial downsampling before full-resolution processing. The demo files are about 4.6 GB and 5.3 GB, so the notebook should default to downsampled preview for detection tuning.

Crop margins should preserve some surrounding context around each brain section. The rat demo defaults should use a wider margin than the first pass because the user wants extra space around saved crops.

## Expected Behavior

From a notebook, the user can:

1. Select `.nd2` files from a fast folder scan by default, or explicitly enable a local multiple-selection file dialog.
2. See the selected or discovered `.nd2` files.
3. Select files to process without editing numeric indices when the dialog is used.
4. Preview merged image and detected crop boxes for every selected file.
5. Run batch processing.
6. Receive per-file merged preview images, crop overlay images, metadata/manifests, and all crop images in `cropped_sections` with continuous names such as `section001.tif`, `section002.tif`, and so on. Primary crop files should default to direct RGB packing so later RGB split recovers the independent raw channels.

## Verification

- Run unit tests against synthetic images containing multiple separated sections and NaN/Inf values.
- Compile package source files.
- Validate that the notebook imports from `src/` and does not duplicate core logic.
- Verify downsampled previews on the demo ND2 files and confirm that both slides use blue-channel detection.
- Verify that the notebook preview cell loops over all selected files instead of only `selected_files[0]`.
- Verify that the wider crop margin is consistently applied to the notebook, script preview, and reusable pipeline defaults.
- Verify that batch crop output names continue numbering across files instead of resetting for each slide.
- Verify that primary crop files can be saved as direct RGB images with channel 2 in R, channel 1 in G, and channel 0 in B, so RGB split recovers unmixed channel planes.
- Verify that raw stack output remains available as an option for workflows that prefer channel-stack TIFFs.
- Validate that the file-dialog helper imports without requiring GUI access during package import.
- Validate that the notebook can skip the modal file dialog by default to avoid hidden-dialog waits in VS Code.
- Verify row-wise right-to-left crop ordering so a top-right section can be numbered first when the slide layout requires it.

## Non-Goals

- Do not implement manual GUI drawing for crop correction in this first pass.
- Do not attempt full whole-slide stitching or ND2 pyramid handling.
- Do not modify the original `section_isolator` reference files.
- Do not guarantee all microscope acquisition axis layouts without test data; instead expose axis/scene/time/z parameters and record detected metadata.
