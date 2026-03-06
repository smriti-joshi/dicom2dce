"""
CLI entry point for the dicom2dce pipeline.

Processes all configured centers and patients through extraction, filtering,
consistency checks, NIfTI conversion, validation, and reporting.

Usage:
    python -m dicom2dce.main
"""

import os
import json
from dicom2dce.process_dicom import DicomProcessingPipeline
from dicom2dce.pipeline.config import Config
from dicom2dce.pipeline.stage6_report import (
    flatten_validation_result, flatten_consistency_details,
    save_center_results, print_summary,
)


def main():
    Config.load()

    centers = Config.get_centers()
    pipeline = DicomProcessingPipeline()

    for center in centers:
        print(f"\n{'='*70}")
        print(f"  CENTER: {center}")
        print('='*70)

        # Input directory
        center_root_dir = os.path.join(Config.get_dicom_root(), center)
        if not os.path.isdir(center_root_dir):
            print(f"\n✗ Center directory not found: {center_root_dir}")
            continue

        # Output directories
        results_dir     = os.path.join(Config.get_results_dir(), center.lower())
        csv_out_dir     = os.path.join(results_dir, "intermediate_results", "per_patient_validation_csvs")
        extract_out_dir = os.path.join(results_dir, "intermediate_results", "all_dicom_files")
        filter_out_dir  = os.path.join(results_dir, "intermediate_results", "filtered_dicom_files")
        nifti_images_root   = os.path.join(results_dir, "dce", "images")
        nifti_metadata_root = os.path.join(results_dir, "dce", "dicom_metadata")

        patient_dirs = sorted([d for d in os.listdir(center_root_dir)
                               if os.path.isdir(os.path.join(center_root_dir, d))])

        print(f"\n  Found {len(patient_dirs)} patient(s)")
        print('='*70)

        csv_results = []
        validation_details = {}
        nifti_stats = {"success": 0, "failed": 0, "skipped": 0}
        validation_stats = {"ok": 0, "warning": 0, "error": 0}

        for idx, patient_dir_name in enumerate(patient_dirs, 1):
            patient_dir = os.path.join(center_root_dir, patient_dir_name)
            print(f"\n[{idx}/{len(patient_dirs)}]")

            result = pipeline.process_patient_with_nifti_conversion(
                patient_dir, patient_dir_name,
                extract_out_dir, filter_out_dir,
                nifti_images_root, nifti_metadata_root,
                csv_out_dir=csv_out_dir
            )

            if not result["patient_id"]:
                continue

            patient_id = result["patient_id"]
            val_status = result["nifti_validation_status"]

            # Track stats
            nifti_stats[{"SUCCESS": "success", "FAILED": "failed"}.get(result["nifti_conversion"], "skipped")] += 1
            if val_status in ("OK", "WARNING", "ERROR"):
                validation_stats[val_status.lower()] += 1

            if result["nifti_error"]:
                print(f"  ✗ NIfTI Error: {result['nifti_error']}")
            
            # Determine if we have date-structured validations (dict of dicts) and count dates
            date_structured = False
            num_dates = 0
            if result["nifti_validation"] and isinstance(result["nifti_validation"], dict):
                first_val = next(iter(result["nifti_validation"].values()), None)
                date_structured = first_val and isinstance(first_val, dict) and "consistency" in first_val
                if date_structured:
                    num_dates = len(result["nifti_validation"])
            
            if date_structured and num_dates > 1:
                # Multi-date case: show warnings from all dates
                if val_status == "WARNING":
                    for date_str, validation in result["nifti_validation"].items():
                        if validation.get("all_issues"):
                            print(f"  ⚠ Study Date: {date_str}: {validation['all_issues'][0]}")
            else:
                # Single date or non-date-structured case: show warnings normally
                if val_status == "WARNING" and result["nifti_validation"] and result["nifti_validation"].get("all_issues"):
                    for issue in result["nifti_validation"].get("all_issues", [])[:3]:
                        print(f"  ⚠ {issue}")

            # Build CSV rows - one per date for multi-date, one row for single-date
            dates_info = result.get("dates_info", {})
            all_dates = sorted(dates_info.keys())
            validated_dates = set((result["nifti_validation"] or {}).keys())

            if all_dates:
                # Always write one row per date, regardless of whether validation ran
                for date_str in all_dates:
                    di = dates_info.get(date_str, {})
                    validation = (result["nifti_validation"] or {}).get(date_str)
                    csv_row = {
                        "patient_id": patient_id,
                        "study_date": date_str,
                        "dicom_status": di.get("status", result["status"]),
                        "entry_count": di.get("entry_count", result["entry_count"]),
                        "dicom_flags": di.get("flags", result["flags"]),
                        "nifti_conversion": result["nifti_conversion"] if date_str in validated_dates else "SKIPPED",
                        "nifti_overall_status": validation.get("overall_status", "NOT_RUN") if validation else val_status,
                    }
                    if validation:
                        csv_row.update(flatten_validation_result(validation))
                    csv_row.update(flatten_consistency_details(di.get("consistency_details", result["consistency_details"])))
                    csv_results.append(csv_row)

                    if validation:
                        validation_details[f"{patient_id}_{date_str}" if len(all_dates) > 1 else patient_id] = validation
            else:
                # Absolute fallback: no date info at all
                csv_row = {
                    "patient_id": patient_id,
                    "study_date": "",
                    "dicom_status": result["status"],
                    "entry_count": result["entry_count"],
                    "dicom_flags": result["flags"],
                    "nifti_conversion": result["nifti_conversion"],
                    "nifti_overall_status": val_status,
                }
                csv_row.update(flatten_validation_result(result["nifti_validation"]))
                csv_row.update(flatten_consistency_details(result["consistency_details"]))
                csv_results.append(csv_row)

                if result["nifti_validation"]:
                    validation_details[patient_id] = result["nifti_validation"]

        print(f"\n{'='*70}")
        print("  SAVING RESULTS")
        print('='*70)
        save_center_results(csv_results, validation_details, results_dir, center)
        print_summary(csv_results, nifti_stats, validation_stats)


if __name__ == "__main__":
    main()
