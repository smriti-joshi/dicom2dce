"""Pipeline stages for DICOM extraction, filtering, conversion, and validation."""

from .config import Config
from .stage1_extractor import ExtractionStage
from .stage2_filter import FilteringStage
from .stage3_dcmconsistency import VisualChecks
from .stage4_niiconvert import process_patient_json
from .stage5_niivalidate import validate_patient_nifti
from .stage6_report import (
    flatten_validation_result,
    flatten_consistency_details,
    save_center_results,
    print_summary,
)
