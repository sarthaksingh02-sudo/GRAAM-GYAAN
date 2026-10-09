"""
backend/routers/documents.py — Document upload, polling, confirmation, and audio playback.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    Header,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from PIL import Image
from pydantic import BaseModel, Field
import pypdf

from backend.config_loader import get_app_config, get_doc_schema
from backend.db import get_conn
from backend.active_user import get_active_user_id
from backend.document_processor import (
    calculate_missing_documents,
    compute_age_years,
    process_document_job,
)
from backend.privacy import mask_value_by_type, redact_identifiers, sanitize_extracted_dict
from backend.sarvam_client import SarvamClient

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/documents", tags=["Documents"])

BASE_DIR = Path(__file__).resolve().parent.parent.parent


class ExtractedFieldItem(BaseModel):
    key: str
    label: str
    value: Any = None
    confidence: Optional[float] = 0.95
    masked: bool = False


class NoticeDetails(BaseModel):
    summary: Optional[str] = None
    whatToDo: List[str] = Field(default_factory=list)
    deadline: Optional[str] = None
    documentsNeeded: List[str] = Field(default_factory=list)
    audioUrl: Optional[str] = None
    audioAvailable: bool = False


class DocumentJobResponse(BaseModel):
    jobId: str
    status: str
    docType: Optional[str] = None
    category: Optional[str] = None
    extractedFields: List[ExtractedFieldItem] = Field(default_factory=list)
    noticeDetails: Optional[NoticeDetails] = None
    error: Optional[str] = None
    isMock: bool = False
    mode: str = "live"


class ConfirmField(BaseModel):
    key: str
    value: Any = None


class ConfirmRequest(BaseModel):
    memberId: Optional[int] = None
    createFamilyMembers: bool = False
    fields: List[ConfirmField] = Field(default_factory=list)


_get_active_user_id = get_active_user_id


def _run_job_in_background(job_id: str, user_id: int, file_path: Path, lang: str, original_filename: str | None = None):
    """Background task runner for document AI job."""
    log.info("Starting background processing for job %s (user %d)", job_id, user_id)
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE document_jobs SET status = 'processing', updated_at = ? WHERE job_id = ?",
            (datetime.now(timezone.utc).isoformat(), job_id),
        )
        conn.commit()

        app_cfg = get_app_config()
        audio_dir = BASE_DIR / app_cfg.get("audio_output_dir", "uploads/audio")
        client = SarvamClient()

        result = process_document_job(
            file_path=file_path,
            lang=lang,
            client=client,
            audio_dir=audio_dir,
            original_filename=original_filename,
        )

        result = redact_identifiers(result)
        now_iso = datetime.now(timezone.utc).isoformat()
        cur.execute(
            """
            UPDATE document_jobs
            SET status = 'ready', doc_type = ?, category = ?, result_json = ?, updated_at = ?
            WHERE job_id = ?
            """,
            (
                result.get("docType"),
                result.get("category"),
                json.dumps(result, ensure_ascii=False),
                now_iso,
                job_id,
            ),
        )
        conn.commit()
        log.info("Background job %s completed successfully", job_id)
    except Exception as e:
        log.error("Background job %s failed: %s", job_id, e)
        now_iso = datetime.now(timezone.utc).isoformat()
        cur.execute(
            """
            UPDATE document_jobs
            SET status = 'failed', error_code = 'PROCESSING_FAILED', updated_at = ?
            WHERE job_id = ?
            """,
            (now_iso, job_id),
        )
        conn.commit()
    finally:
        conn.close()
        file_path.unlink(missing_ok=True)


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    lang: str = Form(default="hi-IN"),
    x_user_id: Optional[str] = Header(default=None),
) -> dict:
    """
    Upload camera photo (JPG/PNG/HEIC) or PDF (up to 10 pages).
    Rejects invalid types or unconsented users.
    Downscales large photos and processes asynchronously in background.
    """
    user_id = _get_active_user_id(x_user_id)
    app_cfg = get_app_config()

    # Check extension
    filename = file.filename or "upload"
    ext = Path(filename).suffix.lower()
    allowed_exts = app_cfg.get("allowed_extensions", [".jpg", ".jpeg", ".png", ".heic", ".pdf"])

    if ext not in allowed_exts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "INVALID_FILE_TYPE",
                "message": f"Unsupported file type '{ext}'. Allowed: {', '.join(allowed_exts)}",
            },
        )

    content = await file.read(10 * 1024 * 1024 + 1)
    max_bytes = app_cfg.get("max_upload_bytes", 10485760)
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "FILE_TOO_LARGE", "message": "File exceeds 10MB limit."},
        )

    job_id = f"doc-job-{uuid.uuid4().hex[:12]}"
    user_dir = BASE_DIR / app_cfg.get("upload_dir", "uploads") / f"user_{user_id}"
    user_dir.mkdir(parents=True, exist_ok=True)

    saved_path: Path

    if ext == ".pdf":
        # Check PDF page limit
        try:
            reader = pypdf.PdfReader(io.BytesIO(content))
            max_pages = app_cfg.get("max_pdf_pages", 10)
            if len(reader.pages) > max_pages:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "error": "PDF_PAGE_LIMIT_EXCEEDED",
                        "message": f"PDF has {len(reader.pages)} pages, exceeding limit of {max_pages}.",
                    },
                )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "INVALID_FILE_TYPE", "message": f"Could not read PDF: {e}"},
            )

        saved_path = user_dir / f"{job_id}.pdf"
        saved_path.write_bytes(content)

    else:
        # Camera photo: downscale large images and normalize to JPG
        try:
            img = Image.open(io.BytesIO(content))
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            max_dim = app_cfg.get("max_image_dimension", 2048)
            if max(img.size) > max_dim:
                img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
            saved_path = user_dir / f"{job_id}.jpg"
            img.save(saved_path, format="JPEG", quality=85)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "INVALID_FILE_TYPE", "message": f"Failed to process image: {e}"},
            )

    # Record job in database
    conn = get_conn()
    try:
        cur = conn.cursor()
        now_iso = datetime.now(timezone.utc).isoformat()
        cur.execute(
            """
            INSERT INTO document_jobs (job_id, user_id, status, file_path, lang, created_at, updated_at)
            VALUES (?, ?, 'queued', ?, ?, ?, ?)
            """,
            (job_id, user_id, str(saved_path), lang, now_iso, now_iso),
        )
        conn.commit()
    finally:
        conn.close()

    # Spawn background task
    background_tasks.add_task(_run_job_in_background, job_id, user_id, saved_path, lang, filename)

    return {"jobId": job_id}


@router.get("/{job_id}", response_model=DocumentJobResponse)
def get_document_job(job_id: str, x_user_id: Optional[str] = Header(default=None)) -> DocumentJobResponse:
    """Poll the status of a document extraction job."""
    user_id = _get_active_user_id(x_user_id)
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM document_jobs WHERE job_id = ? AND user_id = ?", (job_id, user_id))
        row = cur.fetchone()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "JOB_NOT_FOUND", "message": f"Job {job_id} not found."},
            )

        job_status = row["status"]
        if job_status == "failed":
            return DocumentJobResponse(
                jobId=job_id,
                status="failed",
                error=row["error_code"] or "PROCESSING_FAILED",
            )

        if job_status in ("queued", "processing"):
            return DocumentJobResponse(jobId=job_id, status=job_status)

        # Parse ready result
        res_json = row["result_json"]
        if not res_json:
            return DocumentJobResponse(jobId=job_id, status="ready")

        data = json.loads(res_json)
        fields = [
            ExtractedFieldItem(
                key=f.get("key", ""),
                label=f.get("label", ""),
                value=f.get("value"),
                confidence=f.get("confidence", 0.95),
                masked=f.get("masked", False),
            )
            for f in data.get("extractedFields", [])
        ]

        notice_data = data.get("noticeDetails")
        notice = NoticeDetails(**notice_data) if notice_data else None

        return DocumentJobResponse(
            jobId=job_id,
            status="ready",
            docType=data.get("docType"),
            category=data.get("category"),
            extractedFields=fields,
            noticeDetails=notice,
            isMock=data.get("isMock", False),
            mode=data.get("mode", "live"),
        )
    finally:
        conn.close()


@router.post("/{job_id}/confirm")
def confirm_document(
    job_id: str,
    req: ConfirmRequest,
    x_user_id: Optional[str] = Header(default=None),
) -> dict:
    """
    Confirm user-reviewed fields, bind document to family member,
    and recalculate missing documents checklist.
    """
    user_id = _get_active_user_id(x_user_id)
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM document_jobs WHERE job_id = ? AND user_id = ?", (job_id, user_id))
        job_row = cur.fetchone()
        if not job_row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "JOB_NOT_FOUND", "message": f"Job {job_id} not found."},
            )

        if job_row["status"] != "ready":
            raise HTTPException(409, "Document is not ready for approval")
        existing = cur.execute("SELECT id FROM documents WHERE job_id = ? AND user_id = ?", (job_id, user_id)).fetchone()
        if existing:
            return {"success": True, "documentId": existing["id"], "alreadyConfirmed": True}
        if req.memberId and not cur.execute("SELECT id FROM family_members WHERE id = ? AND user_id = ?", (req.memberId, user_id)).fetchone():
            raise HTTPException(404, "Family member not found")
        result = json.loads(job_row["result_json"] or "{}")
        if not req.fields:
            req.fields = [ConfirmField(key=f["key"], value=f.get("value")) for f in result.get("extractedFields", [])]
        if result.get("noticeDetails"):
            req.fields = [ConfirmField(key=k, value=v) for k, v in result["noticeDetails"].items() if k not in {"audioUrl", "audioAvailable"}]
        doc_type = job_row["doc_type"] or "other"
        category = job_row["category"] or "id_benefit"
        now_iso = datetime.now(timezone.utc).isoformat()

        # 1. Insert document record
        cur.execute(
            """
            INSERT INTO documents (user_id, member_id, job_id, doc_type, category, file_path, language, status, approved_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'approved', ?)
            """,
            (user_id, req.memberId, job_id, doc_type, category, job_row["file_path"], job_row["lang"], now_iso),
        )
        doc_id = cur.lastrowid

        # 2. Insert extracted fields (masked)
        fields_dict: dict[str, Any] = {}
        schema_fields = get_doc_schema(doc_type).get("fields", [])
        for f in req.fields:
            f.value = redact_identifiers(sanitize_extracted_dict({f.key: f.value}, schema_fields)[f.key])
            fields_dict[f.key] = f.value
            # Mask if identifier
            masked_val = mask_value_by_type(f.value)
            cur.execute(
                """
                INSERT INTO extracted_fields (document_id, field_name, field_label, field_value, confidence, is_masked, is_mock)
                VALUES (?, ?, ?, ?, 1.0, 1, ?)
                """,
                (doc_id, f.key, f.key, json.dumps(masked_val, ensure_ascii=False) if isinstance(masked_val, (list, dict)) else str(masked_val) if masked_val is not None else None, int(bool(result.get("isMock")))),
            )

        # 3. Handle family members update/creation
        created_members: list[dict[str, Any]] = []
        target_member_id = req.memberId

        # Auto-create members if requested (e.g. from ration card members list)
        if req.createFamilyMembers and "members" in fields_dict:
            members_data = fields_dict["members"]
            if isinstance(members_data, list):
                for m in members_data:
                    if isinstance(m, dict) and m.get("name"):
                        m_name = m.get("name")
                        m_rel = m.get("relation", "other")
                        cur.execute(
                            """
                            INSERT INTO family_members (user_id, name, relation, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (user_id, m_name, m_rel, now_iso, now_iso),
                        )
                        new_id = cur.lastrowid
                        created_members.append({"id": new_id, "name": m_name, "relation": m_rel})

        # Update target family member if specified or if self/head
        if not target_member_id and category == "id_benefit":
            # Check if there is an existing member matching name or default 'self'
            cur.execute("SELECT id FROM family_members WHERE user_id = ? AND relation = 'self' LIMIT 1", (user_id,))
            self_row = cur.fetchone()
            if self_row:
                target_member_id = self_row["id"]
            else:
                # Create primary member
                name_val = fields_dict.get("name") or fields_dict.get("head_of_family") or "Primary Member"
                dob_val = fields_dict.get("dob")
                gender_val = (fields_dict.get("gender") or "").lower()
                cur.execute(
                    """
                    INSERT INTO family_members (user_id, name, dob, gender, relation, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 'self', ?, ?)
                    """,
                    (user_id, name_val, dob_val, gender_val, now_iso, now_iso),
                )
                target_member_id = cur.lastrowid

        # Update member with extracted details
        if target_member_id:
            cur.execute("SELECT * FROM family_members WHERE id = ?", (target_member_id,))
            mem_row = cur.fetchone()
            if mem_row:
                up_name = fields_dict.get("name") or fields_dict.get("head_of_family") or mem_row["name"]
                up_dob = fields_dict.get("dob") or mem_row["dob"]
                up_gender = (fields_dict.get("gender") or mem_row["gender"] or "").lower()
                cur.execute(
                    """
                    UPDATE family_members
                    SET name = ?, dob = ?, gender = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (up_name, up_dob, up_gender, now_iso, target_member_id),
                )

        # Update document's member_id link
        if target_member_id:
            cur.execute("UPDATE documents SET member_id = ? WHERE id = ?", (target_member_id, doc_id))

        conn.commit()

        # 4. Fetch updated member and compute missing documents
        member_resp = None
        if target_member_id:
            cur.execute("SELECT * FROM family_members WHERE id = ?", (target_member_id,))
            updated_mem = cur.fetchone()
            if updated_mem:
                cur.execute("SELECT doc_type FROM documents WHERE member_id = ?", (target_member_id,))
                held_docs = [r["doc_type"] for r in cur.fetchall()]
                missing_docs = calculate_missing_documents(updated_mem["relation"], held_docs)

                member_resp = {
                    "id": updated_mem["id"],
                    "name": updated_mem["name"],
                    "dob": updated_mem["dob"],
                    "ageYears": compute_age_years(updated_mem["dob"]),
                    "gender": updated_mem["gender"],
                    "relation": updated_mem["relation"],
                    "documentsHeld": held_docs,
                    "missingDocuments": missing_docs,
                }

        return {
            "success": True,
            "documentId": doc_id,
            "member": member_resp,
            "createdMembers": created_members,
        }
    finally:
        conn.close()


@router.get("/audio/{filename}")
def stream_audio(filename: str):
    """Serve generated Bulbul TTS WAV audio file."""
    from backend.active_user import public_mode
    if public_mode() and not filename.startswith("guide_"):
        user_id = get_active_user_id()
        conn = get_conn()
        try:
            url = "/api/documents/audio/" + filename
            owned = conn.execute("SELECT 1 FROM conversations WHERE user_id=? AND audio_path=?", (user_id, url)).fetchone()
            if not owned:
                owned = conn.execute("SELECT 1 FROM document_jobs WHERE user_id=? AND job_id=?", (user_id, Path(filename).stem)).fetchone()
            if not owned:
                raise HTTPException(404, "Audio file not found")
        finally:
            conn.close()
    app_cfg = get_app_config()
    audio_dir = BASE_DIR / app_cfg.get("audio_output_dir", "uploads/audio")
    audio_path = (audio_dir / filename).resolve()
    if audio_path.parent != audio_dir.resolve():
        raise HTTPException(404, "Audio file not found")
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")
    return FileResponse(audio_path, media_type="audio/wav")
