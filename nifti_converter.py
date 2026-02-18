import os
import json
import subprocess
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
    """Split 4D NIfTI file into multiple 3D volumes and remove the 4D file."""
    img = nib.load(nifti_path)
    data = img.get_fdata()
    if data.ndim == 4:
        n_vols = data.shape[3]
        for i in range(n_vols):
            out_name = f"{patient_id}_{seq_idx+i:04d}.nii.gz"
            out_path = os.path.join(patient_images_dir, out_name)
            vol_img = nib.Nifti1Image(data[..., i], img.affine, img.header)
            nib.save(vol_img, out_path)
        os.remove(nifti_path)
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

    if not os.path.exists(final_nii_path):
        return seq_idx

    # Check if the converted file is actually 4D
    img = nib.load(final_nii_path)
    is_4d = img.get_fdata().ndim == 4
    
    if is_4d:
        # dcm2niix created a 4D file, need to split it
        n_vols = split_4d_nifti_overwrite(
            final_nii_path, patient_images_dir, patient_id, seq_idx
        )
        if n_vols > 0:
            for i in range(n_vols):
                mapping.append(
                    {
                        "nifti_image": os.path.join(
                            patient_images_dir,
                            f"{patient_id}_{seq_idx + i:04d}.nii.gz",
                        ),
                        "dicom_folder": dicom_folder,
                    }
                )
            seq_idx += n_vols
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
        # dcm2niix created a 3D file (or already split volumes)
        mapping.append(
            {
                "nifti_image": final_nii_path,
                "dicom_folder": dicom_folder,
            }
        )
        seq_idx += 1

    # Move all JSON sidecars for this sequence to the metadata directory
    for fname in os.listdir(patient_images_dir):
        if fname.startswith(out_basename) and fname.endswith('.json'):
            src_json = os.path.join(patient_images_dir, fname)
            dst_json = os.path.join(patient_metadata_dir, fname)
            os.rename(src_json, dst_json)

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
