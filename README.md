# dicom2dce

A DICOM processing pipeline for extracting, filtering, and converting medical imaging data to NIfTI format.

## Overview

This tool processes DICOM files from multiple medical centers, specifically targeting Dynamic Contrast Enhanced (DCE) sequences. The pipeline:

1. **Extracts** DICOM metadata from patient directories
2. **Filters** DCE sequences based on configurable criteria
3. **Converts** to NIfTI format
4. **Validates** the output files

## Installation

```bash
pip install -e .
```

### Requirements

- Python >= 3.9
- pydicom
- nibabel
- numpy
- tqdm

## Quick Start

### Configuration

Edit `config.json` to set paths and processing parameters:

```json
{
  "dicom_root": "/path/to/dicom/data",
  "results_dir": "/path/to/results"
}
```

### Usage

```bash
python -m dicom2dce.main
```

This processes all configured centers and patients, generating:
- NIfTI images and metadata
- Validation reports
- CSV summaries of results

## Project Structure

- `process_dicom.py` - Main pipeline orchestrator
- `pipeline/` - Processing stages (extraction, filtering, conversion, validation)
- `config.json` - Configuration file
- `main.py` - CLI entry point

## Output

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
