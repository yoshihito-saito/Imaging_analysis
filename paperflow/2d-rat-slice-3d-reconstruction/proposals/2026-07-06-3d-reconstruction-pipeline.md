# Proposal: 3D Reconstruction Pipeline For The Demo Rat Histology Dataset

## Direct Recommendation

Build the pipeline in two modes:

1. **Sparse 2D atlas mode first**: robust for the current 17-section demo.
2. **Dense 3D reconstruction mode later**: only once a complete ordered serial
   section set, z-spacing, and orientation metadata are available.

BrainGlobe should be treated as the downstream atlas-analysis layer, not the
only reconstruction tool.

## Proposed Repository Pipeline

### Stage 0: Environment

Keep the current `histology` environment for ND2 preprocessing. Create a
separate registration environment later for BrainGlobe/napari/Fiji-dependent
tools so package conflicts do not break ND2 reading.

### Stage 1: ND2 to ordered section crops

Use the existing package:

- `find_nd2_files`
- `read_nd2_image`
- `detect_section_crops`
- `process_selected_files`

Add or expose a command-line script that exports:

- full-resolution crops;
- downsampled registration crops;
- overlay QC images;
- `section_manifest.csv`.

The manifest should include:

| Field | Purpose |
| --- | --- |
| `animal_id` | group crops by sample |
| `slide_id` | original ND2 file |
| `crop_path` | raw crop location |
| `registration_crop_path` | downsampled image for registration |
| `section_index` | physical serial order |
| `ap_order_confidence` | manual/automatic/unknown |
| `pixel_size_um` | x/y scale |
| `section_thickness_um` | z scale |
| `section_interval_um` | spacing between sampled sections |
| `flip_rotate_notes` | orientation corrections |
| `qc_status` | pass/fail/review |

### Stage 2A: Sparse 2D atlas mode

Use this first for the demo.

1. Export section crops.
2. Manually confirm section order and orientation.
3. Select a rat reference atlas/tool.
4. Register each section to a corresponding atlas plane.
5. Save forward and inverse transforms.
6. Segment signals/regions in section space.
7. Transform atlas labels into section space, or section labels into atlas
   coordinates.
8. Aggregate measurements by atlas region.

Candidate software:

- ABBA/Fiji/ImageJ if you want GUI-assisted slice registration with BigWarp and
  Elastix-style correction.
- Slice2Volume if BioFormats and arbitrary 3D volumes are most important.
- Custom Python/napari prototype if you want tight integration with this repo.

### Stage 2B: Dense 3D reconstruction mode

Use this when a complete serial dataset exists.

1. Build a z-ordered stack from crops.
2. Normalize intensity/background across sections.
3. Mask tissue and repair obvious artifacts.
4. Do coarse rigid/affine slice-to-slice alignment.
5. Add global constraints: atlas, blockface, MRI, landmarks, or regularized
   reference volume.
6. Apply nonrigid correction with guarded deformation limits.
7. Export a 3D volume with physical voxel spacing.
8. Register the reconstructed volume using `brainreg`.
9. Use `brainglobe-segmentation` for region/object analysis.

### Stage 3: Validation

Minimum validation checks:

- overlay atlas boundaries on each section;
- compare expected AP order with anatomical landmarks;
- measure deformation magnitude per section;
- flag sections with tears, missing tissue, folds, or bad labels;
- compare left/right hemisphere symmetry when appropriate;
- verify that labelled signal is not used as the only anatomical registration
  contrast.

## Non-Goals For The First Implementation

- Do not attempt high-fidelity whole-brain 3D reconstruction from only the 17
  demo sections.
- Do not hard-code mouse Allen CCF assumptions for rat data.
- Do not discard raw ND2/channel data after making RGB previews.

## Concrete Next Implementation Step

Implement a manifest-driven crop export script:

```text
scripts/export_sections.py
```

It should produce:

```text
processed/
  sample_id/
    sections_raw/
    sections_registration/
    qc_overlays/
    section_manifest.csv
```

That gives every downstream registration tool the same stable inputs.
