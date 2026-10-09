# Integration repair — 9 October 2026

## Repaired

- Environment initialization precedes all module settings; missing credentials no longer produce silent mock responses. Health and response modes agree.
- React/Vite replaces the legacy imperative demo UI. Build output is served by FastAPI; Vite development uses a backend proxy.
- Shared consent-aware household selection eliminates hardcoded household ID 1 across knowledge and export routes.
- Grounded live conversation includes recent household-scoped history, rule-evaluated schemes, location-filtered projects, guides, document context and validated source IDs.
- Greetings and unknown questions no longer recommend arbitrary schemes. Live provider failures return an actionable error. Model output budget accounts for reasoning tokens.
- Profile changes require stored, expiring, session-bound confirmation. Negative confirmations win; arbitrary database fields are rejected.
- Correct audio container/extension, language forwarding, genuine WAV chunks, consistent playback directory, input cleanup, empty-audio checks and visible speech failures.
- Document Extract schemas converted to valid JSON Schema; Digitise results read from structured page content. Review edits are persisted, duplicate approvals are idempotent, notices do not create fake family members, and original scans are removed after processing.
- Private API routes are excluded from offline caches. An updated worker clears the prior cache. Public catalog/guide offline responses are explicitly labelled. Location edits can be explicitly synced from an already-loaded profile.
- Missing locations return unavailable data. Missing profiles require consent. Sample household names remain marked TEST rather than silently converted to real data.
- Eligibility-filtered suggestions use local TF-IDF sparse vectors and cosine similarity. This is deterministic lexical ranking, not a pretrained semantic embedding service.
- Health module uses an NHM ASHA referral source. No unsourced diagnosis, prescription, or invented program information is added.
- Source snapshot tooling distinguishes configured, fetched, and manually verified data; fetching alone does not certify policy accuracy.

## Verification

Automated tests run in isolated copies, with synthetic temporary databases for new regression tests. Production family data is preserved. Live verification uses a separate synthetic household and synthetic notice, and checks chat follow-ups, served WAV responses, STT, document Digitise and Extract.

## Scope limits

The checked-in catalog covers five schemes and one district project snapshot. Unknown districts and subjects correctly show unavailable information. This does not create a nationwide government data feed. Existing snapshots retain their original verification dates.

Mock mode is explicitly synthetic, including a fixed STT sample and silent valid WAV fixture. Demo cache mode plays prerecorded sample content and is labelled. Real AI processing requires a configured key, provider availability and internet. Offline data browsing does not perform cloud OCR/STT/chat. The offline sync queue currently handles household-location edits, not document uploads.

The application follows the original single-device village-operator model. Header household selection is not internet-facing authentication; deploy behind an authenticated gateway before exposing it beyond a trusted local environment.

The original sample eligibility rules were incomplete. All five existing scheme records are now explicitly preliminary; a matching snapshot produces POSSIBLE rather than confirmed eligibility. Caste-only criteria for PM-JAY and PMAY-G were removed in favor of explicit official verification. Source dates were not falsely refreshed.


## Hosting and regional discovery update
The frontend now has refreshable district feeds scoped to the selected household location, including block, tehsil and census village code fields. Automatic rechecks run on access after one hour; sources may be unavailable and coverage is not exhaustive. District notices are not asserted to be active village works. Source publication dates and check timestamps are distinct. Conversation uses sarvam-105b-conversations with JSON output, saved-source fallback and separate on-demand text-to-speech. Public hosting isolates anonymous households by secure HTTP-only browser cookies. Free Render storage is ephemeral, with an explicit UI warning.
