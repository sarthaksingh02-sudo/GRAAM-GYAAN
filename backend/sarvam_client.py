"""
backend/sarvam_client.py — Sarvam AI client wrapper with MOCK mode and disk cache.

Usage:
    client = SarvamClient()        # reads SARVAM_MOCK, SARVAM_API_KEY from env
    result = client.chat(messages) # returns dict, MOCK-flagged if in mock mode

MOCK mode is activated by setting SARVAM_MOCK=true in the environment.
All mock responses are clearly prefixed with [MOCK] in logs and response metadata.
Never present mock outputs as real in demos.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_MOCK_ENV = os.getenv("SARVAM_MOCK", "false").lower() in ("1", "true", "yes")
_API_KEY = os.getenv("SARVAM_API_KEY", "")
_CACHE_DIR = Path(os.getenv("SARVAM_CACHE_DIR", ".cache/sarvam"))

# ---------------------------------------------------------------------------
# Canned mock responses
# ---------------------------------------------------------------------------
_MOCK_CHAT = {
    "mock": True,
    "content": "[MOCK] ग्राम-ज्ञान एक AI-संचालित ग्रामीण कल्याण सहायक है जो सरकारी योजनाओं, स्वास्थ्य मार्गदर्शन और आजीविका संसाधनों तक पहुंच प्रदान करता है।",
    "model": "sarvam-105b-MOCK",
}

_MOCK_STT = {
    "mock": True,
    "transcript": "[MOCK] नमस्ते, मुझे पीएम किसान योजना के बारे में जानना है।",
    "language": "hi-IN",
}

_MOCK_TTS = {
    "mock": True,
    "audio_b64": base64.b64encode(b"MOCK_WAV_BYTES").decode(),
    "note": "[MOCK] Audio not real. Set SARVAM_MOCK=false for real audio.",
}

_MOCK_DOC_AI = {
    "mock": True,
    "job_id": "mock-job-00000000",
    "status": "completed",
    "result": {
        "name": "[MOCK] Ramesh Kumar",
        "aadhaar_present": False,
        "scheme_name": "[MOCK] PM Kisan Samman Nidhi",
    },
    "note": "[MOCK] Fields not extracted from a real document.",
}


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------
def _cache_key(prefix: str, payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str).encode()
    return f"{prefix}_{hashlib.sha256(raw).hexdigest()[:16]}.json"


def _cache_load(key: str) -> dict | None:
    path = _CACHE_DIR / key
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return None


def _cache_save(key: str, data: dict) -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (_CACHE_DIR / key).write_text(json.dumps(data, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------
class SarvamClient:
    """
    Thin wrapper around the `sarvamai` SDK that adds:
      - MOCK mode (canned responses, no network, no API key needed)
      - On-disk JSON cache (keyed by SHA-256 of request payload)
      - Structured logging of every call
    """

    def __init__(self, mock: bool | None = None) -> None:
        self.mock = _MOCK_ENV if mock is None else mock
        if self.mock:
            log.warning("[SARVAM] MOCK mode active — responses are synthetic, NOT real.")
            self._sdk = None
        else:
            if not _API_KEY:
                raise EnvironmentError(
                    "SARVAM_API_KEY is not set. "
                    "Either set it in .env or enable SARVAM_MOCK=true."
                )
            from sarvamai import SarvamAI  # type: ignore[import]
            self._sdk = SarvamAI(api_subscription_key=_API_KEY)
            log.info("[SARVAM] Live mode — using key ending …%s", _API_KEY[-4:])

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------
    def chat(
        self,
        messages: list[dict],
        model: str = "sarvam-105b",
        use_cache: bool = True,
    ) -> dict:
        if self.mock:
            log.warning("[SARVAM][MOCK] chat called")
            return _MOCK_CHAT

        ck = _cache_key("chat", {"model": model, "messages": messages})
        if use_cache and (cached := _cache_load(ck)):
            log.debug("[SARVAM][CACHE] chat hit %s", ck)
            return cached

        log.info("[SARVAM] chat → model=%s msgs=%d", model, len(messages))
        t0 = time.monotonic()
        resp = self._sdk.chat.completions(model=model, messages=messages)
        elapsed = time.monotonic() - t0
        result = {
            "mock": False,
            "content": resp.choices[0].message.content,
            "model": model,
            "latency_s": round(elapsed, 2),
        }
        if use_cache:
            _cache_save(ck, result)
        return result

    # ------------------------------------------------------------------
    # Speech-to-Text (Saaras)
    # ------------------------------------------------------------------
    def transcribe(
        self,
        audio_path: str | Path,
        model: str = "saaras:v4",
        mode: str = "transcribe",
        language_code: str = "hi-IN",
        use_cache: bool = True,
    ) -> dict:
        if self.mock:
            log.warning("[SARVAM][MOCK] stt called")
            return _MOCK_STT

        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        ck = _cache_key("stt", {"file": audio_path.name, "model": model, "mode": mode})
        if use_cache and (cached := _cache_load(ck)):
            log.debug("[SARVAM][CACHE] stt hit %s", ck)
            return cached

        log.info("[SARVAM] stt → %s model=%s mode=%s", audio_path.name, model, mode)
        t0 = time.monotonic()
        with audio_path.open("rb") as f:
            resp = self._sdk.speech_to_text.transcribe(
                file=f,
                model=model,
                mode=mode,
            )
        elapsed = time.monotonic() - t0
        result = {
            "mock": False,
            "transcript": resp.transcript,
            "language": language_code,
            "latency_s": round(elapsed, 2),
        }
        if use_cache:
            _cache_save(ck, result)
        return result

    # ------------------------------------------------------------------
    # Text-to-Speech (Bulbul)
    # ------------------------------------------------------------------
    def synthesize(
        self,
        text: str,
        language_code: str = "hi-IN",
        model: str = "bulbul:v4-flash",
        speaker: str = "meera",
        use_cache: bool = True,
    ) -> dict:
        """Returns dict with 'audio_b64' (base64-encoded WAV bytes)."""
        if self.mock:
            log.warning("[SARVAM][MOCK] tts called")
            return _MOCK_TTS

        ck = _cache_key("tts", {"text": text, "language_code": language_code, "speaker": speaker})
        if use_cache and (cached := _cache_load(ck)):
            log.debug("[SARVAM][CACHE] tts hit %s", ck)
            return cached

        log.info("[SARVAM] tts → %d chars lang=%s speaker=%s", len(text), language_code, speaker)
        t0 = time.monotonic()
        audio_resp = self._sdk.text_to_speech.convert(
            text=text,
            language_code=language_code,
            model=model,
            speaker=speaker,
        )
        elapsed = time.monotonic() - t0
        # SDK returns list of base64 chunks; join them
        audios = getattr(audio_resp, "audios", None) or []
        audio_b64 = "".join(audios) if audios else ""
        result = {
            "mock": False,
            "audio_b64": audio_b64,
            "latency_s": round(elapsed, 2),
        }
        if use_cache:
            _cache_save(ck, result)
        return result

    # ------------------------------------------------------------------
    # Document AI (Sarvam Vision) — Extract
    # ------------------------------------------------------------------
    def doc_extract(
        self,
        file_path: str | Path,
        schema: dict,
        language: str = "hi-IN",
        output_format: str = "json",
        poll_interval: int = 5,
        timeout: int = 300,
    ) -> dict:
        """
        Run Sarvam Vision Document AI Extract on a file.
        Polls until complete (or timeout) and returns the structured result.
        """
        if self.mock:
            log.warning("[SARVAM][MOCK] doc_extract called")
            return _MOCK_DOC_AI

        import json as _json

        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Document file not found: {file_path}")

        log.info("[SARVAM] doc_extract → %s lang=%s", file_path.name, language)
        t0 = time.monotonic()

        with file_path.open("rb") as f:
            mime = "application/pdf" if file_path.suffix.lower() == ".pdf" else "image/png"
            job = self._sdk.doc_ai.extract(
                file=[(file_path.name, f, mime)],
                schema=_json.dumps(schema),
                language=language,
                output_format=output_format,
            )
        log.info("[SARVAM] doc_extract job_id=%s status=%s", job.job_id, job.status)

        # Poll
        TERMINAL = {"completed", "partially_completed", "failed", "rejected"}
        while True:
            st = self._sdk.doc_ai.get_status(job_id=job.job_id)
            log.debug("[SARVAM] doc_extract status=%s", st.status)
            if st.status.lower() in TERMINAL:
                break
            if time.monotonic() - t0 > timeout:
                raise TimeoutError(f"doc_extract timed out after {timeout}s")
            time.sleep(poll_interval)

        if st.status.lower() in ("completed", "partially_completed"):
            results = self._sdk.doc_ai.get_results(job_id=job.job_id)
            return {
                "mock": False,
                "job_id": job.job_id,
                "status": st.status,
                "result": results.result,
                "latency_s": round(time.monotonic() - t0, 2),
            }
        return {
            "mock": False,
            "job_id": job.job_id,
            "status": st.status,
            "result": None,
            "error": f"Job ended with status: {st.status}",
            "latency_s": round(time.monotonic() - t0, 2),
        }

    # ------------------------------------------------------------------
    # Document AI — Digitise (full OCR)
    # ------------------------------------------------------------------
    def doc_digitise(
        self,
        file_path: str | Path,
        language: str = "en-IN",
        output_format: str = "md",
        poll_interval: int = 5,
        timeout: int = 300,
    ) -> dict:
        """
        Run Sarvam Vision Document AI Digitise on a file.
        Polls until complete and returns the download URL.
        """
        if self.mock:
            log.warning("[SARVAM][MOCK] doc_digitise called")
            return {**_MOCK_DOC_AI, "result": "[MOCK] Full document text would appear here."}

        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Document file not found: {file_path}")

        log.info("[SARVAM] doc_digitise → %s lang=%s fmt=%s", file_path.name, language, output_format)
        t0 = time.monotonic()

        with file_path.open("rb") as f:
            mime = "application/pdf" if file_path.suffix.lower() == ".pdf" else "image/png"
            job = self._sdk.doc_ai.digitise(
                file=[(file_path.name, f, mime)],
                language=language,
                output_format=output_format,
            )
        log.info("[SARVAM] doc_digitise job_id=%s status=%s", job.job_id, job.status)

        TERMINAL = {"completed", "partially_completed", "failed", "rejected"}
        while True:
            st = self._sdk.doc_ai.get_status(job_id=job.job_id)
            if st.status.lower() in TERMINAL:
                break
            if time.monotonic() - t0 > timeout:
                raise TimeoutError(f"doc_digitise timed out after {timeout}s")
            time.sleep(poll_interval)

        if st.status.lower() in ("completed", "partially_completed"):
            dl = self._sdk.doc_ai.get_download_url(job_id=job.job_id)
            return {
                "mock": False,
                "job_id": job.job_id,
                "status": st.status,
                "download_method": dl.method,
                "download_url": dl.url,
                "latency_s": round(time.monotonic() - t0, 2),
            }
        return {
            "mock": False,
            "job_id": job.job_id,
            "status": st.status,
            "download_url": None,
            "error": f"Job ended with status: {st.status}",
            "latency_s": round(time.monotonic() - t0, 2),
        }
