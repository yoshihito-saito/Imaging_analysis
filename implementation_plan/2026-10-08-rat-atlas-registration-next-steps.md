# Next Steps for Rat Brain Section Registration

Date: 2026-10-08

## Goal and Scope

Improve anatomical alignment of rat histology sections to a rat brain atlas,
using the successful experience with BrainJ on mouse sections as a practical
reference. The first milestone is accurate registration of individual sections
to confirmed atlas planes. Automatic plane selection and dense 3D reconstruction
are later milestones.

Keep the existing ND2 extraction, channel exports, manifests, and QC outputs as
the starting point. Use BrainGlobe for atlas data and anatomical labels, and
evaluate an established registration engine such as Elastix for alignment.
Atlas access and registration do not need to use the same software backend.

## Current Baseline and BrainJ Reference

The current pipeline detects and exports sections, pairs them with atlas planes,
fits similarity or constrained affine transforms, and produces overlays and
region intensity summaries. Registration mainly uses tissue masks, gross shape,
and boundary agreement. Its optional `boundary_spline` refinement smooths
displacements derived from tissue boundaries; it does not optimize correspondence
of internal image structures.

BrainJ's public implementation aligns serial sections with rigid transforms,
constructs a volume, and registers the atlas with affine followed by B-spline
transforms. Its atlas registration uses mutual information and multiple image
resolution levels. These components provide a concrete starting point for
improving the current registration method, although performance on rat sections
must be established separately.

## Development Priorities

| Priority | Work | Intended benefit |
| --- | --- | --- |
| 1 | Add registration using internal image information after the existing coarse alignment. Compare a multiresolution affine stage followed by a regularized B-spline stage. | Align visible structures such as ventricles, hippocampus, and white matter, in addition to the tissue outline. |
| 2 | Estimate atlas position and cutting angle across the section series, using known order and physical spacing. | Reduce inconsistent plane assignments and excessive deformation caused by choosing the wrong atlas plane. |
| 3 | Add damage exclusion masks and optional anatomical landmarks. | Improve difficult cases without allowing tears, folds, or missing tissue to drive deformation of intact anatomy. |

Mutual information is a candidate metric for differing image contrasts, not a
guarantee of anatomical correspondence. Keep coarse shape alignment for
initialization, then assess whether internal image information improves the
result. Control local deformation through smoothness and displacement limits.

Use `whs_sd_rat_39um` as the atlas for the planned registration work.

For series-level plane selection, use section order and measured sampling
intervals as constraints. Allow limited deviations for missing sections and
spacing uncertainty. Share the cutting-angle estimate across a series when the
acquisition supports that assumption. Sparse sections can use these constraints
without constructing a continuous 3D sample volume.

## Evaluation and Adoption Criteria

Use independent internal landmarks as the primary anatomical evaluation. Measure
the distance between corresponding landmarks after transformation in micrometres,
and report per-section errors and their distribution. Landmarks used to fit or
tune registration must be separate from those used to evaluate it. Keep
evaluation sections separate from development sections where available.

Also review internal atlas boundaries, tissue coverage, maximum displacement,
and local folding or implausible compression. Report tissue-mask Dice as a
secondary measure: improved outline overlap alone is insufficient evidence of
improved anatomical registration.

Agree on an anatomical error target based on the intended regions and atlas
resolution before evaluating the final method. Adoption should require reduced
internal landmark error, acceptable deformation, and no systematic regressions
across the reviewed sections. Preserve difficult cases in the report rather than
removing them to improve aggregate scores.

## Coordinate Transforms and Quantification

Save the full mapping from the original section image to the atlas plane,
including all crop offsets, orientation corrections, affine transforms, and
nonlinear transforms. Record the plane's position, angle, and mapping into the
3D atlas coordinate system. Transform direction, axis order, and physical units
must be explicit.

Apply the same anatomical transform to all signal channels and detected cell
coordinates. Choose interpolation according to the data: continuous
interpolation for intensity images and nearest-neighbour interpolation for
categorical labels. Preserve native images and coordinates for measurement and
traceability.

Before using region summaries for quantitative analysis, exclude failed
registrations and distinguish missing tissue from measured zero signal. Define
whether each measurement is made in native tissue space or atlas space, and use
the appropriate sampled area or volume for density estimates.

## Deliverables and Later Milestones

The registration work should produce a reusable implementation,
reproducible configurations, complete saved transforms, comparison overlays, a
landmark-error table, and a short recommendation with representative failures.
Preserve existing raw data, historical outputs, and public interfaces.

Once the registration method meets the agreed anatomical criteria, improve
series-level plane selection and manual correction. Pursue dense 3D reconstruction
when section coverage, spacing, and orientation support it; that route also
requires section-to-section anatomical alignment before volume-to-atlas
registration.

## Code and Source References

- [Current slice registration](../src/brain_section_pipeline/slice_registration.py)
- [Atlas plane preparation](../src/brain_section_pipeline/slice_atlas.py)
- [Atlas candidate selection](../src/brain_section_pipeline/atlas_indexing.py)
- [Current region summaries](../src/brain_section_pipeline/atlas_summary.py)
- [BrainJ registration macro](https://github.com/lahammond/BrainJ/blob/master/src/main/resources/scripts/Plugins/BrainJ/5_Registration_and_Atlas_Analysis_%28Batch_Process%29.ijm)
- [BrainJ affine parameters](https://github.com/lahammond/BrainJ/blob/master/Elastix_Parameter_Files/Whole_Brain_Data_V1/MB49_Param_Affine.txt)
- [BrainJ B-spline parameters](https://github.com/lahammond/BrainJ/blob/master/Elastix_Parameter_Files/Whole_Brain_Data_V1/MB49_Param_BSpline.txt)
- [Elastix registration methods](https://elastix.dev/doxygen/parameter.html)
- [BrainGlobe atlas catalogue](https://github.com/brainglobe/brainglobe-atlasapi)
