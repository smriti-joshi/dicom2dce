"""
Interactive review tool for flagged cases from the dicom2dce pipeline.

Reads the processing report CSV to identify patients that failed automated
processing, displays detailed diagnostic information, and allows manual
sequence selection for NIfTI conversion.

Usage:
    python -m dicom2dce.manual_review
    python -m dicom2dce.manual_review --center kauno
"""

import os
import json
import csv
import argparse
import shutil
from pathlib import Path
from dicom2dce.pipeline.stage2_filter import FilteringStage
from dicom2dce.pipeline.stage4_niiconvert import process_patient_json
from dicom2dce.pipeline.stage5_niivalidate import validate_patient_nifti
from dicom2dce.pipeline.stage6_report import flatten_validation_result
from dicom2dce.pipeline.config import Config


class FlaggedCaseProcessor:
    """Process flagged cases with user interaction"""
    
    def __init__(self, center, results_dir=None):
        """
        Initialize the processor.
        
        Args:
            center: Center name (e.g., 'kauno', 'hcb'). Uses Config if not specified.
            results_dir: Root results directory (uses Config if not specified)
        """
        # Load Config if not already loaded
        if not results_dir:
            Config.load()
            results_dir = Config.get_results_dir()
        
        self.center = center
        self.center_lower = center.lower()
        self.results_dir = results_dir
        self.center_results = os.path.join(results_dir, self.center_lower)
        
        # Subdirectories
        self.csv_dir = os.path.join(self.center_results)
        self.per_patient_csv_dir = os.path.join(
            self.center_results, "intermediate_results", "per_patient_validation_csvs"
        )
        self.filtered_json_dir = os.path.join(
            self.center_results, "intermediate_results", "filtered_dicom_files"
        )
        self.nifti_images_root = os.path.join(self.center_results, "dce", "images")
        self.nifti_metadata_root = os.path.join(self.center_results, "dce", "dicom_metadata")
        
        # Ensure paths exist
        os.makedirs(self.nifti_images_root, exist_ok=True)
        os.makedirs(self.nifti_metadata_root, exist_ok=True)
        os.makedirs(self.per_patient_csv_dir, exist_ok=True)
    
    def find_csv_report(self):
        """Find the processing report CSV file."""
        csv_pattern = f"processing_report_{self.center_lower}.csv"
        csv_path = os.path.join(self.csv_dir, csv_pattern)
        
        if os.path.exists(csv_path):
            return csv_path
        
        # Fall back to searching for any processing_report CSV
        for fname in os.listdir(self.csv_dir):
            if fname.startswith("processing_report_") and fname.endswith(".csv"):
                return os.path.join(self.csv_dir, fname)
        
        return None
    
    def load_flagged_cases(self):
        """Load flagged cases from CSV."""
        csv_path = self.find_csv_report()
        
        if not csv_path:
            print(f"✗ No processing report found in {self.csv_dir}")
            return []
        
        print(f"📄 Reading CSV report: {csv_path}")
        
        flagged_cases = []
        
        try:
            with open(csv_path, 'r', newline='') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    status = row.get('dicom_status', '')
                    nifti_status = row.get('nifti_conversion', '')
                    patient_id = row.get('patient_id', '')
                    study_date = row.get('study_date', '')  # New column for date-based organization
                    
                    # Flagged if not 'OK' and patient has entries
                    if status and status != 'OK' and status != 'MANUALLY_RUN' and patient_id:
                        flagged_cases.append({
                            # DICOM extraction and filtering
                            'patient_id': patient_id,
                            'study_date': study_date,
                            'dicom_status': status,
                            'entry_count': row.get('entry_count', ''),
                            'dicom_flags': row.get('dicom_flags', ''),
                            # Consistency check details
                            'consistency_temporal_positions': row.get('consistency_temporal_positions', ''),
                            'consistency_total_dicoms': row.get('consistency_total_dicoms', ''),
                            'consistency_folder_names': row.get('consistency_folder_names', ''),
                            'consistency_slices_per_temporal': row.get('consistency_slices_per_temporal', ''),
                            'consistency_folder_slice_counts': row.get('consistency_folder_slice_counts', ''),
                            'consistency_low_similarity_pairs': row.get('consistency_low_similarity_pairs', ''),
                            # NIfTI conversion
                            'nifti_conversion': row.get('nifti_conversion', ''),
                            # NIfTI validation - overall
                            'nifti_overall_status': row.get('nifti_overall_status', ''),
                            # NIfTI validation - consistency check
                            'val_consistency_status': row.get('val_consistency_status', ''),
                            'val_consistency_issues': row.get('val_consistency_issues', ''),
                            'val_file_count': row.get('val_file_count', ''),
                            # NIfTI validation - temporal order check
                            'val_temporal_status': row.get('val_temporal_status', ''),
                            'val_temporal_issues': row.get('val_temporal_issues', ''),
                            'val_time_gaps': row.get('val_time_gaps', ''),
                            # NIfTI validation - signal progression check
                            'val_signal_status': row.get('val_signal_status', ''),
                            'val_signal_issues': row.get('val_signal_issues', ''),
                            'val_enhancement_ratio': row.get('val_enhancement_ratio', ''),
                            'val_peak_index': row.get('val_peak_index', ''),
                        })
        except Exception as e:
            print(f"✗ Error reading CSV: {e}")
            return []
        
        return flagged_cases
    
    def _try_parse_json(self, data):
        """Try to parse JSON string, return parsed data or original string."""
        if isinstance(data, str):
            try:
                return json.loads(data)
            except:
                pass
        return data
    
    def _format_value(self, value, indent=4):
        """Format a value nicely for display."""
        value = self._try_parse_json(value)
        
        if isinstance(value, dict):
            if not value:
                return "{}"
            lines = ["{"]
            for k, v in value.items():
                lines.append(f"{' ' * (indent + 2)}{k}: {v}")
            lines.append(f"{' ' * indent}" + "}")
            return "\n".join(lines)
        
        elif isinstance(value, list):
            if not value:
                return "[]"
            lines = ["["]
            for item in value:
                if isinstance(item, dict):
                    lines.append(f"{' ' * (indent + 2)}{item}")
                else:
                    lines.append(f"{' ' * (indent + 2)}- {item}")
            lines.append(f"{' ' * indent}]")
            return "\n".join(lines)
        
        else:
            return str(value) if value else ""
    
    def update_csv_with_results(self, patient_id, study_date, validation_result):
        """Update CSV with manually processed results."""
        csv_path = self.find_csv_report()
        
        if not csv_path:
            print(f"  ⚠️  Could not find CSV to update")
            return False
        
        try:
            # Read all rows
            rows = []
            with open(csv_path, 'r', newline='') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    rows.append(row)
            
            # Find and update the patient's row (match both patient_id and study_date if provided)
            updated = False
            for row in rows:
                if row.get('patient_id') == patient_id:
                    # For multi-date cases, also match study_date
                    if study_date and row.get('study_date') != study_date:
                        continue
                    
                    # Update status and validation results
                    row['dicom_status'] = 'MANUALLY_RUN'
                    row['nifti_conversion'] = 'SUCCESS'
                    row['nifti_overall_status'] = validation_result.get('overall_status', '')
                    
                    # Add flattened validation results
                    flattened = flatten_validation_result(validation_result)
                    row.update(flattened)
                    
                    updated = True
                    break
            
            if not updated:
                print(f"  ⚠️  Could not find patient {patient_id} in CSV")
                return False
            
            # Write back to CSV
            if rows and rows[0]:
                fieldnames = list(rows[0].keys())
            else:
                fieldnames = []
            
            with open(csv_path, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            
            print(f"  ✓ Updated CSV with results for {patient_id}")
            return True
            
        except Exception as e:
            print(f"  ⚠️  Error updating CSV: {e}")
            return False
    
    def update_patient_csv_with_results(self, patient_id, study_date=None, validation_result=None):
        """Update individual per-patient CSV with manually processed results."""
        safe_patient_id = str(patient_id).replace("/", "_").replace("\\", "_")
        patient_csv_path = os.path.join(self.per_patient_csv_dir, f"{safe_patient_id}_results.csv")
        
        if not os.path.exists(patient_csv_path):
            print(f"  ⚠️  Per-patient CSV not found: {patient_csv_path}")
            return False
        
        try:
            # Read all rows
            rows = []
            with open(patient_csv_path, 'r', newline='') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    rows.append(row)
            
            # Update rows for this patient (match both patient_id and study_date if provided)
            updated_count = 0
            for row in rows:
                if row.get('patient_id') == patient_id:
                    # For multi-date cases, also match study_date
                    if study_date and row.get('study_date') != study_date:
                        continue
                    
                    # Update status and validation results
                    row['dicom_status'] = 'MANUALLY_RUN'
                    row['nifti_conversion'] = 'SUCCESS'
                    if validation_result:
                        row['nifti_overall_status'] = validation_result.get('overall_status', '')
                        # Add flattened validation results
                        flattened = flatten_validation_result(validation_result)
                        row.update(flattened)
                    
                    updated_count += 1
            
            if updated_count == 0:
                print(f"  ⚠️  Could not find patient {patient_id}" + (f" ({study_date})" if study_date else "") + " in per-patient CSV")
                return False
            
            # Write back to CSV
            if rows and rows[0]:
                fieldnames = list(rows[0].keys())
            else:
                fieldnames = []
            
            with open(patient_csv_path, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            
            print(f"  ✓ Updated per-patient CSV for {patient_id}" + (f" ({study_date})" if study_date else ""))
            return True
            
        except Exception as e:
            print(f"  ⚠️  Error updating per-patient CSV: {e}")
            return False
    
    def display_case_info(self, case):
        """Display detailed information for a flagged case."""
        print(f"\n{'='*70}")
        print(f"  PATIENT: {case['patient_id']}")
        if case.get('study_date'):
            print(f"  STUDY DATE: {case['study_date']}")
        print('='*70)
        
        # DICOM Extraction & Filtering Section
        print(f"\n  📋 DICOM EXTRACTION & FILTERING")
        print(f"  ─" * 35)
        print(f"  Status: {case['dicom_status']}")
        print(f"  Entry Count: {case['entry_count']}")
        
        # Display DICOM Flags
        dicom_flags = case['dicom_flags'].strip() if case['dicom_flags'] else ""
        if dicom_flags:
            dicom_flags_value = self._try_parse_json(dicom_flags)
            if isinstance(dicom_flags_value, str):
                print(f"  Flags: {dicom_flags_value}")
            else:
                print(f"  Flags:")
                print(self._format_value(dicom_flags_value, indent=4))
        
        # Consistency Check Details Section
        consistency_fields = [
            'consistency_total_dicoms',
            'consistency_temporal_positions',
            'consistency_folder_names',
            'consistency_slices_per_temporal',
            'consistency_folder_slice_counts',
            'consistency_low_similarity_pairs'
        ]
        
        if any(case.get(k) for k in consistency_fields):
            print(f"\n  🔍 CONSISTENCY CHECK DETAILS")
            print(f"  ─" * 35)
            
            if case['consistency_total_dicoms']:
                print(f"  Total DICOMs: {case['consistency_total_dicoms']}")
            
            if case['consistency_temporal_positions']:
                temporal = self._try_parse_json(case['consistency_temporal_positions'])
                if isinstance(temporal, str):
                    print(f"  Temporal Positions: {temporal}")
                else:
                    print(f"  Temporal Positions:")
                    print(self._format_value(temporal, indent=4))
            
            if case['consistency_folder_names']:
                folders = self._try_parse_json(case['consistency_folder_names'])
                if isinstance(folders, str):
                    print(f"  Folder Names: {folders}")
                else:
                    print(f"  Folder Names:")
                    print(self._format_value(folders, indent=4))
            
            if case['consistency_slices_per_temporal']:
                slices = self._try_parse_json(case['consistency_slices_per_temporal'])
                if isinstance(slices, str):
                    print(f"  Slices per Temporal: {slices}")
                else:
                    print(f"  Slices per Temporal:")
                    print(self._format_value(slices, indent=4))
            
            if case['consistency_folder_slice_counts']:
                counts = self._try_parse_json(case['consistency_folder_slice_counts'])
                if isinstance(counts, str):
                    print(f"  Folder Slice Counts: {counts}")
                else:
                    print(f"  Folder Slice Counts:")
                    print(self._format_value(counts, indent=4))
            
            if case['consistency_low_similarity_pairs']:
                pairs = self._try_parse_json(case['consistency_low_similarity_pairs'])
                if isinstance(pairs, str):
                    print(f"  Low Similarity Pairs: {pairs}")
                else:
                    print(f"  Low Similarity Pairs:")
                    formatted = self._format_value(pairs, indent=6)
                    for line in formatted.split("\n"):
                        print(f"  {line}")
        
        # NIfTI Conversion Section
        print(f"\n  🔄 NIfTI CONVERSION")
        print(f"  ─" * 35)
        print(f"  Status: {case['nifti_conversion']}")
        
        # NIfTI Validation Section
        validation_fields = [
            'val_consistency_status',
            'val_consistency_issues',
            'val_file_count',
            'val_temporal_status',
            'val_temporal_issues',
            'val_time_gaps',
            'val_signal_status',
            'val_signal_issues',
            'val_enhancement_ratio',
            'val_peak_index'
        ]
        
        if any(case.get(k) for k in validation_fields):
            print(f"\n  ✅ NIfTI VALIDATION")
            print(f"  ─" * 35)
            print(f"  Overall Status: {case['nifti_overall_status']}")
            
            # Consistency validation
            if case['val_consistency_status']:
                print(f"\n  • Consistency Check:")
                print(f"    Status: {case['val_consistency_status']}")
                if case['val_consistency_issues']:
                    print(f"    Issues: {case['val_consistency_issues']}")
                if case['val_file_count']:
                    print(f"    File Count: {case['val_file_count']}")
            
            # Temporal validation
            if case['val_temporal_status']:
                print(f"\n  • Temporal Order Check:")
                print(f"    Status: {case['val_temporal_status']}")
                if case['val_temporal_issues']:
                    print(f"    Issues: {case['val_temporal_issues']}")
                if case['val_time_gaps']:
                    print(f"    Time Gaps: {case['val_time_gaps']}")
            
            # Signal validation
            if case['val_signal_status']:
                print(f"\n  • Signal Progression Check:")
                print(f"    Status: {case['val_signal_status']}")
                if case['val_signal_issues']:
                    print(f"    Issues: {case['val_signal_issues']}")
                if case['val_enhancement_ratio']:
                    print(f"    Enhancement Ratio: {case['val_enhancement_ratio']}")
                if case['val_peak_index']:
                    print(f"    Peak Index: {case['val_peak_index']}")
        
        print('='*70)
    
    def load_filtered_json(self, patient_id, study_date=None):
        """Load the filtered JSON for a patient, optionally filtered by study_date."""
        # Try date-specific directory first if study_date is provided
        if study_date:
            json_path = os.path.join(
                self.filtered_json_dir, patient_id, study_date, f"{patient_id}_filtered.json"
            )
            if os.path.exists(json_path):
                try:
                    with open(json_path, 'r') as f:
                        return json.load(f)
                except Exception as e:
                    print(f"✗ Error loading JSON for {patient_id} ({study_date}): {e}")
                    return None
            
            # Fall back to old format (date/patient_id.json) for backward compatibility
            json_path_old = os.path.join(
                self.filtered_json_dir, study_date, f"{patient_id}_filtered.json"
            )
            if os.path.exists(json_path_old):
                try:
                    with open(json_path_old, 'r') as f:
                        return json.load(f)
                except Exception as e:
                    print(f"✗ Error loading JSON for {patient_id} ({study_date}): {e}")
                    return None
        
        # Fall back to root filtered_json_dir (no date)
        json_path = os.path.join(
            self.filtered_json_dir, f"{patient_id}_filtered.json"
        )
        
        if not os.path.exists(json_path):
            return None
        
        try:
            with open(json_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"✗ Error loading JSON for {patient_id}: {e}")
            return None
    
    def _filter_data_by_date(self, data, patient_id, study_date):
        """Return a copy of data with only entries matching study_date."""
        if not data or not study_date or patient_id not in data:
            return data

        groups_or_entries = data[patient_id]
        if isinstance(groups_or_entries, dict):
            all_entries = [
                entry for group_entries in groups_or_entries.values()
                for entry in group_entries
            ]
        elif isinstance(groups_or_entries, list):
            all_entries = groups_or_entries
        else:
            return data

        filtered = [e for e in all_entries if FilteringStage.get_date_key(e) == study_date]
        return {patient_id: filtered}

    def _load_all_dicom_files(self, patient_id):
        """Load all unfiltered DICOM files for a patient as fallback."""
        all_dicom_dir = os.path.join(
            self.center_results, "intermediate_results", "all_dicom_files"
        )
        
        if not os.path.exists(all_dicom_dir):
            return None
        
        # Try multiple naming patterns
        json_patterns = [
            f"{patient_id}_all.json",
            f"{patient_id}.json"
        ]
        
        for pattern in json_patterns:
            json_path = os.path.join(all_dicom_dir, pattern)
            if os.path.exists(json_path):
                try:
                    with open(json_path, 'r') as f:
                        data = json.load(f)
                    # Handle both grouped and flat entry formats
                    if isinstance(data, dict) and patient_id in data:
                        return {patient_id: data[patient_id]}
                    elif isinstance(data, dict) and len(data) == 1:
                        return data
                    else:
                        return {patient_id: data} if isinstance(data, list) else None
                except Exception as e:
                    pass
        
        return None
    
    def display_sequences(self, filtered_data, patient_id):
        """Display available DicomPaths for selection."""
        if not filtered_data or patient_id not in filtered_data:
            print(f"✗ No filtered data found for {patient_id}")
            return []
        
        groups_or_entries = filtered_data[patient_id]
        
        # Handle both grouped and flat entry formats
        all_entries = []
        if isinstance(groups_or_entries, dict):
            all_entries = [
                entry for group_entries in groups_or_entries.values() 
                for entry in group_entries
            ]
        elif isinstance(groups_or_entries, list):
            all_entries = groups_or_entries
        
        if not all_entries:
            print(f"✗ No sequences found for {patient_id}")
            return []

        # Sort using the same intelligent mechanism as stage2_filter (folder-name
        # pattern detection, timing fields, None-entry placement)
        all_entries = FilteringStage().sort_entries(all_entries)
        
        # Find common prefix of all DicomPaths to identify where they first differ
        dicom_paths = [entry.get('DicomPath', entry.get('dicom_file', '')) for entry in all_entries]
        common_prefix = self._find_common_path_prefix(dicom_paths)
        
        print(f"\nAvailable DICOM sequences ({len(all_entries)} total):")
        print('─' * 100)
        
        for idx, entry in enumerate(all_entries):
            dicom_path = entry.get('DicomPath', entry.get('dicom_file', 'N/A'))
            
            # Extract scan folder based on where paths first differ
            scan_folder = self._extract_scan_folder(dicom_path, common_prefix)
            
            # Extract raw folder name from path (segment containing SeriesDescription)
            series_desc = entry.get('SeriesDescription', '')
            folder_name = ""
            if dicom_path and dicom_path != 'N/A':
                segments = [p for p in dicom_path.split("/") if p]
                if series_desc:
                    for seg in segments:
                        if series_desc.lower() in seg.lower():
                            folder_name = seg
                            break
                if not folder_name and "/scans/" in dicom_path:
                    parts = dicom_path.split("/scans/")
                    if len(parts) > 1:
                        folder_name = parts[1].split("/")[0]
            
            # Show series description and folder name if available
            if series_desc and folder_name and folder_name != scan_folder:
                print(f"  [{idx}] {scan_folder} - {series_desc}  (folder: {folder_name})")
            elif series_desc:
                print(f"  [{idx}] {scan_folder} - {series_desc}")
            elif folder_name and folder_name != scan_folder:
                print(f"  [{idx}] {scan_folder}  (folder: {folder_name})")
            else:
                print(f"  [{idx}] {scan_folder}")
            
            # Show parameters if available
            params = []

            study_date_val = entry.get('StudyDate', '')
            if study_date_val:
                params.append(f"Date={study_date_val}")
            if 'ImageType' in entry and entry['ImageType']:
                params.append(f"Type={entry['ImageType']}")
            if 'RepetitionTime' in entry and entry['RepetitionTime']:
                params.append(f"TR={entry['RepetitionTime']}")
            if 'EchoTime' in entry and entry['EchoTime']:
                params.append(f"TE={entry['EchoTime']}")
            if 'FlipAngle' in entry and entry['FlipAngle']:
                params.append(f"FA={entry['FlipAngle']}")
            if 'AcquisitionNumber' in entry and entry['AcquisitionNumber']:
                params.append(f"AcqNum={entry['AcquisitionNumber']}")
            if 'TemporalPositionIdentifier' in entry and entry['TemporalPositionIdentifier']:
                params.append(f"TempPos={entry['TemporalPositionIdentifier']}")
            
            if params:
                print(f"           {', '.join(params)}")
        
        print('─' * 100)
        
        return all_entries
    
    def _find_common_path_prefix(self, paths):
        """Find the common prefix of multiple file paths."""
        if not paths:
            return ""
        
        paths = [str(p) for p in paths if p]
        if not paths:
            return ""
        
        if len(paths) == 1:
            # For single path, return up to the last directory separator
            return paths[0].rsplit('/', 1)[0] + '/'
        
        # Find character-by-character common prefix
        common = ""
        for chars in zip(*paths):
            if len(set(chars)) == 1:  # All characters are the same
                common += chars[0]
            else:
                break
        
        # Extend to the last directory separator
        last_sep = common.rfind('/')
        if last_sep != -1:
            return common[:last_sep + 1]
        
        return common
    
    def _extract_scan_folder(self, dicom_path, common_prefix):
        """Extract scan folder name from DicomPath based on common prefix."""
        if not dicom_path:
            return "Unknown"
        
        # Remove common prefix
        if common_prefix and dicom_path.startswith(common_prefix):
            remainder = dicom_path[len(common_prefix):]
        else:
            remainder = dicom_path
        
        # Get the first path component after the common prefix
        parts = remainder.split('/')
        if parts:
            scan_folder = parts[0]
            return scan_folder if scan_folder else "Unknown"
        
        return "Unknown"
    
    def get_user_sequence_selection(self, all_entries):
        """Get user input for sequence selection by index (DicomPath-based)."""
        print(f"\nEnter the indices of DICOM files to process in desired order, separated by spaces.")
        print(f"Example: 0 2 1")
        print(f"Press Enter with no input to skip this patient.")
        
        # Find common prefix for scan folder extraction
        dicom_paths = [entry.get('DicomPath', entry.get('dicom_file', '')) for entry in all_entries]
        common_prefix = self._find_common_path_prefix(dicom_paths)
        
        while True:
            user_input = input("Order: ").strip()
            
            if not user_input:
                return []
            
            try:
                # Parse indices - handle both valid and invalid gracefully
                indices = [int(i) for i in user_input.split() if i.lstrip('-').isdigit()]
                valid_indices = [i for i in indices if 0 <= i < len(all_entries)]
                
                if not valid_indices:
                    print(f"✗ No valid indices provided. Please try again.")
                    continue
                
                if len(valid_indices) != len(indices):
                    invalid = [i for i in indices if i not in valid_indices]
                    print(f"⚠️  Skipping invalid indices: {invalid}")
                
                selected = [all_entries[i] for i in valid_indices]
                
                # Show selected sequences
                print(f"\n✓ Selected {len(selected)} DICOM file(s) in processing order:")
                for i, seq_idx in enumerate(valid_indices, 1):
                    dicom_path = all_entries[seq_idx].get('DicomPath', all_entries[seq_idx].get('dicom_file', 'Unknown'))
                    scan_folder = self._extract_scan_folder(dicom_path, common_prefix)
                    print(f"  {i}. [{seq_idx}] {scan_folder}")
                print()
                
                return selected
                    
            except ValueError:
                print(f"✗ Invalid input. Please enter space-separated numbers.")
                continue
    
    def process_patient(self, patient_id, selected_entries, study_date=None):
        """
        Process selected entries for a patient.
        
        Args:
            patient_id: Patient ID
            selected_entries: List of selected entry dictionaries
            study_date: (Optional) Study date for date-based organization
        
        Returns:
            Boolean indicating success
        """
        if not selected_entries:
            print(f"  ⊘ No sequences selected. Skipping {patient_id}.")
            return False
        
        # Check if already processed - account for date-based structure
        if study_date:
            patient_nifti_dir = os.path.join(self.nifti_images_root, patient_id, study_date)
            patient_metadata_dir = os.path.join(self.nifti_metadata_root, patient_id, study_date)
        else:
            patient_nifti_dir = os.path.join(self.nifti_images_root, patient_id)
            patient_metadata_dir = os.path.join(self.nifti_metadata_root, patient_id)
        if os.path.exists(patient_nifti_dir):
            response = input(f"  ⚠️  {patient_id} already has NIfTI images. Overwrite? (y/n): ").strip().lower()
            if response != 'y':
                print(f"  ⊘ Skipping {patient_id}.")
                return False
            # Remove existing data before reprocessing
            try:
                if os.path.exists(patient_nifti_dir):
                    shutil.rmtree(patient_nifti_dir)
                    print(f"  🗑️  Removed existing NIfTI images for {patient_id}")
                if os.path.exists(patient_metadata_dir):
                    shutil.rmtree(patient_metadata_dir)
                    print(f"  🗑️  Removed existing metadata for {patient_id}")
            except Exception as e:
                print(f"  ⚠️  Error removing existing files: {e}")
                return False
        
        # Normalize entries: convert DicomPath to dicom_file for compatibility
        normalized_entries = []
        for entry in selected_entries:
            normalized_entry = entry.copy()
            # Map DicomPath to dicom_file if needed
            if 'DicomPath' in entry and 'dicom_file' not in entry:
                normalized_entry['dicom_file'] = entry['DicomPath']
            normalized_entries.append(normalized_entry)
        
        # Create temporary JSON with selected entries
        temp_json_data = {patient_id: normalized_entries}
        temp_json_path = os.path.join(
            self.filtered_json_dir, f"{patient_id}_manual_selection.json"
        )
        
        try:
            with open(temp_json_path, 'w') as f:
                json.dump(temp_json_data, f, indent=2)
            
            print(f"  ⚙️  Converting {len(selected_entries)} DICOM file(s)...")
            
            # Process with interactive=False since we already selected
            process_patient_json(
                temp_json_path,
                self.nifti_images_root,
                self.nifti_metadata_root,
                interactive=False,
                patient_id=patient_id,
                study_date=study_date
            )
            
            print(f"  ✅ Successfully converted {patient_id}")
            
            # Run NIfTI validation
            print(f"  🔍 Running NIfTI validation checks...")
            validation_result = None
            
            try:
                validation_result = validate_patient_nifti(
                    patient_nifti_dir,
                    patient_id,
                    normalized_entries
                )
                
                # Display validation results
                self._display_validation_results(patient_id, validation_result)
                
                # Update CSV with results
                if validation_result:
                    self.update_csv_with_results(patient_id, study_date, validation_result)
                    self.update_patient_csv_with_results(patient_id, study_date, validation_result)
                
            except Exception as val_e:
                print(f"  ⚠️  Validation error: {val_e}")
            
            return True
            
        except Exception as e:
            print(f"  ✗ Error processing {patient_id}: {e}")
            return False
        finally:
            # Clean up temporary JSON
            if os.path.exists(temp_json_path):
                os.remove(temp_json_path)
    
    def _display_validation_results(self, patient_id, validation_result):
        """Display NIfTI validation results in a structured format."""
        print(f"\n  📊 NIfTI VALIDATION RESULTS")
        print(f"  ─" * 35)
        
        if not validation_result:
            print(f"  No validation results available")
            return
        
        overall_status = validation_result.get('overall_status', 'UNKNOWN')
        status_icon = '✅' if overall_status == 'OK' else ('⚠️ ' if overall_status == 'WARNING' else '❌')
        print(f"  Overall Status: {status_icon} {overall_status}")
        
        # Consistency check results
        consistency = validation_result.get('consistency', {})
        if consistency:
            print(f"\n  • Consistency Check: {consistency.get('status', 'N/A')}")
            issues = consistency.get('issues', [])
            if issues:
                for issue in issues[:3]:  # Show first 3 issues
                    print(f"    - {issue}")
            metrics = consistency.get('metrics', {})
            if metrics.get('file_count'):
                print(f"    Files: {metrics['file_count']}")
        
        # Temporal order check results
        temporal = validation_result.get('temporal_order', {})
        if temporal:
            print(f"\n  • Temporal Order Check: {temporal.get('status', 'N/A')}")
            issues = temporal.get('issues', [])
            if issues:
                for issue in issues[:3]:  # Show first 3 issues
                    print(f"    - {issue}")
            metrics = temporal.get('metrics', {})
            if metrics.get('time_gaps_sec'):
                print(f"    Time Gaps: {metrics['time_gaps_sec']}")
        
        # Signal progression check results
        signal = validation_result.get('signal_progression', {})
        if signal:
            print(f"\n  • Signal Progression Check: {signal.get('status', 'N/A')}")
            issues = signal.get('issues', [])
            if issues:
                for issue in issues[:3]:  # Show first 3 issues
                    print(f"    - {issue}")
            metrics = signal.get('metrics', {})
            if metrics.get('enhancement_ratio'):
                print(f"    Enhancement Ratio: {metrics['enhancement_ratio']}")
            if metrics.get('peak_index'):
                print(f"    Peak Index: {metrics['peak_index']}")
        
        # Overall issues summary
        all_issues = validation_result.get('all_issues', [])
        if all_issues:
            print(f"\n  ⚠️  Total Issues Found: {len(all_issues)}")
            for issue in all_issues[:5]:  # Show first 5
                print(f"    - {issue}")
            if len(all_issues) > 5:
                print(f"    ... and {len(all_issues) - 5} more issues")
        else:
            print(f"\n  ✅ No validation issues detected!")
    
    def interactive_workflow(self):
        """Run the interactive workflow for flagged cases."""
        print(f"\n{'='*70}")
        print(f"  MANUAL PROCESSOR FOR FLAGGED CASES")
        print(f"  Center: {self.center}")
        print('='*70)
        
        # Load flagged cases
        flagged_cases = self.load_flagged_cases()
        
        if not flagged_cases:
            print("✓ No flagged cases found. All patients processed successfully!")
            return
        
        print(f"\n📊 Found {len(flagged_cases)} flagged case(s)")
        
        processed_count = 0
        skipped_count = 0
        
        for case_idx, case in enumerate(flagged_cases, 1):
            patient_id = case['patient_id']
            
            # Display case info
            self.display_case_info(case)
            
            # Ask if user wants to process this case
            response = input(f"\n  Process {patient_id}? (y/n/skip): ").strip().lower()
            
            if response == 'n' or response == 'skip':
                skipped_count += 1
                continue
            
            if response != 'y':
                continue
            
            # Load and display sequences
            filtered_data = self.load_filtered_json(patient_id, case.get('study_date'))
            show_all = False
            
            study_date = case.get('study_date')

            # If filtered data is empty, try loading all_dicom_files as fallback
            if not filtered_data:
                print(f"  ⚠️  No filtered DICOM data found. Loading all available sequences...")
                raw_data = self._load_all_dicom_files(patient_id)
                if raw_data:
                    if study_date:
                        filtered_data = self._filter_data_by_date(raw_data, patient_id, study_date)
                        if not filtered_data or not filtered_data.get(patient_id):
                            print(f"  ⚠️  No sequences found for study date {study_date}. Showing all dates.")
                            filtered_data = raw_data
                        else:
                            print(f"  ℹ️  Showing sequences for study date {study_date}.")
                    else:
                        filtered_data = raw_data
                        print(f"  ℹ️  Showing ALL available DICOM sequences instead of filtered ones.")
                    show_all = True

            if not filtered_data:
                skipped_count += 1
                continue

            # Display filtered sequences
            all_entries = self.display_sequences(filtered_data, patient_id)
            if not all_entries:
                skipped_count += 1
                continue

            # Ask if user wants to see all sequences instead
            if not show_all:
                see_all = input(f"\n  Would you like to see ALL available DICOM sequences instead? (y/n): ").strip().lower()
                if see_all == 'y':
                    raw_all_data = self._load_all_dicom_files(patient_id)
                    if raw_all_data:
                        # Still filter by date when a study_date is set
                        if study_date:
                            date_filtered = self._filter_data_by_date(raw_all_data, patient_id, study_date)
                            display_data = date_filtered if (date_filtered and date_filtered.get(patient_id)) else raw_all_data
                            print(f"\n  ℹ️  Showing ALL sequences for study date {study_date}:" if display_data is date_filtered else f"\n  ℹ️  Showing ALL sequences (no date filter applied):")
                        else:
                            display_data = raw_all_data
                            print(f"\n  ℹ️  Showing ALL available DICOM sequences:")
                        all_entries = self.display_sequences(display_data, patient_id)
                        if not all_entries:
                            skipped_count += 1
                            continue
                    else:
                        print(f"  ⚠️  Could not load all available sequences.")
            
            # Get user selection
            selected_entries = self.get_user_sequence_selection(all_entries)
            
            # Process selected sequences
            if self.process_patient(patient_id, selected_entries, case.get('study_date')):
                processed_count += 1
            else:
                skipped_count += 1
            
            # Ask if continuing
            if case_idx < len(flagged_cases):
                cont = input(f"\n  Continue to next case? (y/n): ").strip().lower()
                if cont != 'y':
                    break
        
        # Summary
        print(f"\n{'='*70}")
        print(f"  PROCESSING SUMMARY")
        print('='*70)
        total = len(flagged_cases)
        total_skipped = total - processed_count
        pct = lambda n: (n / total * 100) if total > 0 else 0
        print(f"  Total flagged cases: {total}")
        print(f"  ✓ Processed: {processed_count:3d} ({pct(processed_count):.1f}%)")
        print(f"  ⊘ Skipped:   {total_skipped:3d} ({pct(total_skipped):.1f}%)")
        print('='*70)


def main():
    """Main entry point."""
    # Load Config first to get available centers
    Config.load()
    available_centers = Config.get_centers()
    
    parser = argparse.ArgumentParser(
        description="Manual processor for flagged DICOM cases"
    )
    parser.add_argument(
        '--center',
        default=None,
        help=f'Center name. Available: {", ".join(available_centers)}. If not specified, will prompt.'
    )
    parser.add_argument(
        '--results-dir',
        default=None,
        help='Results directory (uses Config if not specified)'
    )
    
    args = parser.parse_args()
    
    # Get results directory from Config if not specified
    if not args.results_dir:
        args.results_dir = Config.get_results_dir()
    
    # Determine center
    center = args.center
    if not center:
        print(f"\nAvailable centers: {', '.join(available_centers)}")
        center = input("Enter center name: ").strip()
        
        if not center:
            print("✗ No center specified. Exiting.")
            return
        
        if center not in available_centers:
            print(f"⚠️  Warning: '{center}' not in configured centers.")
            response = input("Continue anyway? (y/n): ").strip().lower()
            if response != 'y':
                return
    
    # Initialize and run processor
    processor = FlaggedCaseProcessor(center)
    processor.interactive_workflow()


if __name__ == "__main__":
    main()
