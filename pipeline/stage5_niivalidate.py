"""Stage 5: NIfTI validation — quality checks on converted volumes."""

import os
import json
import nibabel as nib
import numpy as np
from datetime import datetime
from .config import Config


def parse_acquisition_time(acq_time, trigger_time=None):
    """
    Parse AcquisitionTime or TriggerTime to seconds.
    
    Args:
        acq_time: AcquisitionTime in format HHMMSS.ffffff (string) or None
        trigger_time: TriggerTime in milliseconds (int/float) or None
        
    Returns:
        Time in seconds (float) or None if neither available
    """
    if acq_time and acq_time != "None":
        try:
            # Convert HHMMSS.ffffff to seconds
            time_str = str(acq_time).split('.')[0]
            if len(time_str) >= 6:
                hours = int(time_str[0:2])
                minutes = int(time_str[2:4])
                seconds = int(time_str[4:6])
                total_seconds = hours * 3600 + minutes * 60 + seconds
                return float(total_seconds)
        except (ValueError, IndexError, TypeError):
            pass
    
    if trigger_time and trigger_time != "None":
        try:
            # TriggerTime is in milliseconds, convert to seconds
            trigger_ms = float(trigger_time)
            return trigger_ms / 1000.0
        except (ValueError, TypeError):
            pass
    
    return None


def load_patient_niftis(patient_images_dir, patient_id):
    """
    Load all NIfTI files for a patient once.
    
    Args:
        patient_images_dir: Path to NIfTI images directory
        patient_id: Patient identifier
        
    Returns:
        Tuple of (nifti_files, images_dict)
        - nifti_files: List of sorted filenames
        - images_dict: Dict mapping filename to nibabel image object
    """
    nifti_files = sorted([f for f in os.listdir(patient_images_dir) 
                          if f.endswith('.nii.gz') and f.startswith(patient_id)])
    
    images_dict = {}
    for fname in nifti_files:
        try:
            img = nib.load(os.path.join(patient_images_dir, fname))
            images_dict[fname] = img
        except Exception as e:
            print(f"Failed to load {fname}: {str(e)}")
    
    return nifti_files, images_dict


def check_nifti_consistency(nifti_files, images_dict, patient_id):
    """
    Verify NIfTI files are complete and spatially consistent.
    
    Args:
        nifti_files: List of sorted NIfTI filenames
        images_dict: Dict mapping filename to nibabel image object (pre-loaded)
        patient_id: Patient identifier
    
    Returns: (status, issues, metrics)
    """
    issues = []
    metrics = {}
    
    if not nifti_files:
        return "ERROR", ["No NIfTI files found"], {}
    
    metrics["file_count"] = len(nifti_files)
    
    # Check filename format: patient_id_XXXX.nii.gz
    invalid_filenames = []
    expected_indices = set(range(len(nifti_files)))
    actual_indices = set()
    
    for fname in nifti_files:
        # Check if filename matches expected pattern
        expected_pattern = f"{patient_id}_"
        if not fname.startswith(expected_pattern):
            invalid_filenames.append(f"{fname} (doesn't start with {expected_pattern})")
            continue
        
        if not fname.endswith('.nii.gz'):
            invalid_filenames.append(f"{fname} (doesn't end with .nii.gz)")
            continue
        
        try:
            # Extract index from filename
            idx_str = fname[len(expected_pattern):-len('.nii.gz')]
            idx = int(idx_str)
            
            # Check if index has correct 4-digit format (e.g., 0000, 0001, etc.)
            if f"{idx:04d}" != idx_str:
                invalid_filenames.append(f"{fname} (index not 4-digit zero-padded: got '{idx_str}', expected '{idx:04d}')")
            
            actual_indices.add(idx)
        except ValueError:
            # Check if there's a suffix (non-numeric characters after index)
            if any(c.isalpha() or c == '_' for c in idx_str):
                invalid_filenames.append(f"{fname} (contains suffix/extra characters: '{idx_str}')")
            else:
                invalid_filenames.append(f"{fname} (index is not numeric: '{idx_str}')")
    
    # Report filename format issues
    if invalid_filenames:
        for invalid in invalid_filenames:
            issues.append(f"Invalid filename format: {invalid}")
    
    # Check sequential numbering (no gaps)
    missing_indices = expected_indices - actual_indices
    if missing_indices:
        issues.append(f"Missing indices: {sorted(missing_indices)}")
    
    # Check if images were successfully loaded
    if len(images_dict) != len(nifti_files):
        missing_count = len(nifti_files) - len(images_dict)
        issues.append(f"Failed to load {missing_count} NIfTI file(s)")
    
    if not images_dict:
        return "ERROR", issues, metrics
    
    # Check spatial dimensions are identical
    images_list = [(fname, images_dict[fname]) for fname in nifti_files if fname in images_dict]
    ref_shape = images_list[0][1].shape
    ref_affine = images_list[0][1].affine
    metrics["reference_shape"] = ref_shape
    
    dimension_mismatches = []
    orientation_mismatches = []
    
    for fname, img in images_list[1:]:
        if img.shape != ref_shape:
            dimension_mismatches.append(f"{fname}: {img.shape}")
        if not np.allclose(img.affine, ref_affine, atol=1e-3):
            orientation_mismatches.append(fname)
    
    if dimension_mismatches:
        issues.append(f"Shape mismatches: {dimension_mismatches}")
    if orientation_mismatches:
        issues.append(f"Orientation mismatches: {orientation_mismatches}")
    
    metrics["consistent_shapes"] = len(dimension_mismatches) == 0
    metrics["consistent_orientations"] = len(orientation_mismatches) == 0
    
    status = "OK" if not issues else "WARNING"
    return status, issues, metrics


def check_temporal_order(patient_id, filtered_entries):
    """
    Verify temporal ordering matches acquisition times from filtered entries.
    
    Args:
        patient_id: Patient identifier
        filtered_entries: List of filtered DICOM entries with AcquisitionTime/TriggerTime
    
    Returns: (status, issues, metrics)
    """
    issues = []
    metrics = {}
    
    if not filtered_entries:
        return "WARNING", ["No filtered entries provided"], {}
    
    # Extract acquisition times from filtered entries
    times = []
    times_str = []
    
    # Sort entries by TemporalPositionIdentifier (fallback to original index if not available)
    sorted_entries = sorted(enumerate(filtered_entries),
                           key=lambda item: (
                               int(item[1].get("TemporalPositionIdentifier", item[0]))
                               if item[1].get("TemporalPositionIdentifier") != "None"
                               else item[0]
                           ))
    
    # Extract times from sorted entries
    for orig_idx, entry in sorted_entries:
        acq_time = entry.get("AcquisitionTime")
        trigger_time = entry.get("TriggerTime")
        
        time_sec = parse_acquisition_time(acq_time, trigger_time)
        times.append(time_sec)
        times_str.append(f"{acq_time}" if acq_time != "None" else f"TriggerTime:{trigger_time}")
    
    metrics["times_retrieved"] = len([t for t in times if t is not None])
    metrics["times_sources"] = times_str[:5]  # Store first 5 for debugging
    
    # Check monotonically increasing
    if None in times:
        issues.append(f"Missing AcquisitionTime/TriggerTime in {times.count(None)} entry/entries")
        metrics["time_monotonicity"] = "UNKNOWN"
    elif times != sorted(times):
        issues.append("Acquisition times NOT monotonically increasing")
        metrics["time_monotonicity"] = "INCORRECT"
        metrics["times"] = times
    else:
        metrics["time_monotonicity"] = "CORRECT"
        metrics["times"] = times
        if len(times) > 1:
            time_gaps = [times[i+1] - times[i] for i in range(len(times)-1)]
            metrics["time_gaps_sec"] = time_gaps
            metrics["mean_gap"] = np.mean(time_gaps)
            metrics["gap_consistency"] = np.std(time_gaps) / np.mean(time_gaps) if np.mean(time_gaps) > 0 else 0
    
    status = "OK" if not issues else "WARNING"
    return status, issues, metrics


def check_signal_progression(nifti_files, images_dict, patient_id):
    """
    Check signal intensity progression pattern (pre-contrast baseline → peak → washout).
    
    Args:
        nifti_files: List of sorted NIfTI filenames
        images_dict: Dict mapping filename to nibabel image object (pre-loaded)
        patient_id: Patient identifier
    
    Returns: (status, issues, metrics)
    """
    issues = []
    metrics = {}
    
    min_temporal = Config.get_min_temporal_positions()
    if len(nifti_files) < min_temporal:
        return "WARNING", [f"Less than {min_temporal} volumes - cannot assess progression"], {"file_count": len(nifti_files)}
    
    # Calculate mean intensities from pre-loaded images
    mean_intensities = []
    max_intensities = []
    
    for fname in nifti_files:
        try:
            img = images_dict[fname]
            data = img.get_fdata()
            
            # Calculate mean excluding background (assume background is 0 or very low)
            mask = data > np.percentile(data, 5)  # Use 5th percentile as threshold
            if np.sum(mask) > 0:
                mean_val = np.mean(data[mask])
                max_val = np.max(data[mask])
            else:
                mean_val = np.mean(data)
                max_val = np.max(data)
            
            mean_intensities.append(mean_val)
            max_intensities.append(max_val)
        except Exception as e:
            issues.append(f"Failed to process {fname}: {str(e)}")
            return "ERROR", issues, metrics
    
    metrics["mean_intensities"] = mean_intensities
    metrics["max_intensities"] = max_intensities
    metrics["baseline_intensity"] = mean_intensities[0]
    metrics["peak_intensity"] = max(mean_intensities)
    metrics["peak_index"] = mean_intensities.index(max(mean_intensities))
    
    # Check pre-contrast baseline (first volume should be low)
    baseline = mean_intensities[0]
    overall_min = min(mean_intensities)
    
    if baseline > overall_min * 1.2:  # Allow 20% tolerance
        issues.append(f"First volume NOT baseline (intensity {baseline:.0f} vs min {overall_min:.0f})")
    
    # Check contrast enhancement (should be significant)
    enhancement_ratio = max(mean_intensities) / baseline if baseline > 0 else 0
    metrics["enhancement_ratio"] = enhancement_ratio
    
    if enhancement_ratio < 1.1:
        issues.append(f"Minimal contrast enhancement (ratio {enhancement_ratio:.2f})")
    elif enhancement_ratio < 1.3:
        issues.append(f"Weak contrast enhancement (ratio {enhancement_ratio:.2f})")
    
    # Check peak timing (should occur in middle/later volumes, not first)
    peak_idx = metrics["peak_index"]
    early_threshold = len(nifti_files) // 4
    
    if peak_idx < early_threshold:
        issues.append(f"Peak too early (volume {peak_idx+1} of {len(nifti_files)})")
    
    status = "OK" if not issues else "WARNING"
    return status, issues, metrics


def check_volume_integrity(nifti_files, images_dict, patient_id):
    """
    Check individual volume integrity (no NaNs, no extreme values).
    
    Args:
        nifti_files: List of sorted NIfTI filenames
        images_dict: Dict mapping filename to nibabel image object (pre-loaded)
        patient_id: Patient identifier
    
    Returns: (status, issues, metrics)
    """
    issues = []
    metrics = {}
    
    problematic_volumes = []
    
    for fname in nifti_files:
        try:
            img = images_dict[fname]
            data = img.get_fdata()
            
            # Check for NaN values
            if np.isnan(data).any():
                problematic_volumes.append((fname, "Contains NaN values"))
                issues.append(f"{fname}: Contains NaN values")
            
            # Check for inf values
            if np.isinf(data).any():
                problematic_volumes.append((fname, "Contains Inf values"))
                issues.append(f"{fname}: Contains Inf values")
            
            # Check for extreme outliers (more than 3 std devs from mean)
            mask = data > np.percentile(data, 5)
            if np.sum(mask) > 0:
                masked_data = data[mask]
                mean = np.mean(masked_data)
                std = np.std(masked_data)
                outliers = np.sum(np.abs(masked_data - mean) > 3 * std) / len(masked_data)
                
                if outliers > 0.05:  # More than 5% outliers
                    problematic_volumes.append((fname, f"High outlier density: {outliers*100:.1f}%"))
        
        except Exception as e:
            issues.append(f"{fname}: Error reading - {str(e)}")
    
    metrics["problematic_volumes"] = problematic_volumes
    metrics["integrity_ok"] = len(problematic_volumes) == 0
    
    status = "OK" if len(problematic_volumes) == 0 else "WARNING"
    return status, issues, metrics


def validate_patient_nifti(patient_images_dir, patient_id, filtered_entries):
    """
    Comprehensive NIfTI validation for a patient.
    
    Args:
        patient_images_dir: Path to NIfTI images directory
        patient_id: Patient identifier
        filtered_entries: List of filtered DICOM entries with AcquisitionTime/TriggerTime
    
    Returns: validation_result dict
    """
    result = {
        "patient_id": patient_id,
        "consistency": {},
        "temporal_order": {},
        "signal_progression": {},
        "overall_status": "OK",
        "all_issues": []
    }
    
    # Load all NIfTI files once
    nifti_files, images_dict = load_patient_niftis(patient_images_dir, patient_id)
    
    # Run all checks with pre-loaded images
    cons_status, cons_issues, cons_metrics = check_nifti_consistency(nifti_files, images_dict, patient_id)
    result["consistency"]["status"] = cons_status
    result["consistency"]["issues"] = cons_issues
    result["consistency"]["metrics"] = cons_metrics
    result["all_issues"].extend(cons_issues)
    
    temp_status, temp_issues, temp_metrics = check_temporal_order(patient_id, filtered_entries)
    result["temporal_order"]["status"] = temp_status
    result["temporal_order"]["issues"] = temp_issues
    result["temporal_order"]["metrics"] = temp_metrics
    result["all_issues"].extend(temp_issues)
    
    sig_status, sig_issues, sig_metrics = check_signal_progression(nifti_files, images_dict, patient_id)
    result["signal_progression"]["status"] = sig_status
    result["signal_progression"]["issues"] = sig_issues
    result["signal_progression"]["metrics"] = sig_metrics
    result["all_issues"].extend(sig_issues)
    
    # Determine overall status
    statuses = [cons_status, temp_status, sig_status]  # vol_status is commented out
    if "ERROR" in statuses:
        result["overall_status"] = "ERROR"
    elif "WARNING" in statuses:
        result["overall_status"] = "WARNING"
    else:
        result["overall_status"] = "OK"
    
    return result
