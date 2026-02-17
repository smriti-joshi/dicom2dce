import pydicom
import os
import json
from tqdm import tqdm
import numpy as np
import re
from difflib import SequenceMatcher


def natural_sort_key(s):
    """
    Returns a key that allows for natural sorting (e.g., '2' before '10').
    """
    return [int(text) if text.isdigit() else text.lower()
            for text in re.split('([0-9]+)', s)]


class FilterConfig:
    """Configuration for DCE filtering"""
    MAX_TR = 15
    MAX_TE = 15
    IMAGE_TYPE_EXCLUSIONS = ["DERIVED", "SECONDARY", "SCREEN SAVE", "LOCALIZER", "SCOUT", "PROJECTION IMAGE", "MONTAGE", "MPR", "SUBTRACT"]
    SERIES_DESC_EXCLUSIONS = ["t2", "adc", "dwi", "sdyn", "loc", "sub", "survey", "rec", 
                              "sustraccion", "test", "wi", "wo", "pei",    
                              "scout", "pos", "ref", "cal", "shimming", 
                              "mip", "mpr", "map", "normalized", "nd"]   
    SIMILARITY_THRESHOLD = 0.8
    CONTRAST_AGENT_TAGS = ["ContrastBolusAgent", "ContrastBolusStartTime", "ContrastBolusVolume"]
    # Dynamic/temporal sequence markers - if any series has these, filter out the rest
    DYNAMIC_MARKERS = ["dyn", "din", "lava", "thrive", "vibe"]
    # When multiple image sizes exist, keep the one with most files
    KEEP_LARGEST_SIZE_GROUP = True


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
            for tag in FilterConfig.CONTRAST_AGENT_TAGS:
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
                
                if tr_val <= FilterConfig.MAX_TR and te_val <= FilterConfig.MAX_TE:
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
                
                if any(tag in str(image_type).upper() for tag in FilterConfig.IMAGE_TYPE_EXCLUSIONS):
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
            if any(substr in desc for substr in FilterConfig.SERIES_DESC_EXCLUSIONS):
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
        if not FilterConfig.KEEP_LARGEST_SIZE_GROUP:
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
            if any(marker in series_desc for marker in FilterConfig.DYNAMIC_MARKERS):
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
    def group_by_tr_te(filtered_entries):
        """Group filtered entries by (TR, TE) pairs, flag inconsistencies, and flatten"""
        grouped = {}
        
        for entry in filtered_entries:
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
            if similarity < FilterConfig.SIMILARITY_THRESHOLD:
                if dce_marked_entries:
                    # Low similarity but has DCE markers - keep only DCE-marked sequences
                    entries_sorted = dce_marked_entries
                    group_flags.append(f"low_similarity:{similarity:.2f}_kept_dce_marked_only")
                else:
                    # Low similarity and no DCE markers - flag it
                    group_flags.append(f"low_similarity:{similarity:.2f}")
            
            # Flag if no DCE markers at all (only if similarity was acceptable)
            if not has_dyn and not has_contrast and similarity >= FilterConfig.SIMILARITY_THRESHOLD:
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
        def sort_key(entry):
            acq_time = get_numeric_value(entry, "AcquisitionNumber")
            temp_pos = get_numeric_value(entry, "TemporalPositionIdentifier", is_int=True)
            trigger_time = get_numeric_value(entry, "TriggerTime")
            frame_ref_time = get_numeric_value(entry, "FrameReferenceTime")
            return (acq_time, temp_pos, trigger_time, frame_ref_time)
        
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
    
    def save_filtered_results(self, flat_entries, patient_id, out_dir, metadata=None, flags=None):
        """Save flat list of filtered entries with FLAG key to each entry"""
        if not flat_entries:
            # Print series descriptions from filtered metadata if available
            series_descriptions = []
            if metadata:
                series_descriptions = [entry.get("SeriesDescription", "Unknown") for entry in metadata]
            print("======================================================================================")
            desc_str = "\n".join(series_descriptions) if series_descriptions else "No metadata available"
            print(f"⚠️  No DCE files found for patient {patient_id} - manual inspection needed")
            print(f"   Available series:\n {desc_str}")
            return None
        
        # Sort entries before saving
        sorted_entries = self.sort_entries(flat_entries)
        
        os.makedirs(out_dir, exist_ok=True)
        safe_patient_id = str(patient_id).replace('/', '_').replace('\\', '_')
        
        output_file = os.path.join(out_dir, f"{safe_patient_id}_filtered.json")
        with open(output_file, "w") as f:
            json.dump({patient_id: sorted_entries}, f, indent=2)
        
        return output_file


class ConsistencyChecker:
    """Check consistency of image dimensions and file counts across filtered DICOM folders"""
    
    @staticmethod
    def extract_image_info(dicom_path):
        """Extract image dimensions and metadata from DICOM file"""
        try:
            ds = pydicom.dcmread(dicom_path, stop_before_pixels=True)
            
            # Get pixel dimensions
            rows = ds.get("Rows", None)
            cols = ds.get("Columns", None)
            
            # Get number of frames if multi-frame
            frames = ds.get("NumberOfFrames", 1)
            try:
                frames = int(frames)
            except (ValueError, TypeError):
                frames = 1
            
            return {
                "rows": rows,
                "columns": cols,
                "frames": frames,
                "dimensions": f"{rows}x{cols}x{frames}" if rows and cols else "Unknown"
            }
        except Exception as e:
            return {
                "rows": None,
                "columns": None,
                "frames": None,
                "dimensions": f"Error: {str(e)}"
            }
    
    @staticmethod
    def group_by_series(filtered_entries):
        """Group filtered entries by SeriesInstanceUID"""
        grouped = {}
        
        for entry in filtered_entries:
            series_uid = entry.get("SeriesInstanceUID", "Unknown")
            series_desc = entry.get("SeriesDescription", "Unknown")
            
            if series_uid not in grouped:
                grouped[series_uid] = {
                    "series_description": series_desc,
                    "entries": []
                }
            
            grouped[series_uid]["entries"].append(entry)
        
        return grouped
    
    @staticmethod
    def check_series_consistency(series_data):
        """Check consistency within a series: dimensions and file count"""
        entries = series_data["entries"]
        dimensions_map = {}
        issues = []
        
        # Extract dimensions for each file
        for entry in entries:
            dicom_path = entry.get("DicomPath")
            if not dicom_path or not os.path.exists(dicom_path):
                issues.append(f"File not found: {dicom_path}")
                continue
            
            info = ConsistencyChecker.extract_image_info(dicom_path)
            dim_key = info["dimensions"]
            
            if dim_key not in dimensions_map:
                dimensions_map[dim_key] = []
            dimensions_map[dim_key].append({
                "path": dicom_path,
                "info": info
            })
        
        # Check for dimension inconsistencies within series
        consistency_stats = {
            "total_files": len(entries),
            "dimensions_found": list(dimensions_map.keys()),
            "files_by_dimension": {dim: len(files) for dim, files in dimensions_map.items()},
            "is_consistent": len(dimensions_map) <= 1,
            "issues": issues
        }
        
        # Flag if multiple different dimensions exist
        if len(dimensions_map) > 1:
            dim_summary = ", ".join([f"{dim}({count}files)" for dim, count in consistency_stats["files_by_dimension"].items()])
            consistency_stats["issues"].append(f"Inconsistent dimensions within series: {dim_summary}")
        
        return consistency_stats
    
    @staticmethod
    def check_patient_consistency(filtered_entries, patient_id):
        """Check consistency across all series for a patient"""
        grouped = ConsistencyChecker.group_by_series(filtered_entries)
        
        patient_results = {
            "patient_id": patient_id,
            "total_series": len(grouped),
            "total_files": len(filtered_entries),
            "series_consistency": {},
            "overall_issues": [],
            "flagged": False
        }
        
        # Check each series
        all_consistent = True
        dimensions_across_series = {}
        
        for series_uid, series_data in grouped.items():
            consistency = ConsistencyChecker.check_series_consistency(series_data)
            patient_results["series_consistency"][series_uid] = {
                "series_description": series_data["series_description"],
                "consistency_check": consistency
            }
            
            if not consistency["is_consistent"]:
                all_consistent = False
            
            # Track dimensions across different series
            for dim in consistency["dimensions_found"]:
                if dim not in dimensions_across_series:
                    dimensions_across_series[dim] = []
                dimensions_across_series[dim].append(series_uid)
        
        # Check for cross-series dimension inconsistencies
        if len(dimensions_across_series) > 1:
            all_consistent = False
            dim_summary = ", ".join([f"{dim}({series_count}series)" for dim, series_count in 
                                    [(d, len(s)) for d, s in dimensions_across_series.items()]])
            patient_results["overall_issues"].append(f"Inconsistent dimensions across series: {dim_summary}")
        
        # Check if file counts are significantly different
        file_counts = [len(series_data["entries"]) for series_data in grouped.values()]
        if file_counts and len(set(file_counts)) > 1:
            all_consistent = False
            count_summary = ", ".join([f"{series_uid}:{len(grouped[series_uid]['entries'])}files" 
                                      for series_uid in grouped.keys()])
            patient_results["overall_issues"].append(f"Inconsistent file counts across series: {count_summary}")
        
        patient_results["flagged"] = not all_consistent
        
        return patient_results
    
    @staticmethod
    def save_consistency_report(patient_results, out_dir):
        """Save consistency check report"""
        os.makedirs(out_dir, exist_ok=True)
        safe_patient_id = str(patient_results["patient_id"]).replace('/', '_').replace('\\', '_')
        
        output_file = os.path.join(out_dir, f"{safe_patient_id}_consistency_check.json")
        with open(output_file, "w") as f:
            json.dump(patient_results, f, indent=2)
        
        # Print summary
        if patient_results["flagged"]:
            print(f"\n⚠️  FLAGGED - {patient_results['patient_id']}")
            print(f"   Total series: {patient_results['total_series']}")
            print(f"   Total files: {patient_results['total_files']}")
            for issue in patient_results["overall_issues"]:
                print(f"   ❌ {issue}")
        else:
            print(f"\n✓ CONSISTENT - {patient_results['patient_id']}")
            print(f"   Total series: {patient_results['total_series']}")
            print(f"   Total files: {patient_results['total_files']}")
        
        return output_file




