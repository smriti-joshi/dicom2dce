"""dicom2dce — DICOM to DCE-MRI NIfTI conversion pipeline."""

from .process_dicom import DicomProcessingPipeline
from .pipeline.config import Config
from .pipeline.stage1_extractor import ExtractionStage
from .pipeline.stage2_filter import FilteringStage
from .pipeline.stage3_dcmconsistency import VisualChecks
from .pipeline.stage4_niiconvert import process_patient_json
from .pipeline.stage5_niivalidate import validate_patient_nifti
from .pipeline.stage6_report import (
    flatten_validation_result,
    flatten_consistency_details,
    save_center_results,
    print_summary,
)

__all__ = [
    "DicomProcessingPipeline",
    "Config",
    "ExtractionStage",
    "FilteringStage",
    "VisualChecks",
    "process_patient_json",
    "validate_patient_nifti",
    "flatten_validation_result",
    "flatten_consistency_details",
    "save_center_results",
    "print_summary",
]
