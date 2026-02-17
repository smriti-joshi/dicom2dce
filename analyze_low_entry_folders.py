#!/usr/bin/env python
"""
Analyze filtered JSON files with special focus on single-entry cases.

For single-entry cases:
- Group DICOM slices by TemporalPositionIdentifier
- Verify equal slice counts across temporal positions
- Extract and save representative DICOM metadata
- Flag inconsistencies
"""

import json
import os
from pathlib import Path
import pydicom
from collections import defaultdict
import argparse


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


def extract_dicom_metadata(dicom_path):
    """Extract key metadata from DICOM file"""
    try:
        ds = pydicom.dcmread(dicom_path, stop_before_pixels=True)
        
        # Extract all relevant fields
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
    except Exception as e:
        return None


def analyze_low_entry_files(filtered_dir, min_entries=3):
    """Analyze filtered JSON files, focusing on single-entry cases"""
    filtered_files = list(Path(filtered_dir).glob("*_filtered.json"))
    
    if not filtered_files:
        print(f"No filtered JSON files found in {filtered_dir}")
        return
    
    print(f"Found {len(filtered_files)} filtered patient files\n")
    
    results = []
    processed_count = 0
    
    for filtered_file in sorted(filtered_files):
        processed_count += 1
        print(f"[{processed_count}/{len(filtered_files)}] Processing {filtered_file.name}...", end=" ")
        try:
            with open(filtered_file, "r") as f:
                data = json.load(f)
            
            patient_id = list(data.keys())[0]
            entries = data[patient_id]
            
            # Check for multiple entries (flag if 2)
            if len(entries) == 2:
                print(f"⚠️  TWO_SEQUENCES (skipped)")
                results.append({
                    "patient_id": patient_id,
                    "entry_count": len(entries),
                    "flagged": True,
                    "reason": "TWO_SEQUENCES",
                    "analysis": None
                })
                continue
            
            # Only analyze single-entry cases
            if len(entries) != 1:
                print(f"✓ {len(entries)} entries (skipped)")
                continue
            
            print(f"Analyzing single entry...", end=" ")
            entry = entries[0]
            dicom_path = entry.get("DicomPath")
            folder_path = get_folder_from_dicom_path(dicom_path)
            
            if not folder_path:
                print(f"❌ Could not extract folder path")
                continue
            
            # Get all DICOMs in folder
            all_dicoms = get_all_dicoms_in_folder(folder_path)
            print(f"Found {len(all_dicoms)} DICOMs.", end=" ")
            
            # Extract metadata for all DICOMs
            all_metadata = []
            for dcm_path in all_dicoms:
                metadata = extract_dicom_metadata(dcm_path)
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
            
            # Check for issues
            flagged = False
            flags = []
            
            # Flag if TemporalPositionIdentifier is missing
            if missing_temp_id:
                flagged = True
                flags.append(f"MISSING_TEMPORAL_ID: {len(missing_temp_id)} files without TemporalPositionIdentifier")
            
            # Check if all temporal groups have equal slices
            slice_counts = [len(slices) for slices in temp_groups.values()]
            equal_slices = len(set(slice_counts)) <= 1
            
            if not equal_slices:
                flagged = True
                flags.append(f"UNEQUAL_SLICES: {dict((k, len(temp_groups[k])) for k in sorted(temp_groups.keys()))}")
            
            # Extract representative from each temporal position
            representatives = {}
            for temp_id in sorted(temp_groups.keys()):
                # Take first slice as representative
                representatives[temp_id] = temp_groups[temp_id][0]
            
            # Build analysis result
            analysis = {
                "total_dicoms_in_folder": len(all_metadata),
                "temporal_positions_found": len(temp_groups),
                "slices_per_temporal_position": {k: len(temp_groups[k]) for k in sorted(temp_groups.keys())},
                "equal_slice_counts": equal_slices,
                "missing_temporal_id_count": len(missing_temp_id),
                "representatives": representatives,
                "flags": flags if flags else None
            }
            
            status = "🚩 FLAGGED" if flagged else "✓ OK"
            print(f"{status}")
            
            # Display detailed results immediately for single-entry analysis
            print(f"    Total DICOMs in folder: {analysis['total_dicoms_in_folder']}")
            print(f"    Temporal positions: {analysis['temporal_positions_found']}")
            
            if analysis['slices_per_temporal_position']:
                print(f"    Slices per temporal position:")
                for temp_id in sorted(analysis['slices_per_temporal_position'].keys()):
                    count = analysis['slices_per_temporal_position'][temp_id]
                    print(f"      • Temporal {temp_id}: {count} slices")
            
            if analysis['flags']:
                print(f"    🚩 FLAGS:")
                for flag in analysis['flags']:
                    print(f"      • {flag}")
            
            results.append({
                "patient_id": patient_id,
                "entry_count": 1,
                "flagged": flagged,
                "reason": "SINGLE_ENTRY_ANALYSIS",
                "analysis": analysis
            })
        
        except Exception as e:
            print(f"❌ Error: {e}")
    
    # Final summary
    print(f"\n{'='*100}")
    print("SUMMARY")
    print("="*100)
    
    if not results:
        print("No cases processed")
        return
    
    two_seq_count = sum(1 for r in results if r['reason'] == "TWO_SEQUENCES")
    single_entry_count = sum(1 for r in results if r['reason'] == "SINGLE_ENTRY_ANALYSIS")
    flagged_count = sum(1 for r in results if r['flagged'])
    
    print(f"Total cases processed:           {len(results)}")
    print(f"Two-sequence cases (flagged):    {two_seq_count}")
    print(f"Single-entry cases analyzed:    {single_entry_count}")
    print(f"Cases with issues/flags:        {flagged_count}")
    
    # Save results to JSON
    output_file = os.path.join(filtered_dir, "low_entry_analysis.json")
    
    # Convert representatives to serializable format
    for result in results:
        if result['analysis'] and result['analysis']['representatives']:
            result['analysis']['representatives'] = {
                k: v for k, v in result['analysis']['representatives'].items()
            }
    
    with open(output_file, "w") as f:
        json.dump({
            "total_cases": len(results),
            "cases": results
        }, f, indent=2)
    
    print(f"\nResults saved to: {output_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Analyze filtered JSON files with low entry counts"
    )
    parser.add_argument(
        "filtered_dir",
        help="Directory containing *_filtered.json files"
    )
    parser.add_argument(
        "-m", "--min-entries",
        type=int,
        default=3,
        help="Minimum number of entries to consider as 'low' (default: 3)"
    )
    
    args = parser.parse_args()
    
    analyze_low_entry_files(args.filtered_dir, args.min_entries)
