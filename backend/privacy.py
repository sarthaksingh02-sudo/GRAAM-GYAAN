"""
backend/privacy.py — Strict Privacy & Identifier Masking for GRAAM-GYAAN.

Preserves only the last 4 characters (e.g. XXXX-XXXX-1234).
Masking runs at extraction time BEFORE saving to DB, logging, or caching.
"""

from __future__ import annotations

import re
from typing import Any


def mask_aadhaar(val: str | None) -> str | None:
    """Mask a 12-digit Aadhaar number to XXXX-XXXX-1234."""
    if not val:
        return val
    # Remove spaces and hyphens
    cleaned = re.sub(r"[\s\-]", "", str(val).strip())
    if len(cleaned) >= 4:
        last4 = cleaned[-4:]
        return f"XXXX-XXXX-{last4}"
    return "XXXX-XXXX-XXXX"


def mask_pan(val: str | None) -> str | None:
    """Mask a 10-char PAN to XXXXXX1234."""
    if not val:
        return val
    cleaned = re.sub(r"[\s\-]", "", str(val).strip())
    if len(cleaned) >= 4:
        last4 = cleaned[-4:]
        return f"XXXXXX{last4}"
    return "XXXXXXXXXX"


def mask_last4(val: str | None, prefix_len: int = 8) -> str | None:
    """Mask generic account or identifier keeping only last 4 chars."""
    if not val:
        return val
    cleaned = re.sub(r"[\s\-]", "", str(val).strip())
    if len(cleaned) >= 4:
        last4 = cleaned[-4:]
        prefix = "X" * max(4, min(prefix_len, len(cleaned) - 4))
        return f"{prefix}{last4}"
    return "XXXX"


def mask_value_by_type(val: Any, mask_type: str | None = None) -> Any:
    """Mask a value based on specified mask type."""
    if val is None or not isinstance(val, str):
        return val

    if mask_type == "aadhaar":
        return mask_aadhaar(val)
    elif mask_type == "pan":
        return mask_pan(val)
    elif mask_type in ("last4", "account", "consumer", "ration"):
        return mask_last4(val)

    # General regex-based detection fallback
    # Aadhaar pattern: 12 consecutive digits or 4-4-4
    if re.fullmatch(r"\d{4}\s?\d{4}\s?\d{4}", val.strip()):
        return mask_aadhaar(val)
    # PAN pattern: 5 letters, 4 digits, 1 letter
    if re.fullmatch(r"[A-Z]{5}\d{4}[A-Z]", val.strip().upper()):
        return mask_pan(val)

    return val


def sanitize_extracted_dict(data: dict[str, Any], schema_fields: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Sanitize an extracted dictionary by applying schema-defined masking rules.
    Ensures raw unmasked PII never escapes this step.
    """
    field_map = {f.get("key"): f for f in schema_fields if isinstance(f, dict)}
    sanitized: dict[str, Any] = {}

    for k, v in data.items():
        field_def = field_map.get(k, {})
        is_masked = field_def.get("masked", False)
        mask_type = field_def.get("mask_type")

        if is_masked or mask_type:
            sanitized[k] = mask_value_by_type(v, mask_type or "last4")
        elif isinstance(v, list):
            # If array of members or items
            sanitized[k] = redact_identifiers(v)
        else:
            # Check if value accidentally matches PII pattern
            if isinstance(v, str):
                if re.search(r"\b\d{4}\s?\d{4}\s?\d{4}\b", v):
                    sanitized[k] = re.sub(
                        r"\b\d{4}\s?\d{4}\s?(\d{4})\b",
                        r"XXXX-XXXX-\1",
                        v,
                    )
                else:
                    sanitized[k] = redact_identifiers(v)
            else:
                sanitized[k] = redact_identifiers(v)

    return sanitized


def redact_identifiers(value):
    """Recursively redact identifiers in free text, nested OCR and conversations."""
    if isinstance(value, str):
        value = re.sub(r"(?<!\d)\d{4}[ -]?\d{4}[ -]?\d{4}(?!\d)", "[ID removed]", value)
        return re.sub(r"\b[A-Z]{5}\d{4}[A-Z]\b", "[PAN removed]", value)
    if isinstance(value, list):
        return [redact_identifiers(item) for item in value]
    if isinstance(value, dict):
        return {key: redact_identifiers(item) for key, item in value.items()}
    return value
