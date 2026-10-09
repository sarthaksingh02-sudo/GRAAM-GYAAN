# GRAAM-GYAAN

A Hindi-first React PWA for household profiles, welfare schemes, document review and a source-grounded Sarvam voice assistant.

## Run locally

Requires Python 3.11+ and Node.js 22+.

```powershell
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
# Set SARVAM_API_KEY in .env. Do not commit this file.
cd frontend
npm ci
npm run build
cd ..
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000. The backend serves the production React build. After rebuilding, reload the browser; after Python changes, restart the server or run with `--reload`.

For frontend development, run `npm run dev` in `frontend` while the backend runs on port 8000. Vite proxies API requests. The service worker is registered only in production builds.

`.env` is loaded automatically without overwriting environment variables. `SARVAM_MOCK=true` explicitly enables offline synthetic AI responses. `DEMO_CACHE=1` explicitly enables prerecorded demo responses. Neither is silently enabled when a key is missing. `/healthz` reports configured mode, not a guarantee of provider availability. The UI labels mock/demo answers.

## Working flows

- Explicit consent and editable household location; add/edit family members.
- Same active household across chat, eligibility, missing documents and exports. This is a single-device/operator app, not a multi-tenant authenticated service.
- Live Sarvam chat with household context, source records, scoped conversation history and validated citation IDs. Profile changes require a session-bound read-back/confirmation.
- Saaras transcription preserves browser audio formats; Bulbul WAV output is served from the correct directory. Text remains readable if TTS fails.
- Document OCR and structured extraction use the installed SDK, JSON Schema conversion, editable field review, explicit family creation and idempotent approval.
- Source-based scheme eligibility, eligibility-filtered local TF-IDF vector ranking, application steps and local project filtering. Unavailable districts return no data rather than another district's projects.
- Health referral information from an NHM ASHA source and a livelihood guide based on the existing MGNREGA snapshot. Neither provides diagnosis or guarantees official benefit approval.
- PDF, text and JSON exports for the active household.
- Offline app shell, public scheme snapshots and saved guides. Private profiles, conversations, scans, audio and exports are never service-worker cached. Location edits made while a profile is already loaded can be queued on-device and explicitly synced on reconnection.

## Data and privacy

`data/real` contains a small curated snapshot catalog, not a live nationwide government feed. Sources and snapshot dates are shown; most existing scheme records are dated March 2026. Adding a new location requires a reviewed source record. Rates, deadlines and complete eligibility must be checked with the responsible authority.

Original uploaded scans are temporarily used for OCR and deleted after processing, including failed jobs. Extracted identifiers and conversation text are redacted; live personal chat/STT/TTS caches are disabled by default. Sarvam processes submitted documents/audio remotely. Demo family records remain clearly labelled; seeding is optional and can overwrite local demo data, so review the seed script before running it.

Source metadata generation does not verify a source. `python scripts/scrape_sources.py --fetch` fetches configured public pages for manual review and records a content hash; it never silently replaces scheme rules or updates verification dates.

## Verification

```powershell
python scripts/test_isolated.py
python scripts/check_hardcoded.py
cd frontend
npm run build
cd ..
# Optional: uses configured Sarvam credit with synthetic data only
python scripts/verify_live_repairs.py
```

Use the isolated test runner: legacy test fixtures remove their own uploads directory. The runner copies the project into `.cache/test-runs` and never uses the working household database. Live checks likewise use a separate synthetic database and files.

See `docs/IMPLEMENTATION_STATUS.md` for scope and verification evidence.
