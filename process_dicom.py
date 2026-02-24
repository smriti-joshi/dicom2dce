import pydicom
import os
import json
import csv
from tqdm import tqdm
import numpy as np
import re

from .pipeline.stage1_extractor import ExtractionStage
from .pipeline.stage2_filter import FilteringStage
from .pipeline.stage3_dcmconsistency import VisualChecks
from .pipeline.stage4_niiconvert import process_patient_json
from .pipeline.stage5_niivalidate import validate_patient_nifti
from .pipeline.stage6_report import flatten_validation_result, save_patient_csv_row


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

    def process_and_save_csv_report(self, center, center_root_dir, extract_out_dir, filter_out_dir, csv_out_dir):
        """
        Process all patients in a center and generate CSV report with consistency check results.
        
        Args:
            center: Center name/identifier
            center_root_dir: Root directory containing patient subdirectories
            extract_out_dir: Output directory for extracted DICOM metadata
            filter_out_dir: Output directory for filtered DICOM data
            csv_out_dir: Output directory for CSV report
            
        Returns:
            (results_list, summary_stats): List of result dicts and summary statistics
        """
        results = []
        
        # Check if center directory exists
        if not os.path.isdir(center_root_dir):
            print(f"Center directory not found: {center_root_dir}")
            return results, {}
        
        # Get list of patient directories
        patient_dirs = sorted([d for d in os.listdir(center_root_dir)
                               if os.path.isdir(os.path.join(center_root_dir, d))])
        
        print(f"\nExtracting and filtering DICOM metadata...")
        
        # Process each patient
        for idx, patient_dir_name in enumerate(patient_dirs, 1):
            patient_dir = os.path.join(center_root_dir, patient_dir_name)
            
            # Extract, filter, and check consistency in one pass
            filtered_data = self.extract_filter_and_save(
                patient_dir,
                extract_out_dir,
                filter_out_dir,
                save_extracted=True,
                save_filtered=True
            )
            
            # Process results
            if filtered_data and filtered_data[0] is not None:
                try:
                    summary, filtered_entries, status, flags, details = filtered_data
                    
                    # Extract patient_id from summary dict
                    if summary and isinstance(summary, dict):
                        patient_id = list(summary.keys())[0]
                    else:
                        continue
                        
                    # Format flags for CSV
                    flags_str = " | ".join(flags) if flags else "OK"
                    
                    # Extract details fields
                    temporal_positions = details.get("temporal_positions", "")
                    total_dicoms = details.get("total_dicoms", "")
                    folder_names = json.dumps(details.get("folder_names", [])) if details.get("folder_names") else ""
                    slices_per_temporal = json.dumps(details.get("slices_per_temporal", {})) if details.get("slices_per_temporal") else ""
                    folder_slice_counts = json.dumps(details.get("folder_slice_counts", {})) if details.get("folder_slice_counts") else ""
                    low_similarity_pairs = json.dumps(details.get("low_similarity_pairs", [])) if details.get("low_similarity_pairs") else ""
                    
                    # Add result row
                    results.append({
                        "patient_id": patient_id,
                        "status": status,
                        "entry_count": len(filtered_entries),
                        "flags": flags_str,
                        "folder_names": folder_names,
                        "temporal_positions": temporal_positions,
                        "total_dicoms": total_dicoms,
                        "slices_per_temporal": slices_per_temporal,
                        "folder_slice_counts": folder_slice_counts,
                        "low_similarity_pairs": low_similarity_pairs,
                    })
                    
                    # Print progress
                    status_icon = "✓" if status == "OK" else "⚠️"
                    print(f"[{idx}] {patient_id}: {status_icon} {status} - {flags_str if flags else 'No issues'}")
                    
                except Exception as e:
                    print(f"Error processing {patient_dir_name}: {e}")
                    continue
        
        # Ensure output directories exist
        os.makedirs(csv_out_dir, exist_ok=True)
        os.makedirs(filter_out_dir, exist_ok=True)
        
        # Save results to CSV
        csv_output_file = os.path.join(csv_out_dir, f"consistency_check_results_{center.lower()}.csv")
        
        fieldnames = [
            "patient_id",
            "status",
            "entry_count",
            "flags",
            "folder_names",
            "temporal_positions",
            "total_dicoms",
            "slices_per_temporal",
            "folder_slice_counts",
            "low_similarity_pairs",
        ]
        
        # Write CSV
        with open(csv_output_file, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)
        
        print(f"\n{'='*60}")
        print(f"✓ Results saved to: {csv_output_file}")
        
        # Calculate and return summary statistics
        ok_count = sum(1 for r in results if r["status"] == "OK")
        flagged_count = len(results) - ok_count
        summary_stats = {
            "total": len(results),
            "ok": ok_count,
            "flagged": flagged_count
        }
        
        print(f"Summary: {ok_count} OK, {flagged_count} FLAGGED out of {len(results)} patients")
        
        return results, summary_stats

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
            "nifti_validation_status": "NOT_RUN"
        }
        
        try:
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
                
                # Add consistency check details from the filtered_data
                if 'details' in locals():
                    csv_row.update({
                        "consistency_temporal_positions": details.get("temporal_positions", ""),
                        "consistency_total_dicoms": details.get("total_dicoms", ""),
                        "consistency_folder_names": json.dumps(details.get("folder_names", [])) if details.get("folder_names") else "",
                        "consistency_slices_per_temporal": json.dumps(details.get("slices_per_temporal", {})) if details.get("slices_per_temporal") else "",
                        "consistency_folder_slice_counts": json.dumps(details.get("folder_slice_counts", {})) if details.get("folder_slice_counts") else "",
                        "consistency_low_similarity_pairs": json.dumps(details.get("low_similarity_pairs", [])) if details.get("low_similarity_pairs") else "",
                    })
                
                save_patient_csv_row(csv_row, csv_out_dir, result["patient_id"])
            
            return result
            
        except Exception as e:
            print(f"ERROR: {str(e)}")
            result["status"] = "ERROR"
            result["nifti_conversion"] = "SKIPPED"
            return result




