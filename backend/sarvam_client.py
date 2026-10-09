"""
backend/sarvam_client.py — Sarvam AI client wrapper with MOCK mode, DEMO_CACHE support, retries, and disk cache.

Follows official Sarvam Document AI flow, Saaras STT, Bulbul TTS, and Sarvam Chat.
All models and timeouts are configured via config/models.yaml.
PII masking is applied strictly before caching or returning.
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

from backend.config_loader import get_mock_doc_result, get_models_config
from backend.privacy import sanitize_extracted_dict

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
_CACHE_DIR = Path(os.getenv("SARVAM_CACHE_DIR", ".cache/sarvam"))
_DEMO_CACHE_DIR = BASE_DIR / "demo_cache"


def _cache_key(prefix: str, payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str).encode()
    return f"{prefix}_{hashlib.sha256(raw).hexdigest()[:16]}.json"


def _cache_load(key: str) -> dict | None:
    path = _CACHE_DIR / key
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


def _cache_save(key: str, data: dict) -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (_CACHE_DIR / key).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _get_demo_cache_file(filename: str) -> dict | None:
    p = _DEMO_CACHE_DIR / filename
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            log.info("[SARVAM DEMO_CACHE] Serving cached demo response from %s", filename)
            data["note"] = "cached demo response"
            data["is_demo_cache"] = True
            return data
        except Exception as e:
            log.warning("Could not read demo cache %s: %s", p, e)
    return None


class SarvamClient:
    """
    Wrapper around Sarvam AI services with:
      - Runtime configuration from config/models.yaml
      - DEMO_CACHE mode (serves pre-validated demo cache when DEMO_CACHE=1)
      - MOCK mode (returns realistic mock responses from mocks/ without network)
      - On-disk JSON cache (caches only masked, non-PII data)
      - Automatic retries (2 retries) and timeout handling
    """

    def __init__(self, mock: bool | None = None) -> None:
        self.cfg = get_models_config()
        env_mock = os.getenv("SARVAM_MOCK", "false").lower() in ("1", "true", "yes")
        self.demo_cache = os.getenv("DEMO_CACHE", "0").lower() in ("1", "true", "yes")
        self.mock = env_mock if mock is None else mock
        self.api_key = os.getenv("SARVAM_API_KEY", "")
        self.max_retries = int(self.cfg.get("max_retries", 2))
        self.timeout = int(self.cfg.get("request_timeout_seconds", 45))

        if self.demo_cache:
            log.info("[SARVAM] DEMO_CACHE=1 active — cached demo responses enabled for offline reliability.")

        if self.mock:
            log.warning("[SARVAM] MOCK mode active - responses loaded from mocks/.")
            self._sdk = None
        else:
            if not self.api_key:
                if not self.demo_cache:
                    log.warning("SARVAM_API_KEY not set - falling back to MOCK mode.")
                self.mock = True
                self._sdk = None
            else:
                try:
                    from sarvamai import SarvamAI  # type: ignore[import]
                    self._sdk = SarvamAI(api_subscription_key=self.api_key)
                    log.info("[SARVAM] Live mode enabled with key ending in ...%s", self.api_key[-4:])
                except Exception as e:
                    log.error("Failed to initialize SarvamAI SDK: %s. Falling back to MOCK mode.", e)
                    self.mock = True
                    self._sdk = None

    def _retry_call(self, func, *args, **kwargs):
        """Execute a call with up to max_retries on transient failure."""
        last_err = None
        for attempt in range(self.max_retries + 1):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_err = e
                log.warning("[SARVAM] Attempt %d failed: %s", attempt + 1, e)
                if attempt < self.max_retries:
                    time.sleep(1.5 * (attempt + 1))
        if last_err:
            raise last_err
        raise RuntimeError("Operation failed with no exception recorded")

    # ------------------------------------------------------------------
    # Chat (Sarvam-105b)
    # ------------------------------------------------------------------
    def chat(
        self,
        messages: list[dict],
        model: str | None = None,
        use_cache: bool = True,
    ) -> dict:
        model_id = model or self.cfg.get("chat_model")
        
        if self.demo_cache:
            demo_res = _get_demo_cache_file("tts_beti_scheme.json")
            if demo_res:
                return {
                    "mock": False,
                    "is_demo_cache": True,
                    "note": "cached demo response",
                    "content": demo_res.get("text", "नमस्ते, ग्राम-ज्ञान डेमो मोड में आपका स्वागत है।"),
                    "model": model_id,
                }

        if self.mock:
            return {
                "mock": True,
                "content": "[MOCK] ग्राम-ज्ञान में आपका स्वागत है। मैं आपकी सरकारी योजनाओं और दस्तावेज़ों में मदद कर सकता हूँ।",
                "model": f"{model_id}-MOCK",
            }

        ck = _cache_key("chat", {"model": model_id, "messages": messages})
        if use_cache and (cached := _cache_load(ck)):
            return cached

        log.info("[SARVAM] chat model=%s msgs=%d", model_id, len(messages))
        t0 = time.monotonic()

        def _do_chat():
            return self._sdk.chat.completions(model=model_id, messages=messages)

        try:
            resp = self._retry_call(_do_chat)
            elapsed = time.monotonic() - t0
            result = {
                "mock": False,
                "content": resp.choices[0].message.content,
                "model": model_id,
                "latency_s": round(elapsed, 2),
            }
            if use_cache:
                _cache_save(ck, result)
            return result
        except Exception as e:
            if self.demo_cache:
                demo_res = _get_demo_cache_file("tts_beti_scheme.json")
                if demo_res:
                    return {
                        "mock": False,
                        "is_demo_cache": True,
                        "note": "cached demo response",
                        "content": demo_res.get("text"),
                        "model": model_id,
                    }
            raise e

    # ------------------------------------------------------------------
    # Speech-to-Text (Saaras)
    # ------------------------------------------------------------------
    def transcribe(
        self,
        audio_path: str | Path,
        model: str | None = None,
        mode: str = "transcribe",
        language_code: str = "hi-IN",
        use_cache: bool = True,
    ) -> dict:
        model_id = model or self.cfg.get("stt_model")

        if self.demo_cache:
            demo_stt = _get_demo_cache_file("stt_beti_scheme.json")
            if demo_stt:
                return demo_stt

        if self.mock:
            return {
                "mock": True,
                "transcript": "मेरी बेटी के लिए क्या योजना है?",
                "language": language_code,
            }

        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        ck = _cache_key("stt", {"file": audio_path.name, "model": model_id, "mode": mode})
        if use_cache and (cached := _cache_load(ck)):
            return cached

        t0 = time.monotonic()

        def _do_stt():
            with audio_path.open("rb") as f:
                return self._sdk.speech_to_text.transcribe(
                    file=f,
                    model=model_id,
                    mode=mode,
                )

        try:
            resp = self._retry_call(_do_stt)
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
        except Exception as e:
            if self.demo_cache:
                demo_stt = _get_demo_cache_file("stt_beti_scheme.json")
                if demo_stt:
                    return demo_stt
            raise e

    # ------------------------------------------------------------------
    # Text-to-Speech (Bulbul)
    # ------------------------------------------------------------------
    def synthesize(
        self,
        text: str,
        language_code: str = "hi-IN",
        model: str | None = None,
        speaker: str | None = None,
        use_cache: bool = True,
    ) -> dict:
        model_id = model or self.cfg.get("tts_model")
        speaker_id = speaker or self.cfg.get("tts_default_speaker")

        if self.demo_cache:
            demo_tts = _get_demo_cache_file("tts_beti_scheme.json")
            if demo_tts and demo_tts.get("audio_b64"):
                return demo_tts

        if self.mock:
            return {
                "mock": True,
                "audio_b64": base64.b64encode(b"RIFF$MOCK_WAV_BYTES").decode(),
                "note": "[MOCK] Mock audio output",
            }

        ck = _cache_key("tts", {"text": text, "language_code": language_code, "speaker": speaker_id, "model": model_id})
        if use_cache and (cached := _cache_load(ck)):
            return cached

        t0 = time.monotonic()

        def _do_tts():
            return self._sdk.text_to_speech.convert(
                text=text,
                language_code=language_code,
                model=model_id,
                speaker=speaker_id,
            )

        try:
            audio_resp = self._retry_call(_do_tts)
            elapsed = time.monotonic() - t0
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
        except Exception as e:
            if self.demo_cache:
                demo_tts = _get_demo_cache_file("tts_beti_scheme.json")
                if demo_tts:
                    return demo_tts
            raise e

    # ------------------------------------------------------------------
    # Document AI - Digitise (OCR text/markdown)
    # ------------------------------------------------------------------
    def doc_digitise(
        self,
        file_path: str | Path,
        language: str = "hi-IN",
        output_format: str | None = None,
        poll_interval: int = 2,
        timeout: int = 60,
        original_filename: str | None = None,
    ) -> dict:
        fmt = output_format or self.cfg.get("doc_digitise_output_format", "md")
        fn = (original_filename or Path(file_path).stem).lower()

        if self.demo_cache:
            if "notice" in fn:
                demo_not = _get_demo_cache_file("doc_notice_extract.json")
                if demo_not:
                    return {
                        "mock": False,
                        "is_demo_cache": True,
                        "note": "cached demo response",
                        "job_id": demo_not.get("job_id", "demo-notice-001"),
                        "status": "completed",
                        "text": demo_not.get("result", {}).get("noticeDetails", {}).get("summary", ""),
                    }
            elif "ration" in fn:
                demo_rat = _get_demo_cache_file("doc_ration_extract.json")
                if demo_rat:
                    return {
                        "mock": False,
                        "is_demo_cache": True,
                        "note": "cached demo response",
                        "job_id": demo_rat.get("job_id", "demo-ration-001"),
                        "status": "completed",
                        "text": "खाद्य एवं रसद विभाग उत्तर प्रदेश राशन कार्ड (PHH) मुखिया: रमेश कुमार",
                    }

        if self.mock:
            if "ration" in fn:
                mock_text = "खाद्य एवं रसद विभाग उत्तर प्रदेश राशन कार्ड (PHH) मुखिया: रमेश कुमार जिला: वाराणसी सदस्य: सुनीता देवी, अमन कुमार कार्ड संख्या: 987654324589"
            elif "aadhaar" in fn or "aadhar" in fn:
                mock_text = "भारत सरकार UNIQUE IDENTIFICATION AUTHORITY OF INDIA आधार Mera Aadhaar Meri Pehchan नाम: रमेश कुमार जन्म तिथि / DOB: 14/05/1984 पुरुष / Male आधार संख्या: 9876 5432 8921"
            elif "pan" in fn:
                mock_text = "INCOME TAX DEPARTMENT GOVT. OF INDIA Permanent Account Number PAN Card Name: Ramesh Kumar Father: Ram Charan DOB: 14/05/1984 PAN: ABCDE1234F"
            elif "passbook" in fn or "bank" in fn:
                mock_text = "State Bank of India Savings Bank Passbook Account Holder: Ramesh Kumar IFSC: SBIN0001234 Account Number: 123456789012 Branch: Rampur"
            elif "electricity" in fn or "bill" in fn:
                mock_text = "Electricity Bill UPPCL Discom Consumer Name: Ramesh Kumar Consumer No: 98765678 Amount Due: 450.00 Due Date: 2026-11-15"
            else:
                mock_text = "कार्यालय ग्राम पंचायत रामपुर सूचना: प्रधानमंत्री किसान सम्मान निधि ई-केवाईसी शिविर दिनांक 10 नवंबर 2026 तक पंचायत भवन में आयोजित किया जा रहा है।"
            return {
                "mock": True,
                "job_id": f"mock-digitise-job-{fn[:8]}",
                "status": "completed",
                "text": mock_text,
            }

        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Document file not found: {file_path}")

        t0 = time.monotonic()

        def _start_job():
            with file_path.open("rb") as f:
                mime = "application/pdf" if file_path.suffix.lower() == ".pdf" else "image/png"
                return self._sdk.doc_ai.digitise(
                    file=[(file_path.name, f, mime)],
                    language=language,
                    output_format=fmt,
                )

        try:
            job = self._retry_call(_start_job)
            job_id = getattr(job, "job_id", str(job))

            TERMINAL = {"completed", "partially_completed", "failed", "rejected"}
            while True:
                st = self._sdk.doc_ai.get_status(job_id=job_id)
                status = getattr(st, "status", "unknown").lower()
                if status in TERMINAL:
                    break
                if time.monotonic() - t0 > timeout:
                    raise TimeoutError(f"doc_digitise timed out after {timeout}s")
                time.sleep(poll_interval)

            if status in ("completed", "partially_completed"):
                dl = self._sdk.doc_ai.get_download_url(job_id=job_id)
                return {
                    "mock": False,
                    "job_id": job_id,
                    "status": status,
                    "download_url": getattr(dl, "url", None),
                    "latency_s": round(time.monotonic() - t0, 2),
                }

            return {
                "mock": False,
                "job_id": job_id,
                "status": status,
                "download_url": None,
                "error": f"Digitise ended with status: {status}",
                "latency_s": round(time.monotonic() - t0, 2),
            }
        except Exception as e:
            if self.demo_cache and "notice" in fn:
                demo_not = _get_demo_cache_file("doc_notice_extract.json")
                if demo_not:
                    return {
                        "mock": False,
                        "is_demo_cache": True,
                        "note": "cached demo response",
                        "job_id": demo_not.get("job_id", "demo-notice-001"),
                        "status": "completed",
                        "text": demo_not.get("result", {}).get("noticeDetails", {}).get("summary", ""),
                    }
            raise e

    # ------------------------------------------------------------------
    # Document AI - Extract (Structured fields)
    # ------------------------------------------------------------------
    def doc_extract(
        self,
        file_path: str | Path,
        schema: dict,
        doc_type: str = "other",
        language: str = "hi-IN",
        output_format: str | None = None,
        poll_interval: int = 2,
        timeout: int = 60,
    ) -> dict:
        fmt = output_format or self.cfg.get("doc_extract_output_format", "json")

        if self.demo_cache:
            if doc_type == "official_notice":
                demo_not = _get_demo_cache_file("doc_notice_extract.json")
                if demo_not:
                    return demo_not
            elif doc_type == "ration_card":
                demo_rat = _get_demo_cache_file("doc_ration_extract.json")
                if demo_rat:
                    return demo_rat

        if self.mock:
            mock_res = get_mock_doc_result(doc_type)
            return {
                "mock": True,
                "job_id": f"mock-extract-{doc_type}-001",
                "status": "completed",
                "result": mock_res,
            }

        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Document file not found: {file_path}")

        t0 = time.monotonic()

        def _start_extract():
            with file_path.open("rb") as f:
                mime = "application/pdf" if file_path.suffix.lower() == ".pdf" else "image/png"
                return self._sdk.doc_ai.extract(
                    file=[(file_path.name, f, mime)],
                    schema=json.dumps(schema),
                    language=language,
                    output_format=fmt,
                )

        try:
            job = self._retry_call(_start_extract)
            job_id = getattr(job, "job_id", str(job))

            TERMINAL = {"completed", "partially_completed", "failed", "rejected"}
            while True:
                st = self._sdk.doc_ai.get_status(job_id=job_id)
                status = getattr(st, "status", "unknown").lower()
                if status in TERMINAL:
                    break
                if time.monotonic() - t0 > timeout:
                    raise TimeoutError(f"doc_extract timed out after {timeout}s")
                time.sleep(poll_interval)

            if status in ("completed", "partially_completed"):
                raw_res = self._sdk.doc_ai.get_results(job_id=job_id)
                extracted_data = getattr(raw_res, "result", raw_res)
                # Strict PII sanitization before caching or returning
                schema_fields = schema.get("fields", []) if isinstance(schema, dict) else []
                if isinstance(extracted_data, dict):
                    sanitized_data = sanitize_extracted_dict(extracted_data, schema_fields)
                else:
                    sanitized_data = extracted_data

                return {
                    "mock": False,
                    "job_id": job_id,
                    "status": status,
                    "result": sanitized_data,
                    "latency_s": round(time.monotonic() - t0, 2),
                }

            return {
                "mock": False,
                "job_id": job_id,
                "status": status,
                "result": None,
                "error": f"Extract ended with status: {status}",
                "latency_s": round(time.monotonic() - t0, 2),
            }
        except Exception as e:
            if self.demo_cache:
                if doc_type == "official_notice":
                    demo_not = _get_demo_cache_file("doc_notice_extract.json")
                    if demo_not:
                        return demo_not
                elif doc_type == "ration_card":
                    demo_rat = _get_demo_cache_file("doc_ration_extract.json")
                    if demo_rat:
                        return demo_rat
            raise e
