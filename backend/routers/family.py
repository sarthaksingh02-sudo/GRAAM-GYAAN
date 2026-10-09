"""
backend/routers/family.py — Family members and household profile management.

Implements:
  - GET /api/profile (with dynamically computed ageYears and missingDocuments)
  - PUT /api/profile
  - POST /api/family
  - PUT /api/family/:memberId
  - DELETE /api/family/:memberId
  - DELETE /api/data (deletes DB records and disk files for user)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import shutil
from datetime import datetime, timezone
from typing import Any, List, Optional

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field

from backend.config_loader import get_app_config
from backend.db import get_conn
from backend.document_processor import calculate_missing_documents, compute_age_years

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Profile & Family"])
BASE_DIR = Path(__file__).resolve().parent.parent.parent


class FamilyMemberCreate(BaseModel):
    name: str
    dob: Optional[str] = None
    gender: Optional[str] = None
    relation: str = "self"
    education_level: Optional[str] = None
    occupation: Optional[str] = None
    caste_category: Optional[str] = None
    is_disabled: bool = False
    land_acres: float = 0.0


class FamilyMemberUpdate(BaseModel):
    name: Optional[str] = None
    dob: Optional[str] = None
    gender: Optional[str] = None
    relation: Optional[str] = None
    education_level: Optional[str] = None
    occupation: Optional[str] = None
    caste_category: Optional[str] = None
    is_disabled: Optional[bool] = None
    land_acres: Optional[float] = None


class ProfileUpdateRequest(BaseModel):
    village: Optional[str] = None
    panchayat: Optional[str] = None
    district: Optional[str] = None
    state: Optional[str] = None
    language_pref: Optional[str] = None


def _get_user_id(x_user_id: Optional[str] = None) -> int:
    conn = get_conn()
    try:
        cur = conn.cursor()
        if x_user_id and x_user_id.isdigit():
            cur.execute("SELECT id FROM users WHERE id = ?", (int(x_user_id),))
        else:
            cur.execute("SELECT id FROM users ORDER BY id ASC LIMIT 1")
        row = cur.fetchone()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "PROFILE_NOT_FOUND", "message": "No profile found. Please record consent first."},
            )
        return row["id"]
    finally:
        conn.close()


@router.get("/profile")
def get_profile(x_user_id: Optional[str] = Header(default=None)) -> dict:
    """Get household profile with all members and computed ageYears & missingDocuments."""
    user_id = _get_user_id(x_user_id)
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        user_row = cur.fetchone()
        if not user_row:
            raise HTTPException(status_code=404, detail="User not found")

        # Fetch family members
        cur.execute("SELECT * FROM family_members WHERE user_id = ? ORDER BY id ASC", (user_id,))
        member_rows = cur.fetchall()

        # Fetch documents
        cur.execute("SELECT * FROM documents WHERE user_id = ? ORDER BY id ASC", (user_id,))
        doc_rows = cur.fetchall()

        members = []
        for m in member_rows:
            mem_id = m["id"]
            # Get documents held by this member
            held_docs = [d["doc_type"] for d in doc_rows if d["member_id"] == mem_id]
            missing_docs = calculate_missing_documents(m["relation"], held_docs)

            members.append({
                "id": mem_id,
                "name": m["name"],
                "dob": m["dob"],
                "ageYears": compute_age_years(m["dob"]),
                "gender": m["gender"],
                "relation": m["relation"],
                "education_level": m["education_level"],
                "occupation": m["occupation"],
                "caste_category": m["caste_category"],
                "is_disabled": bool(m["is_disabled"]),
                "land_acres": m["land_acres"],
                "documentsHeld": held_docs,
                "missingDocuments": missing_docs,
            })

        documents = [
            {
                "id": d["id"],
                "member_id": d["member_id"],
                "doc_type": d["doc_type"],
                "category": d["category"],
                "uploaded_at": d["uploaded_at"],
                "status": d["status"],
            }
            for d in doc_rows
        ]

        return {
            "household": {
                "id": user_row["id"],
                "village": user_row["village"],
                "panchayat": user_row["panchayat"],
                "district": user_row["district"],
                "state": user_row["state"],
                "language_pref": user_row["language_pref"],
                "consentGiven": bool(user_row["consent_given"]),
                "consentAt": user_row["consent_at"],
            },
            "familyMembers": members,
            "documents": documents,
        }
    finally:
        conn.close()


@router.put("/profile")
def update_profile(req: ProfileUpdateRequest, x_user_id: Optional[str] = Header(default=None)) -> dict:
    """Update household metadata."""
    user_id = _get_user_id(x_user_id)
    conn = get_conn()
    try:
        cur = conn.cursor()
        now_iso = datetime.now(timezone.utc).isoformat()
        cur.execute(
            """
            UPDATE users
            SET village = COALESCE(?, village),
                panchayat = COALESCE(?, panchayat),
                district = COALESCE(?, district),
                state = COALESCE(?, state),
                language_pref = COALESCE(?, language_pref),
                updated_at = ?
            WHERE id = ?
            """,
            (req.village, req.panchayat, req.district, req.state, req.language_pref, now_iso, user_id),
        )
        conn.commit()
        return {"success": True, "message": "Profile updated successfully."}
    finally:
        conn.close()


@router.post("/family", status_code=status.HTTP_201_CREATED)
def add_family_member(req: FamilyMemberCreate, x_user_id: Optional[str] = Header(default=None)) -> dict:
    """Add a new family member to household."""
    user_id = _get_user_id(x_user_id)
    conn = get_conn()
    try:
        cur = conn.cursor()
        now_iso = datetime.now(timezone.utc).isoformat()
        cur.execute(
            """
            INSERT INTO family_members (
                user_id, name, dob, gender, relation,
                education_level, occupation, caste_category,
                is_disabled, land_acres, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                req.name,
                req.dob,
                req.gender,
                req.relation,
                req.education_level,
                req.occupation,
                req.caste_category,
                1 if req.is_disabled else 0,
                req.land_acres,
                now_iso,
                now_iso,
            ),
        )
        new_id = cur.lastrowid
        conn.commit()

        missing_docs = calculate_missing_documents(req.relation, [])

        return {
            "id": new_id,
            "name": req.name,
            "dob": req.dob,
            "ageYears": compute_age_years(req.dob),
            "gender": req.gender,
            "relation": req.relation,
            "education_level": req.education_level,
            "occupation": req.occupation,
            "caste_category": req.caste_category,
            "is_disabled": req.is_disabled,
            "land_acres": req.land_acres,
            "documentsHeld": [],
            "missingDocuments": missing_docs,
        }
    finally:
        conn.close()


@router.put("/family/{member_id}")
def update_family_member(
    member_id: int,
    req: FamilyMemberUpdate,
    x_user_id: Optional[str] = Header(default=None),
) -> dict:
    """Update family member details."""
    user_id = _get_user_id(x_user_id)
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM family_members WHERE id = ? AND user_id = ?", (member_id, user_id))
        mem = cur.fetchone()
        if not mem:
            raise HTTPException(status_code=404, detail="Family member not found")

        now_iso = datetime.now(timezone.utc).isoformat()
        cur.execute(
            """
            UPDATE family_members
            SET name = COALESCE(?, name),
                dob = COALESCE(?, dob),
                gender = COALESCE(?, gender),
                relation = COALESCE(?, relation),
                education_level = COALESCE(?, education_level),
                occupation = COALESCE(?, occupation),
                caste_category = COALESCE(?, caste_category),
                is_disabled = COALESCE(?, is_disabled),
                land_acres = COALESCE(?, land_acres),
                updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (
                req.name,
                req.dob,
                req.gender,
                req.relation,
                req.education_level,
                req.occupation,
                req.caste_category,
                1 if req.is_disabled else (0 if req.is_disabled is not None else None),
                req.land_acres,
                now_iso,
                member_id,
                user_id,
            ),
        )
        conn.commit()

        # Fetch updated
        cur.execute("SELECT * FROM family_members WHERE id = ?", (member_id,))
        updated = cur.fetchone()

        cur.execute("SELECT doc_type FROM documents WHERE member_id = ?", (member_id,))
        held_docs = [r["doc_type"] for r in cur.fetchall()]
        missing_docs = calculate_missing_documents(updated["relation"], held_docs)

        return {
            "id": updated["id"],
            "name": updated["name"],
            "dob": updated["dob"],
            "ageYears": compute_age_years(updated["dob"]),
            "gender": updated["gender"],
            "relation": updated["relation"],
            "education_level": updated["education_level"],
            "occupation": updated["occupation"],
            "caste_category": updated["caste_category"],
            "is_disabled": bool(updated["is_disabled"]),
            "land_acres": updated["land_acres"],
            "documentsHeld": held_docs,
            "missingDocuments": missing_docs,
        }
    finally:
        conn.close()


@router.delete("/family/{member_id}")
def delete_family_member(member_id: int, x_user_id: Optional[str] = Header(default=None)) -> dict:
    """Delete a family member."""
    user_id = _get_user_id(x_user_id)
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM family_members WHERE id = ? AND user_id = ?", (member_id, user_id))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Family member not found")
        conn.commit()
        return {"success": True, "message": "Family member deleted successfully."}
    finally:
        conn.close()


@router.delete("/data")
def delete_all_user_data(x_user_id: Optional[str] = Header(default=None)) -> dict:
    """
    Strict privacy compliance: delete all profile data, family members,
    documents, extracted fields, and purge uploaded files from disk.
    """
    user_id = _get_user_id(x_user_id)
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM extracted_fields WHERE document_id IN (SELECT id FROM documents WHERE user_id = ?)", (user_id,))
        cur.execute("DELETE FROM documents WHERE user_id = ?", (user_id,))
        cur.execute("DELETE FROM document_jobs WHERE user_id = ?", (user_id,))
        cur.execute("DELETE FROM family_members WHERE user_id = ?", (user_id,))
        cur.execute("DELETE FROM conversations WHERE user_id = ?", (user_id,))
        cur.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()

        # Delete physical user uploads folder
        app_cfg = get_app_config()
        user_upload_dir = BASE_DIR / app_cfg.get("upload_dir", "uploads") / f"user_{user_id}"
        if user_upload_dir.exists():
            shutil.rmtree(user_upload_dir, ignore_errors=True)

        return {"success": True, "message": "All user data and uploaded files successfully wiped."}
    finally:
        conn.close()
