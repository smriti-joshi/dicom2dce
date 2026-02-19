"""
Consistency checker for filtered DICOM entries.
Integrated into the pipeline to flag issues after filtering.
"""

import pydicom
import os
from collections import defaultdict
from difflib import SequenceMatcher
from dce_filter import FilterConfig


class VisualChecks:
    """Consistency checks for filtered DICOM entries"""
    
    @staticmethod
    def extract_dicom_metadata(dicom_path):
        """Extract key metadata from DICOM file"""
        try:
            ds = pydicom.dcmread(dicom_path, stop_before_pixels=True)
            
            metadata = {
                "DicomPath": dicom_path,
                "SeriesDescription": str(ds.get("SeriesDescription", "N/A")),
                "SeriesInstanceUID": str(ds.get("SeriesInstanceUID", "N/A")),
                "Rows": int(ds.get("Rows", -1)),
                "Columns": int(ds.get("Columns", -1)),
                "RepetitionTime": float(ds.get("RepetitionTime", -1)) if ds.get("RepetitionTime") else None,
                "EchoTime": float(ds.get("EchoTime", -1)) if ds.get("EchoTime") else None,
                "FlipAngle": float(ds.get("FlipAngle", -1)) if ds.get("FlipAngle") else None,
                "AcquisitionNumber": int(ds.get("AcquisitionNumber", -1)) if ds.get("AcquisitionNumber") else None,
                "TemporalPositionIdentifier": int(ds.get("TemporalPositionIdentifier", -1)) if ds.get("TemporalPositionIdentifier") else None,
                "NumberOfTemporalPositions": int(ds.get("NumberOfTemporalPositions", -1)) if ds.get("NumberOfTemporalPositions") else None,
                "ImageType": list(ds.get("ImageType", [])),
                "ScanningSequence": str(ds.get("ScanningSequence", "N/A")),
                "SequenceVariant": str(ds.get("SequenceVariant", "N/A")),
            }
            
            return metadata
        except Exception:
            return None
    
    @staticmethod
    def get_folder_from_dicom_path(dicom_path):
        """Extract the DICOM folder path from file path"""
        if "/scans/" not in dicom_path:
            return None
        
        parts = dicom_path.split("/scans/")
        if len(parts) < 2:
            return None
        
        exp_path = parts[0]
        scan_remainder = parts[1]
        
        scan_parts = scan_remainder.split("/")
        if not scan_parts:
            return None
        
        scan_folder = scan_parts[0]
        
        return os.path.join(exp_path, "scans", scan_folder)
    
    @staticmethod
    def extract_folder_name(dicom_path):
        """Extract just the folder name (without path)"""
        if "/scans/" not in dicom_path:
            return ""
        
        parts = dicom_path.split("/scans/")
        if len(parts) < 2:
            return ""
        
        scan_remainder = parts[1]
        folder_name = scan_remainder.split("/")[0]
        
        return folder_name
    
    @staticmethod
    def calculate_name_similarity(name1, name2):
        """Calculate similarity between two folder names"""
        return SequenceMatcher(None, name1.lower(), name2.lower()).ratio()
    
    @staticmethod
    def check_folder_name_similarity(filtered_entries, similarity_threshold=0.9):
        """Check if all folder names are similar (>= similarity_threshold)"""
        if not filtered_entries or len(filtered_entries) <= 1:
            return True, []
        
        folder_names = []
        for entry in filtered_entries:
            dicom_path = entry.get("DicomPath")
            if dicom_path:
                folder_name = VisualChecks.extract_folder_name(dicom_path)
                if folder_name:
                    folder_names.append(folder_name)
        
        if not folder_names or len(folder_names) <= 1:
            return True, []
        
        # Calculate average similarity to first folder name (as reference)
        reference = folder_names[0]
        similarities = []
        
        for name in folder_names[1:]:
            sim = VisualChecks.calculate_name_similarity(reference, name)
            similarities.append(sim)
        
        # Check if all similarities are above threshold
        low_similarity_pairs = []
        for i, sim in enumerate(similarities):
            if sim < similarity_threshold:
                low_similarity_pairs.append({
                    "folder1": reference,
                    "folder2": folder_names[i + 1],
                    "similarity": f"{sim:.2%}"
                })
        
        is_consistent = len(low_similarity_pairs) == 0
        
        return is_consistent, low_similarity_pairs
    
    @staticmethod
    def get_all_dicoms_in_folder(folder_path):
        """Get all DICOM files in a folder"""
        if not os.path.exists(folder_path):
            return []
        
        dicom_files = []
        
        for root, dirs, files in os.walk(folder_path):
            for file in files:
                file_path = os.path.join(root, file)
                try:
                    ds = pydicom.dcmread(file_path, stop_before_pixels=True)
                    dicom_files.append(file_path)
                except Exception:
                    pass
        
        return dicom_files
    
    @staticmethod
    def check_consistency(filtered_entries, patient_id):
        """
        Check consistency of filtered entries.
        
        Returns:
            tuple: (status, flags_list, details_dict)
            - status: 'OK' or 'FLAGGED'
            - flags_list: List of flag strings
            - details_dict: Additional details for logging
        """
        flags = []
        details = {
            "patient_id": patient_id,
            "entry_count": 0,
            "flags": []
        }
        
        # Handle None or empty entries
        if filtered_entries is None or not isinstance(filtered_entries, list):
            flags.append("NO_FILTERED_ENTRIES")
            return "FLAGGED", flags, details
        
        if len(filtered_entries) == 0:
            flags.append("EMPTY_FILTERED_ENTRIES")
            return "FLAGGED", flags, details
        
        # Update details with entry count
        details["entry_count"] = len(filtered_entries)
        
        # Extract folder names from all entries
        folder_names = []
        for entry in filtered_entries:
            dicom_path = entry.get("DicomPath")
            if dicom_path:
                folder_name = VisualChecks.extract_folder_name(dicom_path)
                if folder_name and folder_name not in folder_names:
                    folder_names.append(folder_name)
        details["folder_names"] = folder_names
        
        # Check folder name similarity across all cases (applies to all entry counts)
        is_similar, low_similarity_pairs = VisualChecks.check_folder_name_similarity(filtered_entries, similarity_threshold=FilterConfig.get_folder_name_similarity_threshold())
        if not is_similar:
            flags.append("LOW_FOLDER_NAME_SIMILARITY")
            details["low_similarity_pairs"] = low_similarity_pairs
        
        # Case 1: More than 3 entries
        if len(filtered_entries) > 3:
            # Check if slices per DICOM folder are equal
            # Just count .dcm files, don't load metadata
            folder_slice_counts = {}
            
            for entry in filtered_entries:
                dicom_path = entry.get("DicomPath")
                folder_path = VisualChecks.get_folder_from_dicom_path(dicom_path)
                
                if not folder_path:
                    continue
                
                # Count .dcm files in this folder (no metadata loading)
                if folder_path not in folder_slice_counts:
                    dcm_count = 0
                    for root, dirs, files in os.walk(folder_path):
                        dcm_count += sum(1 for f in files if f.lower().endswith('.dcm'))
                    folder_slice_counts[folder_path] = dcm_count
            
            min_slice_count = min(folder_slice_counts.values()) if folder_slice_counts else 0
            if min_slice_count > 0 and min_slice_count < FilterConfig.get_min_slice_count():
                flags.append(f"LOW_SLICE_COUNT_{min_slice_count}")
            # Check if all folders have equal slice counts
            if folder_slice_counts:
                slice_counts = list(folder_slice_counts.values())
                if len(set(slice_counts)) > 1:
                    flags.append("UNEQUAL_SLICES_ACROSS_FOLDERS")
                    details["folder_slice_counts"] = folder_slice_counts
        
        # Case 2: Exactly 1 entry
        elif len(filtered_entries) == 1:
            entry = filtered_entries[0]
            dicom_path = entry.get("DicomPath")
            folder_path = VisualChecks.get_folder_from_dicom_path(dicom_path)
            
            if folder_path:
                # Get all DICOMs in folder
                all_dicoms = VisualChecks.get_all_dicoms_in_folder(folder_path)
                
                # Extract metadata
                all_metadata = []
                for dcm_path in all_dicoms:
                    metadata = VisualChecks.extract_dicom_metadata(dcm_path)
                    if metadata:
                        all_metadata.append(metadata)
                
                # Group by TemporalPositionIdentifier
                temp_groups = defaultdict(list)
                missing_temp_id = []
                
                for metadata in all_metadata:
                    temp_id = metadata.get("TemporalPositionIdentifier")
                    
                    if temp_id is None or temp_id == -1:
                        missing_temp_id.append(metadata)
                    else:
                        temp_groups[temp_id].append(metadata)
                
                # Flag if TemporalPositionIdentifier is missing
                if missing_temp_id:
                    flags.append(f"MISSING_TEMPORAL_ID_{len(missing_temp_id)}_SLICES")
                
                # Check if all temporal groups have equal slices
                slice_counts = [len(slices) for slices in temp_groups.values()]
                if len(set(slice_counts)) > 1:
                    flags.append("UNEQUAL_SLICES_PER_TEMPORAL_POS")
                    details["slices_per_temporal"] = {k: len(temp_groups[k]) for k in sorted(temp_groups.keys())}
                
                # Check if slices per temporal position < 20
                min_slices = min(slice_counts) if slice_counts else 0
                if min_slices > 0 and min_slices < 20:
                    flags.append(f"LOW_SLICE_COUNT_{min_slices}")
                
                # Check if less than minimum temporal positions (phases too few)
                if len(temp_groups) < FilterConfig.get_min_temporal_positions():
                    flags.append("PHASES_TOO_FEW")
                
                details["temporal_positions"] = len(temp_groups)
                details["total_dicoms"] = len(all_metadata)
        
        # Case 3: 2 entries
        elif len(filtered_entries) == 2:
            flags.append("UNEXPECTED_TWO_SEQUENCES")
        
        # Case 4: 3 entries
        elif len(filtered_entries) == 3:
            flags.append("UNEXPECTED_THREE_SEQUENCES")
        
        # Determine final status
        status = "FLAGGED" if flags else "OK"
        details["flags"] = flags
        
        return status, flags, details
