"""
backend/routers/consent.py — Consent management and profile initialization.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from backend.db import get_conn
from backend.active_user import public_mode, device_key

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/consent", tags=["Consent"])


class ConsentRequest(BaseModel):
    block: Optional[str] = None
    tehsil: Optional[str] = None
    village_code: Optional[str] = None
    village: str = Field(default="Unknown", description="Village name")
    panchayat: Optional[str] = Field(default=None, description="Gram Panchayat name")
    district: Optional[str] = Field(default=None, description="District name")
    state: str = Field(default="Unknown", description="State name")
    language_pref: str = Field(default="hi-IN", description="Preferred language code")
    consent: bool = Field(default=False, description="Consent flag")


class ConsentResponse(BaseModel):
    userId: int
    village: str
    panchayat: Optional[str] = None
    district: Optional[str] = None
    state: str
    language_pref: str
    consentGiven: bool
    consentAt: str


@router.post("", response_model=ConsentResponse)
def record_consent(req: ConsentRequest) -> ConsentResponse:
    """
    Record user consent and create/update household profile.
    Must be completed before any document uploads are allowed.
    """
    if not req.consent:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "CONSENT_REQUIRED", "message": "Consent must be explicitly accepted."},
        )

    now_iso = datetime.now(timezone.utc).isoformat()
    conn = get_conn()
    try:
        # Check if single default user exists or create new
        cur = conn.cursor()
        if public_mode():
            cur.execute("SELECT id FROM users WHERE device_key=?", (device_key.get(),))
        else:
            cur.execute("SELECT id FROM users ORDER BY id ASC LIMIT 1")
        row = cur.fetchone()

        if row:
            user_id = row["id"]
            cur.execute(
                """
                UPDATE users
                SET village = ?, panchayat = ?, district = ?, state = ?,
                    language_pref = ?, consent_given = 1, consent_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (req.village, req.panchayat, req.district, req.state, req.language_pref, now_iso, now_iso, user_id),
            )
        else:
            cur.execute(
                """
                INSERT INTO users (village, panchayat, district, state, language_pref, consent_given, consent_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (req.village, req.panchayat, req.district, req.state, req.language_pref, now_iso, now_iso, now_iso),
            )
            user_id = cur.lastrowid

        if public_mode():
            cur.execute("UPDATE users SET device_key=? WHERE id=?", (device_key.get(), user_id))
        cur.execute("UPDATE users SET block=?, tehsil=?, village_code=? WHERE id=?", (req.block,req.tehsil,req.village_code,user_id))
        conn.commit()

        return ConsentResponse(
            userId=user_id,
            village=req.village,
            panchayat=req.panchayat,
            district=req.district,
            state=req.state,
            language_pref=req.language_pref,
            consentGiven=True,
            consentAt=now_iso,
        )
    finally:
        conn.close()
