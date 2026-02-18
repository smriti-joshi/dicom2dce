from process_dicom import DicomProcessingPipeline
from dce_filter import FilterConfig
import os
import json
import csv

def flatten_validation_result(validation_result):
    """
    Flatten nested validation result into flat dictionary for CSV columns.
    
    Args:
        validation_result: Dictionary with consistency/temporal_order/signal_progression/volume_integrity keys
        
    Returns:
        Dictionary with flattened validation columns
    """
    if not validation_result:
        return {
            "val_consistency_status": "",
            "val_temporal_status": "",
            "val_signal_status": "",
            "val_volume_status": "",
            "val_consistency_issues": "",
            "val_temporal_issues": "",
            "val_signal_issues": "",
            "val_volume_issues": "",
            "val_file_count": "",
            "val_enhancement_ratio": "",
            "val_peak_index": "",
            "val_time_gaps": "",
            "val_problematic_volumes": "",
        }
    
    flat = {}
    
    # Consistency check
    cons = validation_result.get("consistency", {})
    flat["val_consistency_status"] = cons.get("status", "")
    cons_issues = cons.get("issues", [])
    flat["val_consistency_issues"] = "; ".join(cons_issues[:2]) if cons_issues else ""
    cons_metrics = cons.get("metrics", {})
    flat["val_file_count"] = cons_metrics.get("file_count", "")
    
    # Temporal order check
    temp = validation_result.get("temporal_order", {})
    flat["val_temporal_status"] = temp.get("status", "")
    temp_issues = temp.get("issues", [])
    flat["val_temporal_issues"] = "; ".join(temp_issues[:2]) if temp_issues else ""
    temp_metrics = temp.get("metrics", {})
    flat["val_time_gaps"] = temp_metrics.get("time_gaps_sec", "")
    
    # Signal progression check
    sig = validation_result.get("signal_progression", {})
    flat["val_signal_status"] = sig.get("status", "")
    sig_issues = sig.get("issues", [])
    flat["val_signal_issues"] = "; ".join(sig_issues[:2]) if sig_issues else ""
    sig_metrics = sig.get("metrics", {})
    flat["val_enhancement_ratio"] = sig_metrics.get("enhancement_ratio", "")
    flat["val_peak_index"] = sig_metrics.get("peak_index", "")
    
    # Volume integrity check
    vol = validation_result.get("volume_integrity", {})
    flat["val_volume_status"] = vol.get("status", "")
    vol_issues = vol.get("issues", [])
    flat["val_volume_issues"] = "; ".join(vol_issues[:2]) if vol_issues else ""
    vol_metrics = vol.get("metrics", {})
    flat["val_problematic_volumes"] = vol_metrics.get("problematic_volumes", "")
    
    return flat

if __name__ == "__main__":
    # Load configuration from config.json
    FilterConfig.load()
    
    centers = {'UNIPI'}
    pipeline = DicomProcessingPipeline()

    for center in centers:
        print(f"\n{'='*70}")
        print(f"  CENTER: {center}")
        print('='*70)
        
        # Setup paths
        center_root_dir = f"/dataall/dicoms/{center}"
        results_folder = f"/workspace/project_data_processing/dicom2dce/results"
        extract_out_dir = f"{results_folder}/{center.lower()}/dicom_files"
        filter_out_dir = f"{results_folder}/{center.lower()}/filtered_dicom_files"
        csv_out_dir = f"{results_folder}/{center.lower()}"
        
        # NIfTI conversion output directories
        nifti_images_root = f"/dataall/eucanimage_second_try/{center}/images"
        nifti_metadata_root = f"/dataall/eucanimage_second_try/{center}/dicom_metadata"
        
        # Collect results for CSV and validation details
        csv_results = []
        validation_details = {}
        
        # Setup paths and validate
        if not os.path.isdir(center_root_dir):
            print(f"\n✗ Center directory not found: {center_root_dir}")
            continue
        
        patient_dirs = sorted([d for d in os.listdir(center_root_dir)
                               if os.path.isdir(os.path.join(center_root_dir, d))])
        
        print(f"\n  Found {len(patient_dirs)} patient(s)")
        print('='*70)
        
        nifti_stats = {"success": 0, "failed": 0, "skipped": 0}
        validation_stats = {"ok": 0, "warning": 0, "error": 0}
        
        for idx, patient_dir_name in enumerate(patient_dirs, 1):
            patient_dir = os.path.join(center_root_dir, patient_dir_name)
            
            print(f"\n[{idx}/{len(patient_dirs)}]")
            
            # Process patient and convert to NIfTI in one pass
            result = pipeline.process_patient_with_nifti_conversion(
                patient_dir,
                patient_dir_name,
                extract_out_dir,
                filter_out_dir,
                nifti_images_root,
                nifti_metadata_root
            )
            
            if result["patient_id"]:
                patient_id = result["patient_id"]
                
                # Track NIfTI conversion stats
                if result["nifti_conversion"] == "SUCCESS":
                    nifti_stats["success"] += 1
                elif result["nifti_conversion"] == "FAILED":
                    nifti_stats["failed"] += 1
                else:
                    nifti_stats["skipped"] += 1
                
                # Track validation stats
                val_status = result["nifti_validation_status"]
                if val_status == "OK":
                    validation_stats["ok"] += 1
                elif val_status == "WARNING":
                    validation_stats["warning"] += 1
                elif val_status == "ERROR":
                    validation_stats["error"] += 1
                
                # Print only errors and warnings (pipeline already printed success info)
                if result["nifti_error"]:
                    print(f"  ✗ NIfTI Error: {result['nifti_error']}")
                
                if result["nifti_validation_status"] == "WARNING" and result["nifti_validation"]:
                    val_issues = result["nifti_validation"].get("all_issues", [])
                    if val_issues:
                        print(f"  ⚠ Validation warnings:")
                        for issue in val_issues[:3]:  # Show first 3 issues
                            print(f"     - {issue}")
                
                # Add to CSV results
                val_flat = flatten_validation_result(result["nifti_validation"])
                csv_row = {
                    "patient_id": patient_id,
                    "dicom_status": result["status"],
                    "entry_count": result["entry_count"],
                    "dicom_flags": result["flags"],
                    "nifti_conversion": result["nifti_conversion"],
                    "nifti_overall_status": val_status,
                }
                # Add all flattened validation columns
                csv_row.update(val_flat)
                csv_results.append(csv_row)
                
                # Store validation details
                if result["nifti_validation"]:
                    validation_details[patient_id] = result["nifti_validation"]
        
        # Save outputs
        print(f"\n{'='*70}")
        print("  SAVING RESULTS")
        print('='*70)
        
        os.makedirs(csv_out_dir, exist_ok=True)
        csv_output_file = os.path.join(csv_out_dir, f"processing_report_{center.lower()}.csv")
        
        if csv_results:
            fieldnames = [
                # DICOM extraction and filtering
                "patient_id",
                "dicom_status",
                "entry_count",
                "dicom_flags",
                # NIfTI conversion
                "nifti_conversion",
                # NIfTI validation - overall
                "nifti_overall_status",
                # NIfTI validation - consistency check
                "val_consistency_status",
                "val_consistency_issues",
                "val_file_count",
                # NIfTI validation - temporal order check
                "val_temporal_status",
                "val_temporal_issues",
                "val_time_gaps",
                # NIfTI validation - signal progression check
                "val_signal_status",
                "val_signal_issues",
                "val_enhancement_ratio",
                "val_peak_index",
                # NIfTI validation - volume integrity check
                "val_volume_status",
                "val_volume_issues",
                "val_problematic_volumes",
            ]
            with open(csv_output_file, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(csv_results)
            print(f"  ✓ CSV report: {csv_output_file}")
        
        # Save validation details as JSON
        validation_output_file = os.path.join(csv_out_dir, f"nifti_validation_details_{center.lower()}.json")
        if validation_details:
            with open(validation_output_file, "w") as f:
                json.dump(validation_details, f, indent=2)
            print(f"  ✓ Validation details: {validation_output_file}")
        
        # Print final summary
        print(f"\n{'='*70}")
        print("  SUMMARY")
        print('='*70)
        print(f"  Total patients: {len(csv_results)}")
        print(f"  DICOM status:")
        dicom_ok = sum(1 for r in csv_results if r["dicom_status"] == "OK")
        dicom_flagged = len(csv_results) - dicom_ok
        print(f"    ✓ OK: {dicom_ok}")
        print(f"    ⚠ Flagged: {dicom_flagged}")
        print(f"  NIfTI conversion:")
        print(f"    ✓ Success: {nifti_stats['success']}")
        print(f"    ⊘ Skipped: {nifti_stats['skipped']}")
        print(f"    ✗ Failed: {nifti_stats['failed']}")
        print(f"  NIfTI validation:")
        print(f"    ✓ OK: {validation_stats['ok']}")
        print(f"    ⚠ WARNING: {validation_stats['warning']}")
        print(f"    ✗ ERROR: {validation_stats['error']}")
        print('='*70)

