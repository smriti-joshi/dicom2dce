import pydicom
import os
import json
import csv
from tqdm import tqdm
import numpy as np
import re

from dicom_reader import ExtractionStage
from dce_filter import FilteringStage
from consistency_checker import VisualChecks


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



