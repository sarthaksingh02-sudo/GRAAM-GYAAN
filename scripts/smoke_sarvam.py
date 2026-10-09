#!/usr/bin/env python3
"""
scripts/smoke_sarvam.py — GRAAM-GYAAN Sarvam AI smoke test.

Makes one REAL call each to:
  1. Document AI Extract  (Sarvam Vision) — on data/real/snapshots/sample.png
  2. Saaras STT           (saaras:v4)     — on data/real/snapshots/sample.wav
  3. Bulbul TTS           (bulbul:v4-flash)  — Hindi sentence
  4. Chat                 (sarvam-105b)   — asks what GRAAM-GYAAN is

Rules:
  - Prints PASS / FAIL per service with error text.
  - Aborts and prints instructions if ANY service fails.
  - Requires SARVAM_API_KEY to be set (not a MOCK run).
  - Do NOT run with SARVAM_MOCK=true — this test verifies LIVE connectivity.

Usage:
    python scripts/smoke_sarvam.py
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time
from pathlib import Path

# ── ensure repo root is on path ──────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# ── load .env if present ─────────────────────────────────────────────────────
_env_file = REPO_ROOT / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

# ── Guard: refuse to run in MOCK mode ────────────────────────────────────────
if os.getenv("SARVAM_MOCK", "false").lower() in ("1", "true", "yes"):
    print("ERROR: SARVAM_MOCK=true detected. This smoke test requires LIVE API access.")
    print("       Unset SARVAM_MOCK or set it to false before running.")
    sys.exit(1)

API_KEY = os.getenv("SARVAM_API_KEY", "")
if not API_KEY:
    print("ERROR: SARVAM_API_KEY is not set.")
    print()
    print("To fix:")
    print("  1. Sign up at https://dashboard.sarvam.ai")
    print("  2. Create an API key")
    print("  3. Set it in your .env file:")
    print("       SARVAM_API_KEY=your_key_here")
    print("  4. Re-run: python scripts/smoke_sarvam.py")
    sys.exit(1)

SAMPLE_PNG = REPO_ROOT / "data" / "real" / "snapshots" / "sample.png"
SAMPLE_WAV = REPO_ROOT / "data" / "real" / "snapshots" / "sample.wav"

results: list[dict] = []


def report(service: str, passed: bool, detail: str = "", latency_s: float = 0.0) -> None:
    status = "PASS" if passed else "FAIL"
    bar = "=" * 60
    print(bar)
    print(f"  {status}  [{service}]")
    if latency_s:
        print(f"  latency: {latency_s:.2f}s")
    if detail:
        print(f"  detail:  {detail[:300]}")
    print(bar)
    results.append({"service": service, "passed": passed, "detail": detail})


# ── Import SDK ────────────────────────────────────────────────────────────────
try:
    from sarvamai import SarvamAI  # type: ignore[import]
except ImportError:
    print("ERROR: sarvamai SDK not installed.")
    print("       Run: pip install sarvamai")
    sys.exit(1)

client = SarvamAI(api_subscription_key=API_KEY)

print()
print("GRAAM-GYAAN — Sarvam AI Smoke Test")
print(f"API key: ...{API_KEY[-4:]}")
print()

# ─────────────────────────────────────────────────────────────────────────────
# 1. Document AI Extract  (Sarvam Vision)
# ─────────────────────────────────────────────────────────────────────────────
print("[1/4] Document AI Extract — Sarvam Vision")

schema = {
    "type": "object",
    "properties": {
        "document_type": {
            "type": "string",
            "description": "Type of government document (e.g. ration card, income certificate)"
        },
        "applicant_name": {
            "type": "string",
            "description": "Full name of the applicant or document holder"
        },
    }
}

try:
    t0 = time.monotonic()
    with SAMPLE_PNG.open("rb") as f:
        job = client.doc_ai.extract(
            file=[(SAMPLE_PNG.name, f, "image/png")],
            schema=json.dumps(schema),
            language="en-IN",
            output_format="json",
        )
    job_id = job.job_id

    # Poll
    TERMINAL = {"completed", "partially_completed", "failed", "rejected"}
    for _ in range(60):
        st = client.doc_ai.get_status(job_id=job_id)
        if st.status.lower() in TERMINAL:
            break
        time.sleep(5)

    elapsed = time.monotonic() - t0

    if st.status.lower() in ("completed", "partially_completed"):
        res = client.doc_ai.get_results(job_id=job_id)
        report("Document AI Extract", True, f"job_id={job_id} result={res.result}", elapsed)
    else:
        report("Document AI Extract", False, f"job_id={job_id} terminal_status={st.status}", elapsed)

except Exception as exc:
    report("Document AI Extract", False, f"{type(exc).__name__}: {exc}")

if not results[-1]["passed"]:
    print()
    print("ABORT: Document AI Extract failed. Fix the issue above before proceeding.")
    print()
    print("Common causes:")
    print("  - Invalid API key (check https://dashboard.sarvam.ai)")
    print("  - Insufficient credits or plan does not include Document AI")
    print("  - Image file too small or corrupt (sample.png is a minimal 1x1 test image;")
    print("    replace data/real/snapshots/sample.png with a real document scan for better results)")
    sys.exit(2)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Saaras STT
# ─────────────────────────────────────────────────────────────────────────────
print("[2/4] Saaras STT — speech-to-text")

try:
    t0 = time.monotonic()
    with SAMPLE_WAV.open("rb") as f:
        resp = client.speech_to_text.transcribe(
            file=f,
            model="saaras:v4",
            mode="transcribe",
        )
    elapsed = time.monotonic() - t0
    transcript = resp.transcript
    report("Saaras STT", True, f"transcript={repr(transcript)}", elapsed)

except Exception as exc:
    report("Saaras STT", False, f"{type(exc).__name__}: {exc}")

if not results[-1]["passed"]:
    print()
    print("ABORT: Saaras STT failed. Fix the issue above before proceeding.")
    print()
    print("Common causes:")
    print("  - Invalid API key")
    print("  - Audio file too short (sample.wav is a silent 44-byte file;")
    print("    replace data/real/snapshots/sample.wav with a real Hindi audio clip)")
    print("  - Audio format not supported (use WAV, 16kHz mono recommended)")
    sys.exit(2)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Bulbul TTS
# ─────────────────────────────────────────────────────────────────────────────
print("[3/4] Bulbul TTS — text-to-speech")

HINDI_SENTENCE = "नमस्ते! ग्राम-ज्ञान आपकी सरकारी योजनाओं तक पहुंच आसान बनाता है।"
OUT_WAV = REPO_ROOT / "scripts" / "output_tts_smoke.wav"

try:
    t0 = time.monotonic()
    audio_resp = client.text_to_speech.convert(
        text=HINDI_SENTENCE,
        language_code="hi-IN",
        model="bulbul:v4-flash",
        speaker="meera",
    )
    elapsed = time.monotonic() - t0

    audios = getattr(audio_resp, "audios", None) or []
    audio_b64 = "".join(audios)
    if not audio_b64:
        raise ValueError("Empty audio response — no 'audios' data returned")

    raw_audio = base64.b64decode(audio_b64)
    OUT_WAV.write_bytes(raw_audio)
    report("Bulbul TTS", True, f"saved {len(raw_audio)} bytes → {OUT_WAV.name}", elapsed)

except Exception as exc:
    report("Bulbul TTS", False, f"{type(exc).__name__}: {exc}")

if not results[-1]["passed"]:
    print()
    print("ABORT: Bulbul TTS failed. Fix the issue above before proceeding.")
    print()
    print("Common causes:")
    print("  - Invalid API key")
    print("  - Speaker name not available on your plan (try 'meera' or 'anushka')")
    print("  - Language code not supported by bulbul:v4-flash")
    sys.exit(2)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Chat (sarvam-105b)
# ─────────────────────────────────────────────────────────────────────────────
print("[4/4] Chat — sarvam-105b")

try:
    t0 = time.monotonic()
    resp = client.chat.completions(
        model="sarvam-105b",
        messages=[
            {"role": "user", "content": "ग्राम-ज्ञान क्या है? एक वाक्य में बताओ।"}
        ],
    )
    elapsed = time.monotonic() - t0
    reply = resp.choices[0].message.content
    report("Chat (sarvam-105b)", True, f"reply={repr(reply[:120])}", elapsed)

except Exception as exc:
    report("Chat (sarvam-105b)", False, f"{type(exc).__name__}: {exc}")

if not results[-1]["passed"]:
    print()
    print("ABORT: Chat failed. Fix the issue above before proceeding.")
    print()
    print("Common causes:")
    print("  - Invalid API key")
    print("  - sarvam-105b not available on your plan (check dashboard.sarvam.ai)")
    sys.exit(2)


# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────
print()
print("=" * 60)
print("SMOKE TEST SUMMARY")
print("=" * 60)
all_passed = True
for r in results:
    icon = "✓" if r["passed"] else "✗"
    print(f"  {icon}  {r['service']}")
    if not r["passed"]:
        all_passed = False

print("=" * 60)
if all_passed:
    print("ALL 4 SERVICES PASSED — you are ready to proceed to Phase 1.")
else:
    print("SOME SERVICES FAILED — see details above.")
    sys.exit(1)
