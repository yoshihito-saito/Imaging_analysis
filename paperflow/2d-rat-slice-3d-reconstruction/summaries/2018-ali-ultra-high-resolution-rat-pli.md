# Ali et al. 2018 - Ultra-high resolution 3D reconstruction of a whole rat brain from 3D-PLI data

## Citation

Ali, S., Schober, M., Schlöme, P., Amunts, K., Axer, M., & Rohr, K. (2018).
Towards ultra-high resolution 3D reconstruction of a whole rat brain from
3D-PLI data. arXiv:1807.11080. https://arxiv.org/abs/1807.11080

## Library Status

- Google Drive/Paperpile: not found by targeted title search.
- PDF status: open-access PDF available from arXiv.
- Read status: abstract read.

## One-Sentence Takeaway

This is the most directly rat-specific reconstruction paper found in this pass:
it reconstructs a Wistar rat brain from hundreds of high-resolution serial
histological 3D-PLI sections using feature-based and nonrigid registration.

## Method Summary

The method targets 3D polarized light imaging data at two scales: 64 um and
1.3 um pixel size. The authors use multi-scale, multi-modal data and propose a
feature-transform similarity measure plus weighted regularization for robust
nonrigid registration. The ultra-high-resolution data are transformed to
reference blockface images by feature-based registration followed by nonrigid
registration.

The reported dataset contains 278 histological sections from a Wistar rat brain,
and performance is evaluated with manually placed expert landmarks.

## Relevance To This Repository

High. It is rat-specific and addresses true serial-section 3D reconstruction,
but the acquisition context differs: this repository has three fluorescence ND2
slide mosaics with 17 detected 2D sections, not a complete 278-section 3D-PLI
series with blockface references. The method argues strongly for collecting or
recording a reference frame such as blockface images, consistent section spacing,
and expert landmarks/QC.

## Limitations For Current Dataset

- The demo dataset is sparse relative to the paper's 278-section series.
- No blockface images are currently present in `demo/`.
- The paper's exact algorithm is not packaged as an immediately reusable
  BrainGlobe-style workflow in this pass.

## Relevance Score

5/5 for rat-specific reconstruction principles; 3/5 for immediate software reuse.
