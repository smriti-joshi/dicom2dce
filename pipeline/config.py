"""
Configuration management for the dicom2dce pipeline.

Loads processing parameters from config_params.json and
path settings from config_paths.yaml.
"""

import os
import json
import re
import yaml


def load_config(config_dir=None):
    """
    Load configuration from both JSON (parameters) and YAML (paths) files.

    Args:
        config_dir: Directory containing config files. Defaults to dicom2dce package root.

    Returns:
        Merged configuration dictionary.
    """
    if config_dir is None:
        config_dir = os.path.join(os.path.dirname(__file__), "..")

    params_path = os.path.join(config_dir, "config_params.json")
    if not os.path.exists(params_path):
        raise FileNotFoundError(f"Config file not found: {params_path}")

    with open(params_path, "r") as f:
        config = json.load(f)

    paths_path = os.path.join(config_dir, "config_paths.yaml")
    if not os.path.exists(paths_path):
        raise FileNotFoundError(f"Config file not found: {paths_path}")

    with open(paths_path, "r") as f:
        paths_config = yaml.safe_load(f)

    if paths_config and "paths" in paths_config:
        config["paths"] = paths_config["paths"]

    return config


def natural_sort_key(s):
    """Return a key for natural sorting (e.g., '2' before '10')."""
    return [int(text) if text.isdigit() else text.lower()
            for text in re.split('([0-9]+)', s)]


class Config:
    """
    Singleton configuration accessor for the dicom2dce pipeline.

    Reads config_params.json (processing parameters) and config_paths.yaml (paths).
    Call ``Config.load()`` once at startup; subsequent access methods auto-load if needed.
    """

    _config = None

    @classmethod
    def load(cls, config_dir=None):
        """Load configuration from files (config_params.json and config_paths.yaml)."""
        cls._config = load_config(config_dir)

    @classmethod
    def _ensure_loaded(cls):
        """Ensure config is loaded before access."""
        if cls._config is None:
            cls.load()

    @classmethod
    def get_config(cls):
        """Get the entire config dictionary."""
        cls._ensure_loaded()
        return cls._config

    # -- Filtering parameters --------------------------------------------------

    @classmethod
    def get_max_tr(cls):
        """Maximum RepetitionTime (ms) for DCE sequence filtering."""
        cls._ensure_loaded()
        return cls._config["filtering"]["tr_te"]["max_tr"]

    @classmethod
    def get_max_te(cls):
        """Maximum EchoTime (ms) for DCE sequence filtering."""
        cls._ensure_loaded()
        return cls._config["filtering"]["tr_te"]["max_te"]

    @classmethod
    def get_image_type_exclusions(cls):
        """DICOM ImageType values to exclude (e.g. DERIVED, LOCALIZER)."""
        cls._ensure_loaded()
        return cls._config["filtering"]["image_type_exclusions"]["values"]

    @classmethod
    def get_series_desc_exclusions(cls):
        """SeriesDescription substrings to exclude (e.g. t2, adc, dwi)."""
        cls._ensure_loaded()
        return cls._config["filtering"]["series_desc_exclusions"]["values"]

    @classmethod
    def get_similarity_threshold(cls):
        """Minimum similarity (0–1) for sequence descriptions within a group."""
        cls._ensure_loaded()
        return cls._config["filtering"]["similarity_threshold"]["value"]

    @classmethod
    def get_folder_name_similarity_threshold(cls):
        """Minimum similarity (0–1) for DICOM folder names across sequences."""
        cls._ensure_loaded()
        return cls._config["consistency_checks"]["folder_name_similarity_threshold"]["value"]

    @classmethod
    def get_contrast_agent_tags(cls):
        """DICOM tags used to detect contrast agent presence."""
        cls._ensure_loaded()
        return cls._config["filtering"]["contrast_agent_tags"]["values"]

    @classmethod
    def get_dynamic_markers(cls):
        """Series description keywords indicating dynamic sequences (e.g. dyn, vibe)."""
        cls._ensure_loaded()
        return cls._config["filtering"]["dynamic_markers"]["values"]

    @classmethod
    def keep_largest_size_group(cls):
        """Whether to keep only the largest image-size group when multiple sizes exist."""
        cls._ensure_loaded()
        return cls._config["filtering"]["keep_largest_size_group"]["value"]

    # -- Consistency check parameters ------------------------------------------

    @classmethod
    def get_min_slice_count(cls):
        """Minimum acceptable slices per temporal position."""
        cls._ensure_loaded()
        return cls._config["consistency_checks"]["min_slice_count"]["value"]

    @classmethod
    def get_min_temporal_positions(cls):
        """Minimum number of temporal positions (phases) required."""
        cls._ensure_loaded()
        return cls._config["consistency_checks"]["min_temporal_positions"]["value"]

    # -- Processing options ----------------------------------------------------

    @classmethod
    def stop_before_pixels(cls):
        """Whether to skip pixel data when reading DICOMs (faster extraction)."""
        cls._ensure_loaded()
        return cls._config["processing"]["stop_before_pixels"]["value"]

    @classmethod
    def get_dicom_extension(cls):
        """File extension for DICOM files (default: .dcm)."""
        cls._ensure_loaded()
        return cls._config["processing"]["dicom_extension"]["value"]

    # -- Path settings ---------------------------------------------------------

    @classmethod
    def get_centers(cls):
        """List of medical center names to process."""
        cls._ensure_loaded()
        paths = cls._config.get("paths", {})
        centers = paths.get("centers", [])
        if isinstance(centers, dict) and "values" in centers:
            return centers["values"]
        return centers

    @classmethod
    def get_dicom_root(cls):
        """Root directory containing per-center DICOM input folders."""
        cls._ensure_loaded()
        paths = cls._config.get("paths", {})
        dicom_root = paths.get("dicom_root", "")
        if isinstance(dicom_root, dict) and "value" in dicom_root:
            return dicom_root["value"]
        return dicom_root

    @classmethod
    def get_results_dir(cls):
        """Root directory for NIfTI output and reports."""
        cls._ensure_loaded()
        paths = cls._config.get("paths", {})
        results_dir = paths.get("results_dir", "")
        if isinstance(results_dir, dict) and "value" in results_dir:
            return results_dir["value"]
        return results_dir

    @classmethod
    def get_select_ids(cls):
        """Optional list of patient IDs to process. Empty list means process all."""
        cls._ensure_loaded()
        paths = cls._config.get("paths", {})
        select_ids = paths.get("select_ids", [])
        if isinstance(select_ids, dict) and "values" in select_ids:
            return select_ids["values"]
        return select_ids or []
