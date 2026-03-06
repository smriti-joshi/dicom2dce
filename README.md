# 🏥 dicom2dce

A DICOM processing pipeline to take you from messy DICOM folders to consistent DCE-MRI NIfTI sequences. Currently, the pipeline focuses on processing Breast DCE-MRI data. There are two components: an **Automatic Pipeline** to process the data, followed by an **Interactive Manual Review** for flagged cases.

The pipeline fully supports patients with **multiple acquisition dates** (study timepoints). Each date is processed independently and produces its own NIfTI output directory and CSV row.
## 📤 Output

### Directory Structure

Results are organized per center:
```
results/
└── center_name/
   ├── dce/
   │   ├── images/                               # Final NIfTI volumes
   │   │   └── PATIENT_ID/
   │   │       └── YYYYMMDD/                     # Study date subfolder
   │   │           ├── PATIENT_ID_0000.nii.gz    # Pre-contrast baseline
   │   │           ├── PATIENT_ID_0001.nii.gz    # 1st post-contrast phase
   │   │           ├── PATIENT_ID_0002.nii.gz    # 2nd post-contrast phase
   │   │           └── ...
   │   └── dicom_metadata/                       # dcm2niix JSON sidecars
   │       └── PATIENT_ID/
   │           └── YYYYMMDD/                     # Study date subfolder
   │               ├── PATIENT_ID_0000.json
   │               ├── PATIENT_ID_0001.json
   │               ├── ...
   │               └── PATIENT_ID_nifti_dicom_mapping.json
   └── intermediate_results/
        ├── all_dicom_files/                      # Stage 1: raw extraction JSONs
        ├── filtered_dicom_files/                 # Stage 2: filtered sequence JSONs
        │   └── PATIENT_ID/
        │       └── YYYYMMDD/
        │           └── PATIENT_ID_filtered.json
        ├── per_patient_validation_csvs/          # Per-patient validation CSVs
        ├── processing_report_center.csv          # Center-level processing report
        └── nifti_validation_details_center.json  # Full validation details
```

Patients with a single study date follow the same structure — the `YYYYMMDD/` subfolder is always present.

### NIfTI Files

Each patient/date combination gets its own subfolder under `dce/images/PATIENT_ID/YYYYMMDD/`. Volumes are 3D NIfTI files (`.nii.gz`) named sequentially:
```
PATIENT_ID_0000.nii.gz   # index 0000 = first temporal position (pre-contrast)
PATIENT_ID_0001.nii.gz   # index 0001 = second temporal position
...
```

If dcm2niix produces a 4D volume (e.g. a multi-phase baseline), it is automatically split into individual 3D files with sequential indices.

### JSON Metadata

For each NIfTI file, a matching JSON sidecar is saved under `dce/dicom_metadata/PATIENT_ID/YYYYMMDD/`. These are produced by dcm2niix and contain DICOM-derived metadata.

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

**Center-level report** (`processing_report_center.csv`) : one row per patient **per study date**, with columns covering:

| Group | Columns |
|-------|--------|
| Identification | `patient_id`, `study_date` |
| DICOM extraction | `dicom_status`, `entry_count`, `dicom_flags` |
| Consistency checks | `consistency_temporal_positions`, `consistency_total_dicoms`, `consistency_folder_names`, `consistency_slices_per_temporal`, `consistency_folder_slice_counts`, `consistency_low_similarity_pairs` |
| NIfTI conversion | `nifti_conversion` |
| NIfTI validation | `nifti_overall_status`, `val_consistency_status`, `val_consistency_issues`, `val_file_count`, `val_temporal_status`, `val_temporal_issues`, `val_time_gaps`, `val_signal_status`, `val_signal_issues`, `val_enhancement_ratio`, `val_peak_index` |

Patients with multiple study dates have one row per date, each with its own `study_date` value and independent validation results.

**Per-patient CSVs** (`per_patient_validation_csvs/PATIENT_ID_results.csv`) : same schema, one row per (patient, study_date) run — allows tracking re-processing.

**Validation details JSON** (`nifti_validation_details_center.json`) : detailed and nested nifti validation results for every patient/date combination.

## 💾 Installation

```bash
pip install -e .
```

This also installs CLI commands:
- `dicom2dce` : run the full automated pipeline
- `dicom2dce-review` : interactive review of flagged cases

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

Stages 2–6 are run independently for each study date found in the patient's DICOMs.

**Stage 1: 📥 Extraction**
- Reads DICOM files from patient directories
- Extracts metadata including all date fields: StudyDate, SeriesDate, AcquisitionDate, ContentDate, StudyInstanceUID, StudyID
- Organizes metadata into a structured format for downstream processing

**Stage 2: 🔍 Filtering & Date Grouping**
- Identifies and selects DCE MRI sequences from all extracted sequences
- Groups entries by study date using a 6-tier fallback chain:
  StudyDate → SeriesDate → AcquisitionDate → ContentDate → StudyInstanceUID → StudyID → `UNKNOWN_DATE`
- Filtered results saved to `filtered_dicom_files/PATIENT_ID/YYYYMMDD/`

**Stage 3: ✅ Consistency Checks**
- Run independently for each study date
- Validates consistency of filtered DICOM sequences for that date
- If no DCE sequences survived filtering for a date, raises `EMPTY_FILTERED_ENTRIES`
- Flags dates with data quality issues (blocking) or warnings (non-blocking)

**Stage 4: 🔁 NIfTI Conversion**
- Only runs for dates where consistency check passed (`OK`)
- Converts DICOM sequences to NIfTI format using dcm2niix
- Output saved to `dce/images/PATIENT_ID/YYYYMMDD/`
- Automatically handles 4D volume splitting when needed

**Stage 5: 🧪 NIfTI Validation**
- Run independently for each study date after conversion
- Validates consistency (file integrity, dimension matching)
- Checks temporal ordering and signal progression
- Calculates enhancement metrics and peak indices

**Stage 6: 📊 Reporting**
- Saves per-patient and center-level results
- Generates one CSV row per (patient, study date)
- Exports detailed validation metrics as JSON

## 🎯 Manual Review

For cases `FLAGGED` during automated processing (due to consistency check failures or other issues), the manual review tool allows you to:
- Review flagged cases with detailed error information, including the study date
- Select specific sequences manually for problematic patients
- Convert selected sequences to NIfTI into the correct `PATIENT_ID/YYYYMMDD/` directory
- Run validation on the converted data
- Update both the main center CSV and the per-patient CSV (matched on `patient_id` + `study_date`)

### Manual Review Workflow

1. **Load Flagged Cases** : automatically loads all patients with status != 'OK' from the processing CSV, including their `study_date`
2. **Review Case Details** : shows:
   - Patient ID and Study Date
   - DICOM extraction summary (sequences found, parameters)
   - Consistency check details (what failed and why)
   - NIfTI conversion status
   - Validation results (if previously converted)

3. **Select Sequences** : view all detected sequences with parameters:
   ```
   Sequences for patient PATIENT_ID (Study Date: YYYYMMDD):
   [0] /path/to/dicom_folder_1 (TR=4.2ms, TE=2.1ms, FA=12°)
   [1] /path/to/dicom_folder_2 (TR=4.2ms, TE=2.1ms, FA=12°)
   [2] /path/to/dicom_folder_3 (TR=100ms, TE=50ms, FA=90°)
   ```
   Enter space-separated indices: `0 1`

4. **Automatic Processing** : selected sequences are:
   - Converted from DICOM to NIfTI using dcm2niix into `PATIENT_ID/YYYYMMDD/`
   - Validated automatically (signal integrity, temporal ordering, enhancement)
   - Results summarized in console output

5. **CSV Updates** : both main and per-patient CSVs are updated with:
   - Status: `MANUALLY_RUN`
   - All NIfTI validation fields
   - Matching done on both `patient_id` and `study_date`

## 📁 Project Structure

- `main.py` : CLI entry point for automated processing
- `manual_review.py` : interactive review tool for flagged cases
- `process_dicom.py` : pipeline orchestrator
- `pipeline/` : processing stages:
  - `config.py` : configuration management
  - `stage1_extractor.py` : DICOM metadata extraction (all date fields)
  - `stage2_filter.py` : DCE sequence filtering and date grouping (`get_date_key()`, `group_by_date_and_tr_te()`)
  - `stage3_dcmconsistency.py` : consistency checks per study date
  - `stage4_niiconvert.py` : NIfTI conversion into date-based directories
  - `stage5_niivalidate.py` : NIfTI quality validation per study date
  - `stage6_report.py` : CSV/JSON reporting with one row per (patient, date)
- `config_paths.yaml.example` : template for path configuration
- `config_params.json` : processing parameters (filtering, validation thresholds)

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

