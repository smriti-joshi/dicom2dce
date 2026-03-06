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
    
    def extract_filter_and_save_by_date(self, patient_dir, extract_output_path, filter_output_path, 
                                        save_extracted=True, save_filtered=True):
        """
        Run extraction, filtering organized by StudyDate, and consistency checks in one pass.
        Returns data organized by date: {date: {patient_id: entries}}
        """
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
        
        # Group by DATE and TR/TE
        grouped_by_date = self.filter_stage.group_by_date_and_tr_te(filtered)
        
        # If no DCE sequences found at all, still run consistency check to raise the flag.
        # Use dates from raw metadata as representative; otherwise only process dates that have DCE entries.
        if grouped_by_date:
            dates_to_process = set(grouped_by_date.keys())
        else:
            dates_to_process = {self.filter_stage.get_date_key(e) for e in metadata_list} or {"UNKNOWN_DATE"}
        
        # Process each date separately (including dates with no filtered entries)
        entries_by_date = {}
        status_by_date = {}
        flags_by_date = {}
        details_by_date = {}
        
        for date_str in sorted(dates_to_process):
            # Get entries for this date from grouped_by_date if they exist, otherwise empty list
            entries_for_date = grouped_by_date.get(date_str, [])
            
            # Sort entries for this date
            sorted_entries = self.filter_stage.sort_entries(entries_for_date) if entries_for_date else []
            
            # Save filtered results for this date (optional)
            if save_filtered:
                dated_filter_output = os.path.join(filter_output_path, patient_id, date_str)
                self.filter_stage.save_filtered_results(sorted_entries, patient_id, dated_filter_output, metadata=metadata_list, study_date=date_str)
            
            # Run consistency checks for this date (will flag empty entries)
            status, flags, details = self.check_consistency(sorted_entries, f"{patient_id}_{date_str}")
            
            entries_by_date[date_str] = sorted_entries
            status_by_date[date_str] = status
            flags_by_date[date_str] = flags
            details_by_date[date_str] = details
        
        return summary, entries_by_date, status_by_date, flags_by_date, details_by_date

    def process_patient_with_nifti_conversion(self, patient_dir, patient_dir_name, extract_out_dir, 
                                              filter_out_dir, nifti_images_root, nifti_metadata_root, csv_out_dir=None):
        """
        Process a single patient through the complete pipeline including NIfTI conversion and CSV saving.
        Handles multiple acquisition dates - organizes output as patient_id/YYYYMMDD/niftis
        
        Args:
            patient_dir: Path to patient DICOM directory
            patient_dir_name: Name of patient directory
            extract_out_dir: Output directory for extracted metadata
            filter_out_dir: Output directory for filtered results
            nifti_images_root: Root directory for NIfTI images (structure: patient_id/date/)
            nifti_metadata_root: Root directory for NIfTI metadata (structure: patient_id/date/)
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
            "consistency_details": None,
            "dates_info": {}  # {date_str: {"status", "flags", "entry_count", "consistency_details"}}
        }
        
        try:
            patient_id = patient_dir_name
            
            # STAGE 1: EXTRACTION & FILTERING & CONSISTENCY CHECKS (DATE-BASED)
            print(f"  [EXTRACTION] Reading DICOM metadata from {patient_dir_name}...", end=" ", flush=True)
            
            filtered_data = self.extract_filter_and_save_by_date(
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
            
            summary, entries_by_date, status_by_date, flags_by_date, details_by_date = filtered_data

            # Store per-date info so callers can use it even when validation didn't run
            result["dates_info"] = {
                date_str: {
                    "status": status_by_date.get(date_str, ""),
                    "flags": " | ".join(flags_by_date.get(date_str, [])) or "OK",
                    "entry_count": len(entries_by_date.get(date_str, [])),
                    "consistency_details": details_by_date.get(date_str),
                }
                for date_str in entries_by_date
            }
            
            # Extract patient_id from summary
            if not summary or not isinstance(summary, dict):
                print(f"  [ERROR] Invalid summary format")
                result["status"] = "INVALID_SUMMARY"
                return result
            
            patient_id = list(summary.keys())[0]
            result["patient_id"] = patient_id
            
            # Aggregate statistics across all dates
            total_entry_count = sum(len(entries) for entries in entries_by_date.values())
            result["entry_count"] = total_entry_count
            
            # Track overall status (use first date's status if only one, else aggregate)
            if len(status_by_date) == 1:
                result["status"] = list(status_by_date.values())[0]
                result["flags"] = " | ".join(list(flags_by_date.values())[0]) if list(flags_by_date.values())[0] else "OK"
                result["consistency_details"] = list(details_by_date.values())[0]
            else:
                # Multiple dates - combine statuses
                all_ok = all(s == "OK" for s in status_by_date.values())
                result["status"] = "OK" if all_ok else "MULTIPLE_DATES_WITH_ISSUES"
                all_flags = []
                for date_flags in flags_by_date.values():
                    all_flags.extend(date_flags)
                result["flags"] = " | ".join(all_flags) if all_flags else "OK"
            
            # STAGE 2: NIFTI CONVERSION PER DATE
            all_validations = {}
            nifti_conversion_status = "SKIPPED"
            overall_validation_status = "NOT_RUN"
            
            for date_str in sorted(entries_by_date.keys()):
                filtered_entries = entries_by_date[date_str]
                status = status_by_date[date_str]
                
                date_icon = "✓" if status == "OK" else "⚠️"
                print(f"  [CONSISTENCY] {date_icon} {status} - {len(filtered_entries)} sequences for Study Date: {date_str}")
                
                if status == "OK" and filtered_entries:
                    # Create date-specific directory structure
                    patient_images_dir = os.path.join(nifti_images_root, patient_id, date_str)
                    patient_metadata_dir = os.path.join(nifti_metadata_root, patient_id, date_str)
                    
                    # Find or create the filtered JSON file for this date
                    filtered_json_path = os.path.join(filter_out_dir, patient_id, date_str, f"{patient_id}_filtered.json")
                    
                    if os.path.exists(filtered_json_path):
                        print(f"  [NIfTI CONVERSION] Converting {len(filtered_entries)} sequences for Study Date: {date_str}...", end=" ", flush=True)
                        try:
                            process_patient_json(
                                filtered_json_path,
                                nifti_images_root,  # Will use patient_id/date/ structure if modified
                                nifti_metadata_root,
                                interactive=False,
                                patient_id=patient_id,
                                study_date=date_str
                            )
                            print(f"✓")
                            nifti_conversion_status = "SUCCESS"
                            
                            # Check if NIfTI files were actually created
                            nifti_files = [f for f in os.listdir(patient_images_dir) if f.endswith('.nii.gz')]
                            if nifti_files:
                                # STAGE 3: NIFTI VALIDATION PER DATE
                                print(f"  [NIfTI VALIDATION] Running quality checks for Study Date: {date_str}...", end=" ", flush=True)
                                
                                validation_result = validate_patient_nifti(
                                    patient_images_dir,
                                    patient_id,
                                    filtered_entries
                                )
                                print(f"✓ {validation_result['overall_status']}")
                                
                                all_validations[date_str] = validation_result
                                if overall_validation_status == "NOT_RUN":
                                    overall_validation_status = validation_result["overall_status"]
                                elif validation_result["overall_status"] == "ERROR" or overall_validation_status == "ERROR":
                                    overall_validation_status = "ERROR"
                                elif validation_result["overall_status"] == "WARNING" and overall_validation_status != "ERROR":
                                    overall_validation_status = "WARNING"
                            else:
                                print(f"No NIfTI files found for Study Date: {date_str} - skipping validation")
                            
                        except Exception as e:
                            print(f"FAILED ({str(e)[:50]})")
                            nifti_conversion_status = "FAILED"
                            result["nifti_error"] = f"Date {date_str}: {str(e)}"
                    else:
                        print(f"  [NIfTI CONVERSION] JSON not found for Study Date: {date_str}")
                        nifti_conversion_status = "JSON_NOT_FOUND"
                else:
                    # Status not OK or no entries - skip conversion
                    print(f"  [NIfTI CONVERSION] SKIPPED for Study Date: {date_str} (consistency check flagged)")
            
            result["nifti_conversion"] = nifti_conversion_status
            result["nifti_validation_status"] = overall_validation_status
            if all_validations:
                result["nifti_validation"] = all_validations
            
            # STAGE 4: REPORT - Save per-patient CSV if directory provided
            if csv_out_dir and result["patient_id"]:
                all_dates = sorted(entries_by_date.keys())
                validated_dates = set(result["nifti_validation"].keys()) if result["nifti_validation"] else set()

                if all_dates:
                    # Always write one row per date, regardless of whether validation ran
                    for date_str in all_dates:
                        di = result["dates_info"].get(date_str, {})
                        validation = (result["nifti_validation"] or {}).get(date_str)
                        csv_row = {
                            "patient_id": result["patient_id"],
                            "study_date": date_str,
                            "dicom_status": di.get("status", result["status"]),
                            "entry_count": di.get("entry_count", result["entry_count"]),
                            "dicom_flags": di.get("flags", result["flags"]),
                            "nifti_conversion": result["nifti_conversion"] if date_str in validated_dates else "SKIPPED",
                            "nifti_overall_status": validation.get("overall_status", "NOT_RUN") if validation else result["nifti_validation_status"],
                        }
                        if validation:
                            csv_row.update(flatten_validation_result(validation))
                        csv_row.update(flatten_consistency_details(di.get("consistency_details", result["consistency_details"])))
                        save_patient_csv_row(csv_row, csv_out_dir, result["patient_id"])
                else:
                    # Fallback: no date info at all
                    csv_row = {
                        "patient_id": result["patient_id"],
                        "study_date": "",
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

