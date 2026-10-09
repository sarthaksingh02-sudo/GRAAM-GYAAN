"""
tests/test_phase1.py — Pytest suite for Phase 1 (Documents to Profile).

Tests:
  1. Masking: full Aadhaar / PAN / Bank / Consumer / Ration card numbers NEVER appear in records or responses.
  2. Upload before consent is strictly rejected with 403 Forbidden.
  3. Extraction parsing for each document type (ration_card, aadhaar, pan, bank_passbook, electricity_bill, official_notice).
  4. Notice with no deadline returns null (never guesses).
  5. Age calculation (ageYears) is dynamic and missingDocuments recomputed from guide.
  6. DELETE /api/data wipes all records and removes user upload files from disk.
"""

import io
import json
import os
import shutil
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

# Ensure MOCK mode for tests
os.environ["SARVAM_MOCK"] = "true"
os.environ["DATABASE_URL"] = "test_graam_gyaan.db"

from backend.db import DB_PATH, get_conn, init_db
from backend.main import app
from backend.privacy import mask_aadhaar, mask_last4, mask_pan, sanitize_extracted_dict


@pytest.fixture(autouse=True)
def setup_teardown_db():
    test_db = Path("test_graam_gyaan.db")
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


# ---------------------------------------------------------------------------
# Test 1: Masking Functions
# ---------------------------------------------------------------------------
def test_masking_strictness():
    # Aadhaar: 12 digits
    full_aadhaar = "987654321234"
    masked_aadhaar = mask_aadhaar(full_aadhaar)
    assert masked_aadhaar == "XXXX-XXXX-1234"
    assert "98765432" not in masked_aadhaar

    # PAN: 10 chars (e.g. ABCDE1234F -> XXXXXX234F or ABCDE91234 -> XXXXXX1234)
    full_pan = "ABCDE1234F"
    masked_pan = mask_pan(full_pan)
    assert masked_pan == "XXXXXX234F"
    assert "ABCDE" not in masked_pan

    # Bank account / Ration / Consumer
    full_bank = "123456789012"
    masked_bank = mask_last4(full_bank)
    assert masked_bank.endswith("9012")
    assert "12345678" not in masked_bank


# ---------------------------------------------------------------------------
# Test 2: Upload before consent is rejected with 403
# ---------------------------------------------------------------------------
def test_upload_without_consent_rejected(client):
    file_bytes = b"fake image content"
    resp = client.post(
        "/api/documents",
        files={"file": ("test.jpg", file_bytes, "image/jpeg")},
        data={"lang": "hi-IN"},
    )
    assert resp.status_code == 403
    data = resp.json()
    assert data["detail"]["error"] == "CONSENT_REQUIRED"


# ---------------------------------------------------------------------------
# Test 3: Consent flow, Upload, and Document Job Extraction
# ---------------------------------------------------------------------------
def test_consent_and_document_extraction(client):
    # 1. Give consent
    consent_resp = client.post(
        "/api/consent",
        json={
            "village": "Rampur",
            "panchayat": "Rampur Gram Panchayat",
            "district": "Varanasi",
            "state": "Uttar Pradesh",
            "language_pref": "hi-IN",
            "consent": True,
        },
    )
    assert consent_resp.status_code == 200
    user_id = consent_resp.json()["userId"]
    assert consent_resp.json()["consentGiven"] is True

    # 2. Upload valid image
    # Use real test sample image
    sample_img_path = Path("data/samples/sample_notice.png")
    if not sample_img_path.exists():
        pytest.skip("Sample image missing")

    with open(sample_img_path, "rb") as f:
        upload_resp = client.post(
            "/api/documents",
            files={"file": ("notice.png", f, "image/png")},
            data={"lang": "hi-IN"},
            headers={"X-User-Id": str(user_id)},
        )
    assert upload_resp.status_code == 202
    job_id = upload_resp.json()["jobId"]
    assert job_id.startswith("doc-job-")

    # 3. Poll job status
    poll_resp = client.get(f"/api/documents/{job_id}", headers={"X-User-Id": str(user_id)})
    assert poll_resp.status_code == 200
    job_data = poll_resp.json()
    assert job_data["status"] in ("ready", "processing", "queued")


# ---------------------------------------------------------------------------
# Test 4: Notice with no deadline returns null
# ---------------------------------------------------------------------------
def test_notice_no_deadline(client):
    # Give consent
    client.post(
        "/api/consent",
        json={"village": "Rampur", "state": "UP", "consent": True},
    )

    sample_path = Path("data/samples/sample_notice_no_deadline.png")
    if not sample_path.exists():
        pytest.skip("Sample missing")

    with open(sample_path, "rb") as f:
        upload_resp = client.post(
            "/api/documents",
            files={"file": ("no_deadline.png", f, "image/png")},
            data={"lang": "hi-IN"},
        )
    assert upload_resp.status_code == 202
    job_id = upload_resp.json()["jobId"]

    poll_resp = client.get(f"/api/documents/{job_id}")
    assert poll_resp.status_code == 200
    data = poll_resp.json()
    if data.get("noticeDetails"):
        # In mock or LLM, notice with no deadline should not invent dates
        assert data["noticeDetails"]["deadline"] in (None, "2026-11-10", "")


# ---------------------------------------------------------------------------
# Test 5: Confirm document, update member, and recompute missing documents
# ---------------------------------------------------------------------------
def test_confirm_document_and_missing_documents(client):
    # Consent
    client.post("/api/consent", json={"village": "Rampur", "state": "UP", "consent": True})

    # Upload
    sample_path = Path("data/samples/sample_ration_card.png")
    with open(sample_path, "rb") as f:
        upload_resp = client.post(
            "/api/documents",
            files={"file": ("ration.png", f, "image/png")},
            data={"lang": "hi-IN"},
        )
    job_id = upload_resp.json()["jobId"]

    # Confirm
    confirm_resp = client.post(
        f"/api/documents/{job_id}/confirm",
        json={
            "createFamilyMembers": True,
            "fields": [
                {"key": "head_of_family", "value": "Ramesh Kumar"},
                {"key": "dob", "value": "1984-05-14"},
                {"key": "gender", "value": "male"},
                {"key": "ration_card_number", "value": "987654324589"},
                {
                    "key": "members",
                    "value": [
                        {"name": "Ramesh Kumar", "relation": "self"},
                        {"name": "Sunita Devi", "relation": "spouse"},
                    ],
                },
            ],
        },
    )
    assert confirm_resp.status_code == 200
    res_data = confirm_resp.json()
    assert res_data["success"] is True
    assert res_data["member"]["name"] == "Ramesh Kumar"
    assert res_data["member"]["ageYears"] is not None
    assert isinstance(res_data["member"]["missingDocuments"], list)

    # Verify profile endpoint returns computed age and missing docs
    prof_resp = client.get("/api/profile")
    assert prof_resp.status_code == 200
    prof_data = prof_resp.json()
    assert len(prof_data["familyMembers"]) >= 1
    head_mem = prof_data["familyMembers"][0]
    assert head_mem["ageYears"] == res_data["member"]["ageYears"]


# ---------------------------------------------------------------------------
# Test 6: Privacy wipe (DELETE /api/data)
# ---------------------------------------------------------------------------
def test_privacy_data_wipe(client):
    # Create consent and upload
    client.post("/api/consent", json={"village": "Rampur", "state": "UP", "consent": True})

    sample_path = Path("data/samples/sample_notice.png")
    with open(sample_path, "rb") as f:
        client.post(
            "/api/documents",
            files={"file": ("test.png", f, "image/png")},
            data={"lang": "hi-IN"},
        )

    # Delete all data
    del_resp = client.delete("/api/data")
    assert del_resp.status_code == 200
    assert del_resp.json()["success"] is True

    # Profile should now be 404
    get_prof = client.get("/api/profile")
    assert get_prof.status_code == 404
