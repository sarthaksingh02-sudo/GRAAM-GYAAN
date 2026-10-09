"""Single-device household selection shared by every API."""
import os
from contextvars import ContextVar
from fastapi import HTTPException

device_key = ContextVar("device_key", default=None)

def public_mode():
    return os.getenv("DEPLOYMENT_MODE") == "public"

from backend.db import get_conn


def get_active_user_id(header: str | None = None) -> int:
    if header is not None and not header.isdigit():
        raise HTTPException(400, "Invalid household ID")
    conn = get_conn()
    try:
        if public_mode():
            row = conn.execute("SELECT id, consent_given FROM users WHERE device_key = ?", (device_key.get(),)).fetchone()
        else:
            row = conn.execute(
            "SELECT id, consent_given FROM users WHERE id = ?" if header else
            "SELECT id, consent_given FROM users ORDER BY id LIMIT 1",
            (int(header),) if header else (),
        ).fetchone()
    finally:
        conn.close()
    if not row or not row["consent_given"]:
        raise HTTPException(403, {"error": "CONSENT_REQUIRED", "message": "Please accept consent and save your household first."})
    return row["id"]
