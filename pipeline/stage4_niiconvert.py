import os
import json
import subprocess
import glob
import re
import nibabel as nib


def convert_dicom_to_nifti(dicom_folder, output_path, out_name=None):
    """Convert DICOM folder to NIfTI using dcm2niix.

    If out_name is provided, use it as the output filename (without extension).
    """
    filename_template = out_name if out_name else "%s"
    cmd = [
        "dcm2niix",
        "-z",
        "y",
        "-o",
        output_path,
        "-f",
        filename_template,
        dicom_folder,
    ]
    subprocess.run(cmd, check=True)


def split_4d_nifti_overwrite(nifti_path, patient_images_dir, patient_id, seq_idx):
    """Split 4D NIfTI file into multiple 3D volumes and remove the 4D file.
    
    Also duplicates associated JSON sidecar for each volume.
    """
    img = nib.load(nifti_path)
    data = img.get_fdata()
    if data.ndim == 4:
        n_vols = data.shape[3]
        nifti_basename = os.path.basename(nifti_path).replace('.nii.gz', '')
        json_path = os.path.join(patient_images_dir, f"{nifti_basename}.json")
        
        # Read original JSON if it exists
        json_data = None
        if os.path.exists(json_path):
            with open(json_path, "r") as f:
                json_data = json.load(f)
        
        # Split NII volumes and duplicate JSON for each
        for i in range(n_vols):
            out_name = f"{patient_id}_{seq_idx+i:04d}.nii.gz"
            out_path = os.path.join(patient_images_dir, out_name)
            vol_img = nib.Nifti1Image(data[..., i], img.affine, img.header)
            nib.save(vol_img, out_path)
            
            # Duplicate JSON for each volume with matching index
            if json_data is not None:
                json_out_name = f"{patient_id}_{seq_idx+i:04d}.json"
                json_out_path = os.path.join(patient_images_dir, json_out_name)
                with open(json_out_path, "w") as f:
                    json.dump(json_data, f, indent=2)
        
        # Remove original 4D NII and JSON
        os.remove(nifti_path)
        if os.path.exists(json_path):
            os.remove(json_path)
        
        return n_vols
    return 0


def _process_single_sequence(
    dicom_folder,
    patient_id,
    seq_idx,
    patient_images_dir,
    patient_metadata_dir,
    mapping,
):
    """Convert one DICOM sequence to NIfTI, update mapping and seq_idx.

    Automatically detects if dcm2niix created 4D files and splits them if needed.
    Returns the updated seq_idx.
    """

    out_basename = f"{patient_id}_{seq_idx:04d}"
    convert_dicom_to_nifti(dicom_folder, patient_images_dir, out_name=out_basename)
    final_nii_path = os.path.join(patient_images_dir, f"{out_basename}.nii.gz")

    # Check if the pre-contrast baseline file was created
    if not os.path.exists(final_nii_path):
        return seq_idx

    # Check if the baseline file is 4D or 3D
    img = nib.load(final_nii_path)
    is_4d = img.get_fdata().ndim == 4
    
    baseline_volumes = 0
    if is_4d:
        # dcm2niix created a 4D baseline file, need to split it
        baseline_volumes = split_4d_nifti_overwrite(
            final_nii_path, patient_images_dir, patient_id, seq_idx
        )
        if baseline_volumes > 0:
            for i in range(baseline_volumes):
                mapping.append(
                    {
                        "nifti_image": os.path.join(
                            patient_images_dir,
                            f"{patient_id}_{seq_idx + i:04d}.nii.gz",
                        ),
                        "dicom_folder": dicom_folder,
                    }
                )
            seq_idx += baseline_volumes
        else:
            # Fallback: add 4D file as-is
            mapping.append(
                {
                    "nifti_image": final_nii_path,
                    "dicom_folder": dicom_folder,
                }
            )
            seq_idx += 1
    else:
        # Baseline is a 3D file
        mapping.append(
            {
                "nifti_image": final_nii_path,
                "dicom_folder": dicom_folder,
            }
        )
        seq_idx += 1
    
    # Handle trigger time files if they exist
    # dcm2niix may save trigger times as {out_basename}_t1.nii.gz, _t2.nii.gz, etc.
    trigger_pattern = os.path.join(patient_images_dir, f"{out_basename}_t*.nii.gz")
    trigger_files = glob.glob(trigger_pattern)
    
    if trigger_files:
        # Extract trigger time numbers and sort by them
        trigger_files_with_time = []
        for f in trigger_files:
            basename = os.path.basename(f).replace('.nii.gz', '')
            # Extract number after _t
            match = re.search(r'_t(\d+)$', basename)
            if match:
                trigger_time = int(match.group(1))
                trigger_files_with_time.append((trigger_time, f))
        
        # Sort by trigger time to maintain proper order
        trigger_files_with_time.sort()
        
        print(f"  Found {len(trigger_files_with_time)} trigger time file(s)")
        
        # Rename in order starting from current seq_idx (after baseline volumes)
        for i, (trigger_time, old_path) in enumerate(trigger_files_with_time):
            new_seq_idx = seq_idx + i
            new_name = f"{patient_id}_{new_seq_idx:04d}.nii.gz"
            new_path = os.path.join(patient_images_dir, new_name)
            os.rename(old_path, new_path)
            
            # Also rename JSON sidecar if it exists
            old_json = old_path.replace('.nii.gz', '.json')
            if os.path.exists(old_json):
                new_json = new_path.replace('.nii.gz', '.json')
                os.rename(old_json, new_json)
            
            # Add to mapping
            mapping.append(
                {
                    "nifti_image": new_path,
                    "dicom_folder": dicom_folder,
                }
            )
            print(f"    Renamed {os.path.basename(old_path)} -> {new_name}")
        
        seq_idx += len(trigger_files_with_time)

    # Move all JSON sidecars to the metadata directory
    # All JSON files should now have proper indices matching their NII files
    json_pattern = os.path.join(patient_images_dir, f"{patient_id}_*.json")
    for json_file in glob.glob(json_pattern):
        dst_json = os.path.join(patient_metadata_dir, os.path.basename(json_file))
        os.rename(json_file, dst_json)

    return seq_idx




def process_patient_json(json_path, images_root, metadata_root, interactive=False):
    """
    Process a single patient's filtered DICOM JSON file and convert to NIfTI.
    
    Args:
        json_path: Path to filtered DICOM JSON file
        images_root: Root directory where NIfTI images will be saved
        metadata_root: Root directory where metadata will be saved
        interactive: If True, prompt user to select sequences (not used for flat entries)
    """
    with open(json_path, "r") as f:
        data = json.load(f)
    
    patient_id = list(data.keys())[0]
    entries = data[patient_id]  # Flat list of entries
    
    patient_images_dir = os.path.join(images_root, patient_id)
    patient_metadata_dir = os.path.join(metadata_root, patient_id)

    if os.path.exists(patient_images_dir):
        print(f"Patient {patient_id} already processed. Skipping.")
        return

    # Create output directories
    if not os.path.exists(patient_images_dir):
        os.makedirs(patient_images_dir, exist_ok=True)
        os.makedirs(patient_metadata_dir, exist_ok=True)

    mapping = []
    seq_idx = 0
    
    print("\n"*3 + "*"*50 + "dicom2niix logs" + "*"*50)
    # Process all entries (flat list format)
    for entry in entries:
        dicom_file = entry["DicomPath"]
        dicom_folder = os.path.dirname(dicom_file)
        
        # Process the sequence (4D detection is automatic)
        seq_idx = _process_single_sequence(
            dicom_folder,
            patient_id,
            seq_idx,
            patient_images_dir,
            patient_metadata_dir,
            mapping,
        )
    
    # Save mapping
    mapping_path = os.path.join(patient_metadata_dir, f"{patient_id}_nifti_dicom_mapping.json")
    with open(mapping_path, "w") as mf:
        json.dump(mapping, mf, indent=2)
    print(f"*"*100)
    print("\n"*3 + f"Mapping saved for {patient_id} at {mapping_path}")
