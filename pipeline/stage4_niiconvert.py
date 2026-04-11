"""Stage 4: DICOM to NIfTI conversion via dcm2niix."""

import os
import json
import subprocess
import glob
import re
import shutil
import nibabel as nib


def _find_dcm2niix():
    """Locate the dcm2niix executable, checking PATH and common fallback locations."""
    exe = shutil.which("dcm2niix")
    if exe:
        return exe
    fallbacks = [
        os.path.expanduser("~/.local/bin/dcm2niix"),
        "/usr/local/bin/dcm2niix",
        "/usr/bin/dcm2niix",
    ]
    for path in fallbacks:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    raise FileNotFoundError(
        "dcm2niix not found on PATH or in common locations. "
        "Install it or add its directory to PATH."
    )


def convert_dicom_to_nifti(dicom_folder, output_path, out_name=None):
    """Convert DICOM folder to NIfTI using dcm2niix.

    If out_name is provided, use it as the output filename (without extension).
    If dcm2niix fails due to JPEG decompression errors, attempts to decompress
    using dcmdjpeg before retrying.
    """
    filename_template = out_name if out_name else "%s"
    cmd = [
        _find_dcm2niix(),
        "-z",
        "y",
        "-o",
        output_path,
        "-f",
        filename_template,
        dicom_folder,
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        error_text = e.stderr + e.stdout if e.stderr and e.stdout else str(e)
        
        # Check if error is related to JPEG decompression
        if "JPEG signature" in error_text or "Failed to decode" in error_text or "dcmdjpeg" in error_text:
            print(f"  [WARNING] dcm2niix encountered JPEG decompression error. Attempting to decompress with dcmdjpeg...")
            
            # Find all DICOM files in the folder
            dicom_files = glob.glob(os.path.join(dicom_folder, "*.dcm"))
            
            if not dicom_files:
                raise RuntimeError(f"No DICOM files found in {dicom_folder} to decompress") from e
            
            # Decompress each DICOM file using dcmdjpeg
            for dicom_file in dicom_files:
                try:
                    # dcmdjpeg modifies in-place by default
                    dcmdjpeg_cmd = ["dcmdjpeg", dicom_file, dicom_file]
                    subprocess.run(dcmdjpeg_cmd, check=True, capture_output=True)
                    print(f"    ✓ Decompressed: {os.path.basename(dicom_file)}")
                except subprocess.CalledProcessError:
                    print(f"    ✗ Failed to decompress {os.path.basename(dicom_file)}")
            
            # Retry dcm2niix after decompression
            print(f"  Retrying dcm2niix after decompression...")
            try:
                subprocess.run(cmd, check=True, capture_output=True, text=True)
                print(f"  ✓ Successfully converted after decompression")
            except subprocess.CalledProcessError as retry_error:
                raise RuntimeError(f"dcm2niix failed even after decompression: {retry_error}") from retry_error
        else:
            # Re-raise if it's not a JPEG-related error
            raise


def split_4d_nifti_overwrite(nifti_path, patient_images_dir, patient_id, seq_idx):
    """Split 4D NIfTI file into multiple 3D volumes and remove the 4D file.
    
    Also duplicates associated JSON sidecar for each volume.
    """
    print(f"  [DEBUG] Splitting 4D NIfTI: {os.path.basename(nifti_path)}")
    
    # Verify file exists
    if not os.path.exists(nifti_path):
        print(f"  [ERROR] Expected 4D NIfTI file not found: {nifti_path}")
        return 0
    
    try:
        img = nib.load(nifti_path)
        data = img.get_fdata()
        
        # Only process if it's actually 4D
        if data.ndim != 4:
            print(f"  [WARNING] Expected 4D but got {data.ndim}D. Not splitting.")
            return 0
        
        n_vols = data.shape[3]
        print(f"  [DEBUG] 4D file has {n_vols} volumes, will create indices {seq_idx} to {seq_idx + n_vols - 1}")
        
        # IMPORTANT: Rename the original 4D file to a temporary name BEFORE creating split files
        # This prevents overwriting the original when we save the first split volume (which has the same index)
        temp_4d_path = nifti_path.replace('.nii.gz', '_temp_4d.nii.gz')
        os.rename(nifti_path, temp_4d_path)
        print(f"  [DEBUG] Renamed original 4D file to temporary: {os.path.basename(temp_4d_path)}")
        
        nifti_basename = os.path.basename(nifti_path).replace('.nii.gz', '')
        json_path = os.path.join(patient_images_dir, f"{nifti_basename}.json")
        temp_json_path = json_path.replace('.json', '_temp.json')
        
        # Rename JSON sidecar too
        if os.path.exists(json_path):
            os.rename(json_path, temp_json_path)
        
        # Read original JSON if it exists
        json_data = None
        if os.path.exists(temp_json_path):
            with open(temp_json_path, "r") as f:
                json_data = json.load(f)
        
        # Now load from temp file and split
        img = nib.load(temp_4d_path)
        data = img.get_fdata()
        
        # Split NII volumes and duplicate JSON for each
        created_files = []
        for i in range(n_vols):
            out_name = f"{patient_id}_{seq_idx+i:04d}.nii.gz"
            out_path = os.path.join(patient_images_dir, out_name)
            try:
                vol_img = nib.Nifti1Image(data[..., i], img.affine, img.header)
                nib.save(vol_img, out_path)
                print(f"    ✓ Created: {out_name}")
                created_files.append(out_path)
                
                # Duplicate JSON for each volume with matching index
                if json_data is not None:
                    json_out_name = f"{patient_id}_{seq_idx+i:04d}.json"
                    json_out_path = os.path.join(patient_images_dir, json_out_name)
                    with open(json_out_path, "w") as f:
                        json.dump(json_data, f, indent=2)
            except Exception as e:
                print(f"    ✗ FAILED to create {out_name}: {e}")
        
        # Remove temporary 4D NII and JSON
        if len(created_files) == n_vols:
            print(f"  [DEBUG] All {n_vols} volumes created successfully. Removing temporary 4D file: {os.path.basename(temp_4d_path)}")
            os.remove(temp_4d_path)
            if os.path.exists(temp_json_path):
                os.remove(temp_json_path)
        else:
            print(f"  [WARNING] Only created {len(created_files)} of {n_vols} volumes. Keeping temporary 4D file: {os.path.basename(temp_4d_path)}")
            print(f"  [WARNING] Created files: {[os.path.basename(f) for f in created_files]}")
        
        return n_vols
        
    except Exception as e:
        print(f"  [ERROR] Failed to split 4D NIfTI: {e}")
        import traceback
        traceback.print_exc()
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

    Handles 4D baseline splitting. Trigger time files are handled at patient level.
    Returns the updated seq_idx.
    """

    out_basename = f"{patient_id}_{seq_idx:04d}"
    print(f"  [DEBUG] Processing sequence at index {seq_idx}: {os.path.basename(dicom_folder)}")
    convert_dicom_to_nifti(dicom_folder, patient_images_dir, out_name=out_basename)
    final_nii_path = os.path.join(patient_images_dir, f"{out_basename}.nii.gz")

    # Check if the pre-contrast baseline file was created
    if not os.path.exists(final_nii_path):
        print(f"  [WARNING] Expected file not created: {out_basename}.nii.gz")
        return seq_idx

    # Check if the baseline file is 4D or 3D
    img = nib.load(final_nii_path)
    is_4d = img.get_fdata().ndim == 4
    print(f"    ✓ Created: {out_basename}.nii.gz ({'4D' if is_4d else '3D'})")
    
    if is_4d:
        # dcm2niix created a 4D baseline file, need to split it
        baseline_volumes = split_4d_nifti_overwrite(
            final_nii_path, patient_images_dir, patient_id, seq_idx
        )
        if baseline_volumes > 0:
            print(f"  [DEBUG] Successfully split into {baseline_volumes} volumes, adding to mapping:")
            for i in range(baseline_volumes):
                nifti_file = os.path.join(
                    patient_images_dir,
                    f"{patient_id}_{seq_idx + i:04d}.nii.gz",
                )
                mapping.append(
                    {
                        "nifti_image": nifti_file,
                        "dicom_folder": dicom_folder,
                    }
                )
                print(f"    + Mapped: {os.path.basename(nifti_file)}")
            print(f"  [DEBUG] seq_idx updated: {seq_idx} -> {seq_idx + baseline_volumes}")
            seq_idx += baseline_volumes
        else:
            # Fallback: add 4D file as-is
            print(f"  [WARNING] Split failed, adding original 4D file as-is")
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
        print(f"  [DEBUG] Added 3D sequence to mapping, seq_idx now: {seq_idx} -> {seq_idx + 1}")
        seq_idx += 1

    return seq_idx




def _handle_multi_echo_files_at_patient_level(patient_id, patient_images_dir):
    """Remove multi-echo (_Eq_*) files from patient directory.
    
    When dcm2niix encounters multiple echo times in a DICOM folder, it creates:
    - Primary echo: patient_id_0000.nii.gz
    - Secondary echoes: patient_id_0000_Eq_1.nii.gz, patient_id_0000_Eq_2.nii.gz, etc.
    
    For DCE analysis, only the primary echo is typically needed, so this function
    removes the extra echo files (keeping the primary).
    
    Args:
        patient_id: Patient identifier
        patient_images_dir: Directory containing patient NIfTI images
    """
    # Find and remove _Eq_* files (multi-echo duplicates - typically not needed)
    echo_pattern = os.path.join(patient_images_dir, f"{patient_id}_*_Eq_*.nii.gz")
    echo_files = glob.glob(echo_pattern)
    
    if echo_files:
        print(f"  [DEBUG] Found {len(echo_files)} multi-echo file(s) - removing as extras (keeping primary echo):")
        for echo_file in echo_files:
            basename = os.path.basename(echo_file)
            print(f"    Removing: {basename}")
            os.remove(echo_file)
            # Also remove associated JSON sidecar
            json_file = echo_file.replace('.nii.gz', '.json')
            if os.path.exists(json_file):
                os.remove(json_file)


def _handle_trigger_times_at_patient_level(patient_id, patient_images_dir, seq_idx_to_dicom_folder, all_dicom_folders=None):
    """Handle trigger time files at patient level after all conversions.
    
    Scans for any _t*.nii.gz files and renames them sequentially starting from
    the next available index after existing files.
    
    Args:
        patient_id: Patient identifier
        patient_images_dir: Directory containing patient NIfTI images
        seq_idx_to_dicom_folder: Dictionary mapping original seq_idx to dicom_folder
        all_dicom_folders: List of all dicom folders involved in processing (fallback if index not found)
    """
    # Find all existing image files
    existing_files = glob.glob(os.path.join(patient_images_dir, f"{patient_id}_*.nii.gz"))
    existing_indices = []
    
    for f in existing_files:
        basename = os.path.basename(f).replace('.nii.gz', '')
        match = re.search(r'_(\d+)$', basename)
        if match:
            index = int(match.group(1))
            existing_indices.append(index)
    
    if not existing_indices:
        next_idx = 0
    else:
        next_idx = max(existing_indices) + 1
    
    # Find all trigger time files (but skip _Eq_* echo files)
    trigger_pattern = os.path.join(patient_images_dir, f"{patient_id}_????_t*.nii.gz")
    trigger_files = glob.glob(trigger_pattern)
    
    if not trigger_files:
        return []  # No trigger time files to process
    
    # Extract trigger time numbers and sort by them
    trigger_files_with_time = []
    for f in trigger_files:
        basename = os.path.basename(f).replace('.nii.gz', '')
        # Extract the original seq_idx (the 4-digit number before _t)
        match = re.search(r'_(\d{4})_t(\d+)$', basename)
        if match:
            original_seq_idx = int(match.group(1))
            trigger_time = int(match.group(2))
            trigger_files_with_time.append((trigger_time, original_seq_idx, f))
    
    if not trigger_files_with_time:
        return []
    
    # Sort by trigger time to maintain proper order
    trigger_files_with_time.sort()
    
    print(f"  Processing {len(trigger_files_with_time)} trigger time file(s) starting at index {next_idx}")
    
    # Determine fallback dicom_folder for trigger times not in mapping
    # If all conversions came from one folder, use that; otherwise use first available
    fallback_folder = "N/A"
    if all_dicom_folders:
        if len(all_dicom_folders) == 1:
            fallback_folder = all_dicom_folders[0]
        elif len(all_dicom_folders) > 0:
            fallback_folder = all_dicom_folders[0]  # Use first if multiple
    
    # Rename in order starting from next_idx and build mapping
    mapping = []
    for i, (trigger_time, original_seq_idx, old_path) in enumerate(trigger_files_with_time):
        new_seq_idx = next_idx + i
        new_name = f"{patient_id}_{new_seq_idx:04d}.nii.gz"
        new_path = os.path.join(patient_images_dir, new_name)
        os.rename(old_path, new_path)
        
        # Also rename JSON sidecar if it exists
        old_json = old_path.replace('.nii.gz', '.json')
        if os.path.exists(old_json):
            new_json = new_path.replace('.nii.gz', '.json')
            os.rename(old_json, new_json)
        
        # Get dicom_folder from the original seq_idx mapping, or use fallback
        dicom_folder = seq_idx_to_dicom_folder.get(original_seq_idx, fallback_folder)
        
        mapping.append({
            "nifti_image": new_path,
            "dicom_folder": dicom_folder,
        })
        
        print(f"    {os.path.basename(old_path)} -> {new_name}")
    
    return mapping





def process_patient_json(json_path, images_root, metadata_root, interactive=False, patient_id=None, study_date=None):
    """
    Process a single patient's filtered DICOM JSON file and convert to NIfTI.
    
    Args:
        json_path: Path to filtered DICOM JSON file
        images_root: Root directory where NIfTI images will be saved
        metadata_root: Root directory where metadata will be saved
        interactive: If True, prompt user to select sequences (not used for flat entries)
        patient_id: (Optional) Explicit patient ID. If provided with study_date, organizes output as patient_id/study_date/
        study_date: (Optional) Study date string (YYYYMMDD format). If provided, organizes output with date subdirectory
    """
    with open(json_path, "r") as f:
        data = json.load(f)
    
    json_patient_id = list(data.keys())[0]
    entries = data[json_patient_id]  # Flat list of entries
    
    # Use provided patient_id or fall back to JSON patient_id
    if patient_id is None:
        patient_id = json_patient_id
    
    # Construct image and metadata directories based on whether date is provided
    if study_date:
        # Date-based organization: root/patient_id/study_date/
        patient_images_dir = os.path.join(images_root, patient_id, study_date)
        patient_metadata_dir = os.path.join(metadata_root, patient_id, study_date)
    else:
        # Original organization: root/patient_id/
        patient_images_dir = os.path.join(images_root, patient_id)
        patient_metadata_dir = os.path.join(metadata_root, patient_id)

    if os.path.exists(patient_images_dir):
        date_suffix = f" (Study Date: {study_date})" if study_date else ""
        print(f"Patient {patient_id}{date_suffix} already processed. Skipping.")
        return

    # Create output directories
    if not os.path.exists(patient_images_dir):
        os.makedirs(patient_images_dir, exist_ok=True)
        os.makedirs(patient_metadata_dir, exist_ok=True)

    mapping = []
    seq_idx = 0
    seq_idx_to_dicom_folder = {}  # Track which dicom_folder each seq_idx came from
    all_dicom_folders = []  # Track all unique dicom folders processed
    
    print("\n"*3 + "*"*50 + "dicom2niix logs" + "*"*50)
    # Process all entries (flat list format)
    for entry in entries:
        dicom_file = entry["DicomPath"]
        dicom_folder = os.path.dirname(dicom_file)
        
        # Track all unique dicom_folders
        if dicom_folder not in all_dicom_folders:
            all_dicom_folders.append(dicom_folder)
        
        # Track the dicom_folder for this seq_idx before processing
        seq_idx_before = seq_idx
        
        # Process the sequence (4D detection is automatic)
        seq_idx = _process_single_sequence(
            dicom_folder,
            patient_id,
            seq_idx,
            patient_images_dir,
            patient_metadata_dir,
            mapping,
        )
        
        # Store mapping for all indices created by this sequence
        for i in range(seq_idx_before, seq_idx):
            seq_idx_to_dicom_folder[i] = dicom_folder
    
    # Handle multi-echo files (remove secondary echoes, keep primary)
    _handle_multi_echo_files_at_patient_level(patient_id, patient_images_dir)
    
    # Handle any trigger time files at patient level
    trigger_mapping = _handle_trigger_times_at_patient_level(patient_id, patient_images_dir, seq_idx_to_dicom_folder, all_dicom_folders)
    
    # Move all JSON sidecars to the metadata directory
    # All JSON files should now have proper indices matching their NII files
    json_pattern = os.path.join(patient_images_dir, f"{patient_id}_*.json")
    for json_file in glob.glob(json_pattern):
        dst_json = os.path.join(patient_metadata_dir, os.path.basename(json_file))
        os.rename(json_file, dst_json)
    
    # Re-read the mapping to include any renamed trigger time files
    # For now, we'll just rebuild it from the converted files
    mapping = []
    converted_niis = sorted(glob.glob(os.path.join(patient_images_dir, f"{patient_id}_*.nii.gz")))
    for nii_file in converted_niis:
        # Check if this file is in the trigger_mapping (renamed trigger times)
        found_in_trigger = False
        for trigger_entry in trigger_mapping:
            if trigger_entry["nifti_image"] == nii_file:
                mapping.append(trigger_entry)
                found_in_trigger = True
                break
        
        # If not in trigger mapping, use the dicom_folder from seq_idx_to_dicom_folder
        if not found_in_trigger:
            basename = os.path.basename(nii_file).replace('.nii.gz', '')
            match = re.search(r'_(\d+)$', basename)
            if match:
                seq_idx = int(match.group(1))
                dicom_folder = seq_idx_to_dicom_folder.get(seq_idx, "N/A")
            else:
                dicom_folder = "N/A"
            
            mapping.append({
                "nifti_image": nii_file,
                "dicom_folder": dicom_folder,
            })
    
    # Save mapping
    mapping_path = os.path.join(patient_metadata_dir, f"{patient_id}_nifti_dicom_mapping.json")
    with open(mapping_path, "w") as mf:
        json.dump(mapping, mf, indent=2)
    print(f"*"*100)
    print("\n"*3 + f"Mapping saved for {patient_id} at {mapping_path}")
