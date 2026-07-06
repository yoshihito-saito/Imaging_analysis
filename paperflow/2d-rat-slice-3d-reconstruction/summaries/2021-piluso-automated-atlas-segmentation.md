# Piluso et al. 2021 - Automated atlas-based segmentation of single coronal mouse brain slices

## Citation

Piluso, S., Souedet, N., Jan, C., Clouchoux, C., & Delzescaux, T. (2021).
Automated Atlas-based Segmentation of Single Coronal Mouse Brain Slices using
Linear 2D-2D Registration. arXiv:2111.08705.
https://arxiv.org/abs/2111.08705

## Library Status

- Google Drive/Paperpile: targeted title search did not find a local PDF.
- PDF status: open-access PDF available from arXiv.
- Read status: abstract read.

## One-Sentence Takeaway

For sparse datasets, per-slice 2D-to-atlas segmentation may be more realistic
than full 3D reconstruction.

## Method Summary

The paper addresses the problem that histological data are often 2D while
reference atlases are 3D. It proposes automatic segmentation of single coronal
mouse slices by finding a corresponding slice in a 3D atlas and applying linear
2D-to-2D registration. The authors validate robustness and performance at
whole-brain scale.

## Relevance To This Repository

High as a fallback strategy. The demo has only 17 detected sections, so a
full reconstructed 3D volume may be underdetermined. A per-section atlas
registration strategy can still support atlas-region quantification from each
slice, then aggregate across sections.

## Limitations For Current Dataset

- Mouse-focused, not rat.
- Linear registration may not correct histology tears, folds, or nonlinear
  tissue deformation.
- Does not solve full 3D reconstruction.

## Relevance Score

4/5 for sparse-section atlas quantification.
