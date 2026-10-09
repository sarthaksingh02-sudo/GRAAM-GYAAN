"""
scripts/seed_demo.py — Seeds the SQLite database from data/personas/test_household_01.yaml.

No-hardcoding compliance:
  - Loads household and family members directly from data/personas/test_household_01.yaml
  - Links sample notice and ration card documents from data/samples/
  - Outputs summary of seeded profile.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from backend.config_loader import load_yaml
from backend.db import get_conn, init_db

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
PERSONA_PATH = BASE_DIR / "data" / "personas" / "test_household_01.yaml"
SAMPLES_DIR = BASE_DIR / "data" / "samples"
UPLOADS_DIR = BASE_DIR / "uploads"


def seed_demo_database(db_path: Path | None = None) -> int:
    """Seed the database with the TEST PERSONA and sample documents."""
    log.info("Reading TEST PERSONA from %s", PERSONA_PATH)
    persona = load_yaml(PERSONA_PATH)
    if not persona:
        raise FileNotFoundError(f"Persona file not found or empty: {PERSONA_PATH}")

    # Re-initialise database
    init_db(db_path)
    conn = get_conn(db_path)

    try:
        cur = conn.cursor()

        # Clean existing tables
        cur.execute("DELETE FROM extracted_fields")
        cur.execute("DELETE FROM documents")
        cur.execute("DELETE FROM family_members")
        cur.execute("DELETE FROM document_jobs")
        cur.execute("DELETE FROM conversations")
        cur.execute("DELETE FROM users")

        # 1. Insert household (user)
        cur.execute(
            """
            INSERT INTO users (village, panchayat, district, state, language_pref, consent_given, consent_at)
            VALUES (?, ?, ?, ?, ?, 1, datetime('now'))
            """,
            (
                persona.get("village", "Nayapara"),
                persona.get("panchayat", "Rampur Gram Panchayat"),
                persona.get("district", "Varanasi"),
                persona.get("state", "Uttar Pradesh"),
                persona.get("language_pref", "hi-IN"),
            ),
        )
        user_id = cur.lastrowid
        log.info("Created Household User ID: %s (%s, %s)", user_id, persona.get("village"), persona.get("district"))

        # 2. Insert family members
        member_map = {}
        for m in persona.get("members", []):
            cur.execute(
                """
                INSERT INTO family_members (
                    user_id, name, dob, gender, relation, education_level,
                    occupation, caste_category, is_disabled, land_acres
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    m.get("name"),
                    m.get("dob"),
                    m.get("gender"),
                    m.get("relation", "self"),
                    m.get("education_level"),
                    m.get("occupation"),
                    m.get("caste_category"),
                    1 if m.get("is_disabled") else 0,
                    float(m.get("land_acres", 0.0)),
                ),
            )
            mem_id = cur.lastrowid
            member_map[m.get("name")] = mem_id
            log.info("  -> Added member: %s (Relation: %s, DOB: %s)", m.get("name"), m.get("relation"), m.get("dob"))

        # 3. Copy sample files to uploads/ and register documents
        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

        sample_notice = SAMPLES_DIR / "sample_notice.png"
        sample_ration = SAMPLES_DIR / "sample_ration_card.png"

        if sample_notice.exists():
            target_notice = UPLOADS_DIR / "seeded_notice.png"
            shutil.copyfile(sample_notice, target_notice)
            cur.execute(
                """
                INSERT INTO documents (user_id, doc_type, category, file_path, status)
                VALUES (?, 'official_notice', 'notice', ?, 'ready')
                """,
                (user_id, str(target_notice.relative_to(BASE_DIR))),
            )
            doc_notice_id = cur.lastrowid
            cur.execute(
                """
                INSERT INTO extracted_fields (document_id, field_name, field_label, field_value, confidence)
                VALUES
                (?, 'issuing_authority', 'जारीकर्ता', 'कार्यालय ग्राम पंचायत रामपुर (वाराणसी)', 0.98),
                (?, 'deadline', 'अंतिम तिथि', '2026-11-10', 0.95),
                (?, 'summary', 'विवरण', 'PM किसान सम्मान निधि ई-केवाईसी शिविर 10 नवंबर 2026 तक पंचायत भवन में आयोजित होगा।', 0.96)
                """,
                (doc_notice_id, doc_notice_id, doc_notice_id),
            )
            log.info("  -> Seeded Official Notice Document (ID: %s)", doc_notice_id)

        if sample_ration.exists():
            target_ration = UPLOADS_DIR / "seeded_ration.png"
            shutil.copyfile(sample_ration, target_ration)
            cur.execute(
                """
                INSERT INTO documents (user_id, doc_type, category, file_path, status)
                VALUES (?, 'ration_card', 'id_benefit', ?, 'ready')
                """,
                (user_id, str(target_ration.relative_to(BASE_DIR))),
            )
            doc_ration_id = cur.lastrowid
            cur.execute(
                """
                INSERT INTO extracted_fields (document_id, field_name, field_label, field_value, confidence, is_masked)
                VALUES
                (?, 'ration_card_number', 'राशन कार्ड संख्या', 'XXXX-XXXX-4589', 0.99, 1),
                (?, 'card_type', 'कार्ड श्रेणी', 'PHH (पात्र गृहस्थी)', 0.97, 0),
                (?, 'fair_price_shop_id', 'उचित दर विक्रेता', 'FPS-VAR-042', 0.94, 0)
                """,
                (doc_ration_id, doc_ration_id, doc_ration_id),
            )
            log.info("  -> Seeded Ration Card Document (ID: %s)", doc_ration_id)

        conn.commit()
        log.info("Database seeding complete for user %d!", user_id)
        return user_id
    finally:
        conn.close()


if __name__ == "__main__":
    seed_demo_database()
