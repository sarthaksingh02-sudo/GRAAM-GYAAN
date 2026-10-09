"""
backend/routers/voice.py — Voice & Text Conversation Router.

Endpoints:
  - POST /api/chat
  - POST /api/voice (Push-to-Talk audio -> Saaras STT -> assistant -> Bulbul TTS)
  - GET /api/conversations/:sessionId
  - GET /api/intents
  - GET /api/languages
"""

from __future__ import annotations

import io
import logging
import os
import uuid
from pathlib import Path
from typing import Any, List, Optional

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from backend.assistant import execute_assistant_turn, get_user_profile_data
from backend.config_loader import get_intents_config, get_languages_config
from backend.db import get_conn
from backend.sarvam_client import SarvamClient

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Voice Conversation"])
BASE_DIR = Path(__file__).resolve().parent.parent.parent


class ChatRequest(BaseModel):
    sessionId: Optional[str] = None
    message: str
    lang: str = "hi-IN"
    confirmAction: Optional[dict[str, Any]] = None


class SourceItem(BaseModel):
    name: str
    url: Optional[str] = None
    verified_date: Optional[str] = None


class ChatResponse(BaseModel):
    sessionId: str
    text: str
    audioUrl: Optional[str] = None
    audioAvailable: bool = False
    sources: List[SourceItem] = Field(default_factory=list)
    requiresConfirmation: bool = False
    pendingAction: Optional[dict[str, Any]] = None
    isMock: bool = False


class VoiceResponse(BaseModel):
    transcript: str
    assistant: ChatResponse


def _get_active_user_id(x_user_id: Optional[str] = None) -> int:
    conn = get_conn()
    try:
        cur = conn.cursor()
        if x_user_id and x_user_id.isdigit():
            cur.execute("SELECT id, consent_given FROM users WHERE id = ?", (int(x_user_id),))
        else:
            cur.execute("SELECT id, consent_given FROM users ORDER BY id ASC LIMIT 1")
        row = cur.fetchone()
        if not row:
            # Create default guest user if needed or raise
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "CONSENT_REQUIRED", "message": "Consent is required before conversing."},
            )
        return row["id"]
    finally:
        conn.close()


@router.post("/chat", response_model=ChatResponse)
def chat_turn(req: ChatRequest, x_user_id: Optional[str] = Header(default=None)) -> ChatResponse:
    """Send text query to assistant and get short, spoken-friendly grounded answer and TTS audio."""
    user_id = _get_active_user_id(x_user_id)
    session_id = req.sessionId or f"sess-{uuid.uuid4().hex[:10]}"

    res = execute_assistant_turn(
        user_id=user_id,
        session_id=session_id,
        user_text=req.message,
        lang=req.lang,
        confirm_action=req.confirmAction,
    )

    sources = [
        SourceItem(
            name=s.get("name", "Source"),
            url=s.get("url"),
            verified_date=s.get("verified_date"),
        )
        for s in res.get("sources", [])
    ]

    return ChatResponse(
        sessionId=res["sessionId"],
        text=res["text"],
        audioUrl=res.get("audioUrl"),
        audioAvailable=res.get("audioAvailable", False),
        sources=sources,
        requiresConfirmation=res.get("requiresConfirmation", False),
        pendingAction=res.get("pendingAction"),
        isMock=res.get("isMock", False),
    )


@router.post("/voice", response_model=VoiceResponse)
async def voice_turn(
    file: UploadFile = File(...),
    sessionId: Optional[str] = Form(default=None),
    lang: str = Form(default="hi-IN"),
    x_user_id: Optional[str] = Header(default=None),
) -> VoiceResponse:
    """
    Push-to-Talk voice endpoint:
    Uploads audio -> Transcribes via Saaras STT -> Executes assistant turn -> Synthesizes Bulbul TTS.
    """
    user_id = _get_active_user_id(x_user_id)
    session_id = sessionId or f"sess-{uuid.uuid4().hex[:10]}"

    # Save incoming audio file
    audio_bytes = await file.read()
    temp_dir = BASE_DIR / "uploads" / "audio_in"
    temp_dir.mkdir(parents=True, exist_ok=True)
    incoming_audio_path = temp_dir / f"{session_id}_{uuid.uuid4().hex[:6]}.wav"
    incoming_audio_path.write_bytes(audio_bytes)

    client = SarvamClient()

    # Step 1: Transcribe via Saaras STT
    stt_res = client.transcribe(incoming_audio_path, language_code=lang)
    transcript = stt_res.get("transcript", "").strip()

    if not transcript:
        transcript = "नमस्ते"

    # Step 2: Assistant turn
    res = execute_assistant_turn(
        user_id=user_id,
        session_id=session_id,
        user_text=transcript,
        lang=lang,
        client=client,
    )

    sources = [
        SourceItem(
            name=s.get("name", "Source"),
            url=s.get("url"),
            verified_date=s.get("verified_date"),
        )
        for s in res.get("sources", [])
    ]

    chat_resp = ChatResponse(
        sessionId=res["sessionId"],
        text=res["text"],
        audioUrl=res.get("audioUrl"),
        audioAvailable=res.get("audioAvailable", False),
        sources=sources,
        requiresConfirmation=res.get("requiresConfirmation", False),
        pendingAction=res.get("pendingAction"),
        isMock=res.get("isMock", False),
    )

    return VoiceResponse(
        transcript=transcript,
        assistant=chat_resp,
    )


@router.get("/conversations/{session_id}")
def get_conversation_history(session_id: str) -> dict:
    """Fetch transcript history for a session."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, turn, role, content_text, audio_path, language, is_mock, created_at
            FROM conversations
            WHERE session_id = ?
            ORDER BY turn ASC
            """,
            (session_id,),
        )
        rows = cur.fetchall()

        turns = [
            {
                "id": r["id"],
                "turn": r["turn"],
                "role": r["role"],
                "text": r["content_text"],
                "audioUrl": r["audio_path"],
                "language": r["language"],
                "isMock": bool(r["is_mock"]),
                "createdAt": r["created_at"],
            }
            for r in rows
        ]
        return {"sessionId": session_id, "turns": turns}
    finally:
        conn.close()


@router.get("/intents")
def get_intents(lang: str = "hi-IN") -> dict:
    """Return quick-question chips and supported intents from config/intents.yaml."""
    intents = get_intents_config()
    chips = []
    for it in intents:
        chip_text = it.get("chips", {}).get(lang) or it.get("chips", {}).get("hi-IN")
        if chip_text:
            chips.append({
                "id": it.get("id"),
                "text": chip_text,
                "tool": it.get("tool"),
            })
    return {"language": lang, "chips": chips, "intents": intents}


@router.get("/languages")
def get_languages() -> dict:
    """Return supported language catalog from config/languages.yaml."""
    return get_languages_config()
