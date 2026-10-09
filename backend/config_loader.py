"""
backend/config_loader.py — Dynamic runtime config, prompts, schemas, and real knowledge loader.

No hardcoded strings, models, or prompt texts in code:
Everything is loaded from files in config/, backend/schemas/, prompts/, and data/real/.
"""

from __future__ import annotations

import json
import os
import logging
from pathlib import Path
from typing import Any
import yaml

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
SCHEMAS_DIR = BASE_DIR / "backend" / "schemas" / "doc_types"
MOCKS_DIR = BASE_DIR / "mocks" / "doc_types"
PROMPTS_DIR = BASE_DIR / "prompts"
REAL_DATA_DIR = BASE_DIR / "data" / "real"
SCHEMES_DIR = REAL_DATA_DIR / "schemes"
PROJECTS_DIR = REAL_DATA_DIR / "projects"
GUIDES_DIR = REAL_DATA_DIR / "guides"


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


def load_text(file_path: Path) -> str:
    """Load text file (prompts/markdown)."""
    if not file_path.exists():
        log.warning("Prompt file not found: %s", file_path)
        return ""
    return file_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Config getters
# ---------------------------------------------------------------------------
def get_app_config() -> dict[str, Any]:
    config = load_yaml(CONFIG_DIR / "app.yaml")
    if os.getenv("DATA_DIR"):
        config["upload_dir"] = str(Path(os.environ["DATA_DIR"]) / "uploads")
        config["audio_output_dir"] = str(Path(os.environ["DATA_DIR"]) / "uploads" / "audio")
    return config


def get_models_config() -> dict[str, Any]:
    return load_yaml(CONFIG_DIR / "models.yaml")


def get_languages_config() -> dict[str, Any]:
    return load_yaml(CONFIG_DIR / "languages.yaml")


def get_doc_types_config() -> dict[str, Any]:
    return load_yaml(CONFIG_DIR / "doc_types.yaml").get("doc_types", {})


def get_doc_schema(doc_type: str) -> dict[str, Any]:
    return load_yaml(SCHEMAS_DIR / f"{doc_type}.yaml")


def get_intents_config() -> list[dict[str, Any]]:
    """Load config/intents.yaml."""
    return load_yaml(CONFIG_DIR / "intents.yaml").get("intents", [])


def get_i18n_messages() -> dict[str, Any]:
    """Load config/i18n.yaml."""
    return load_yaml(CONFIG_DIR / "i18n.yaml").get("messages", {})


def get_i18n_message(key: str, lang: str = "hi-IN", default: str = "") -> str:
    """Retrieve translated message by key and language code."""
    messages = get_i18n_messages()
    item = messages.get(key, {})
    if isinstance(item, dict):
        return item.get(lang) or item.get("hi-IN") or item.get("en-IN") or default
    return default or key


def get_prompt(name: str) -> str:
    """Load markdown prompt from prompts/{name}.md."""
    return load_text(PROMPTS_DIR / f"{name}.md")


# ---------------------------------------------------------------------------
# Knowledge layer (data/real/)
# ---------------------------------------------------------------------------
def get_all_schemes() -> list[dict[str, Any]]:
    """Load all scheme YAML files from data/real/schemes/."""
    schemes = []
    if SCHEMES_DIR.exists():
        for p in SCHEMES_DIR.glob("*.yaml"):
            data = load_yaml(p)
            if data:
                data["_file"] = p.name
                schemes.append(data)
    return schemes


def get_all_projects(district: str | None = None, state: str | None = None) -> list[dict[str, Any]]:
    """Load project YAML files from data/real/projects/."""
    projects_list = []
    if PROJECTS_DIR.exists():
        for p in PROJECTS_DIR.glob("*.yaml"):
            data = load_yaml(p)
            if data:
                data["_file"] = p.name
                projects_list.append(data)
    return projects_list


def get_needs_guide(topic: str) -> dict[str, Any]:
    """Load specific need guide from data/real/guides/{topic}_guide.yaml."""
    path = GUIDES_DIR / f"{topic}_guide.yaml"
    if not path.exists():
        path = GUIDES_DIR / f"{topic}.yaml"
    data = load_yaml(path)
    if data:
        data["_file"] = path.name
    return data


def get_expected_documents_guide() -> dict[str, Any]:
    path = GUIDES_DIR / "expected_documents.yaml"
    if not path.exists():
        log.warning("Expected documents guide missing: %s", path)
        return {}
    return load_yaml(path).get("expected_documents", {})


def get_mock_doc_result(doc_type: str) -> dict[str, Any]:
    mock_path = MOCKS_DIR / f"{doc_type}.json"
    if not mock_path.exists():
        mock_path = MOCKS_DIR / "other.json"
    return load_json(mock_path)
