"""
backend/db.py — SQLite schema and migration runner for GRAAM-GYAAN.

Run directly to initialise the database:
    python -m backend.db

Tables:
  users            - village operator / household accounts (NO Aadhaar stored)
  family_members   - individual members of a household
  documents        - uploaded document records
  extracted_fields - key-value fields extracted by Sarvam Vision
  conversations    - voice/chat conversation turns
"""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
from pathlib import Path

log = logging.getLogger(__name__)

DB_PATH = Path(os.getenv("DATABASE_URL", "graam_gyaan.db").replace("sqlite:///./", ""))

# ---------------------------------------------------------------------------
# DDL — all tables
# ---------------------------------------------------------------------------
SCHEMA_SQL = """
-- ─────────────────────────────────────────────────────────────────────────────
-- users: one row per household / village operator
-- NO Aadhaar or biometric data stored here.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    village         TEXT    NOT NULL,
    panchayat       TEXT,
    district        TEXT,
    state           TEXT    NOT NULL DEFAULT 'Unknown',
    language_pref   TEXT    NOT NULL DEFAULT 'hi-IN',  -- Sarvam language code
    consent_given   INTEGER NOT NULL DEFAULT 0,         -- 1 when consent screen accepted
    consent_at      TEXT,                               -- ISO-8601 timestamp
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ─────────────────────────────────────────────────────────────────────────────
-- family_members: individual members linked to a household
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS family_members (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name            TEXT    NOT NULL,
    dob             TEXT,           -- YYYY-MM-DD; age computed at query time
    gender          TEXT,           -- male / female / other
    education_level TEXT,           -- none / primary / middle / secondary / graduate / postgraduate
    occupation      TEXT,
    caste_category  TEXT,           -- general / obc / sc / st
    is_disabled     INTEGER DEFAULT 0,
    land_acres      REAL,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ─────────────────────────────────────────────────────────────────────────────
-- documents: uploaded or referenced government documents
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS documents (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER REFERENCES users(id) ON DELETE SET NULL,
    doc_type        TEXT    NOT NULL,   -- e.g. income_certificate, ration_card, scheme_notice
    file_path       TEXT,               -- local path (never Aadhaar scan stored)
    source_url      TEXT,               -- original government URL if applicable
    language        TEXT    DEFAULT 'hi-IN',
    status          TEXT    NOT NULL DEFAULT 'pending',  -- pending / extracted / approved / rejected
    uploaded_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    approved_at     TEXT,
    notes           TEXT
);

-- ─────────────────────────────────────────────────────────────────────────────
-- extracted_fields: key-value pairs from Sarvam Vision Doc AI
-- Each row is one field from one document.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS extracted_fields (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id     INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    field_name      TEXT    NOT NULL,
    field_value     TEXT,
    confidence      REAL,           -- 0.0–1.0 if provided by model
    source_span     TEXT,           -- text snippet the model grounded this on
    is_mock         INTEGER DEFAULT 0,   -- 1 if produced in MOCK mode
    extracted_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ─────────────────────────────────────────────────────────────────────────────
-- conversations: turn-by-turn voice / chat assistant history
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS conversations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER REFERENCES users(id) ON DELETE SET NULL,
    session_id      TEXT    NOT NULL,   -- UUID per session
    turn            INTEGER NOT NULL,   -- 1-indexed within a session
    role            TEXT    NOT NULL,   -- user / assistant
    content_text    TEXT    NOT NULL,
    audio_path      TEXT,               -- path to WAV if voice turn
    language        TEXT    DEFAULT 'hi-IN',
    is_mock         INTEGER DEFAULT 0,
    latency_ms      INTEGER,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Indexes
-- ─────────────────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_family_members_user ON family_members(user_id);
CREATE INDEX IF NOT EXISTS idx_documents_user      ON documents(user_id);
CREATE INDEX IF NOT EXISTS idx_extracted_doc       ON extracted_fields(document_id);
CREATE INDEX IF NOT EXISTS idx_conversations_sess  ON conversations(session_id, turn);
"""


# ---------------------------------------------------------------------------
# Migration runner
# ---------------------------------------------------------------------------
def init_db(db_path: Path = DB_PATH) -> None:
    """Create all tables (idempotent — uses IF NOT EXISTS)."""
    log.info("Initialising database at %s", db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
        log.info("Database ready.")
    finally:
        conn.close()


def get_conn(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Return a synchronous SQLite connection with row_factory set."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_db()
    print("Database initialised at:", DB_PATH.resolve())
