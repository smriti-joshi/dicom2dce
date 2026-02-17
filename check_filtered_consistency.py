#!/usr/bin/env python
"""
Check consistency of filtered DICOM folders:
- Image dimensions across files in each series
- File counts across series within each patient
- Flag cases with inconsistencies
"""

import json
import os
from pathlib import Path
import argparse
from dce_filter import ConsistencyChecker
from tqdm import tqdm


def check_filtered_folder(filtered_dir, output_dir):
    """
    Process all filtered JSON files in a directory and check consistency
    
    Args:
        filtered_dir: Directory containing *_filtered.json files
        output_dir: Directory to save consistency reports
    """
    os.makedirs(output_dir, exist_ok=True)
    
    filtered_files = list(Path(filtered_dir).glob("*_filtered.json"))
    
    if not filtered_files:
        print(f"No filtered JSON files found in {filtered_dir}")
        return
    
    print(f"Found {len(filtered_files)} filtered patient files\n")
    
    flagged_patients = []
    consistent_patients = []
    
    for filtered_file in tqdm(sorted(filtered_files), desc="Checking consistency"):
        try:
            with open(filtered_file, "r") as f:
                data = json.load(f)
            
            # Extract patient ID and filtered entries
            patient_id = list(data.keys())[0]
            filtered_entries = data[patient_id]
            
            # Check consistency
            patient_results = ConsistencyChecker.check_patient_consistency(
                filtered_entries, 
                patient_id
            )
            
            # Save report
            ConsistencyChecker.save_consistency_report(patient_results, output_dir)
            
            # Track flagged vs consistent
            if patient_results["flagged"]:
                flagged_patients.append(patient_id)
            else:
                consistent_patients.append(patient_id)
        
        except Exception as e:
            print(f"\nError processing {filtered_file}: {e}")
    
    # Print summary
    print("\n" + "="*70)
    print("CONSISTENCY CHECK SUMMARY")
    print("="*70)
    print(f"Total patients checked: {len(filtered_files)}")
    print(f"✓ Consistent: {len(consistent_patients)}")
    print(f"⚠️  Flagged (inconsistent): {len(flagged_patients)}")
    
    if flagged_patients:
        print(f"\nFlagged patients ({len(flagged_patients)}):")
        for patient_id in sorted(flagged_patients):
            print(f"  - {patient_id}")
    
    # Save summary
    summary = {
        "total_patients": len(filtered_files),
        "consistent_patients": len(consistent_patients),
        "flagged_patients": len(flagged_patients),
        "flagged_patient_ids": sorted(flagged_patients),
        "consistent_patient_ids": sorted(consistent_patients)
    }
    
    summary_file = os.path.join(output_dir, "consistency_check_summary.json")
    with open(summary_file, "w") as f:
        json.dump(summary, f, indent=2)
    
    print(f"\nReports saved to: {output_dir}")
    print(f"Summary saved to: {summary_file}")


def check_single_patient(filtered_json_path, output_dir=None):
    """
    Check consistency for a single patient's filtered JSON file
    
    Args:
        filtered_json_path: Path to *_filtered.json file
        output_dir: Optional directory to save report
    """
    with open(filtered_json_path, "r") as f:
        data = json.load(f)
    
    patient_id = list(data.keys())[0]
    filtered_entries = data[patient_id]
    
    # Check consistency
    patient_results = ConsistencyChecker.check_patient_consistency(
        filtered_entries,
        patient_id
    )
    
    print(json.dumps(patient_results, indent=2))
    
    # Save if output dir specified
    if output_dir:
        ConsistencyChecker.save_consistency_report(patient_results, output_dir)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Check consistency of filtered DICOM folders"
    )
    parser.add_argument(
        "filtered_dir",
        help="Directory containing *_filtered.json files or path to single file"
    )
    parser.add_argument(
        "-o", "--output",
        help="Output directory for consistency reports",
        default="consistency_reports"
    )
    
    args = parser.parse_args()
    
    # Check if input is a directory or single file
    if os.path.isfile(args.filtered_dir):
        check_single_patient(args.filtered_dir, args.output)
    else:
        check_filtered_folder(args.filtered_dir, args.output)
