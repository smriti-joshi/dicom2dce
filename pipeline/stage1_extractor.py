import pydicom
import os
import json

class DicomMetadataExtractor:
    """Handles extraction of DICOM metadata"""
    
    @staticmethod
    def serialize_dicom_value(value):
        """Convert DICOM values to JSON-serializable types"""
        if value is None:
            return "None"
        
        # Handle pydicom MultiValue
        if hasattr(value, '__iter__') and not isinstance(value, (str, bytes)):
            try:
                return [DicomMetadataExtractor.serialize_dicom_value(v) for v in value]
            except:
                pass
        
        # Convert numeric types
        if isinstance(value, (int, float)):
            return value
        
        # Convert to string
        return str(value)
    
    @staticmethod
    def extract_metadata(dcm_path):
        """Extract metadata from a single DICOM file"""
        try:
            ds = pydicom.dcmread(dcm_path, stop_before_pixels=True)
            
            def get_value(tag, default="None"):
                val = ds.get(tag, default)
                return DicomMetadataExtractor.serialize_dicom_value(val)
            
            # Get acquisition time (primary) or trigger time in milliseconds (fallback)
            acq_time = get_value("AcquisitionTime")
            trigger_time = get_value("TriggerTime")
            
            return {
                'DicomPath': dcm_path,
                "SeriesDescription": get_value("SeriesDescription", "NoDescription"),
                "SeriesInstanceUID": get_value("SeriesInstanceUID"),
                "ImageType": get_value("ImageType"),
                "ScanningSequence": get_value("ScanningSequence"),
                "SequenceVariant": get_value("SequenceVariant"),
                "RepetitionTime": get_value("RepetitionTime"),
                "EchoTime": get_value("EchoTime"),
                "FlipAngle": get_value("FlipAngle"),
                "AcquisitionNumber": get_value("AcquisitionNumber"),
                "AcquisitionTime": acq_time,
                "TemporalPositionIdentifier": get_value("TemporalPositionIdentifier"),
                "FrameReferenceTime": get_value("FrameReferenceTime"),
                "TriggerTime": trigger_time,
                "NumberOfTemporalPositions": get_value("NumberOfTemporalPositions"),
                "ContrastBolusAgent": get_value("ContrastBolusAgent"),
                "ContrastBolusVolume": get_value("ContrastBolusVolume"),
                "ContrastBolusStartTime": get_value("ContrastBolusStartTime")
            }
        except Exception as e:
            print(f"Error reading {dcm_path}: {e}")
            return None
    
    # Find one DICOM file per series (one per folder). It is not feasible to read all DICOM files due to time constraints.
    # Also there is no guarantee that different DICOM files in the same series will have different metadata, 
    # so we can just read one file per series and deal with consequences either while filtering or converting to nifti.
    @staticmethod
    def find_dicom_files(patient_dir):
        """Find one .dcm file per directory (representing one series)"""
        dcm_by_folder = {}
        for dirpath, dirnames, filenames in os.walk(patient_dir):
            dcm_files_in_dir = [f for f in filenames if f.endswith('.dcm')]
            if dcm_files_in_dir:
                dcm_path = os.path.join(dirpath, dcm_files_in_dir[0])
                dcm_by_folder[dirpath] = dcm_path
        return list(dcm_by_folder.values())


class ExtractionStage:
    """Stage 1: Extract DICOM metadata"""
    
    def __init__(self):
        self.extractor = DicomMetadataExtractor()
    
    def extract_patient(self, patient_dir):
        """Extract all metadata for a patient"""
        path_parts = patient_dir.rstrip('/').split('/')
        patient_id = path_parts[-1]
        
        dcm_paths = self.extractor.find_dicom_files(patient_dir)
        if not dcm_paths:
            return {}
        
        summary = {patient_id: []}
        error_log = []
        
        for dcm_path in dcm_paths:
            metadata = self.extractor.extract_metadata(dcm_path)
            if metadata:
                summary[patient_id].append(metadata)
            else:
                error_log.append(dcm_path)
        
        return summary, error_log
    
    def save_raw_summary(self, summary, out_dir):
        """Save raw extracted data"""
        if not summary:
            return
        
        patient_id = list(summary.keys())[0]
        patient_data = summary[patient_id]
        
        # Sort by acquisition number
        patient_data_sorted = sorted(
            patient_data,
            key=lambda x: int(x.get("AcquisitionNumber", 0)) if x.get("AcquisitionNumber") != "None" else 0
        )
        
        safe_patient_id = str(patient_id).replace('/', '_').replace('\\', '_')
        os.makedirs(out_dir, exist_ok=True)
        
        output_file = os.path.join(out_dir, f"{safe_patient_id}.json")
        with open(output_file, "w") as pf:
            json.dump({patient_id: patient_data_sorted}, pf, indent=2)
        
        return output_file
    
    def save_error_log(self, error_log, patient_id, out_dir):
        """Save errors to file"""
        if not error_log:
            return
        
        os.makedirs(out_dir, exist_ok=True)
        error_log_path = os.path.join(out_dir, f"{patient_id}_error_log.txt")
        with open(error_log_path, "w") as ef:
            for error_file in error_log:
                ef.write(f"{error_file}\n")
