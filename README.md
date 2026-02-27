# 🏥 dicom2dce

A DICOM processing pipeline to take you from messy DICOM folders to consistent DCE-MRI NIfTI sequences. Currently, the pipeline focuses on processing Breast DCE-MRI data. There are two components: an **Automatic Pipeline** to process the data, followed by an **Interactive Manual Review** for flagged cases.

## 📤 Output

### Directory Structure

Results are organized per center:
```
results/
└── center_name/
   ├── dce/
   │   ├── images/                          # Final NIfTI volumes
   │   │   └── PATIENT_ID/
   │   │       ├── PATIENT_ID_0000.nii.gz   # Pre-contrast baseline
   │   │       ├── PATIENT_ID_0001.nii.gz   # 1st post-contrast phase
   │   │       ├── PATIENT_ID_0002.nii.gz   # 2nd post-contrast phase
   │   │       └── ...
   │   └── dicom_metadata/                  # dcm2niix JSON sidecars
   │       └── PATIENT_ID/
   │           ├── PATIENT_ID_0000.json
   │           ├── PATIENT_ID_0001.json
   │           ├── ...
   │           └── PATIENT_ID_nifti_dicom_mapping.json
   └── intermediate_results/
   |    ├── all_dicom_files/                 # Stage 1: raw extraction JSONs
   |    ├── filtered_dicom_files/            # Stage 2: filtered sequence JSONs
   |    ├── per_patient_validation_csvs/     # Per-patient validation CSVs
   ├── processing_report_center.csv          # Center-level processing report
   └── nifti_validation_details_center.json  # Full validation details
```

### NIfTI Files

Each patient gets one sub-folder under `dce/images/`. Volumes are 3D NIfTI files (`.nii.gz`) named sequentially:
```
PATIENT_ID_0000.nii.gz   # index 0000 = first temporal position (pre-contrast)
PATIENT_ID_0001.nii.gz   # index 0001 = second temporal position
...
```

If dcm2niix produces a 4D volume (e.g. a multi-phase baseline), it is automatically split into individual 3D files with sequential indices.

### JSON Metadata

For each NIfTI file, a matching JSON sidecar is saved under `dce/dicom_metadata/`. These are produced by dcm2niix and contain DICOM-derived metadata.

Additionally, a `PATIENT_ID_nifti_dicom_mapping.json` file maps each NIfTI to its source DICOM folder:
```json
[
  {
    "nifti_image": "/path/to/PATIENT_ID_0000.nii.gz",
    "dicom_folder": "/path/to/source/dicom/folder"
  },
  ...
]
```

### CSV Reports

**Center-level report** (`processing_report_center.csv`) — one row per patient with 22 columns covering:

| Group | Columns |
|-------|---------|
| DICOM extraction | `patient_id`, `dicom_status`, `entry_count`, `dicom_flags` |
| Consistency checks | `consistency_temporal_positions`, `consistency_total_dicoms`, `consistency_folder_names`, `consistency_slices_per_temporal`, `consistency_folder_slice_counts`, `consistency_low_similarity_pairs` |
| NIfTI conversion | `nifti_conversion` |
| NIfTI validation | `nifti_overall_status`, `val_consistency_status`, `val_consistency_issues`, `val_file_count`, `val_temporal_status`, `val_temporal_issues`, `val_time_gaps`, `val_signal_status`, `val_signal_issues`, `val_enhancement_ratio`, `val_peak_index` |

**Per-patient CSVs** (`per_patient_validation_csvs/PATIENT_ID_results.csv`) — same schema, one row per run (allows tracking re-processing).

**Validation details JSON** (`nifti_validation_details_center.json`) — detailed and nested nifti validation results for every patient.

## 💾 Installation

```bash
pip install -e .
```

This also installs CLI commands:
- `dicom2dce` — run the full automated pipeline
- `dicom2dce-review` — interactive review of flagged cases

### 📦 Requirements

- Python >= 3.9
- pydicom
- nibabel
- numpy
- tqdm
- pyyaml
- [dcm2niix](https://github.com/rordenlab/dcm2niix) (must be on PATH)

## 🚀 Quick Start

### ⚙️ Configuration

1. Copy the paths template and edit it:
```bash
cp config_paths.yaml.example config_paths.yaml
```

2. Edit `config_paths.yaml` with your data paths:
```yaml
paths:
  centers:
    - 'CENTER_NAME'
  dicom_root: '/path/to/dicom/input'
  results_dir: '/path/to/output'
```

3. (Optional) Edit `config_params.json` to adjust:
   - DCE sequence filtering criteria (TR/TE limits, image type exclusions)
   - Consistency check thresholds (slice counts, temporal positions)
   - Processing options (DICOM reading, natural sorting)

   Defaults work well for breast DCE-MRI but can be customized for other use cases.

### Run the Pipeline

```bash
# Automated processing of all centers
python -m dicom2dce.main
# or
dicom2dce
```

### Review Flagged Cases

```bash
# Interactive manual review
python -m dicom2dce.manual_review
# or
dicom2dce-review

# Process a specific center
dicom2dce-review --center kauno

# Use a custom results directory
dicom2dce-review --results-dir /path/to/results
```

## 🔄 Automatic Pipeline

The automatic processing pipeline consists of six stages:

**Stage 1: 📥 Extraction**
- Reads DICOM files from patient directories
- Extracts metadata (sequence information, timing, acquisition parameters)
- Organizes metadata into a structured format for downstream processing

**Stage 2: 🔍 Filtering**
- Identifies and selects DCE MRI sequences from all extracted sequences
- Filters based on imaging parameters and sequence names

**Stage 3: ✅ Consistency Checks**
- Validates consistency of extracted DICOM sequences
- Checks temporal ordering of dynamic frames
- Detects and reports issues like mismatched slice counts or temporal gaps
- Flags patients with data quality issues

**Stage 4: 🔁 NIfTI Conversion**
- Converts DICOM sequences to NIfTI format using dcm2niix
- Automatically handles 4D volume splitting when needed
- Files are named and organized sequentially for tracking

**Stage 5: 🧪 NIfTI Validation**
- Performs quality checks on converted NIfTI files
- Validates consistency (file integrity, dimension matching)
- Checks temporal ordering and signal progression
- Calculates enhancement metrics and peak indices

**Stage 6: 📊 Reporting**
- Saves per-patient and center-level results
- Generates CSV reports with processing and validation results
- Exports detailed validation metrics as JSON

## 🎯 Manual Review

For cases `FLAGGED` during automated processing (due to consistency check failures or other issues), the manual review tool allows you to:
- Review flagged cases with detailed error information
- Select specific sequences manually for problematic patients
- Convert selected sequences to NIfTI
- Run validation on the converted data
- Automatically update CSV reports with results

### Manual Review Workflow

1. **Load Flagged Cases** — automatically loads all patients with status != 'OK' from the processing CSV
2. **Review Case Details** — shows:
   - DICOM extraction summary (sequences found, parameters)
   - Consistency check details (what failed and why)
   - NIfTI conversion status
   - Validation results (if previously converted)
   - Summary of issues

3. **Select Sequences** — view all detected sequences with parameters:
   ```
   Sequences for patient PATIENT_ID:
   [0] /path/to/dicom_folder_1 (TR=4.2ms, TE=2.1ms, FA=12°)
   [1] /path/to/dicom_folder_2 (TR=4.2ms, TE=2.1ms, FA=12°)
   [2] /path/to/dicom_folder_3 (TR=100ms, TE=50ms, FA=90°)
   ```
   Enter space-separated indices: `0 1`

4. **Automatic Processing** — selected sequences are:
   - Converted from DICOM to NIfTI using dcm2niix
   - Validated automatically (signal integrity, temporal ordering, enhancement)
   - Results summarized in console output

5. **CSV Updates** — both main and per-patient CSVs are updated with:
   - Status: `MANUALLY_RUN`
   - All NIfTI validation fields

## 📁 Project Structure

- `main.py` — CLI entry point for automated processing
- `manual_review.py` — interactive review tool for flagged cases
- `process_dicom.py` — pipeline orchestrator
- `pipeline/` — processing stages:
  - `config.py` — configuration management
  - `stage1_extractor.py` — DICOM metadata extraction
  - `stage2_filter.py` — DCE sequence filtering
  - `stage3_dcmconsistency.py` — consistency checks
  - `stage4_niiconvert.py` — NIfTI conversion (dcm2niix)
  - `stage5_niivalidate.py` — NIfTI quality validation
  - `stage6_report.py` — CSV/JSON reporting
- `config_paths.yaml.example` — template for path configuration
- `config_params.json` — processing parameters (filtering, validation thresholds)

## 🚩 Processing Flags Reference

Flags are generated during DICOM consistency checks and NIfTI validation. They're categorized as either **blocking** (prevents processing) or **warnings** (allows processing but noted for review).

### DICOM Consistency Check Flags

#### 🛑 Blocking Flags (Prevent Processing)

| Flag | Meaning | Reason |
|------|---------|--------|
| `EMPTY_FILTERED_ENTRIES` | No valid DCE sequences found after filtering | Patient has no DCE-MRI data or all sequences filtered out |
| `LOW_SLICE_COUNT_{N}` | Fewer than minimum slices per temporal position | N < 20 slices per phase (too coarse resolution) |
| `PHASES_TOO_FEW` | Insufficient dynamic phases acquired | Less than configured minimum temporal positions |
| `UNEQUAL_SLICES_PER_TEMPORAL_POS` | Different number of slices across temporal phases | Imaging protocol inconsistency |
| `UNEQUAL_SLICES_ACROSS_FOLDERS` | Different slice counts across DICOM folders | Data from different protocols/acquired at different times |
| `UNEXPECTED_ONLY_TWO_SEQUENCES` | Exactly 2 filtered sequences found | Ambiguous whether sequences form a proper DCE series |

#### ⚠️ Warning Flags (Processing Continues)

| Flag | Meaning | Action |
|------|---------|--------|
| `MISSING_TEMPORAL_ID_{N}_SLICES` | N slices lack temporal position markers in DICOM | Data still processed; temporal order assumed from file order |
| `LOW_FOLDER_NAME_SIMILARITY` | DICOM folder names dissimilar (< 90% match) | May indicate accidental mixing of sequences; review recommended |

### NIfTI Validation Issues

These appear in validation reports after conversion. They're informational and don't block processing.

| Issue | Meaning |
|-------|---------|
| `Invalid filename format` | NIfTI file doesn't match expected naming pattern |
| `Missing indices` | Sequential file numbering has gaps |
| `Failed to load file(s)` | NIfTI file corrupted or unreadable |
| `Shape mismatches` | Different voxel dimensions across volumes |
| `Orientation mismatches` | Inconsistent spatial orientation across volumes |
| `Missing AcquisitionTime` | Metadata missing for temporal ordering |
| `Acquisition times NOT monotonically increasing` | Temporal ordering is non-sequential |
| `First volume NOT baseline` | First image has wrong intensity (should be pre-contrast) |
| `Minimal contrast enhancement` | Very low signal enhancement ratio (< 1.1x) |
| `Weak contrast enhancement` | Low signal enhancement ratio (1.1x - 1.2x) |

