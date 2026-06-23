"""ND2 channel merging and brain section crop pipeline."""

from .crop import CropBox, CropDetectionResult, detect_section_crops, crop_sections
from .io import Nd2Image, find_nd2_files, read_nd2_image, select_nd2_files_dialog, summarize_nd2
from .merge import DEFAULT_CHANNEL_COLORS, merge_channels, robust_scale, sanitize_array
from .pipeline import PipelineConfig, ProcessingResult, process_nd2_file, process_selected_files

__all__ = [
    "CropBox",
    "CropDetectionResult",
    "DEFAULT_CHANNEL_COLORS",
    "Nd2Image",
    "PipelineConfig",
    "ProcessingResult",
    "crop_sections",
    "detect_section_crops",
    "find_nd2_files",
    "merge_channels",
    "process_nd2_file",
    "process_selected_files",
    "read_nd2_image",
    "robust_scale",
    "sanitize_array",
    "select_nd2_files_dialog",
    "summarize_nd2",
]
