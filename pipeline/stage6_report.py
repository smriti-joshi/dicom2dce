"""
Reporting utilities: flatten validation results, save CSV and JSON outputs.
"""

import os
import json
import csv


def flatten_validation_result(validation_result):
    """
    Flatten nested validation result into flat dictionary for CSV columns.

    Args:
        validation_result: Dictionary with consistency/temporal_order/signal_progression keys

    Returns:
        Dictionary with flattened validation columns
    """
    if not validation_result:
        return {
            "val_consistency_status": "",
            "val_temporal_status": "",
            "val_signal_status": "",
            "val_consistency_issues": "",
            "val_temporal_issues": "",
            "val_signal_issues": "",
            "val_file_count": "",
            "val_enhancement_ratio": "",
            "val_peak_index": "",
            "val_time_gaps": "",
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

    return flat


CSV_FIELDNAMES = [
    # DICOM extraction and filtering
    "patient_id",
    "dicom_status",
    "entry_count",
    "dicom_flags",
    # Consistency check details
    "consistency_temporal_positions",
    "consistency_total_dicoms",
    "consistency_folder_names",
    "consistency_slices_per_temporal",
    "consistency_folder_slice_counts",
    "consistency_low_similarity_pairs",
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
]


def save_csv_report(csv_results, output_path):
    """Save processing results to a CSV file."""
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        writer.writerows(csv_results)
    print(f"  ✓ CSV report: {output_path}")


def save_validation_json(validation_details, output_path):
    """Save full validation details to a JSON file."""
    with open(output_path, "w") as f:
        json.dump(validation_details, f, indent=2)
    print(f"  ✓ Validation details: {output_path}")


def save_center_results(csv_results, validation_details, out_dir, center):
    """Save both CSV and JSON outputs for a center."""
    os.makedirs(out_dir, exist_ok=True)

    if csv_results:
        csv_path = os.path.join(out_dir, f"processing_report_{center.lower()}.csv")
        save_csv_report(csv_results, csv_path)

    if validation_details:
        json_path = os.path.join(out_dir, f"nifti_validation_details_{center.lower()}.json")
        save_validation_json(validation_details, json_path)


def save_patient_csv_row(csv_row, output_dir, patient_id):
    """
    Save a single patient's CSV row to a per-patient CSV file.
    Creates file if it doesn't exist, appends row if it does.
    """
    os.makedirs(output_dir, exist_ok=True)
    safe_patient_id = str(patient_id).replace("/", "_").replace("\\", "_")
    patient_csv_path = os.path.join(output_dir, f"{safe_patient_id}_results.csv")
    
    # Check if file exists to determine if we need to write header
    file_exists = os.path.exists(patient_csv_path)
    
    with open(patient_csv_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
        if not file_exists:
            writer.writeheader()
        writer.writerow(csv_row)


def print_summary(csv_results, nifti_stats, validation_stats):
    """Print final summary to stdout."""
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
