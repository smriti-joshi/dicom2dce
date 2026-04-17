"""
Stage 2: DCE sequence filtering with multi-level validation.

Filters extracted DICOM metadata to identify valid DCE-MRI sequences
using TR/TE limits, image type exclusions, scanning sequence checks,
series description matching, size consistency, and dynamic markers.
"""

import pydicom
import os
import json
import re
from difflib import SequenceMatcher

from .config import Config, natural_sort_key


class FilteringStage:
    """Stage 3: Filter DCE sequences with multi-level validation"""
    
    @staticmethod
    def load_summary(json_path):
        """Load saved summary file"""
        with open(json_path, "r") as f:
            return json.load(f)
    
    @staticmethod
    def sequence_similarity(seq_names):
        """Calculate average similarity between sequence descriptions"""
        if not seq_names:
            return 0.0
        n = len(seq_names)
        if n == 1:
            return 1.0
        
        total = 0
        count = 0
        for i in range(n):
            for j in range(i+1, n):
                sim = SequenceMatcher(None, seq_names[i], seq_names[j]).ratio()
                total += sim
                count += 1
        return total / count if count else 1.0
    
    @staticmethod
    def has_contrast_agent(dcm_path):
        """Check if DICOM file has contrast agent markers"""
        try:
            ds = pydicom.dcmread(dcm_path, stop_before_pixels=True)
            for tag in Config.get_contrast_agent_tags():
                if ds.get(tag) is not None:
                    return True
            return False
        except:
            return False
    
    @staticmethod
    def filter_step1_tr_te(metadata_list):
        """Step 1: Remove sequences with TR or TE > 15"""
        filtered = []
        for entry in metadata_list:
            tr = entry.get("RepetitionTime", "None")
            te = entry.get("EchoTime", "None")
            
            # Skip if TR or TE is "None" or unparseable
            try:
                tr_val = float(tr) if tr != "None" else float('inf')
                te_val = float(te) if te != "None" else float('inf')
                
                if tr_val <= Config.get_max_tr() and te_val <= Config.get_max_te():
                    filtered.append(entry)
            except (ValueError, TypeError):
                filtered.append(entry)  # Keep if can't parse
        
        return filtered
    
    @staticmethod
    def filter_step2_scanning_sequence(metadata_list):
        """Step 2: Remove based on scanning sequences"""
        filtered = []
        for entry in metadata_list:
            seq = str(entry.get("ScanningSequence", "")).upper()
            seq_var = str(entry.get("SequenceVariant", "")).upper()
            
            # Drop if contains "EP" (diffusion, EPI)
            if "EP" in seq:
                continue
            
            # Drop if contains "SE" but not "GR" (T2, TSE, FLAIR)
            if "SE" in seq and "GR" not in seq:
                continue
            
            filtered.append(entry)
        
        return filtered
    
    @staticmethod
    def filter_step3_image_type(metadata_list):
        """Step 3: Remove based on ImageType"""
        filtered = []
        for entry in metadata_list:
            dcm_path = entry.get("DicomPath")
            if not dcm_path or not os.path.exists(dcm_path):
                continue
            
            try:
                ds = pydicom.dcmread(dcm_path, stop_before_pixels=True)
                image_type = ds.get("ImageType", [])
                if isinstance(image_type, str):
                    image_type = image_type.split("\\")
                
                if any(tag in str(image_type).upper() for tag in Config.get_image_type_exclusions()):
                    continue
                
                filtered.append(entry)
            except Exception as e:
                print(f"Error checking ImageType for {dcm_path}: {e}")
                filtered.append(entry)
        
        return filtered
    
    @staticmethod
    def filter_step4_series_description(metadata_list):
        """Step 4: Remove based on SeriesDescription"""
        filtered = []
        for entry in metadata_list:
            desc = str(entry.get("SeriesDescription", "")).lower()
            
            # Check if any exclusion substring is in description
            if any(substr in desc for substr in Config.get_series_desc_exclusions()):
                continue
            
            filtered.append(entry)
        
        return filtered
    
    @staticmethod
    def extract_image_dimensions(dicom_path):
        """Extract image dimensions from DICOM file"""
        try:
            ds = pydicom.dcmread(dicom_path, stop_before_pixels=True)
            rows = ds.get("Rows")
            cols = ds.get("Columns")
            
            if rows and cols:
                return (int(rows), int(cols))
            return None
        except Exception:
            return None
    
    @staticmethod
    def filter_step5_size_consistency(metadata_list):
        """Step 5: Handle multiple image sizes - keep only the size group with most files"""
        if not Config.keep_largest_size_group():
            return metadata_list
        
        # Group by image dimensions
        size_groups = {}
        size_errors = []
        
        for entry in metadata_list:
            dicom_path = entry.get("DicomPath")
            if not dicom_path or not os.path.exists(dicom_path):
                size_errors.append(entry)
                continue
            
            dimensions = FilteringStage.extract_image_dimensions(dicom_path)
            
            if dimensions is None:
                size_errors.append(entry)
                continue
            
            if dimensions not in size_groups:
                size_groups[dimensions] = []
            size_groups[dimensions].append(entry)
        
        # If only one size or no valid sizes found, return as-is
        if len(size_groups) <= 1:
            return metadata_list
        
        # Find the size group with most files
        largest_group = max(size_groups.items(), key=lambda x: len(x[1]))
        
        return largest_group[1]
    
    @staticmethod
    def filter_step6_dynamic_markers(metadata_list):
        """Step 6: If any series has dynamic markers, filter out entries without them"""
        if not metadata_list:
            return metadata_list
        
        # Check if any entry has dynamic markers
        has_dynamic = []
        no_dynamic = []
        
        for entry in metadata_list:
            series_desc = str(entry.get("SeriesDescription", "")).lower()
            
            # Check for any dynamic marker
            if any(marker in series_desc for marker in Config.get_dynamic_markers()):
                has_dynamic.append(entry)
            else:
                no_dynamic.append(entry)
        
        # If we have dynamic entries, keep only those
        # If no dynamic entries, keep all
        if has_dynamic:
            return has_dynamic
        
        return metadata_list
    
    @staticmethod
    def filter_dce_sequences(metadata_list):
        """Apply all filtering steps"""
        # Step 1: Filter by TR/TE
        filtered = FilteringStage.filter_step1_tr_te(metadata_list)
        
        # Step 2: Filter by scanning sequence
        filtered = FilteringStage.filter_step2_scanning_sequence(filtered)
        
        # Step 3: Filter by image type
        filtered = FilteringStage.filter_step3_image_type(filtered)
        
        # Step 4: Filter by series description
        filtered = FilteringStage.filter_step4_series_description(filtered)
        
        # Step 5: Handle size consistency - keep largest group
        filtered = FilteringStage.filter_step5_size_consistency(filtered)
        
        # Step 6: Filter by dynamic markers
        filtered = FilteringStage.filter_step6_dynamic_markers(filtered)
        
        return filtered
    
    @staticmethod
    def get_date_key(entry):
        """Extract the date key from a metadata entry using the standard fallback chain."""
        for field in ("StudyDate", "SeriesDate", "AcquisitionDate", "ContentDate", "StudyInstanceUID", "StudyID"):
            val = entry.get(field, "None")
            if val != "None" and val:
                return val
        return "UNKNOWN_DATE"

    @staticmethod
    def group_by_date(metadata_list):
        """
        Group raw metadata entries by date only, with no filtering applied.
        Returns a dictionary: {date_string: [raw_entries_for_that_date]}

        Fallback order for date: StudyDate -> SeriesDate -> AcquisitionDate ->
        ContentDate -> StudyInstanceUID -> StudyID -> UNKNOWN_DATE
        """
        entries_by_date = {}
        for entry in metadata_list:
            date_key = FilteringStage.get_date_key(entry)
            if date_key not in entries_by_date:
                entries_by_date[date_key] = []
            entries_by_date[date_key].append(entry)
        return entries_by_date

    
    def _group_by_tr_te_impl(entries):
        """Internal implementation of TR/TE grouping. Returns flat list of entries with processing."""
        grouped = {}
        
        for entry in entries:
            tr = entry.get("RepetitionTime")
            te = entry.get("EchoTime")
            key = f"TR_{tr}_TE_{te}"
            
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(entry)
        
        # Process groups and add FLAGS to entries
        flagged_entries = []
        group_dce_status = {}  # Track which groups have DCE markers
        
        for idx, (key, entries) in enumerate(sorted(grouped.items()), 1):
            group_name = f"group{idx}"
            
            # Sort within group
            entries_sorted = sorted(
                entries,
                key=lambda x: int(x.get("AcquisitionNumber", 0)) if x.get("AcquisitionNumber") != "None" else 0
            )
            
            # Check similarity of series descriptions within group
            seq_names = [entry.get("SeriesDescription", "") for entry in entries_sorted]
            similarity = FilteringStage.sequence_similarity(seq_names)
            
            group_flags = []
            
            # Check for dynamic (DCE) markers
            has_dyn_entries = []
            has_contrast_entries = []
            
            for e in entries_sorted:
                if "dyn" in str(e.get("SeriesDescription", "")).lower():
                    has_dyn_entries.append(e)
                if FilteringStage.has_contrast_agent(e.get("DicomPath")):
                    has_contrast_entries.append(e)
            
            has_dyn = len(has_dyn_entries) > 0
            has_contrast = len(has_contrast_entries) > 0
            
            # Deduplicate DCE marked entries by comparing DicomPath
            dce_marked_paths = set()
            dce_marked_entries = []
            for e in has_dyn_entries + has_contrast_entries:
                path = e.get("DicomPath")
                if path not in dce_marked_paths:
                    dce_marked_paths.add(path)
                    dce_marked_entries.append(e)
            
            # Track whether this group has DCE markers
            group_dce_status[group_name] = (has_dyn or has_contrast)
            
            # Handle low similarity case
            if similarity < Config.get_similarity_threshold():
                if dce_marked_entries:
                    # Low similarity but has DCE markers - keep only DCE-marked sequences
                    entries_sorted = dce_marked_entries
                    group_flags.append(f"low_similarity:{similarity:.2f}_kept_dce_marked_only")
                else:
                    # Low similarity and no DCE markers - flag it
                    group_flags.append(f"low_similarity:{similarity:.2f}")
            
            # Flag if no DCE markers at all (only if similarity was acceptable)
            if not has_dyn and not has_contrast and similarity >= Config.get_similarity_threshold():
                group_flags.append("no_dyn_or_contrast_markers")
            
            # Add entries with FLAG key
            for entry in entries_sorted:
                entry_with_flag = entry.copy()
                # Don't add FLAG to JSON output - flag issues in pipeline instead
                flagged_entries.append(entry_with_flag)
        
        # Filter out entries from groups without DCE markers if any group has DCE markers
        any_has_dce = any(group_dce_status.values())
        if any_has_dce:
            # Remove entries that don't have DCE markers
            non_dce_entries = []
            filtered_entries_result = []
            
            for entry in flagged_entries:
                dcm_path = entry.get("DicomPath")
                has_dyn = "dyn" in str(entry.get("SeriesDescription", "")).lower()
                has_contrast = FilteringStage.has_contrast_agent(dcm_path)
                
                if has_dyn or has_contrast:
                    filtered_entries_result.append(entry)
            
            return filtered_entries_result
        else:
            return flagged_entries
    
    @staticmethod
    def group_by_tr_te(filtered_entries):
        """
        Legacy function for backward compatibility.
        Groups by TR/TE only (no date grouping).
        Returns a flat list of entries.
        """
        return FilteringStage._group_by_tr_te_impl(filtered_entries)
    
    def sort_entries(self, entries):
        """
        Sort entries hierarchically with intelligent edge case handling:
        1. Separate entries with valid timing data from entries with all missing values
        2. Sort entries with valid timing data
        3. Extract numeric sequences from folder names to determine order
        4. Place all-None entries at top or bottom based on detected pattern
        """
        def get_numeric_value(entry, key, is_int=False):
            """Helper to safely get numeric value (None/"None" becomes inf)"""
            val = entry.get(key)
            if val is None or val == "None":
                return float('inf')
            try:
                return int(val) if is_int else float(val)
            except (ValueError, TypeError):
                return float('inf')
        
        def has_any_valid_timing(entry):
            """Check if entry has at least one valid timing field"""
            
            acq_time = get_numeric_value(entry, "AcquisitionNumber")
            temp_pos = get_numeric_value(entry, "TemporalPositionIdentifier", is_int=True)
            trigger_time = get_numeric_value(entry, "TriggerTime")
            frame_ref_time = get_numeric_value(entry, "FrameReferenceTime")
            
            return not (acq_time == float('inf') and temp_pos == float('inf') and 
                       trigger_time == float('inf') and frame_ref_time == float('inf'))
        
        def extract_folder_name(dicom_path):
            """Extract the scan folder name from DicomPath
            e.g., from '/path/scans/9-t1_fl3d_tra_dynaVIEWS_DINAMICO_P2/resources/...'
            extract '9-t1_fl3d_tra_dynaVIEWS_DINAMICO_P2'
            """
            if not dicom_path:
                return ""
            if "/scans/" in dicom_path:
                parts = dicom_path.split("/scans/")
                if len(parts) > 1:
                    remainder = parts[1]
                    folder_name = remainder.split("/")[0]
                    return folder_name
            return ""
        
        def extract_numbers_from_folder(folder_name):
            """Extract all numbers from folder name
            e.g., '9-t1_fl3d_tra_dynaVIEWS_DINAMICO_P2' -> [9]
            e.g., '20-something_5-more' -> [20, 5]
            """
            import re
            numbers = re.findall(r'\d+', folder_name)
            return [int(n) for n in numbers]
        
        # Separate entries with valid timing from all-None entries
        valid_timing_entries = []
        none_entries = []
        
        for entry in entries:
            if has_any_valid_timing(entry):
                valid_timing_entries.append(entry)
            else:
                none_entries.append(entry)
        
        # Sort valid timing entries by hierarchical key
        def parse_acquisition_time(acq_time_str):
            """Parse AcquisitionTime (HHMMSS.ffffff) to seconds since midnight"""
            if acq_time_str is None or acq_time_str == "None":
                return float('inf')
            try:
                # Handle both string and numeric formats
                acq_time_str = str(acq_time_str).strip()
                if '.' in acq_time_str:
                    time_part = acq_time_str.split('.')[0]
                else:
                    time_part = acq_time_str
                
                if len(time_part) >= 6:
                    hours = int(time_part[0:2])
                    minutes = int(time_part[2:4])
                    seconds = int(time_part[4:6])
                    total_seconds = hours * 3600 + minutes * 60 + seconds
                    return total_seconds
            except (ValueError, TypeError, IndexError):
                pass
            return float('inf')
        
        def sort_key(entry):
            acq_time = get_numeric_value(entry, "AcquisitionTime")
            acq_num = get_numeric_value(entry, "AcquisitionNumber")
            temp_pos = get_numeric_value(entry, "TemporalPositionIdentifier", is_int=True)
            trigger_time = get_numeric_value(entry, "TriggerTime")
            frame_ref_time = get_numeric_value(entry, "FrameReferenceTime")
            return (acq_time, acq_num, temp_pos, trigger_time, frame_ref_time)
        
        sorted_valid = sorted(valid_timing_entries, key=sort_key)
        
        # Analyze folder names to determine order pattern
        if sorted_valid:
            folder_names = [extract_folder_name(entry.get("DicomPath", "")) for entry in sorted_valid]
            # Extract numbers from each folder name
            numbers_lists = [extract_numbers_from_folder(fn) for fn in folder_names]
            
            # Count violations for increasing and decreasing patterns
            violations_increasing = 0
            violations_decreasing = 0
            
            for i in range(len(numbers_lists) - 1):
                if numbers_lists[i] and numbers_lists[i + 1]:
                    if numbers_lists[i] > numbers_lists[i + 1]:
                        violations_increasing += 1
                    if numbers_lists[i] < numbers_lists[i + 1]:
                        violations_decreasing += 1
            
            # Determine the best pattern based on violations
            is_increasing = violations_increasing == 0
            is_decreasing = violations_decreasing == 0
            
            # If both have violations, choose the one with fewer violations
            if not is_increasing and not is_decreasing:
                if violations_increasing <= violations_decreasing:
                    is_increasing = True
                else:
                    is_decreasing = True
            
            # Place None entries based on detected/fixed pattern
            if is_increasing or not is_decreasing:
                # Increasing pattern: sort None entries in increasing order
                sorted_valid = sorted(
                    none_entries + sorted_valid,
                    key=lambda e: extract_numbers_from_folder(extract_folder_name(e.get("DicomPath", "")))
                )
                return sorted_valid
            else:
                # Decreasing pattern: sort None entries in decreasing order
                sorted_valid = sorted(
                    none_entries + sorted_valid,
                    key=lambda e: extract_numbers_from_folder(extract_folder_name(e.get("DicomPath", ""))),
                    reverse=True
                )
                return sorted_valid 
        else:
            # No valid timing entries, return None entries as-is
            return none_entries
    
    def save_filtered_results(self, flat_entries, patient_id, out_dir, metadata=None, flags=None, study_date=None):
        """Save flat list of filtered entries to JSON file
        
        Note: Entries are saved as-is without sorting. 
        Sort separately with sort_entries() if needed.
        
        Returns: flat_entries (list) - the entries that were saved
        """
        if not flat_entries:
            # Print series descriptions from filtered metadata if available
            series_descriptions = []
            if metadata:
                series_descriptions = [entry.get("SeriesDescription", "Unknown") for entry in metadata]
            print("======================================================================================")
            desc_str = "\n".join(series_descriptions) if series_descriptions else "No metadata available"
            date_info = f" (Study Date: {study_date})" if study_date else ""
            print(f"⚠️  No DCE files found for patient {patient_id}{date_info} - manual inspection needed")
            print(f"   Available series:\n {desc_str}")
            return []
        
        os.makedirs(out_dir, exist_ok=True)
        safe_patient_id = str(patient_id).replace('/', '_').replace('\\', '_')
        
        output_file = os.path.join(out_dir, f"{safe_patient_id}_filtered.json")
        with open(output_file, "w") as f:
            json.dump({patient_id: flat_entries}, f, indent=2)
        
        # Return the entries that were saved
        return flat_entries
