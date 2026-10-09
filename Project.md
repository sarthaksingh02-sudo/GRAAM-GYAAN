# GRAAM-GYAAN — AI-Powered Rural Welfare Assistant

> **GitHub**: https://github.com/sarthaksingh02-sudo/GRAAM-GYAAN.git
> **Mission**: Put every government scheme, health guide, and livelihood resource in the hands of India's 900M rural citizens — in their language, on their device, even offline.

---

## Problem Statement

Rural India is drowning in information asymmetry. Welfare schemes exist, health guidelines exist, educational and livelihood pathways exist — but awareness is near zero at the village level. The bottlenecks are:

1. **Language**: Government documents are in English or formal Hindi; most villagers speak regional dialects.
2. **Literacy**: A large fraction of the target audience is semi-literate or prefers voice interaction.
3. **Connectivity**: Broadband is unreliable; the app must function offline.
4. **Trust & Verification**: Misinformation is rampant; every piece of advice must cite its source and be verifiable.

---

## Solution

GRAAM-GYAAN is a **multilingual, voice-first, offline-capable welfare assistant** powered by **Sarvam AI**. It runs on a single Android/web device at the village level and connects to a cloud backend when connectivity is available.

### Core Loop

```
Villager speaks (Hindi / regional) -> Saaras STT -> Intent Engine ->
  |- Scheme lookup & eligibility check
  |- Document field extraction (Sarvam Vision)
  |- Health guidance (verified ASHA/MoH sources only)
  `- Livelihood pathway suggestion
-> Answer in local language -> Bulbul TTS -> Villager hears response
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| **AI Platform** | Sarvam AI (Saaras STT, Bulbul TTS, Sarvam-105B Chat, Sarvam Vision Doc AI) |
| **Backend** | Python 3.11, FastAPI, SQLite, Pydantic v2 |
| **Frontend** | React + Vite PWA (mobile-first, Hindi default) |
| **Database** | SQLite (no Aadhaar stored anywhere) |
| **AI Client** | Custom wrapper with MOCK mode (env var SARVAM_MOCK=true) + disk cache |

---

## Repository Structure

```
GRAAM-GYAAN/
+-- backend/                   # FastAPI server
¦   +-- main.py
¦   +-- db.py                  # SQLite schema + migrations
¦   +-- sarvam_client.py       # AI client wrapper (MOCK + cache)
¦   +-- routers/
+-- frontend/                  # React + Vite PWA
¦   +-- src/
+-- data/
¦   +-- real/
¦       +-- schemes/           # Welfare scheme YAML files (with source_url)
¦       +-- projects/          # Government project data
¦       +-- guides/            # Health & livelihood guides
¦       +-- snapshots/         # Verified document snapshots
+-- data/personas/             # Test persona households (YAML)
+-- scripts/
¦   +-- smoke_sarvam.py        # Live smoke-test for all 4 Sarvam services
+-- .env.example
+-- .gitignore
+-- pyproject.toml
+-- README.md
+-- Project.md                 # This file
```

---

## SQLite Schema

### `users`
Villagers or operator accounts (NO Aadhaar stored).

### `family_members`
Individual members linked to a user household (name, DOB, gender, education, occupation).

### `documents`
Uploaded document records (type, file path, upload timestamp, source).

### `extracted_fields`
Key-value pairs extracted by Sarvam Vision from documents, linked to documents.id.

### `conversations`
Turn-by-turn conversation history for the voice/chat assistant.

---

## Phases

| Phase | Scope |
|---|---|
| **Phase 0** | Repo + env config + Sarvam AI client wrapper (MOCK + cache) + SQLite schema + README + scripts/smoke_sarvam.py |
| **Phase 1** | Scheme ingestion pipeline: YAML loader, eligibility rule engine, family matcher |
| **Phase 2** | Document AI pipeline: upload -> Sarvam Vision extract -> review -> approve |
| **Phase 3** | Voice assistant: STT -> intent -> answer from data -> TTS |
| **Phase 4** | React PWA: home, family profile, scheme cards, health module |
| **Phase 5** | Health module: ASHA/MoH sourced rules only, referral advice with disclaimer |
| **Phase 6** | Suggestion engine: eligibility filter -> embedding ranking -> pathway guidance |
| **Phase 7** | Offline mode: service worker, local cache, sync queue |
| **Phase 8** | Demo: end-to-end script, DEMO.md, all mocked items listed |

---

## Sarvam AI Services Used

| Service | Model | Use Case |
|---|---|---|
| **Saaras STT** | saaras:v4 | Transcribe villager voice queries in Hindi/regional |
| **Bulbul TTS** | bulbul:v4-flash | Read responses aloud in local language |
| **Sarvam Vision (Doc AI)** | Sarvam Vision 1.5 | Extract fields from welfare scheme documents, ID proofs |
| **Chat** | sarvam-105b | Conversational Q&A, scheme explanation, slot-filling |

---

## Constraints

- No Aadhaar numbers stored anywhere.
- Consent screen before profile creation.
- All AI outputs in MOCK mode are clearly flagged — never presented as real.
- Every health/scheme rule must cite its source (source_url + date).
- SARVAM_MOCK=true must make the app fully functional with no API key or internet.

---

## Data Policy

- /data/real/ files are the source of truth. No AI-invented content accepted.
- Each YAML in /data/real/ must include source_url and verified_date.
- /data/personas/ contains synthetic test households only — never real villager data.

---

*Last updated: Phase 0 — October 2026*
