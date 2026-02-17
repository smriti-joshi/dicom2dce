import pydicom
import os
import json
from tqdm import tqdm
import numpy as np
import re

from dicom_reader import ExtractionStage
from dce_filter import FilteringStage


class DicomProcessingPipeline:
    """Orchestrates the DICOM processing pipeline"""
    
    def __init__(self):
        self.extractor_stage = ExtractionStage()
        self.filter_stage = FilteringStage()
    
    def extract_and_save(self, patient_dir, output_path, save=True):
        """Run extraction stage"""
        summary, error_log = self.extractor_stage.extract_patient(patient_dir)
        
        if save:
            if summary:
                self.extractor_stage.save_raw_summary(summary, output_path)
            
            if error_log:
                patient_id = list(summary.keys())[0] if summary else "unknown"
                self.extractor_stage.save_error_log(error_log, patient_id, output_path)
        
        return summary
    
    def filter_and_save(self, json_path, output_path, save=True):
        """Run filtering stage"""
        summary = self.filter_stage.load_summary(json_path)
        patient_id = list(summary.keys())[0]
        metadata_list = summary[patient_id]
        
        filtered = self.filter_stage.filter_dce_sequences(metadata_list)
        grouped = self.filter_stage.group_by_tr_te(filtered)
        
        if save:
            output_file = self.filter_stage.save_filtered_results(grouped, patient_id, output_path, filtered_metadata=filtered)
        
        return grouped
    
    def extract_filter_and_save(self, patient_dir, extract_output_path, filter_output_path, 
                                save_extracted=True, save_filtered=True):
        """Run extraction and filtering in one pass"""
        # Extract
        try: 
            summary, error_log = self.extractor_stage.extract_patient(patient_dir)
        except Exception as e:
            print(f"Error extracting patient {patient_dir}: {e}")
            return None, None
        
        if not summary:
            return None, None
        
        patient_id = list(summary.keys())[0]
        metadata_list = summary[patient_id]
        
        # Save extracted (optional)
        if save_extracted:
            self.extractor_stage.save_raw_summary(summary, extract_output_path)
            if error_log:
                self.extractor_stage.save_error_log(error_log, patient_id, extract_output_path)
        
        # Filter
        filtered = self.filter_stage.filter_dce_sequences(metadata_list)
        grouped = self.filter_stage.group_by_tr_te(filtered)
        
        # Save filtered (optional)
        if save_filtered:
            self.filter_stage.save_filtered_results(grouped, patient_id, filter_output_path, metadata=metadata_list)
        
        return summary, grouped


