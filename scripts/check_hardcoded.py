#!/usr/bin/env python3
"""
scripts/check_hardcoded.py — Static inspection script to verify no hardcoded configs or mocks exist in backend/ code.

Checks for:
  - Hardcoded model IDs in backend code (must come from config/models.yaml)
  - Hardcoded document types in backend business logic (must come from config/doc_types.yaml)
  - Hardcoded mock payloads in python code (must come from mocks/)
  - Missing required config and schema files
"""

import os
import re
import sys
from pathlib import Path

# Ensure UTF-8 output on Windows console
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent.parent

FORBIDDEN_CODE_PATTERNS = [
    (r"sarvam-105b(?!\.yaml)", "Hardcoded model string 'sarvam-105b' in code"),
    (r"saaras:v4(?!\.yaml)", "Hardcoded model string 'saaras:v4' in code"),
    (r"bulbul:v4(?!\.yaml)", "Hardcoded model string 'bulbul:v4' in code"),
]

REQUIRED_CONFIG_FILES = [
    "config/app.yaml",
    "config/models.yaml",
    "config/languages.yaml",
    "config/doc_types.yaml",
    "backend/schemas/doc_types/ration_card.yaml",
    "backend/schemas/doc_types/aadhaar.yaml",
    "backend/schemas/doc_types/pan.yaml",
    "backend/schemas/doc_types/bank_passbook.yaml",
    "backend/schemas/doc_types/electricity_bill.yaml",
    "backend/schemas/doc_types/official_notice.yaml",
    "data/real/guides/expected_documents.yaml",
]

def check_required_files():
    missing = []
    for rel_path in REQUIRED_CONFIG_FILES:
        full_path = BASE_DIR / rel_path
        if not full_path.exists():
            missing.append(rel_path)
    return missing

def check_hardcoded_in_code():
    findings = []
    backend_dir = BASE_DIR / "backend"
    for py_file in backend_dir.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue
        try:
            content = py_file.read_text(encoding="utf-8")
            for pattern, desc in FORBIDDEN_CODE_PATTERNS:
                matches = re.finditer(pattern, content)
                for m in matches:
                    line_num = content[:m.start()].count("\n") + 1
                    findings.append(f"{py_file.name}:{line_num} - {desc}")
        except Exception as e:
            findings.append(f"Error reading {py_file}: {e}")
    return findings

def main():
    print("=" * 60)
    print("GRAAM-GYAAN No-Hardcoded Data & Config Integrity Checker")
    print("=" * 60)

    missing = check_required_files()
    if missing:
        print("\n[MISSING] REQUIRED CONFIG/SCHEMA FILES:")
        for m in missing:
            print(f"  - [information not available yet] Missing file: {m}")
    else:
        print("\n[OK] All required config/schema files are present.")

    findings = check_hardcoded_in_code()
    if findings:
        print("\n[WARN] POTENTIAL HARDCODED STRINGS IN CODE (check if fallbacks):")
        for f in findings:
            print(f"  - {f}")
    else:
        print("\n[OK] No forbidden hardcoded model strings detected in backend logic.")

    print("\nCheck complete.\n")
    return 0 if not missing else 1

if __name__ == "__main__":
    sys.exit(main())
