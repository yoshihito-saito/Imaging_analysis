# ND2 Brain Section Pipeline

Date: 2026-06-14

Status: uncommitted. `D:\Imaging_analysis` is not currently a Git repository, so no commit hash is available.

Plan: [../implementation_plan/2026-06-14-nd2-brain-section-pipeline.md](../implementation_plan/2026-06-14-nd2-brain-section-pipeline.md)

## What Changed

- Added a conda environment file at `environment.yml` for ND2/Jupyter processing.
- Renamed the conda environment to `histology`.
- Added package metadata in `pyproject.toml`.
- Added reusable source code under `src/brain_section_pipeline/`:
  - ND2 discovery, metadata summary, and channel-first loading.
  - NaN/Inf sanitization and robust percentile RGB channel merging.
  - `section_isolator`-style tissue masking, connected-component detection, ordered crop boxes, and crop saving.
  - End-to-end per-file and selected-file processing with merged images, overlays, CSV manifests, and metadata JSON output.
- Added `notebooks/nd2_brain_section_pipeline.ipynb` as the Jupyter execution entrypoint.
- Updated the notebook to support a local multiple-selection ND2 file dialog before processing, with a fallback folder path when the dialog is cancelled or unavailable.
- Changed the notebook default to skip the modal file dialog (`use_file_dialog = False`) and scan `fallback_folder` instead, because hidden modal dialogs in VS Code can make the cell appear to run indefinitely.
- Added `scripts/preview_nd2.py` for downsampled crop-detection previews on large ND2 files.
- Added `select_nd2_files_dialog()` as a notebook-facing helper exported from `brain_section_pipeline`.
- Made `select_nd2_files_dialog()` request topmost window behavior so it is less likely to open behind VS Code when explicitly enabled.
- Added explicit crop ordering modes `row_left_to_right` and `row_right_to_left` while keeping the existing `row` alias.
- Updated the notebook default to `sort_mode="row_right_to_left"` so section numbering starts at the upper right for the current rat slide layout.
- Added a `--sort-mode` option to `scripts/preview_nd2.py`, defaulting to `row_right_to_left`.
- Updated the notebook preview cell to loop over every file in `selected_files` instead of previewing only the first selected file.
- Increased the default crop margin from 150 px to 250 px in the reusable pipeline, notebook config, and preview script.
- Updated batch crop saving so `process_selected_files()` writes all crop images directly under `cropped_sections` with continuous names such as `section001.tif`, `section002.tif`, and so on across all selected slides.
- Kept per-slide merged images, overlays, metadata, and manifests in their existing per-slide subfolders.
- Changed primary crop outputs from pseudo-colored RGB crops to raw channel-stack TIFFs shaped as `(C, Y, X)`, so splitting or reading crop files does not inherit RGB pseudo-color mixing.
- Saved raw channel-stack TIFFs with grayscale photometric metadata and `CYX` axes to avoid 3-channel stacks being interpreted as RGB images.
- Added `crop_output_mode="rgb_direct"` for ordinary RGB crop files that directly pack raw microscope channels without pseudo-color mixing.
- Updated the notebook default crop output to direct RGB packing with `rgb_direct_channels=(2, 1, 0)`, meaning `R=ch2`, `G=ch1`, and `B=ch0`. ImageJ RGB split can recover the original channels from these crop files as long as values are not rescaled or clipped downstream.
- Kept `crop_output_mode="raw_stack"` available for workflows that prefer channel-stack TIFF output.
- Tuned the default detection parameters for the provided rat demo ND2 files: blue-channel masking with ND2 channel index 0, larger minimum area, larger margin, and stronger closing.
- Corrected RGB merge defaults to follow the provided ND2 metadata color order: channel 0 blue `(3, 81, 255)`, channel 1 green `(91, 255, 0)`, and channel 2 orange/red `(255, 160, 0)`.
- Registered the `histology` conda environment as a Jupyter kernel named `histology`.
- Added `tk` to `environment.yml` for reproducible local file-dialog support.
- Added synthetic unit tests in `tests/test_merge_and_crop.py`.
- Moved the invalid root-level notebook dump from `__init__.py` to `reference/section_isolator_notebook_dump.ipynb` so the workspace root is not treated as an importable Python package.

## Why

The user needs a Python-only workflow for Nikon ND2 rat brain section data that may not open in ImageJ, likely because of invalid numeric values or file quirks. The new pipeline starts from selected `.nd2` files, merges channels, detects separated sections, crops them, and saves outputs from a notebook.

## Verification

Commands run:

```powershell
conda run -n histology python -m py_compile src\brain_section_pipeline\__init__.py src\brain_section_pipeline\io.py src\brain_section_pipeline\merge.py src\brain_section_pipeline\crop.py src\brain_section_pipeline\pipeline.py scripts\preview_nd2.py
conda run -n histology python -m pytest
python -m json.tool notebooks\nd2_brain_section_pipeline.ipynb
conda run -n histology python -c "import tkinter; print('tkinter ok')"
conda run -n histology python -c "import nd2; print('nd2', nd2.__version__)"
conda run -n histology python scripts\preview_nd2.py demo --output demo\previews_blue_mask --downsample 16
conda run -n histology python scripts\preview_nd2.py demo --output demo\previews_row_right_to_left --downsample 16 --sort-mode row_right_to_left
conda run -n histology python scripts\preview_nd2.py demo --output demo\previews_margin250_all --downsample 16
```

Result:

- Source compilation passed.
- `conda run -n histology python -m pytest` passed: 9 tests collected, 9 passed.
- Notebook JSON validation passed.
- `tkinter` imported in the `histology` environment.
- `nd2` imported in the `histology` environment: version 0.11.3.
- Downsampled demo previews completed:
  - `Slide_01_x4.nd2`: 6 detected sections.
  - `Slide_02_x4.nd2`: 6 detected sections.
- Right-to-left row-order demo previews completed:
  - `Slide_01_x4.nd2`: 6 detected sections, numbered upper-right to upper-left, then lower-right to lower-left.
  - `Slide_02_x4.nd2`: 6 detected sections.
- Wider-margin all-slide demo previews completed:
  - `Slide_01_x4.nd2`: 6 detected sections.
  - `Slide_02_x4.nd2`: 6 detected sections.

## Observed Behavior

Synthetic tests confirm that:

- NaN and Inf values are converted to finite values during scaling/merging.
- Channel merging returns finite RGB `uint8` images.
- Separated tissue-like sections are detected, sorted, and cropped with expected dimensions.
- Nested internal components are dropped after margin expansion so internal bright regions do not become extra section crops.
- The file-dialog helper is exported without opening a GUI during package import.
- The file-selection notebook cell no longer opens a modal dialog by default, so it should complete quickly when scanning the demo folder or a configured folder.
- Row-wise right-to-left sorting orders a 2-by-3 synthetic layout as upper-right, upper-middle, upper-left, lower-right, lower-middle, lower-left.
- Notebook preview now iterates over all selected files and displays one downsampled overlay per slide.
- Continuous crop filename generation was verified with synthetic crops starting from a non-1 index.
- Channel-first raw stack crop saving was verified by writing and reading a synthetic 3-channel TIFF without channel mixing.
- Direct RGB packing was verified by mapping synthetic raw channels into RGB and checking that R, G, and B exactly match the requested source channels.

Demo ND2 metadata confirmed that channel index 0 is the blue display channel, despite non-informative Nikon channel names such as `TRITC`. The current defaults use channel index 0 for tissue detection. Slide 02 can still look yellow/orange in merged RGB previews because robust percentile scaling and channel 2 display color affect visualization; that display appearance does not change the blue-channel detection mask.

## Known Limitations And Next Steps

- Acquisition axis layouts vary between ND2 files; the loader exposes scene, position, time, and Z controls, but real data may require small axis-handling adjustments.
- The file dialog requires a local GUI-capable Jupyter session. If enabled and it appears slow, it is likely waiting for a hidden dialog; keep `use_file_dialog = False` or check behind VS Code with Alt-Tab.
- Manual crop correction is not implemented yet. If automatic detection misses tissue or merges nearby sections, tune `mask_channel`, `min_area`, `closing_iterations`, and `margin` in the notebook first.
- Full-resolution batch cropping of the multi-GB demo files was not run during verification to avoid creating large output artifacts without an explicit processing target.
