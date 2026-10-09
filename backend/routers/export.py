"""
backend/routers/export.py — PDF, Plain Text, and JSON Export Endpoints.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Response, status
from fastapi.responses import PlainTextResponse

from backend.exporter import (
    generate_json_export,
    generate_pdf_export,
    generate_text_export,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/export", tags=["Export"])


@router.get("/pdf")
def export_pdf(
    lang: str = "hi-IN",
    x_user_id: Optional[str] = Header(default=None),
):
    """Download citizen summary as a styled Devanagari PDF report."""
    user_id = int(x_user_id) if x_user_id and x_user_id.isdigit() else 1
    try:
        pdf_bytes = generate_pdf_export(user_id=user_id, lang=lang)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=graam_gyaan_summary_{user_id}.pdf"},
        )
    except Exception as e:
        log.error("PDF generation failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to generate PDF: {e}")


@router.get("/text", response_class=PlainTextResponse)
def export_text(
    lang: str = "hi-IN",
    x_user_id: Optional[str] = Header(default=None),
) -> str:
    """Get copyable plain text summary."""
    user_id = int(x_user_id) if x_user_id and x_user_id.isdigit() else 1
    try:
        return generate_text_export(user_id=user_id, lang=lang)
    except Exception as e:
        log.error("Text export failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to generate text export: {e}")


@router.get("/json")
def export_json(
    lang: str = "hi-IN",
    x_user_id: Optional[str] = Header(default=None),
) -> dict:
    """Get structured JSON export."""
    user_id = int(x_user_id) if x_user_id and x_user_id.isdigit() else 1
    try:
        return generate_json_export(user_id=user_id, lang=lang)
    except Exception as e:
        log.error("JSON export failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to generate JSON export: {e}")
