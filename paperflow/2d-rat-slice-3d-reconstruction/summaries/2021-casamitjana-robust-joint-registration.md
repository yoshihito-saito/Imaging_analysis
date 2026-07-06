# Casamitjana et al. 2021 - Robust joint registration of multiple stains and MRI for multimodal 3D histology reconstruction

## Citation

Casamitjana, A., Lorenzi, M., Ferraris, S., Peter, L., Modat, M., Stevens, A.,
Fischl, B., Vercauteren, T., & Iglesias, J. E. (2021). Robust joint
registration of multiple stains and MRI for multimodal 3D histology
reconstruction: Application to the Allen human brain atlas. Medical Image
Analysis. https://arxiv.org/abs/2104.14873;
https://doi.org/10.1016/j.media.2021.102265

## Library Status

- Google Drive/Paperpile: targeted title search did not find a local PDF.
- PDF status: open-access PDF available from arXiv.
- Read status: abstract read.

## One-Sentence Takeaway

This paper explains why naive neighboring-slice registration drifts and proposes
a reference-constrained probabilistic reconstruction model that is robust to
multi-stain distortions and outliers.

## Method Summary

The paper frames 3D histology reconstruction as recovering latent transforms
across sections and reference-volume slices. Instead of relying only on
neighbor-to-neighbor registration, it uses a graph/spanning-tree formulation
where pairwise registrations are noisy observations of latent transform
compositions. Bayesian inference estimates transforms that are smooth, robust
to outliers, and constrained by a reference volume.

It specifically calls out two classic failure modes of simple serial alignment:
banana effect and z-shift/drift. The method was applied to Nissl and
parvalbumin sections from the Allen human brain atlas and registered to MNI
space.

## Relevance To This Repository

Medium-high. Species and scale differ, but the core warning is directly useful:
do not reconstruct this rat dataset by only aligning each section to the
previous section. Use an atlas, MRI/blockface reference, or explicit global
constraints to prevent cumulative drift.

## Limitations For Current Dataset

- Human atlas application, not rat.
- Likely more complex than needed for a first practical pipeline.
- Requires enough sections and/or a reference volume to make global constraints
  meaningful.

## Relevance Score

4/5 for reconstruction principles; 2/5 for immediate implementation.
