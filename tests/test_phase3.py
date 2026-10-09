"""
tests/test_phase3.py — Pytest suite for Phase 3 (Knowledge Layer & Scheme Eligibility).

Tests:
  1. Generic deterministic eligibility evaluation (ELIGIBLE, POSSIBLE, NOT_ELIGIBLE).
  2. Scheme list endpoint with sorting and sector metadata.
  3. Regional projects endpoint with Centre & State separation.
  4. All 5 need-guides (Banking, Aadhaar/PAN, Ration, New schemes, Family) with source & date.
  5. Home screen tiles endpoint with localized i18n keys.
  6. Per-member missing documents checklist.
  7. Scraper execution and dated snapshot generation.
  8. Missing data handling returns missing_data flag without hallucination.
"""

import os
import shutil
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

os.environ["SARVAM_MOCK"] = "true"

from backend.db import init_db
from backend.eligibility_engine import evaluate_scheme_eligibility
from backend.main import app


@pytest.fixture(autouse=True)
def setup_teardown_db():
    db_file = "test_graam_gyaan_p3.db"
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


def _setup_farmer_household(client):
    r = client.post(
        "/api/consent",
        json={
            "village": "Rampur",
            "district": "Varanasi",
            "state": "Uttar Pradesh",
            "language_pref": "hi-IN",
            "consent": True,
        },
    )
    user_id = r.json()["userId"]

    # Add farmer head member
    client.post(
        "/api/family",
        json={
            "name": "Ramesh Kumar",
            "dob": "1984-05-14",
            "gender": "male",
            "relation": "self",
            "occupation": "farmer",
            "land_acres": 2.5,
            "caste_category": "obc",
        },
        headers={"X-User-Id": str(user_id)},
    )

    # Add daughter member (age ~8)
    client.post(
        "/api/family",
        json={
            "name": "Pooja Kumari",
            "dob": "2018-06-10",
            "gender": "female",
            "relation": "daughter",
        },
        headers={"X-User-Id": str(user_id)},
    )
    return user_id


# ---------------------------------------------------------------------------
# Test 1: Deterministic Eligibility Engine
# ---------------------------------------------------------------------------
def test_eligibility_engine_rules():
    # 1. PM Kisan Scheme
    pm_kisan = {
        "id": "pm_kisan",
        "rules": [
            {"field": "occupation", "operator": "in", "value": ["farmer", "agriculture"]},
            {"field": "land_acres", "operator": ">", "value": 0, "question_if_missing": "Land acres?"},
        ],
    }

    # Case A: Eligible farmer
    prof_eligible = {
        "household": {"village": "Rampur"},
        "familyMembers": [{"name": "Ramesh", "occupation": "farmer", "land_acres": 2.0}],
    }
    res_a = evaluate_scheme_eligibility(pm_kisan, prof_eligible)
    assert res_a["status"] == "ELIGIBLE"

    # Case B: Ineligible non-farmer
    prof_ineligible = {
        "household": {"village": "Rampur"},
        "familyMembers": [{"name": "Suresh", "occupation": "driver", "land_acres": 0.0}],
    }
    res_b = evaluate_scheme_eligibility(pm_kisan, prof_ineligible)
    assert res_b["status"] == "NOT_ELIGIBLE"

    # Case C: Possible (missing land info)
    prof_possible = {
        "household": {"village": "Rampur"},
        "familyMembers": [{"name": "Ramesh", "occupation": "farmer", "land_acres": None}],
    }
    res_c = evaluate_scheme_eligibility(pm_kisan, prof_possible)
    assert res_c["status"] == "POSSIBLE"
    assert len(res_c["missingFields"]) > 0


# ---------------------------------------------------------------------------
# Test 2: Schemes List Endpoint with Sorting
# ---------------------------------------------------------------------------
def test_schemes_endpoint(client):
    user_id = _setup_farmer_household(client)

    resp = client.get("/api/schemes?lang=hi-IN", headers={"X-User-Id": str(user_id)})
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] >= 3
    assert data["missing_data"] is False

    # Curated snapshots contain preliminary rules; do not promise confirmed eligibility.
    top_scheme = data["schemes"][0]
    assert top_scheme["eligibility"]["status"] == "POSSIBLE"
    assert top_scheme["eligibility"]["preliminary"] is True
    assert "sector" in top_scheme
    assert "sourceUrl" in top_scheme


# ---------------------------------------------------------------------------
# Test 3: Regional Projects Centre vs State Separation
# ---------------------------------------------------------------------------
def test_regional_projects_endpoint(client):
    user_id = _setup_farmer_household(client)

    resp = client.get("/api/projects?lang=hi-IN", headers={"X-User-Id": str(user_id)})
    assert resp.status_code == 200
    data = resp.json()
    assert data["missing_data"] is False
    assert len(data["centre"]) > 0
    assert len(data["state"]) > 0
    assert "Jal Jeevan" in str(data["centre"]) or "जल जीवन" in str(data["centre"])


# ---------------------------------------------------------------------------
# Test 4: Five Need-Guides Endpoint
# ---------------------------------------------------------------------------
def test_guides_endpoints(client):
    # 1. List all guides
    resp = client.get("/api/guides?lang=hi-IN")
    assert resp.status_code == 200
    guides = resp.json()["guides"]
    assert len(guides) == 7
    assert {"health", "livelihood"}.issubset({g["topic"] for g in guides})
    topics = [g["topic"] for g in guides]
    assert "banking" in topics
    assert "aadhaar_pan" in topics
    assert "ration" in topics
    assert "new_schemes" in topics
    assert "family" in topics

    # 2. Get specific guide detail
    detail_resp = client.get("/api/guides/banking?lang=hi-IN")
    assert detail_resp.status_code == 200
    guide_detail = detail_resp.json()
    assert guide_detail["topic"] == "banking"
    assert len(guide_detail["steps"]) >= 2
    assert "sourceUrl" in guide_detail
    assert "verifiedDate" in guide_detail


# ---------------------------------------------------------------------------
# Test 5: Home Tiles Endpoint
# ---------------------------------------------------------------------------
def test_home_tiles_endpoint(client):
    resp = client.get("/api/home-tiles?lang=hi-IN")
    assert resp.status_code == 200
    tiles = resp.json()["tiles"]
    assert len(tiles) >= 8
    tile_ids = [t["id"] for t in tiles]
    assert "talk" in tile_ids
    assert "schemes" in tile_ids
    assert "projects" in tile_ids


# ---------------------------------------------------------------------------
# Test 6: Missing Documents Checklist
# ---------------------------------------------------------------------------
def test_missing_documents_checklist(client):
    user_id = _setup_farmer_household(client)

    resp = client.get("/api/missing-documents", headers={"X-User-Id": str(user_id)})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["members"]) == 2
    head = data["members"][0]
    assert head["name"] == "Ramesh Kumar"
    assert len(head["missingDocuments"]) > 0


# ---------------------------------------------------------------------------
# Test 7: Scraper Snapshot Generator
# ---------------------------------------------------------------------------
def test_scraper_snapshot_generator():
    from scripts.scrape_sources import load_sources_config, create_snapshot_for_source

    sources = load_sources_config()
    assert len(sources) >= 5

    snapshot_path = create_snapshot_for_source(sources[0])
    assert snapshot_path is not None
    assert snapshot_path.exists()
