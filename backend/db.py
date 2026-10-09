"""
backend/db.py — SQLite schema, database connection, and data models for GRAAM-GYAAN.

Run directly to initialise the database:
    python -m backend.db

Tables:
  users            - household accounts with consent tracking (NO Aadhaar stored)
  family_members   - individual members of a household (DOB stored, age computed dynamically)
  documents        - uploaded document records
  extracted_fields - key-value fields extracted by Sarvam Vision (masked)
  document_jobs    - async Document AI processing jobs
  conversations    - voice/chat assistant history
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path

log = logging.getLogger(__name__)

DB_PATH = Path(os.getenv("DATABASE_URL", "graam_gyaan.db").replace("sqlite:///./", ""))

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS pending_actions (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id TEXT NOT NULL,
    action_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, session_id)
);

-- ===========================================================================
-- users: household metadata and consent
-- ===========================================================================
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    village         TEXT    NOT NULL DEFAULT 'Unknown',
    panchayat       TEXT,
    district        TEXT,
    state           TEXT    NOT NULL DEFAULT 'Unknown',
    language_pref   TEXT    NOT NULL DEFAULT 'hi-IN',
    consent_given   INTEGER NOT NULL DEFAULT 0,
    consent_at      TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ===========================================================================
-- family_members: individual members linked to household
-- ===========================================================================
CREATE TABLE IF NOT EXISTS family_members (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name            TEXT    NOT NULL,
    dob             TEXT,           -- YYYY-MM-DD; age computed dynamically as ageYears
    gender          TEXT,           -- male / female / other
    relation        TEXT    NOT NULL DEFAULT 'self', -- self / spouse / son / daughter / father / mother / other
    education_level TEXT,
    occupation      TEXT,
    caste_category  TEXT,
    is_disabled     INTEGER DEFAULT 0,
    land_acres      REAL    DEFAULT 0.0,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ===========================================================================
-- documents: confirmed or uploaded documents
-- ===========================================================================
CREATE TABLE IF NOT EXISTS documents (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER REFERENCES users(id) ON DELETE CASCADE,
    member_id       INTEGER REFERENCES family_members(id) ON DELETE SET NULL,
    job_id          TEXT,
    doc_type        TEXT    NOT NULL,
    category        TEXT    DEFAULT 'id_benefit',
    file_path       TEXT,
    source_url      TEXT,
    language        TEXT    DEFAULT 'hi-IN',
    status          TEXT    NOT NULL DEFAULT 'ready',
    uploaded_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    approved_at     TEXT,
    notes           TEXT
);

-- ===========================================================================
-- extracted_fields: extracted key-value pairs (strictly masked)
-- ===========================================================================
CREATE TABLE IF NOT EXISTS extracted_fields (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id     INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    field_name      TEXT    NOT NULL,
    field_label     TEXT,
    field_value     TEXT,
    confidence      REAL,
    is_masked       INTEGER DEFAULT 0,
    is_mock         INTEGER DEFAULT 0,
    extracted_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ===========================================================================
-- document_jobs: background Document AI job tracking
-- ===========================================================================
CREATE TABLE IF NOT EXISTS document_jobs (
    job_id          TEXT PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status          TEXT NOT NULL DEFAULT 'queued', -- queued / processing / ready / failed
    doc_type        TEXT,
    category        TEXT,
    file_path       TEXT,
    lang            TEXT DEFAULT 'hi-IN',
    result_json     TEXT,
    error_code      TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ===========================================================================
-- conversations: assistant turns
-- ===========================================================================
CREATE TABLE IF NOT EXISTS conversations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER REFERENCES users(id) ON DELETE CASCADE,
    session_id      TEXT    NOT NULL,
    turn            INTEGER NOT NULL,
    role            TEXT    NOT NULL,
    content_text    TEXT    NOT NULL,
    audio_path      TEXT,
    language        TEXT    DEFAULT 'hi-IN',
    is_mock         INTEGER DEFAULT 0,
    latency_ms      INTEGER,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_family_members_user ON family_members(user_id);
CREATE INDEX IF NOT EXISTS idx_documents_user      ON documents(user_id);
CREATE INDEX IF NOT EXISTS idx_documents_member    ON documents(member_id);
CREATE INDEX IF NOT EXISTS idx_extracted_doc       ON extracted_fields(document_id);
CREATE INDEX IF NOT EXISTS idx_doc_jobs_user       ON document_jobs(user_id);
CREATE INDEX IF NOT EXISTS idx_conversations_sess  ON conversations(session_id, turn);
"""


def get_db_path() -> Path:
    """Return the current active database path."""
    db_env = os.getenv("DATABASE_URL", "graam_gyaan.db").replace("sqlite:///./", "")
    return Path(db_env)


def init_db(db_path: Path | None = None) -> None:
    """Create all tables and run lightweight column migrations (idempotent)."""
    target = db_path or get_db_path()
    log.info("Initialising database at %s", target)
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target)
    try:
        # Check and migrate columns if documents table already exists
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='documents'")
        if cur.fetchone():
            cur.execute("PRAGMA table_info(documents)")
            cols = [r[1] for r in cur.fetchall()]
            if "member_id" not in cols:
                cur.execute("ALTER TABLE documents ADD COLUMN member_id INTEGER REFERENCES family_members(id) ON DELETE SET NULL")
            if "job_id" not in cols:
                cur.execute("ALTER TABLE documents ADD COLUMN job_id TEXT")
            if "category" not in cols:
                cur.execute("ALTER TABLE documents ADD COLUMN category TEXT DEFAULT 'id_benefit'")
            conn.commit()

        conn.executescript(SCHEMA_SQL)
        columns = {r[1] for r in conn.execute("PRAGMA table_info(conversations)")}
        if "metadata_json" not in columns:
            conn.execute("ALTER TABLE conversations ADD COLUMN metadata_json TEXT")
        user_columns = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
        for name in ("device_key", "block", "tehsil", "village_code"):
            if name not in user_columns:
                conn.execute(f"ALTER TABLE users ADD COLUMN {name} TEXT")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_device_key ON users(device_key)")
        conn.commit()
        log.info("Database ready.")
    finally:
        conn.close()


def get_conn(db_path: Path | None = None) -> sqlite3.Connection:
    """Return a synchronous SQLite connection with Row factory."""
    target = db_path or get_db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_db()
    print("Database initialised at:", DB_PATH.resolve())
