# 🏥 dicom2dce

A DICOM processing pipeline to take you from messy dicom folders to consistent DCE-MRI nifti sequences. Currently, the pipeline focuses only on processing Breast DCE-MRI data. This helps you automatically process the data, followed by user interactive script for flagged cases.

## 🔄 Automatic Pipeline 

The automatic processing pipeline consists of six main stages:

**Stage 1: 📥 Extraction**
- Reads DICOM files from patient directories
- Extracts metadata (sequence information, timing, acquisition parameters)
- Organizes metadata into a structured format for downstream processing

**Stage 2: 🔍 Filtering**
- Identifies and selects DCE MRI sequences from all extracted sequences
- Filters based on imaging parameters and sequence names

**Stage 3: ✅ Consistency Checks**
- Validates consistency of extracted dicom sequences
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


### Usage

```bash
python -m dicom2dce.main
```

This processes all configured centers and patients, generating:
- NIfTI images and metadata
- Validation reports
- CSV summaries of results

## 🎯 Manual Processing

For cases ```FLAGGED``` during automated processing (due to consistency check failures or other issues), the manual processor allows you to:
- Review flagged cases with detailed error information
- Select specific sequences manually for problematic patients
- Convert selected sequences to NIfTI
- Run validation on the converted data
- Automatically update CSV reports with results

### Running Manual Processing

```bash
python -m dicom2dce.post_manual_processor
```

Optional arguments:
```bash
# Process specific center only
python -m dicom2dce.post_manual_processor --center kauno

# Use custom results directory
python -m dicom2dce.post_manual_processor --results-dir /path/to/results
```

### Manual Processing Workflow

1. **Load Flagged Cases** - Script automatically loads all patients with status != 'OK' from the processing CSV
2. **Review Case Details** - Shows:
   - DICOM extraction summary (sequences found, parameters)
   - Consistency check details (what failed and why)
   - NIfTI conversion status
   - Validation results (if previously converted)
   - Summary of issues

3. **Select Sequences** - View all detected sequences with parameters:
   ```
   Sequences for patient PATIENT_ID:
   [0] /path/to/dicom_folder_1 (TR=4.2ms, TE=2.1ms, FA=12°)
   [1] /path/to/dicom_folder_2 (TR=4.2ms, TE=2.1ms, FA=12°)
   [2] /path/to/dicom_folder_3 (TR=100ms, TE=50ms, FA=90°)
   ```
   Enter space-separated indices: `0 1`

4. **Automatic Processing** - Selected sequences are:
   - Converted from DICOM to NIfTI using dcm2niix
   - Validated automatically (signal integrity, temporal ordering, enhancement)
   - Results summarized in console output

5. **CSV Updates** - Both main and per-patient CSVs are updated with:
   - Status: `MANUALLY_RUN`
   - All nifti validation fields 
## �📁 Project Structure

- `process_dicom.py` - Main pipeline orchestrator
- `pipeline/` - Processing stages (extraction, filtering, conversion, validation)
- `config_paths.yaml` - User configuration (paths and centers)
- `config_params.json` - Processing parameters (filtering, validation thresholds)
- `main.py` - Entry point for automated processing
- `manual_processor.py` - Entry point for manual corrections.

## � Processing Flags Reference

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

## 📤 Output

Results are organized by center with intermediate and final outputs:
```
results/
├── center_name/
│   ├── dce/
│   │   ├── images/          # NIfTI files
│   │   └── dicom_metadata/
│   └── intermediate_results/
```

### Output Files

- **`*_nifti_dicom_mapping.json`** - Maps each NIfTI file to its source DICOM folder
- **`per_patient_validation_csvs/`** - Individual validation reports per patient
- **`consistency_check_results_{center}.csv`** - Summary of all consistency checks

## 💾 Installation

```bash
pip install -e .
```

### 📦 Requirements

- Python >= 3.9
- pydicom
- nibabel
- numpy
- tqdm
- pyyaml

## 🚀 Quick Start

### ⚙️ Configuration

The pipeline uses two configuration files:

#### `config_paths.yaml` (User Configuration)
Edit this file to set your data paths and configure which centers to process:

```yaml
paths:
  # List of medical centers to process
  centers:
    - 'center 1'
    - 'center 2'
  
  # Root directory containing per-center DICOM input folders
  # Expected structure: <dicom_root>/<center_name>/<patient_id>/...
  dicom_root: 'path to dicom input directory'
  
  # Root directory for NIfTI output
  # Output structure: <results_dir>/<center>/dce/images/ and <center>/dce/dicom_metadata/
  results_dir: 'path to output directory'

```

#### `config_params.json` (Processing Parameters)
This file contains filtering and validation parameters. Edit only if you need to adjust:
- DCE sequence filtering criteria (TR/TE limits, image type exclusions)
- Consistency check thresholds (slice counts, temporal positions)
- Processing options (DICOM reading, natural sorting)

These defaults work well for breast DCE-MRI but can be customized for other use cases.


