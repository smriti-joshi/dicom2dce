from process_dicom import DicomProcessingPipeline
from consistency_checker import VisualChecks
import os
import csv
import json

if __name__ == "__main__":
    centers = {'UNIPI'}
    pipeline = DicomProcessingPipeline()

    for center in centers:
        print(f"\n{'='*60}")
        print(f"Processing for center {center}")
        print('='*60)
        
        center_root_dir = f"/dataall/dicoms/{center}"
        extract_out_dir = f"/workspace/project_data_processing/release/dicom_patients_json_{center.lower()}"
        filter_out_dir = f"/workspace/project_data_processing/release/dicom_patients_json_filtered_{center.lower()}"
        csv_out_dir = f"/workspace/project_data_processing/release/consistency_check_results_{center.lower()}"
        # Collect results for CSV
        results = []
        
        # Extract and filter in one pass
        print(f"\nExtracting and filtering DICOM metadata...")
        if os.path.isdir(center_root_dir):
            patient_dirs = sorted([d for d in os.listdir(center_root_dir) 
                                 if os.path.isdir(os.path.join(center_root_dir, d))])
            
            for idx, patient_dir_name in enumerate(patient_dirs, 1):
                # print(f"\nProcessing patient directory: {patient_dir_name}")
                patient_dir = os.path.join(center_root_dir, patient_dir_name)
                # Extract and filter in one pass, save both
                filtered_data = pipeline.extract_filter_and_save(
                    patient_dir, 
                    extract_out_dir, 
                    filter_out_dir,
                    save_extracted=True,
                    save_filtered=True
                )
                
                # Check consistency on filtered data
                if filtered_data:
                    # filtered_data is a tuple (summary, grouped)
                    try:
                        summary = filtered_data[0]  # {patient_id: metadata_list}
                        filtered_entries = filtered_data[1]  # grouped results
                        
                        # Extract patient_id from summary dict
                        if summary and isinstance(summary, dict):
                            patient_id = list(summary.keys())[0]
                        else:
                            continue
                        
                        # Ensure filtered_entries is a list
                        if filtered_entries is None:
                            filtered_entries = []
                        
                        status, flags, details = VisualChecks.check_consistency(filtered_entries, patient_id)
                    except Exception as e:
                        print(f"Error processing {patient_dir_name}: {e}")
                        continue
                    
                    # Format flags for CSV
                    flags_str = " | ".join(flags) if flags else "OK"
        
                    # Extract specific details based on entry count
                    temporal_positions = details.get("temporal_positions", "")
                    total_dicoms = details.get("total_dicoms", "")
                    folder_names = json.dumps(details.get("folder_names", [])) if details.get("folder_names") else ""
                    slices_per_temporal = json.dumps(details.get("slices_per_temporal", {})) if details.get("slices_per_temporal") else ""
                    folder_slice_counts = json.dumps(details.get("folder_slice_counts", {})) if details.get("folder_slice_counts") else ""
                    low_similarity_pairs = json.dumps(details.get("low_similarity_pairs", [])) if details.get("low_similarity_pairs") else ""
                    
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
        
        # Save results to CSV
        csv_output_file = os.path.join(csv_out_dir, f"consistency_check_results_{center.lower()}.csv")
        os.makedirs(csv_out_dir, exist_ok=True)
        os.makedirs(filter_out_dir, exist_ok=True)
        
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
        
        with open(csv_output_file, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)
        
        print(f"\n{'='*60}")
        print(f"✓ Completed for center {center}")
        print(f"Results saved to: {csv_output_file}")
        
        # Print summary
        ok_count = sum(1 for r in results if r["status"] == "OK")
        flagged_count = len(results) - ok_count
        print(f"Summary: {ok_count} OK, {flagged_count} FLAGGED out of {len(results)} patients")