# Reference Materials

- `section_isolator_notebook_dump.ipynb`: notebook JSON that was originally placed at the repository root as `__init__.py`. It is kept here as reference material because a root-level `__init__.py` makes the whole workspace import as a Python package and breaks test collection.
- `brainglobe-histology-segmentation-guide.md`: practical notes for using BrainGlobe, `brainreg`, napari, and `brainglobe-segmentation` to register histology data and analyse 2D/3D segmented structures against an atlas.


9/24/2026 Program Status Report

There are three main functions that this program can execute so far. The program is able to isolate individual brain slices off a slide with multiple slices, search within an AP range for an appropriate atlas index by fitting slices onto different planes and scoring the fits, and finally fit each slice to a chosen atlas plane.

Isolating individual brain slices: 
The mechanism for this is very similar to the original program designed by Yoshi for doing this. Only minor adjustments were needed to consistently identify the right number of slices. The main problem with the previous slice detection was that fragments were being detected as whole slices. To fix this several workflow items were changed: final_box_padding was added which expands the chosen crop boxes without changing total section counts for each slide, and instead of sanitizing the image before identifying slices like the old code did, the new code selects slices first and then sanitizes only the regions detected as slices. Additionally functions were added to identify if smaller slices were fragments of larger ones and to merge them if this was determined to be the case. Some of these functions include: _merge_close_boxes(...)
_should_merge_boxes(...)
_combine_boxes(...)
_axis_overlap(...)
_axis_gap(...)

Overal the isolation of individual brain slices is now very consistent and successful and is not presumed to be needing changes in the near future.



Searching for Appropriate Atlas Indices:
This feature was implemented but is very heavy computationally and may not be super feasible for a final version of the program. 

The software is able to search within a given AP range by fitting a given slice to all the indices within the range and then scoring the fit at each index. This is done by function _rank_candidate_indices(). But for every candidate atlas plane the program follows the following procedure:

Extracts the atlas reference plane.

Extracts the atlas annotation plane.

Converts annotation into an atlas tissue mask.

Registers the histology section onto that atlas plane.

Computes registration metrics.

Adds anatomical alignment metrics.

Computes a final candidate score.

Sorts candidates by score and picks the highest one.

One other recent implementation is that the program can try to correct for a slice that hasn't been cut completely vertically by adjusting the plane angle. This is tested for by the variable atlas_plane_angle_search

After fitting to each atlas index in the range, the score for each fit is calculated using function _candidate_score()

The final score is determined by final_score = overlap rewards - registration loss - shape mismatch penalties - boundary mismatch penalties - anatomical landmark penalties - AP prior penalties

There are also two methods for selecting indices for multiple slices. Either, after the first slice has been assigned an index, every subsequent slice is fitted to the next index at a input step length using variable slice_index_step. The program is also capable of rechoosing the best index for every slice individually as well.

Overall for the index selection feature of the program, the accuracy is decent but going forward it may just be best to assign a starting index and then use a designated step from there instead of having the program choose the best index. This would cut out a very computationally heavy step in the program, speeding things up significantly. The gain in accuracy from having the program compare different atlas indices may not be worth the problems it causes for large datasets. One potential useful feature to keep however is the angle correction feature that was recently implemented. This could work well in concert with an assigned starting index.



Fitting Slices to the Chosen Atlas Plane:
This feature has improved drastically as it has been refined and is now generally quite accurate. I'm not sure whether it is accurate enough yet, but the overall fit now appears to be quite good.

The fitting happens in slice_registration.py, using primary functions register_slice_to_atlas() and _register_prepared_section_to_atlas()

The steps for registration to the atlas are as follows:

-Load section image, atlas reference image, atlas annotation mask
-Build a tissue mask from the section
-Crops the section so that only the tissue of the slice is included in the bounding box
-Builds 3 masks: tissue mask for registration (primary mask), display mask for overlays, lower requirement boundary mask for slice boundary fitting
-Performs the initial transform considering three factors: scale (area ratio), rotation, translation (centroid alignment)
-Searches around the transform to minimize registration loss
-Records transform matrix, fit parameters, and overlay images
