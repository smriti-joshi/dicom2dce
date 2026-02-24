# 🏥 dicom2dce

A DICOM processing pipeline to take you from messy dicom folders to consistent DCE-MRI nifti sequences. Currently, the pipeline focuses only on processing Breast DCE-MRI data.

## 🔄 Pipeline Stages

The processing pipeline consists of six main stages:

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
  centers:
    - KAUNO      # List of centers to process
    - HCB
  dicom_root: /dataall/dicoms              # Root directory with DICOM data
  results_dir: /dataall/eucanimage_second_try  # Output directory for NIfTI files
```

#### `config_params.json` (Processing Parameters)
This file contains filtering and validation parameters. Edit only if you need to adjust:
- DCE sequence filtering criteria (TR/TE limits, image type exclusions)
- Consistency check thresholds (slice counts, temporal positions)
- Processing options (DICOM reading, natural sorting)

These defaults work well for breast DCE-MRI but can be customized for other use cases.

### 🎯 Usage

```bash
python -m dicom2dce.main
```

This processes all configured centers and patients, generating:
- NIfTI images and metadata
- Validation reports
- CSV summaries of results

## 📁 Project Structure

- `process_dicom.py` - Main pipeline orchestrator
- `pipeline/` - Processing stages (extraction, filtering, conversion, validation)
- `config_paths.yaml` - User configuration (paths and centers)
- `config_params.json` - Processing parameters (filtering, validation thresholds)
- `main.py` - CLI entry point

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

## License

See LICENSE file for details.
