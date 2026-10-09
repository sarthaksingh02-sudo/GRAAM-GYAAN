# GRAAM-GYAAN 🌾🎙️

**AI-powered rural welfare assistant — powered by [Sarvam AI](https://sarvam.ai)**

> *"ग्राम-ज्ञान"* — Village Knowledge.  
> Every government scheme, health guide, and livelihood resource — in your language, on your device, even offline.

[![GitHub](https://img.shields.io/badge/GitHub-GRAAM--GYAAN-blue)](https://github.com/sarthaksingh02-sudo/GRAAM-GYAAN)

---

## What it does

GRAAM-GYAAN helps rural Indian households:
- 🗣️ **Ask by voice** in Hindi/regional languages → get answers read back aloud
- 📄 **Digitize documents** → extract fields from scheme applications, ID proofs
- 🏛️ **Find schemes** → eligibility check per family member, with reasons
- 🌱 **Get health guidance** → sourced from ASHA/MoH only, with referral advice
- 📶 **Work offline** → service worker caches data, syncs when connected

**AI Stack**: Sarvam AI — Saaras STT · Bulbul TTS · Sarvam Vision Doc AI · Sarvam-105B Chat

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/sarthaksingh02-sudo/GRAAM-GYAAN.git
cd GRAAM-GYAAN

# 2. Install Python deps
pip install -e ".[dev]"

# 3. Configure
cp .env.example .env
# Edit .env → set SARVAM_API_KEY (get one at https://dashboard.sarvam.ai)

# 4. Run smoke test (verify all 4 Sarvam services work)
python scripts/smoke_sarvam.py

# 5. Init database
python -m backend.db

# 6. Start backend
uvicorn backend.main:app --reload

# 7. Start frontend (in another terminal)
cd frontend && npm install && npm run dev
```

### Run without API key (MOCK mode)

```bash
SARVAM_MOCK=true uvicorn backend.main:app --reload
```

Mock outputs are clearly flagged with `[MOCK]` in logs and API responses. Never use mock outputs in a real demo.

---

## Repository Structure

```
GRAAM-GYAAN/
├── backend/
│   ├── main.py              # FastAPI app
│   ├── db.py                # SQLite schema (users, family_members, documents,
│   │                        #   extracted_fields, conversations)
│   ├── sarvam_client.py     # Sarvam AI wrapper (MOCK + cache)
│   └── routers/             # API route modules (added per phase)
├── frontend/                # React + Vite PWA (added Phase 4)
├── data/
│   └── real/
│       ├── schemes/         # Welfare scheme YAMLs (source_url required)
│       ├── projects/        # Government project data
│       ├── guides/          # Health & livelihood guides (MoH/ASHA sourced)
│       └── snapshots/       # Sample images/audio for smoke tests
├── data/personas/           # Synthetic test households (NOT real data)
├── scripts/
│   └── smoke_sarvam.py      # Live smoke test — verifies all 4 Sarvam APIs
├── .env.example
├── pyproject.toml
├── Project.md               # Full project specification
└── README.md
```

---

## Sarvam AI Services

| Service | Model | Endpoint | Purpose |
|---|---|---|---|
| **Saaras STT** | `saaras:v4` | `speech-to-text` | Transcribe villager voice |
| **Bulbul TTS** | `bulbul:v4-flash` | `text-to-speech` | Read answers aloud |
| **Sarvam Vision** | Vision 1.5 | `doc-ai/v1/job/extract` | Extract document fields |
| **Chat** | `sarvam-105b` | `v1/chat/completions` | Conversational Q&A |

---

## Database Schema

| Table | Purpose |
|---|---|
| `users` | Household / village operator accounts (NO Aadhaar stored) |
| `family_members` | Individual members with DOB, education, occupation |
| `documents` | Uploaded documents with status tracking |
| `extracted_fields` | Key-value fields from Sarvam Vision, with source spans |
| `conversations` | Turn-by-turn voice/chat history |

---

## Phases

| Phase | Status | Scope |
|---|---|---|
| **Phase 0** | ✅ Complete | Repo, env, Sarvam client, DB schema, smoke test |
| **Phase 1** | ⏳ Pending | Scheme loader, eligibility engine, family matcher |
| **Phase 2** | ⏳ Pending | Document AI pipeline, review/approve UI |
| **Phase 3** | ⏳ Pending | Voice assistant (STT → intent → TTS) |
| **Phase 4** | ⏳ Pending | React PWA (mobile-first, Hindi default) |
| **Phase 5** | ⏳ Pending | Health module (ASHA/MoH sourced rules only) |
| **Phase 6** | ⏳ Pending | Suggestion engine (eligibility + embedding ranking) |
| **Phase 7** | ⏳ Pending | Offline mode, service worker, sync queue |
| **Phase 8** | ⏳ Pending | Demo script, DEMO.md |

---

## Data Policy

- `/data/real/` is the source of truth. **No AI-invented welfare content**.
- Every YAML must include `source_url` and `verified_date`.
- `/data/personas/` contains **synthetic test households only** — never real villager data.
- **No Aadhaar numbers** stored anywhere. Consent screen before profile creation.

---

## Contributing

See [Project.md](Project.md) for the full specification and phase plan.

---

*Built with ❤️ for rural India · Powered by [Sarvam AI](https://sarvam.ai)*
