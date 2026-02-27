"""
Pipeline orchestrator: ties together extraction, filtering, consistency
checks, NIfTI conversion, validation, and reporting.
"""

import os
import json

from .pipeline.stage1_extractor import ExtractionStage
from .pipeline.stage2_filter import FilteringStage
from .pipeline.stage3_dcmconsistency import VisualChecks
from .pipeline.stage4_niiconvert import process_patient_json
from .pipeline.stage5_niivalidate import validate_patient_nifti
from .pipeline.stage6_report import (
    flatten_validation_result, flatten_consistency_details, save_patient_csv_row,
)


class DicomProcessingPipeline:
    """Orchestrates the DICOM processing pipeline"""
    
    def __init__(self):
        self.extractor_stage = ExtractionStage()
        self.filter_stage = FilteringStage()
    
    def extract_and_save(self, patient_dir, output_path, save=True):
        """Run extraction stage"""
        summary, error_log = self.extractor_stage.extract_patient(patient_dir)
        
        if save:
            if summary:
                self.extractor_stage.save_raw_summary(summary, output_path)
            
            if error_log:
                patient_id = list(summary.keys())[0] if summary else "unknown"
                self.extractor_stage.save_error_log(error_log, patient_id, output_path)
        
        return summary
    
    def filter_and_save(self, json_path, output_path, save=True):
        """Run filtering stage"""
        summary = self.filter_stage.load_summary(json_path)
        patient_id = list(summary.keys())[0]
        metadata_list = summary[patient_id]
        
        filtered = self.filter_stage.filter_dce_sequences(metadata_list)
        grouped = self.filter_stage.group_by_tr_te(filtered)
        
        if save:
            output_file = self.filter_stage.save_filtered_results(grouped, patient_id, output_path, filtered_metadata=filtered)
        
        return grouped
    
    def check_consistency(self, filtered_entries, patient_id):
        """Run visual consistency checks on filtered entries"""
        status, flags, details = VisualChecks.check_consistency(filtered_entries, patient_id)
        return status, flags, details
    
    def extract_filter_and_save(self, patient_dir, extract_output_path, filter_output_path, 
                                save_extracted=True, save_filtered=True):
        """Run extraction, filtering, and consistency checks in one pass"""
        # Extract
        try: 
            summary, error_log = self.extractor_stage.extract_patient(patient_dir)
        except Exception as e:
            print(f"Error extracting patient {patient_dir}: {e}")
            return None, None, None, None, None
        
        if not summary:
            return None, None, None, None, None
        
        patient_id = list(summary.keys())[0]
        metadata_list = summary[patient_id]
        
        # Save extracted (optional)
        if save_extracted:
            self.extractor_stage.save_raw_summary(summary, extract_output_path)
            if error_log:
                self.extractor_stage.save_error_log(error_log, patient_id, extract_output_path)
        
        # Filter
        filtered = self.filter_stage.filter_dce_sequences(metadata_list)
        grouped = self.filter_stage.group_by_tr_te(filtered)
        
        # Sort entries before saving (independent operation)
        sorted_entries = self.filter_stage.sort_entries(grouped) if grouped else []
        
        # Save filtered (optional)
        if save_filtered:
            self.filter_stage.save_filtered_results(sorted_entries, patient_id, filter_output_path, metadata=metadata_list)
        
        # Run consistency checks
        status, flags, details = self.check_consistency(sorted_entries, patient_id)
        
        return summary, sorted_entries, status, flags, details

    def process_patient_with_nifti_conversion(self, patient_dir, patient_dir_name, extract_out_dir, 
                                              filter_out_dir, nifti_images_root, nifti_metadata_root, csv_out_dir=None):
        """
        Process a single patient through the complete pipeline including NIfTI conversion and CSV saving.
        
        Args:
            patient_dir: Path to patient DICOM directory
            patient_dir_name: Name of patient directory
            extract_out_dir: Output directory for extracted metadata
            filter_out_dir: Output directory for filtered results
            nifti_images_root: Root directory for NIfTI images
            nifti_metadata_root: Root directory for NIfTI metadata
            csv_out_dir: (Optional) Directory for per-patient CSV; if provided, result is saved as {patient_id}_results.csv
            
        Returns:
            Dictionary with patient processing and conversion results
        """
        result = {
            "patient_id": None,
            "status": None,
            "flags": None,
            "entry_count": 0,
            "nifti_conversion": "SKIPPED",
            "nifti_error": None,
            "nifti_validation": None,
            "nifti_validation_status": "NOT_RUN",
            "consistency_details": None
        }
        
        try:
            # Extract patient_id from directory name (assuming format like PREFIX_PREFIX_ID or similar)
            # We need to check early if patient is already processed
            patient_id = patient_dir_name
            
            # Check if patient NIfTI folder already exists (already processed)
            patient_nifti_dir = os.path.join(nifti_images_root, patient_id)
            if os.path.exists(patient_nifti_dir):
                print(f"  [SKIPPED] Patient {patient_id} already processed")
                result["patient_id"] = patient_id
                result["status"] = "ALREADY_PROCESSED"
                result["nifti_conversion"] = "ALREADY_PROCESSED"
                result["nifti_validation_status"] = "NOT_RUN"
                return result
            
            # STAGE 1: EXTRACTION & FILTERING & CONSISTENCY CHECKS
            print(f"  [EXTRACTION] Reading DICOM metadata from {patient_dir_name}...", end=" ", flush=True)
            
            filtered_data = self.extract_filter_and_save(
                patient_dir,
                extract_out_dir,
                filter_out_dir,
                save_extracted=True,
                save_filtered=True
            )
            
            if not filtered_data or filtered_data[0] is None:
                print(f"FAILED (extraction error)")
                result["status"] = "EXTRACTION_FAILED"
                return result
            
            print(f"✓")
            
            summary, filtered_entries, status, flags, details = filtered_data
            
            # Extract patient_id from summary
            if not summary or not isinstance(summary, dict):
                print(f"  [ERROR] Invalid summary format")
                result["status"] = "INVALID_SUMMARY"
                return result
            
            patient_id = list(summary.keys())[0]
            result["patient_id"] = patient_id
            result["status"] = status
            result["flags"] = " | ".join(flags) if flags else "OK"
            result["entry_count"] = len(filtered_entries)
            result["consistency_details"] = details
            
            # STAGE 2: CONSISTENCY CHECK RESULT
            status_icon = "✓" if status == "OK" else "⚠️"
            print(f"  [CONSISTENCY] {status_icon} {status} - {result['entry_count']} sequences")
            
            # STAGE 3: NIFTI CONVERSION
            if status == "OK":
                filtered_json_path = os.path.join(filter_out_dir, f"{patient_id}_filtered.json")
                
                if os.path.exists(filtered_json_path):
                    print(f"  [NIfTI CONVERSION] Converting {result['entry_count']} sequences...", end=" ", flush=True)
                    try:
                        process_patient_json(
                            filtered_json_path,
                            nifti_images_root,
                            nifti_metadata_root,
                            interactive=False
                        )
                        print(f"✓")
                        result["nifti_conversion"] = "SUCCESS"
                        
                        # STAGE 4: NIFTI VALIDATION
                        patient_nifti_dir = os.path.join(nifti_images_root, patient_id)
                        print(f"  [NIfTI VALIDATION] Running quality checks...", end=" ", flush=True)
                        
                        validation_result = validate_patient_nifti(
                            patient_nifti_dir,
                            patient_id,
                            filtered_entries
                        )
                        print(f"✓ {validation_result['overall_status']}")
                        
                        result["nifti_validation"] = validation_result
                        result["nifti_validation_status"] = validation_result["overall_status"]
                        
                    except Exception as e:
                        print(f"FAILED ({str(e)[:50]})")
                        result["nifti_conversion"] = "FAILED"
                        result["nifti_error"] = str(e)
                else:
                    print(f"  [NIfTI CONVERSION] JSON file not found")
                    result["nifti_conversion"] = "JSON_NOT_FOUND"
            else:
                # Flagged case, skip conversion
                print(f"  [NIfTI CONVERSION] SKIPPED (consistency check flagged)")
                result["nifti_conversion"] = "SKIPPED"
            
            # STAGE 6: REPORT - Save per-patient CSV if directory provided
            if csv_out_dir and result["patient_id"]:
                csv_row = {
                    "patient_id": result["patient_id"],
                    "dicom_status": result["status"],
                    "entry_count": result["entry_count"],
                    "dicom_flags": result["flags"],
                    "nifti_conversion": result["nifti_conversion"],
                    "nifti_overall_status": result["nifti_validation_status"],
                }
                csv_row.update(flatten_validation_result(result["nifti_validation"]))
                csv_row.update(flatten_consistency_details(result["consistency_details"]))
                
                save_patient_csv_row(csv_row, csv_out_dir, result["patient_id"])
            
            return result
            
        except Exception as e:
            print(f"ERROR: {str(e)}")
            result["status"] = "ERROR"
            result["nifti_conversion"] = "SKIPPED"
            return result

