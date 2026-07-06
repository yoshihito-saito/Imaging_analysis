# BrainJ Workflow Summary

Source checked: 2026-07-06

Primary source: https://github.com/lahammond/BrainJ

Read status: documentation/readme-level. The repository's guide PDF was
identified but its text could not be extracted through the available connector,
so fine GUI operation names should be verified manually in the PDF before
reproducing a BrainJ run.

## What BrainJ Is

BrainJ is a Fiji/ImageJ pipeline for automated serial section reconstruction,
mesoscale mapping, and cell analysis. The README describes it as a tool for
reconstructing serial tissue sections into whole brains and analysing them in a
common coordinate framework. It is designed for accessibility: GUI-driven,
minimal coding, and high-throughput processing of confocal or widefield serial
section datasets.

The README states that BrainJ uses freely available tools for machine-learning
pixel classification for cell detection and mesoscale mapping of axons and
dendrites, and that a typical whole-brain dataset can be reconstructed and
analysed within 2-4 hours.

## Dependencies And Toolchain

BrainJ is built around the Fiji ecosystem:

- Fiji/ImageJ
- BrainJ jar plugin
- MultiStackReg
- TurboReg
- Elastix 5.x
- Ilastik 1.3.3post3
- BrainJ atlas files
- BrainJ Ilastik project

This tells us the workflow likely combines:

- ImageJ/Fiji image IO and GUI orchestration;
- stack registration through MultiStackReg/TurboReg-style transforms;
- deformable registration through Elastix;
- machine-learning segmentation/classification through Ilastik;
- atlas-based quantification using bundled mouse atlas resources.

## Atlas Support

BrainJ explicitly supports mouse brain workflows and the enhanced/unified mouse
brain atlas. The README does not document rat atlas support. For this project,
that means BrainJ is best treated as:

- a proven workflow model for serial slide images;
- a useful reference for preprocessing, registration QC, and signal analysis;
- not the primary rat atlas solution unless the atlas resources and macros are
  intentionally adapted.

## What BrainJ Does Well

BrainJ's strengths match the user's prior experience:

- starts from serial tissue section images rather than assuming a clean 3D
  volume;
- handles a mouse whole-brain serial section workflow in Fiji;
- combines reconstruction, atlas alignment, signal/cell analysis, and
  visualization;
- supports cell/projection analysis and probe/GRIN placement workflows according
  to the README/workshop description;
- lowers the barrier for manual QC and batch processing.

## Important Limitations

The README lists two limitations directly:

- badly damaged tissue may prevent registration and atlas alignment;
- sections must span at least 2-3 mm in the anterior-posterior axis.

For the current demo dataset with 17 sections, this is an important warning:
the slices may be useful for prototyping, but a robust reconstruction/atlas
alignment workflow needs enough AP coverage and anatomical continuity.

## How BrainJ Treats Channels

The README does not provide detailed channel rules in the extractable text.
Based on the listed Ilastik dependency and BrainJ's stated cell/projection
analysis goals, the safe interpretation is:

- one or more channels are used to define anatomy/section registration;
- signal channels are then analysed for cells, axons, dendrites, probes, or
  lesions after reconstruction/alignment;
- machine-learning pixel classification can separate labelled signal from
  background when the model/project matches the staining and imaging modality.

For this rat project, BrainJ's channel idea should be adopted, but the exact
model should not be reused blindly. The registration channel and signal channels
should be explicitly recorded in `section_manifest.csv`.

## Relevance To This Repository

BrainJ is a strong design reference for a slide-section pipeline:

1. Prepare one image per physical section.
2. Keep section order and AP coverage explicit.
3. Use a structural/background channel for registration.
4. Keep signal channels separate for measurement.
5. Register sections into a common atlas space.
6. Analyse cells/projections/probes/regions after atlas alignment.

The key difference is atlas target: this repository needs rat atlas support, so
BrainGlobe is the better base for the atlas layer.

## Practical Role In This Project

Recommended role: use BrainJ as a conceptual template, not as the production
rat atlas backend.

Keep from BrainJ:

- Fiji-style section QC mindset;
- section-first reconstruction logic;
- explicit registration-vs-signal channel separation;
- downstream signal quantification after atlas alignment;
- expectation that damaged tissue and insufficient AP coverage can break the
  workflow.

Avoid depending on BrainJ for:

- rat atlas registration out of the box;
- fully automated use on this ND2 dataset without converting and validating the
  section images;
- Ilastik models trained for mouse/other signal types unless retrained.
