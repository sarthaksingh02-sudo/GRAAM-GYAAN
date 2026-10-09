"""
tests/test_phase2.py — Pytest suite for Phase 2 (Voice Conversation).

Tests:
  1. Push-to-talk voice flow: audio file -> STT -> routing -> answer -> TTS audio generation.
  2. Chat endpoint with grounded citations from /data/real/.
  3. Profile lookup tool (get_profile) and missing documents.
  4. Profile update confirmation gate (update_profile) requiring explicit user confirmation.
  5. Scheme search tool (find_schemes) answering strictly from /data/real/schemes.
  6. Missing data topic returns i18n INFO_NOT_AVAILABLE without hallucination.
  7. Intents and quick-question chips endpoint (/api/intents).
  8. Conversation transcript history endpoint (/api/conversations/:sessionId).
"""

import os
import shutil
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

os.environ["SARVAM_MOCK"] = "true"
os.environ["DATABASE_URL"] = "test_graam_gyaan_p2.db"

from backend.db import DB_PATH, get_conn, init_db
from backend.main import app


@pytest.fixture(autouse=True)
def setup_teardown_db():
    db_file = "test_graam_gyaan_p2.db"
    os.environ["DATABASE_URL"] = db_file
    test_db = Path(db_file)
    if test_db.exists():
        test_db.unlink()
    init_db(test_db)
    yield
    if test_db.exists():
        test_db.unlink()
    test_uploads = Path("uploads")
    if test_uploads.exists():
        shutil.rmtree(test_uploads, ignore_errors=True)


@pytest.fixture
def client():
    return TestClient(app)


def _setup_user_with_consent(client):
    r = client.post(
        "/api/consent",
        json={
            "village": "Nayapara",
            "panchayat": "Rampur Gram Panchayat",
            "district": "Varanasi",
            "state": "Uttar Pradesh",
            "language_pref": "hi-IN",
            "consent": True,
        },
    )
    return r.json()["userId"]


# ---------------------------------------------------------------------------
# Test 1: Intents and Quick Chips from YAML
# ---------------------------------------------------------------------------
def test_intents_endpoint(client):
    resp = client.get("/api/intents?lang=hi-IN")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["chips"]) >= 3
    assert any("योजना" in c["text"] or "दस्तावेज़" in c["text"] for c in data["chips"])


# ---------------------------------------------------------------------------
# Test 2: Grounded Scheme Search Chat (find_schemes)
# ---------------------------------------------------------------------------
def test_chat_find_schemes(client):
    user_id = _setup_user_with_consent(client)

    resp = client.post(
        "/api/chat",
        json={"message": "किसान के लिए कौन सी योजना है?", "lang": "hi-IN"},
        headers={"X-User-Id": str(user_id)},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "किसान" in data["text"] or "PM Kisan" in data["text"]
    assert len(data["sources"]) > 0
    assert data["audioAvailable"] is True
    assert data["audioUrl"] is not None


# ---------------------------------------------------------------------------
# Test 3: Profile Tool (get_profile)
# ---------------------------------------------------------------------------
def test_chat_get_profile(client):
    user_id = _setup_user_with_consent(client)

    # Add a member
    client.post(
        "/api/family",
        json={"name": "Ramesh Kumar", "dob": "1984-05-14", "relation": "self"},
        headers={"X-User-Id": str(user_id)},
    )

    resp = client.post(
        "/api/chat",
        json={"message": "मेरी प्रोफाइल और कौन से कागज़ बाकी हैं?", "lang": "hi-IN"},
        headers={"X-User-Id": str(user_id)},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "सदस्य" in data["text"] or "दस्तावेज़" in data["text"]
    assert len(data["sources"]) > 0


# ---------------------------------------------------------------------------
# Test 4: Profile Update Confirmation Gate
# ---------------------------------------------------------------------------
def test_update_profile_confirmation_flow(client):
    user_id = _setup_user_with_consent(client)

    # Propose update
    resp1 = client.post(
        "/api/chat",
        json={
            "sessionId": "profile-confirmation",
            "message": "मेरा गाँव बदलकर रामपुर कर दो",
            "lang": "hi-IN",
            "confirmAction": {"tool": "update_profile", "field": "village", "value": "Rampur"},
        },
        headers={"X-User-Id": str(user_id)},
    )
    assert resp1.status_code == 200

    # Confirm with 'हाँ'
    resp2 = client.post(
        "/api/chat",
        json={
            "sessionId": "profile-confirmation",
            "message": "हाँ, अपडेट कर दो",
            "lang": "hi-IN",
            "confirmAction": {"tool": "update_profile", "field": "village", "value": "Rampur"},
        },
        headers={"X-User-Id": str(user_id)},
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert "सफलतापूर्वक" in data2["text"] or "updated" in data2["text"].lower()

    # Verify profile reflected change
    prof = client.get("/api/profile", headers={"X-User-Id": str(user_id)}).json()
    assert prof["household"]["village"] == "Rampur"


# ---------------------------------------------------------------------------
# Test 5: Voice Push-to-Talk Endpoint (/api/voice)
# ---------------------------------------------------------------------------
def test_voice_turn_endpoint(client):
    user_id = _setup_user_with_consent(client)

    sample_audio = Path("data/real/snapshots/sample.wav")
    if not sample_audio.exists():
        pytest.skip("Sample audio missing")

    with open(sample_audio, "rb") as f:
        resp = client.post(
            "/api/voice",
            files={"file": ("query.wav", f, "audio/wav")},
            data={"sessionId": "sess-test-01", "lang": "hi-IN"},
            headers={"X-User-Id": str(user_id)},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "transcript" in data
    assert "assistant" in data
    assert data["assistant"]["text"] != ""
    assert data["assistant"]["audioUrl"] is not None

    # Verify conversation transcript stored in DB
    hist_resp = client.get("/api/conversations/sess-test-01")
    assert hist_resp.status_code == 200
    hist = hist_resp.json()
    assert len(hist["turns"]) >= 2
    assert hist["turns"][0]["role"] == "user"
    assert hist["turns"][1]["role"] == "assistant"


# ---------------------------------------------------------------------------
# Test 6: Absence of Data File Returns Refusal Message
# ---------------------------------------------------------------------------
def test_missing_topic_guide_refusal(client):
    user_id = _setup_user_with_consent(client)

    from backend.assistant import tool_get_needs_guide
    # Query non-existent guide topic
    res = tool_get_needs_guide(topic="space_travel_guide", lang="hi-IN")
    assert "उपलब्ध नहीं है" in res["text"] or "not available" in res["text"].lower()
    assert "missing_file" in res
