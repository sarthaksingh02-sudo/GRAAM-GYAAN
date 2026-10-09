"""
backend/config_loader.py — Dynamic runtime config and schema loader for GRAAM-GYAAN.

No hardcoded constants in code: all configs, models, doc types, schemas,
and guides are loaded dynamically from files on disk.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
import yaml

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
SCHEMAS_DIR = BASE_DIR / "backend" / "schemas" / "doc_types"
MOCKS_DIR = BASE_DIR / "mocks" / "doc_types"
GUIDES_DIR = BASE_DIR / "data" / "real" / "guides"


def load_yaml(file_path: Path) -> dict[str, Any]:
    """Load a YAML file safely; returns empty dict if missing or invalid."""
    if not file_path.exists():
        log.warning("Config/data file not found: %s", file_path)
        return {}
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data if isinstance(data, dict) else {}
    except Exception as e:
        log.error("Error loading YAML %s: %s", file_path, e)
        return {}


def load_json(file_path: Path) -> dict[str, Any]:
    """Load a JSON file safely."""
    if not file_path.exists():
        log.warning("Mock/JSON file not found: %s", file_path)
        return {}
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.error("Error loading JSON %s: %s", file_path, e)
        return {}


def get_app_config() -> dict[str, Any]:
    """Load config/app.yaml."""
    return load_yaml(CONFIG_DIR / "app.yaml")


def get_models_config() -> dict[str, Any]:
    """Load config/models.yaml."""
    return load_yaml(CONFIG_DIR / "models.yaml")


def get_languages_config() -> dict[str, Any]:
    """Load config/languages.yaml."""
    return load_yaml(CONFIG_DIR / "languages.yaml")


def get_doc_types_config() -> dict[str, Any]:
    """Load config/doc_types.yaml."""
    return load_yaml(CONFIG_DIR / "doc_types.yaml").get("doc_types", {})


def get_doc_schema(doc_type: str) -> dict[str, Any]:
    """Load backend/schemas/doc_types/{doc_type}.yaml."""
    schema_path = SCHEMAS_DIR / f"{doc_type}.yaml"
    return load_yaml(schema_path)


def get_expected_documents_guide() -> dict[str, Any]:
    """
    Load data/real/guides/expected_documents.yaml.
    If missing, returns empty dict and logs warning per requirement.
    """
    path = GUIDES_DIR / "expected_documents.yaml"
    if not path.exists():
        log.warning("Expected documents guide missing: %s", path)
        return {}
    return load_yaml(path).get("expected_documents", {})


def get_mock_doc_result(doc_type: str) -> dict[str, Any]:
    """Load mocks/doc_types/{doc_type}.json."""
    mock_path = MOCKS_DIR / f"{doc_type}.json"
    if not mock_path.exists():
        mock_path = MOCKS_DIR / "other.json"
    return load_json(mock_path)
