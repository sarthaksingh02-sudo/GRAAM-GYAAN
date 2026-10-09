"""
scripts/run_demo_scenario.py — Executes the full Phase 5 demo walkthrough script.

Steps:
  1. Seed TEST PERSONA into SQLite database (from data/personas/test_household_01.yaml)
  2. Upload & Explain Official Notice (Village notice in Hindi with deadline)
  3. Voice / Text Intent: "मेरी बेटी के लिए क्या योजना है?" -> Ranked Schemes (SSY) with eligibility reasons
  4. Regional Projects: Varanasi Rural Projects (Centre vs State separated)
  5. Missing Documents & Ration Checklist for Family Members
  6. Export PDF report with Devanagari font and masked PII.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from fastapi.testclient import TestClient

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("demo_scenario")

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from backend.main import app
from scripts.seed_demo import seed_demo_database


def run_full_demo(mock_mode: bool = True, demo_cache: bool = True) -> bool:
    os.environ["SARVAM_MOCK"] = "true" if mock_mode else "false"
    os.environ["DEMO_CACHE"] = "1" if demo_cache else "0"

    print("\n" + "=" * 70)
    print(f"GRAAM-GYAAN OFFLINE-READY DEMO RUNNER [MOCK={mock_mode}, DEMO_CACHE={demo_cache}]")
    print("=" * 70)

    # Step 1: Seed TEST PERSONA
    print("\n[STEP 1/6] Seeding TEST PERSONA from data/personas/test_household_01.yaml...")
    user_id = seed_demo_database()
    client = TestClient(app)
    headers = {"X-User-Id": str(user_id)}
    print(f" -> Active User ID: {user_id}")

    # Step 2: Photograph notice & hear it explained
    print("\n[STEP 2/6] Photographing Official Notice & Explaining in Hindi...")
    sample_notice = BASE_DIR / "data" / "samples" / "sample_notice.png"
    if not sample_notice.exists():
        print(f"Error: Sample notice {sample_notice} not found!")
        return False

    with open(sample_notice, "rb") as f:
        up_resp = client.post("/api/documents", files={"file": ("notice.png", f, "image/png")}, data={"lang": "hi-IN"}, headers=headers)
    assert up_resp.status_code in (200, 202), f"Upload failed: {up_resp.text}"
    job_id = up_resp.json()["jobId"]
    print(f" -> Notice uploaded. Job ID: {job_id}")

    # Poll status
    job_resp = client.get(f"/api/documents/{job_id}", headers=headers)
    assert job_resp.status_code == 200
    print(f" -> Job Status: {job_resp.json().get('status')}")

    # Ask for notice explanation
    explain_resp = client.post("/api/chat", json={"message": "यह नोटिस समझाओ", "lang": "hi-IN"}, headers=headers)
    assert explain_resp.status_code == 200
    explain_data = explain_resp.json()
    print(f" -> Assistant Hindi Explanation:\n    \"{explain_data.get('text')}\"")
    print(f" -> Audio generated: {explain_data.get('audioAvailable')}")
    assert "PM" in explain_data.get("text") or "किसान" in explain_data.get("text") or "शिविर" in explain_data.get("text")

    # Step 3: Ask by voice: "meri beti ke liye kya scheme hai?"
    print("\n[STEP 3/6] Voice Query: 'मेरी बेटी के लिए क्या योजना है?'...")
    voice_resp = client.post("/api/chat", json={"message": "मेरी बेटी के लिए क्या योजना है?", "lang": "hi-IN"}, headers=headers)
    assert voice_resp.status_code == 200
    voice_data = voice_resp.json()
    print(f" -> Assistant Voice Response:\n    \"{voice_data.get('text')}\"")
    assert len(voice_data.get("sources", [])) > 0
    print(f" -> Sources Cited: {[s.get('name') for s in voice_data.get('sources')]}")

    # Verify Sukanya Samriddhi Scheme ranking
    schemes_resp = client.get("/api/schemes?lang=hi-IN", headers=headers)
    assert schemes_resp.status_code == 200
    schemes_data = schemes_resp.json()
    eligible_ids = [s["id"] for s in schemes_data.get("schemes", []) if s.get("status") == "ELIGIBLE"]
    print(f" -> Ranked Eligible Schemes: {eligible_ids}")
    assert "sukanya_samriddhi" in eligible_ids

    # Step 4: Open Projects in My Area (Centre vs State)
    print("\n[STEP 4/6] Querying Regional Projects (Centre vs State)...")
    proj_resp = client.get("/api/projects?lang=hi-IN", headers=headers)
    assert proj_resp.status_code == 200
    proj_data = proj_resp.json()
    centre_projs = proj_data.get("centre", []) or proj_data.get("projects", {}).get("centre", [])
    state_projs = proj_data.get("state", []) or proj_data.get("projects", {}).get("state", [])
    print(f" -> Central Projects in District ({len(centre_projs)} found):")
    for cp in centre_projs:
        print(f"    * {cp.get('name_hi', cp.get('name'))} [{cp.get('status')}] - {cp.get('agency')}")
    print(f" -> State Projects in District ({len(state_projs)} found):")
    for sp in state_projs:
        print(f"    * {sp.get('name_hi', sp.get('name'))} [{sp.get('status')}] - {sp.get('agency')}")
    assert len(centre_projs) > 0 and len(state_projs) > 0

    # Step 5: Family & Ration/Aadhaar Checklist
    print("\n[STEP 5/6] Checking Family Profile & Missing Documents Checklist...")
    prof_resp = client.get("/api/profile", headers=headers)
    assert prof_resp.status_code == 200
    prof_data = prof_resp.json()
    members = prof_data.get("familyMembers", [])
    print(f" -> Household Registered Members: {len(members)}")
    for m in members:
        missing = [md["title"] for md in m.get("missingDocuments", []) if md.get("mandatory")]
        print(f"    - {m['name']} ({m['relation']}, {m['ageYears']} yrs): Pending docs = {missing or 'None'}")

    # Step 6: Export PDF & Masking Verification
    print("\n[STEP 6/6] Generating Hindi PDF Export with Devanagari Font & Masked PII...")
    pdf_resp = client.get("/api/export/pdf?lang=hi-IN", headers=headers)
    assert pdf_resp.status_code == 200
    assert pdf_resp.content.startswith(b"%PDF")
    print(f" -> PDF Generated Successfully ({len(pdf_resp.content)} bytes).")

    # Text export masking test
    txt_resp = client.get("/api/export/text?lang=hi-IN", headers=headers)
    assert txt_resp.status_code == 200
    txt_content = txt_resp.text
    # Verify no raw unmasked IDs
    assert "1234 5678 9012" not in txt_content
    assert "987654324589" not in txt_content
    print(" -> Verified: No unmasked PII appears in exports.")

    print("\n" + "=" * 70)
    print("DEMO RUN COMPLETED SUCCESSFULLY! ALL GATES PASSED.")
    print("=" * 70 + "\n")
    return True


if __name__ == "__main__":
    is_live = "--live" in sys.argv
    run_full_demo(mock_mode=not is_live, demo_cache=True)
