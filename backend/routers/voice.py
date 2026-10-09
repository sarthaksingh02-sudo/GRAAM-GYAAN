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
import json
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
from backend.active_user import get_active_user_id
from backend.sarvam_client import SarvamClient
from starlette.concurrency import run_in_threadpool
from backend.config_loader import get_app_config

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Voice Conversation"])
BASE_DIR = Path(__file__).resolve().parent.parent.parent


class ChatRequest(BaseModel):
    sessionId: Optional[str] = None
    message: str = Field(min_length=1, max_length=4000)
    lang: str = "hi-IN"
    confirmAction: Optional[dict[str, Any]] = None
    includeAudio: bool = True


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
    mode: str = "live"
    audioError: Optional[str] = None


class VoiceResponse(BaseModel):
    transcript: str
    assistant: ChatResponse


_get_active_user_id = get_active_user_id


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
        include_audio=req.includeAudio,
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
        mode=res.get("mode", "live"),
        audioError=res.get("audioError"),
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
    audio_bytes = await file.read(10 * 1024 * 1024 + 1)
    if not audio_bytes or len(audio_bytes) > 10 * 1024 * 1024:
        raise HTTPException(400, "Audio must be non-empty and under 10 MB")
    ext = Path(file.filename or "recording.webm").suffix.lower()
    if ext not in {".wav", ".webm", ".mp4", ".m4a", ".ogg", ".mp3"}:
        raise HTTPException(400, "Unsupported audio format")
    temp_dir = BASE_DIR / get_app_config().get("upload_dir", "uploads") / "audio_in"
    temp_dir.mkdir(parents=True, exist_ok=True)
    incoming_audio_path = temp_dir / f"{uuid.uuid4().hex}{ext}"
    incoming_audio_path.write_bytes(audio_bytes)

    client = SarvamClient()

    # Step 1: Transcribe via Saaras STT
    try:
        stt_res = await run_in_threadpool(client.transcribe, incoming_audio_path, language_code=lang)
    except Exception:
        raise HTTPException(503, "Speech recognition failed. Please retry or type your question.")
    finally:
        incoming_audio_path.unlink(missing_ok=True)
    from backend.privacy import redact_identifiers
    transcript = redact_identifiers(stt_res.get("transcript", "").strip())

    if not transcript:
        raise HTTPException(422, "No speech detected. Please speak again.")

    # Step 2: Assistant turn
    res = await run_in_threadpool(execute_assistant_turn,
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
        mode=res.get("mode", "live"),
        audioError=res.get("audioError"),
    )

    return VoiceResponse(
        transcript=transcript,
        assistant=chat_resp,
    )


@router.get("/conversations/{session_id}")
def get_conversation_history(session_id: str, x_user_id: Optional[str] = Header(default=None)) -> dict:
    user_id = get_active_user_id(x_user_id)
    """Fetch transcript history for a session."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, turn, role, content_text, audio_path, language, is_mock, created_at, metadata_json
            FROM conversations
            WHERE session_id = ? AND user_id = ?
            ORDER BY turn ASC
            """,
            (session_id, user_id),
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
                **json.loads(r["metadata_json"] or "{}"),
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


class SpeechRequest(BaseModel):
    sessionId: str
    text: str = Field(min_length=1, max_length=20000)
    lang: str = "hi-IN"

@router.post("/speech")
def speech(req: SpeechRequest, x_user_id: Optional[str] = Header(default=None)):
    import base64
    user_id = _get_active_user_id(x_user_id)
    conn = get_conn()
    try:
        row = conn.execute("SELECT id FROM conversations WHERE user_id=? AND session_id=? AND role='assistant' AND content_text=? ORDER BY id DESC LIMIT 1", (user_id,req.sessionId,req.text)).fetchone()
        if not row:
            raise HTTPException(404, "Saved answer not found")
        try:
            audio = SarvamClient().synthesize(req.text, language_code=req.lang)
            if not audio.get("audio_b64"):
                raise ValueError("Empty audio")
        except Exception:
            raise HTTPException(503,"Speech is unavailable. Your text answer is still saved.")
        directory = BASE_DIR / get_app_config().get("audio_output_dir", "uploads/audio")
        directory.mkdir(parents=True,exist_ok=True)
        name = f"conv_{uuid.uuid4().hex}.wav"
        (directory/name).write_bytes(base64.b64decode(audio["audio_b64"]))
        url = f"/api/documents/audio/{name}"
        conn.execute("UPDATE conversations SET audio_path=? WHERE id=?", (url,row["id"]))
        conn.commit()
        return {"audioUrl": url}
    finally:
        conn.close()
