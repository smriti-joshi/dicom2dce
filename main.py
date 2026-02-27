import os
import json
from dicom2dce.process_dicom import DicomProcessingPipeline
from dicom2dce.pipeline.stage2_filter import Config
from dicom2dce.pipeline.stage6_report import flatten_validation_result, save_center_results, print_summary

if __name__ == "__main__":
    Config.load()

    centers = Config.get_centers()
    pipeline = DicomProcessingPipeline()

    SKIP_PATIENT_IDS = [
            "_".join(x.split("_")[:3])
            for x in os.listdir("/dataall/breast_masks/first_phase_eucanimage")
        ]
    for center in centers:
        print(f"\n{'='*70}")
        print(f"  CENTER: {center}")
        print('='*70)

        # input directory
        center_root_dir = os.path.join(Config.get_dicom_root(), center)
        if not os.path.isdir(center_root_dir):
            print(f"\n✗ Center directory not found: {center_root_dir}")
            continue

        #output directories
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


        # loop through patients
        for idx, patient_dir_name in enumerate(patient_dirs, 1):
            patient_dir = os.path.join(center_root_dir, patient_dir_name)

            print(f"\n[{idx}/{len(patient_dirs)}]")
            
            if patient_dir in SKIP_PATIENT_IDS:
                print(f"{patient_dir} has been processed in previous iterations by Dimitri/Lidia")

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

            # Print warnings/errors
            if result["nifti_error"]:
                print(f"  ✗ NIfTI Error: {result['nifti_error']}")
            if val_status == "WARNING" and result["nifti_validation"]:
                for issue in result["nifti_validation"].get("all_issues", [])[:3]:
                    print(f"  ⚠ {issue}")

            # Accumulate results
            csv_row = {
                "patient_id": patient_id,
                "dicom_status": result["status"],
                "entry_count": result["entry_count"],
                "dicom_flags": result["flags"],
                "nifti_conversion": result["nifti_conversion"],
                "nifti_overall_status": val_status,
            }
            csv_row.update(flatten_validation_result(result["nifti_validation"]))
            
            # Add consistency check details
            if result["consistency_details"]:
                details = result["consistency_details"]
                csv_row.update({
                    "consistency_temporal_positions": details.get("temporal_positions", ""),
                    "consistency_total_dicoms": details.get("total_dicoms", ""),
                    "consistency_folder_names": json.dumps(details.get("folder_names", [])) if details.get("folder_names") else "",
                    "consistency_slices_per_temporal": json.dumps(details.get("slices_per_temporal", {})) if details.get("slices_per_temporal") else "",
                    "consistency_folder_slice_counts": json.dumps(details.get("folder_slice_counts", {})) if details.get("folder_slice_counts") else "",
                    "consistency_low_similarity_pairs": json.dumps(details.get("low_similarity_pairs", [])) if details.get("low_similarity_pairs") else "",
                })
            
            csv_results.append(csv_row)

            if result["nifti_validation"]:
                validation_details[patient_id] = result["nifti_validation"]

        print(f"\n{'='*70}")
        print("  SAVING RESULTS")
        print('='*70)
        save_center_results(csv_results, validation_details, results_dir, center)
        print_summary(csv_results, nifti_stats, validation_stats)

