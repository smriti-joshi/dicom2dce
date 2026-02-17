from process_dicom import DicomProcessingPipeline
from dce_filter import FilterConfig
import sys
import os

# Add parent directories to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from convert_to_nifti import process_patient_json

if __name__ == "__main__":
    # Load configuration from config.json
    FilterConfig.load()
    
    centers = {'UNIPI'}
    pipeline = DicomProcessingPipeline()

    for center in centers:
        print(f"\n{'='*60}")
        print(f"Processing for center {center}")
        print('='*60)
        
        # Setup paths
        center_root_dir = f"/dataall/dicoms/{center}"
        results_folder = f"/workspace/project_data_processing/dicom2dce/results"
        extract_out_dir = f"{results_folder}/{center.lower()}/dicom_files"
        filter_out_dir = f"{results_folder}/{center.lower()}/filtered_dicom_files"
        csv_out_dir = f"{results_folder}/{center.lower()}"
        
        # NIfTI conversion output directories
        nifti_images_root = f"/dataall/eucanimage/{center}/images"
        nifti_metadata_root = f"/dataall/eucanimage/{center}/dicom_metadata"
        
        # Process center and generate CSV report
        results, summary_stats = pipeline.process_and_save_csv_report(
            center,
            center_root_dir,
            extract_out_dir,
            filter_out_dir,
            csv_out_dir
        )
        
        # Convert non-flagged cases to NIfTI
        print(f"\n{'='*60}")
        print(f"Converting non-flagged cases to NIfTI...")
        print('='*60)
        
        nifti_success_count = 0
        nifti_skip_count = 0
        nifti_error_count = 0
        
        for result in results:
            patient_id = result["patient_id"]
            status = result["status"]
            
            if status == "OK":
                # Construct path to filtered JSON file
                filtered_json_path = os.path.join(filter_out_dir, f"{patient_id}_filtered.json")
                
                if not os.path.exists(filtered_json_path):
                    print(f"⚠️  [SKIP] {patient_id}: Filtered JSON not found at {filtered_json_path}")
                    nifti_skip_count += 1
                    continue
                
                try:
                    print(f"\n🔄 Converting {patient_id}...")
                    process_patient_json(
                        filtered_json_path,
                        nifti_images_root,
                        nifti_metadata_root,
                        interactive=False
                    )
                    nifti_success_count += 1
                except Exception as e:
                    print(f"❌ [ERROR] {patient_id}: {str(e)}")
                    nifti_error_count += 1
            else:
                # Flagged case, skip NIfTI conversion
                flags = result["flags"]
                print(f"⊘  [SKIP] {patient_id}: Flagged - {flags}")
                nifti_skip_count += 1
        
        # Print completion message
        print(f"\n{'='*60}")
        print(f"✓ Completed for center {center}")
        print(f"CSV Report: {csv_out_dir}")
        print(f"NIfTI Conversion: {nifti_success_count} success, {nifti_skip_count} skipped, {nifti_error_count} errors")
        print('='*60)
