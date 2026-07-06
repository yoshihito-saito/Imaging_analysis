# Tyson et al. 2022 - brainreg / marker localization in whole-brain microscopy

## Citation

Tyson, A. L., Vélez-Fort, M., Rousseau, C. V., Cossell, L., Tsitoura, C.,
Lenzi, S. C., Obenhaus, H. A., Claudi, F., Branco, T., & Margrie, T. W.
(2022). Accurate determination of marker location within whole-brain microscopy
images. Scientific Reports, 12, 867. https://doi.org/10.1038/s41598-021-04676-9

## Library Status

- Google Drive/Paperpile: targeted `brainreg aMAP` search did not find a local
  PDF, but the tool is referenced in the user's `Brain Slice Registration`
  spreadsheet.
- PDF status: citation and method details verified from official BrainGlobe
  documentation; local PDF status unknown.
- Read status: documentation read.

## One-Sentence Takeaway

`brainreg` is appropriate once the sample is already represented as a 3D volume,
but it is not itself a complete sparse 2D serial-section reconstruction tool.

## Method Summary

BrainGlobe documentation describes `brainreg` as the successor/update to aMAP,
using NiftyReg as the registration backend. Its aim is to register a template
brain to a sample image, allowing template-space annotations to be aligned to
sample space and inverted so sample data can be mapped into common atlas space.
The documented process includes filtering, reorientation, affine registration,
and freeform registration.

`brainglobe-segmentation` is a companion napari plugin for segmenting regions or
objects and analysing their brain-region distribution after `brainreg`
registration.

## Relevance To This Repository

High for the final atlas-analysis stage, lower for initial reconstruction. The
existing ND2 crop pipeline must first produce an ordered stack or another
atlas-registerable representation. After that, `brainreg` plus
`brainglobe-segmentation` can provide atlas alignment and region-level analysis.

## Limitations For Current Dataset

- `brainreg` expects a 3D image volume, not independent sparse slide-crop images.
- Requires careful orientation and voxel spacing metadata.
- Atlas choice for rat must be checked in the installed BrainGlobe atlas list.

## Relevance Score

5/5 for downstream atlas analysis; 2/5 for initial 2D-to-3D reconstruction.
