"""
backend/document_processor.py — Document classification, Sarvam Extract/Digitise, and LLM processing.

Handles:
  - Document type classification (Digitise + keywords -> LLM fallback)
  - ID/Benefit extraction with YAML schemas and PII masking
  - Notice processing (summary, whatToDo, deadline, documentsNeeded, TTS audio)
  - Missing documents checklist recomputation from expected_documents.yaml
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from backend.config_loader import (
    get_app_config,
    get_doc_schema,
    get_doc_types_config,
    get_expected_documents_guide,
    get_mock_doc_result,
)
from backend.privacy import mask_value_by_type, sanitize_extracted_dict, redact_identifiers
from backend.sarvam_client import SarvamClient

log = logging.getLogger(__name__)


def compute_age_years(dob_str: str | None) -> int | None:
    """Compute age in years from DOB string (YYYY-MM-DD or YYYY). Never stored."""
    if not dob_str:
        return None
    try:
        from datetime import date
        dob_str = str(dob_str).strip()
        if len(dob_str) == 4 and dob_str.isdigit():
            return date.today().year - int(dob_str)
        # Parse ISO date or DD/MM/YYYY
        if "-" in dob_str:
            parts = [int(p) for p in dob_str.split("-")]
            if len(parts) == 3:
                dob_date = date(parts[0], parts[1], parts[2])
                today = date.today()
                return today.year - dob_date.year - ((today.month, today.day) < (dob_date.month, dob_date.day))
        elif "/" in dob_str:
            parts = [int(p) for p in dob_str.split("/")]
            if len(parts) == 3:
                # DD/MM/YYYY
                dob_date = date(parts[2], parts[1], parts[0])
                today = date.today()
                return today.year - dob_date.year - ((today.month, today.day) < (dob_date.month, dob_date.day))
    except Exception:
        pass
    return None


def calculate_missing_documents(relation: str | None, documents_held: list[str]) -> list[dict[str, Any]]:
    """
    Recompute member's missing documents from expected_documents.yaml.
    If file missing or empty, returns [] and logs warning.
    """
    guide = get_expected_documents_guide()
    if not guide:
        return []

    rel_key = (relation or "default").lower().strip()
    expected_list = guide.get(rel_key) or guide.get("default", [])

    held_set = set(d.lower().strip() for d in documents_held)
    missing = []
    for item in expected_list:
        doc_type = item.get("doc_type", "")
        if doc_type.lower() not in held_set:
            missing.append({
                "doc_type": doc_type,
                "title": item.get("title", doc_type),
                "mandatory": item.get("mandatory", False),
            })
    return missing


def classify_document(text: str, client: SarvamClient, language: str = "hi-IN") -> str:
    """
    Classify document type using keyword matching, falling back to LLM.
    Returns one of: ration_card, aadhaar, pan, bank_passbook, electricity_bill, official_notice, other.
    """
    doc_types_cfg = get_doc_types_config()
    text_lower = text.lower()

    scores: dict[str, int] = {}
    for dtype, info in doc_types_cfg.items():
        if dtype == "other":
            continue
        keywords = info.get("keywords", [])
        score = sum(1 for kw in keywords if kw.lower() in text_lower)
        if score > 0:
            scores[dtype] = score

    if scores:
        # Pick highest scoring doc_type
        best_match = max(scores, key=scores.get)
        log.info("[CLASSIFIER] Keyword match: %s (score=%d)", best_match, scores[best_match])
        return best_match

    # Fallback to LLM if keyword rules are unsure
    if not client.mock and text.strip():
        try:
            prompt = (
                "You are a document classifier for Indian rural administrative documents. "
                "Classify the following text into exactly ONE category from: "
                "ration_card, aadhaar, pan, bank_passbook, electricity_bill, official_notice, other.\n"
                "Return ONLY the category string with no other text.\n\n"
                f"Document text snippet:\n{text[:1500]}"
            )
            resp = client.chat([{"role": "user", "content": prompt}])
            res = resp.get("content", "").strip().lower()
            for candidate in ("ration_card", "aadhaar", "pan", "bank_passbook", "electricity_bill", "official_notice", "other"):
                if candidate in res:
                    log.info("[CLASSIFIER] LLM match: %s", candidate)
                    return candidate
        except Exception as e:
            log.warning("[CLASSIFIER] LLM classification fallback failed: %s", e)

    return "official_notice" if ("notice" in text_lower or "सूचना" in text_lower) else "other"


def process_document_job(
    file_path: Path,
    lang: str = "hi-IN",
    client: SarvamClient | None = None,
    audio_dir: Path | None = None,
    original_filename: str | None = None,
) -> dict[str, Any]:
    """
    Main background pipeline for processing an uploaded document.
    """
    client = client or SarvamClient()
    doc_types_cfg = get_doc_types_config()

    # Step 1: Digitise OCR pass
    digitise_res = client.doc_digitise(file_path, language=lang, original_filename=original_filename)
    ocr_text = digitise_res.get("text") or ""
    if not ocr_text and digitise_res.get("download_url"):
        # Live mode download
        try:
            import httpx
            with httpx.Client(timeout=15.0) as http_client:
                r = http_client.get(digitise_res["download_url"])
                if r.status_code == 200:
                    ocr_text = r.text
        except Exception as e:
            log.warning("Could not download digitised markdown: %s", e)

    if not ocr_text.strip():
        raise ValueError("No readable text was found in this document")
    ocr_text = redact_identifiers(ocr_text)

    # Step 2: Classify doc type
    doc_type = classify_document(ocr_text, client, language=lang)
    doc_meta = doc_types_cfg.get(doc_type, {})
    category = doc_meta.get("category", "notice_other")

    extracted_fields: list[dict[str, Any]] = []
    notice_details: dict[str, Any] | None = None

    if category == "id_benefit":
        # ID / Benefit document extraction with schema
        schema = get_doc_schema(doc_type)
        extract_res = client.doc_extract(file_path, schema=schema, doc_type=doc_type, language=lang)
        raw_fields = extract_res.get("result", {})

        # Format into ExtractedField list
        schema_fields = schema.get("fields", [])
        field_defs = {f["key"]: f for f in schema_fields if "key" in f}

        if isinstance(raw_fields, dict) and "fields" in raw_fields and isinstance(raw_fields["fields"], list):
            # Mock or pre-formatted list
            for item in raw_fields["fields"]:
                k = item.get("key")
                fdef = field_defs.get(k, {})
                masked_flag = item.get("masked", fdef.get("masked", False))
                val = item.get("value")
                if masked_flag:
                    val = mask_value_by_type(val, fdef.get("mask_type", "last4"))
                extracted_fields.append({
                    "key": k,
                    "label": item.get("label", fdef.get("label", k)),
                    "value": val,
                    "confidence": item.get("confidence", 0.95),
                    "masked": masked_flag,
                })
        elif isinstance(raw_fields, dict):
            # Dict of key-values from Sarvam Extract
            for k, fdef in field_defs.items():
                val = raw_fields.get(k)
                masked_flag = fdef.get("masked", False)
                if masked_flag and val is not None:
                    val = mask_value_by_type(val, fdef.get("mask_type", "last4"))
                extracted_fields.append({
                    "key": k,
                    "label": fdef.get("label", k),
                    "value": val,
                    "confidence": 0.95 if val is not None else 0.0,
                    "masked": masked_flag,
                })

    else:
        # Notice / Circular / Other document processing
        # Use LLM to extract strictly grounded fields: summary, whatToDo, deadline, documentsNeeded
        summary = None
        what_to_do: list[str] = []
        deadline = None
        documents_needed: list[str] = []

        if client.mock:
            mock_res = get_mock_doc_result(doc_type if doc_type == "official_notice" else "other")
            fields_list = mock_res.get("fields", [])
            for f in fields_list:
                k = f.get("key")
                v = f.get("value")
                if k == "summary":
                    summary = v
                elif k == "whatToDo" and isinstance(v, list):
                    what_to_do = v
                elif k == "deadline":
                    deadline = v
                elif k == "documentsNeeded" and isinstance(v, list):
                    documents_needed = v
        else:
            # Live LLM extraction strictly grounded in text
            prompt = (
                f"You are a rural administrative assistant in India. Analyze the following document text in {lang}.\n"
                "You must extract four fields strictly based on the text provided. Do NOT infer, invent, or guess any dates or amounts.\n"
                "- summary: A clear 2-3 sentence explanation of the notice in spoken-friendly language.\n"
                "- whatToDo: A JSON list of action steps the citizen should take.\n"
                "- deadline: The explicit deadline mentioned in the document. If NO deadline is stated, return null (never guess).\n"
                "- documentsNeeded: A JSON list of documents required.\n\n"
                "Return ONLY a valid JSON object matching:\n"
                "{\n"
                '  "summary": "...",\n'
                '  "whatToDo": ["..."],\n'
                '  "deadline": "YYYY-MM-DD or null",\n'
                '  "documentsNeeded": ["..."]\n'
                "}\n\n"
                f"Document text:\n{ocr_text}"
            )
            try:
                resp = client.chat([{"role": "user", "content": prompt}])
                content = resp.get("content", "{}")
                # Parse JSON block
                json_match = re.search(r"\{.*\}", content, re.DOTALL)
                if json_match:
                    parsed = json.loads(json_match.group(0))
                    summary = parsed.get("summary")
                    what_to_do = parsed.get("whatToDo") or []
                    deadline = parsed.get("deadline")
                    if deadline in ("null", "None", "", "not specified", "not found"):
                        deadline = None
                    documents_needed = parsed.get("documentsNeeded") or []
            except Exception as e:
                log.warning("LLM notice extraction parse error: %s", e)
                raise ValueError("Could not extract the notice. Please retry.") from e

        # Bulbul TTS generation for notice explanation
        audio_url = None
        audio_available = False
        if summary:
            try:
                tts_res = client.synthesize(summary, language_code=lang)
                if tts_res.get("audio_b64") and audio_dir:
                    audio_dir.mkdir(parents=True, exist_ok=True)
                    audio_filename = f"{file_path.stem}.wav"
                    audio_file = audio_dir / audio_filename
                    audio_bytes = base64.b64decode(tts_res["audio_b64"])
                    audio_file.write_bytes(audio_bytes)
                    audio_url = f"/api/documents/audio/{audio_filename}"
                    audio_available = True
            except Exception as e:
                log.warning("TTS audio generation failed for notice: %s", e)
                audio_available = False

        notice_details = {
            "summary": summary,
            "whatToDo": what_to_do,
            "deadline": deadline,
            "documentsNeeded": documents_needed,
            "audioUrl": audio_url,
            "audioAvailable": audio_available,
        }

    return {
        "status": "ready",
        "docType": doc_type,
        "category": category,
        "extractedFields": extracted_fields,
        "noticeDetails": notice_details,
        "isMock": client.mock,
        "mode": client.mode,
    }
