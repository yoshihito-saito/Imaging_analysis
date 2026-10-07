"""Run the full sparse slice-wise atlas workflow from ND2 input to atlas outputs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from brain_section_pipeline import (
    AtlasSummaryConfig,
    BrainGlobeExportConfig,
    PipelineConfig,
    SliceAtlasConfig,
    SliceAtlasQcConfig,
    SliceRegistrationConfig,
    run_slicewise_atlas_workflow,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="ND2 file or folder containing ND2 files.")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"), help="Root directory for workflow outputs.")
    parser.add_argument("--sample-id", default="sample", help="Sample identifier used for export layout.")
    parser.add_argument("--atlas", default="whs_sd_rat_39um", help="BrainGlobe atlas name.")
    parser.add_argument("--orientation", default=None, help="Optional dense-mode orientation metadata to record.")
    parser.add_argument("--registration-channel", type=int, default=0, help="Channel index used for registration exports.")
    parser.add_argument("--section-thickness-um", type=float, default=None)
    parser.add_argument("--section-interval-um", type=float, default=None)
    parser.add_argument("--start-z-um", type=float, default=0.0)
    parser.add_argument("--mask-channel", type=int, default=0)
    parser.add_argument("--min-area", type=int, default=1_000_000)
    parser.add_argument("--margin", type=int, default=250)
    parser.add_argument("--opening-radius", type=int, default=2)
    parser.add_argument("--closing-iterations", type=int, default=160)
    parser.add_argument("--threshold-method", choices=("otsu", "quantile"), default="otsu")
    parser.add_argument("--threshold-quantile", type=float, default=0.90)
    parser.add_argument(
        "--detection-downsample",
        type=int,
        default=4,
        help="Downsampling factor for coarse section detection; use 1 to retain full-slide detection.",
    )
    parser.add_argument(
        "--detection-refinement-padding",
        type=int,
        default=128,
        help="Full-resolution pixels around each coarse candidate used for final box refinement.",
    )
    parser.add_argument("--sort-mode", choices=("row", "row_left_to_right", "row_right_to_left", "diagonal", "area"), default="row_right_to_left")
    parser.add_argument("--final-box-padding", type=int, default=32, help="Final per-box padding in full-resolution pixels.")
    parser.add_argument("--anatomical-axis", choices=("ap", "si", "dv", "rl", "ml"), default="ap")
    parser.add_argument("--start-slice-index", type=int, default=0)
    parser.add_argument("--slice-index-step", type=int, default=1)
    parser.add_argument("--qc-status", dest="qc_statuses", action="append", default=None, help="Allowed QC status for atlas pairing. Repeat to allow multiple.")
    parser.add_argument("--ignore-include-flag", action="store_true", help="Include sections even when include_in_stack is false.")
    parser.add_argument("--generate-qc", action="store_true", help="Generate optional coarse slice-atlas QC overlays.")
    parser.add_argument("--skip-summary", action="store_true", help="Skip atlas-region summary generation.")
    parser.add_argument("--write-rgb-crops", action="store_true", help="Write full-resolution RGB crops for every section.")
    parser.add_argument("--write-slide-diagnostics", action="store_true", help="Write per-slide merged previews and diagnostic metadata.")
    parser.add_argument("--keep-raw-channel-crops", action="store_true", help="Keep legacy multi-channel crop stacks.")
    parser.add_argument("--copy-section-source", action="store_true", help="Copy section sources into slice_atlas/sections.")
    parser.add_argument("--overlay-alpha", type=float, default=0.55)
    parser.add_argument("--registration-threshold-quantile", type=float, default=0.8)
    parser.add_argument("--max-rotation-degrees", type=float, default=35.0)
    parser.add_argument("--min-scale-factor", type=float, default=0.6)
    parser.add_argument("--max-scale-factor", type=float, default=1.6)
    parser.add_argument("--translation-search-fraction", type=float, default=0.25)
    parser.add_argument("--save-individual-overlays", action="store_true", help="Save every final registration overlay.")
    parser.add_argument("--low-quality-dice-threshold", type=float, default=0.80, help="Save an individual overlay below this Dice score.")
    parser.add_argument("--min-region-pixels", type=int, default=1)
    parser.add_argument("--include-background", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pipeline_config = PipelineConfig(
        mask_channel=args.mask_channel,
        min_area=args.min_area,
        margin=args.margin,
        opening_radius=args.opening_radius,
        closing_iterations=args.closing_iterations,
        threshold_method=args.threshold_method,
        threshold_quantile=args.threshold_quantile,
        detection_downsample=args.detection_downsample,
        detection_refinement_padding=args.detection_refinement_padding,
        sort_mode=args.sort_mode,
        final_box_padding=args.final_box_padding,
    )
    export_config = BrainGlobeExportConfig(
        sample_id=args.sample_id,
        atlas_name=args.atlas,
        orientation=args.orientation,
        registration_channel=args.registration_channel,
        section_thickness_um=args.section_thickness_um,
        section_interval_um=args.section_interval_um,
        start_z_um=args.start_z_um,
        write_rgb_crops=args.write_rgb_crops,
        write_slide_diagnostics=args.write_slide_diagnostics,
        keep_raw_channel_crops=args.keep_raw_channel_crops,
    )
    slice_atlas_config = SliceAtlasConfig(
        atlas_name=args.atlas,
        anatomical_axis=args.anatomical_axis,
        start_slice_index=args.start_slice_index,
        slice_index_step=args.slice_index_step,
        sample_id=args.sample_id,
        allowed_qc_statuses=tuple(args.qc_statuses) if args.qc_statuses is not None else None,
        require_include_in_stack=not args.ignore_include_flag,
        copy_section_source=args.copy_section_source,
    )
    qc_config = SliceAtlasQcConfig(overlay_alpha=args.overlay_alpha)
    registration_config = SliceRegistrationConfig(
        tissue_threshold_quantile=args.registration_threshold_quantile,
        overlay_alpha=args.overlay_alpha,
        max_rotation_degrees=args.max_rotation_degrees,
        min_scale_factor=args.min_scale_factor,
        max_scale_factor=args.max_scale_factor,
        translation_search_fraction=args.translation_search_fraction,
        save_individual_overlays=args.save_individual_overlays,
        low_quality_dice_threshold=args.low_quality_dice_threshold,
    )
    summary_config = AtlasSummaryConfig(
        include_background=args.include_background,
        min_region_pixels=args.min_region_pixels,
    )

    result = run_slicewise_atlas_workflow(
        args.input,
        args.output_dir,
        pipeline_config=pipeline_config,
        export_config=export_config,
        slice_atlas_config=slice_atlas_config,
        qc_config=qc_config,
        registration_config=registration_config,
        atlas_summary_config=summary_config,
        generate_qc=args.generate_qc,
        generate_summary=not args.skip_summary,
    )

    print(f"Sample export: {result.export_result.sample_dir}")
    print(f"Section review montage: {result.export_result.section_montage_path}")
    print(f"Per-slide section overlays: {result.export_result.review_dir}")
    print(f"Section manifest: {result.export_result.manifest_path}")
    print(f"Slice-atlas manifest: {result.slice_atlas_result.manifest_path}")
    if result.qc_result is not None:
        print(f"QC overlay directory: {result.qc_result.output_dir}")
    print(f"Registration manifest: {result.registration_result.manifest_path}")
    print(f"Registration contact sheet: {result.registration_result.contact_sheet_path}")
    if result.summary_result is not None:
        print(f"Atlas summary directory: {result.summary_result.output_dir}")


if __name__ == "__main__":
    main()
