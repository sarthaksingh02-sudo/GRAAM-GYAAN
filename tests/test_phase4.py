import os
import shutil
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

os.environ["SARVAM_MOCK"] = "true"
os.environ["DATABASE_URL"] = "test_graam_gyaan_p4.db"

from backend.db import get_conn, init_db
from backend.main import app


@pytest.fixture(autouse=True)
def setup_teardown_db():
    db_file = "test_graam_gyaan_p4.db"
    os.environ["DATABASE_URL"] = db_file
    test_db = Path(db_file)
    try:
        if test_db.exists():
            test_db.unlink()
    except Exception:
        pass
    init_db(test_db)
    yield
    try:
        if test_db.exists():
            test_db.unlink()
    except Exception:
        pass
    test_uploads = Path("uploads")
    if test_uploads.exists():
        shutil.rmtree(test_uploads, ignore_errors=True)


@pytest.fixture
def client():
    return TestClient(app)


def _setup_seeded_user(client):
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
    user_id = r.json()["userId"]

    # Add family members
    client.post(
        "/api/family",
        json={"name": "Ramesh Kumar", "dob": "1984-05-14", "relation": "self"},
        headers={"X-User-Id": str(user_id)},
    )
    client.post(
        "/api/family",
        json={"name": "Pooja Kumar", "dob": "2008-01-10", "relation": "daughter"},
        headers={"X-User-Id": str(user_id)},
    )

    # Insert a document with sensitive extracted fields directly to test masking
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO documents (user_id, doc_type, file_path, status) VALUES (?, ?, ?, ?)",
        (user_id, "aadhaar", "uploads/test.jpg", "ready"),
    )
    doc_id = cur.lastrowid
    cur.execute(
        "INSERT INTO extracted_fields (document_id, field_name, field_value, confidence) VALUES (?, ?, ?, ?)",
        (doc_id, "aadhaar_number", "1234 5678 9012", 0.99),
    )
    cur.execute(
        "INSERT INTO extracted_fields (document_id, field_name, field_value, confidence) VALUES (?, ?, ?, ?)",
        (doc_id, "pan_number", "ABCDE1234F", 0.98),
    )
    conn.commit()
    conn.close()

    return user_id


def test_pwa_static_files(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "GRAAM-GYAAN" in r.text or "ग्राम-ज्ञान" in r.text

    r_manifest = client.get("/manifest.json")
    assert r_manifest.status_code == 200
    assert "GRAAM-GYAAN" in r_manifest.text

    r_sw = client.get("/sw.js")
    assert r_sw.status_code == 200
    assert "CACHE_NAME" in r_sw.text

    r_css = client.get("/style.css")
    assert r_css.status_code == 200

    r_js = client.get("/app.js")
    assert r_js.status_code == 200


def test_export_pdf_endpoint(client):
    user_id = _setup_seeded_user(client)

    # Hindi PDF
    resp_hi = client.get("/api/export/pdf?lang=hi", headers={"X-User-Id": str(user_id)})
    assert resp_hi.status_code == 200
    assert resp_hi.headers["content-type"] == "application/pdf"
    assert resp_hi.content.startswith(b"%PDF")
    assert len(resp_hi.content) > 1000

    # English PDF
    resp_en = client.get("/api/export/pdf?lang=en", headers={"X-User-Id": str(user_id)})
    assert resp_en.status_code == 200
    assert resp_en.content.startswith(b"%PDF")


def test_export_text_endpoint_and_masking(client):
    user_id = _setup_seeded_user(client)

    resp = client.get("/api/export/text?lang=hi", headers={"X-User-Id": str(user_id)})
    assert resp.status_code == 200
    text = resp.text

    # Must contain summary information
    assert "ग्राम-ज्ञान" in text or "GRAAM-GYAAN" in text
    assert "Ramesh Kumar" in text or "Nayapara" in text

    # Citations must be present
    assert "स्रोत:" in text or "Source:" in text or "http" in text

    # Sensitive numbers MUST be masked: full numbers never appear
    assert "1234 5678 9012" not in text
    assert "123456789012" not in text
    assert "ABCDE1234F" not in text


def test_export_json_endpoint_and_masking(client):
    user_id = _setup_seeded_user(client)

    resp = client.get("/api/export/json?lang=hi", headers={"X-User-Id": str(user_id)})
    assert resp.status_code == 200
    data = resp.json()

    assert "household" in data
    assert "familyMembers" in data
    assert "eligibleSchemes" in data
    assert "centreProjects" in data
    assert "stateProjects" in data

    # Check raw payload for any unmasked PII
    raw_json_str = resp.text
    assert "1234 5678 9012" not in raw_json_str
    assert "123456789012" not in raw_json_str
    assert "ABCDE1234F" not in raw_json_str

    # Check citations in schemes and projects
    for s in data["eligibleSchemes"]:
        assert "sourceUrl" in s
        assert "verifiedDate" in s
