# 🌾 GRAAM-GYAAN (ग्राम-ज्ञान) — Official Demo Walkthrough (DEMO.md)

This document provides a click-by-click demonstration guide for **GRAAM-GYAAN**, an offline-ready, voice-enabled rural welfare assistant built for Indian citizens.

---

## 🚀 Quickstart: Launching the Demo

Run the demo using either `make demo` or standard Python commands:

```bash
# 1. Seed demo persona and start app in offline-ready demo mode:
make demo

# Or manually:
python scripts/seed_demo.py
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

Open your browser at: **[http://localhost:8000](http://localhost:8000)**

---

## 📱 Click-by-Click Demo Walkthrough Script

### Step 1: Photograph & Scan an Official Village Notice
1. On the home screen, click the **"कागज़ स्कैन (Scan Document)"** icon tile.
2. Select or upload `data/samples/sample_notice.png` (or take a photo with your mobile camera).
3. The UI shows an active scanning pulse state while **Sarvam Document AI** extracts the notice.
4. The system classifies the document as `official_notice` and extracts:
   - **Issuing Authority:** कार्यालय ग्राम पंचायत रामपुर (वाराणसी)
   - **Action Deadline:** `2026-11-10`
   - **Summary:** PM-Kisan e-KYC and land seeding camp at Panchayat Bhavan.

### Step 2: Hear the Notice Explained in Spoken Hindi
1. Tap the **"बोलो (Voice Assistant)"** or microphone button.
2. Say: *"यह नोटिस समझाओ"* (or type it in the chat box).
3. **Response:** The assistant speaks out a 2-sentence conversational Hindi explanation using **Sarvam Bulbul TTS**:
   > *"ग्राम पंचायत रामपुर में प्रधानमंत्री किसान सम्मान निधि के अंतर्गत e-KYC एवं भूलेख अंकन शिविर 10 नवंबर 2026 तक पंचायत भवन पर आयोजित किया जा रहा है।"*
4. Grounded citation displays: `कार्यालय ग्राम पंचायत रामपुर (वाराणसी) • 2026-10-05`.

### Step 3: Voice Query for Daughter's Welfare Schemes
1. Press and hold the **Push-to-Talk (PTT)** button.
2. Speak clearly in Hindi: *"मेरी बेटी के लिए क्या योजना है?"* (What schemes exist for my daughter?).
3. **Speech-to-Text (Saaras):** Transcribes the query with high accuracy.
4. **Eligibility Engine:** Evaluates data in `data/real/schemes/*.yaml` against the daughter's profile (Pooja Kumar, age 8):
   - **Rank #1 (ELIGIBLE):** **Sukanya Samriddhi Yojana (SSY)** — Matched `gender == female` and `ageYears <= 10`.
5. **Bulbul TTS Spoken Answer:**
   > *"आपके लिए मुख्य योजना 'सुकन्या समृद्धि योजना' है। इसके तहत बेटी की उच्च शिक्षा और विवाह हेतु 8.2% वार्षिक ब्याज दर के साथ बचत खाता खोला जाता है। इसके अलावा आयुष्मान भारत का लाभ भी उपलब्ध है।"*

### Step 4: Explore Regional Development Projects (Centre vs State)
1. Tap the **"विकास कार्य (Projects in My Area)"** tile from the home screen.
2. The UI cleanly presents two distinct sections for **Varanasi Rural**:
   - **Central Government Projects (केंद्र सरकार):**
     - *जल जीवन मिशन - हर घर नल से जल* (Ministry of Jal Shakti, GoI)
     - *प्रधानमंत्री ग्राम सड़क योजना* (Ministry of Rural Development, GoI)
   - **State Government Projects (उत्तर प्रदेश सरकार):**
     - *मुख्यमंत्री सौर स्ट्रीट लाइट योजना* (UPNEDA, UP)
     - *ग्राम सचिवालय डिजिटल सेवा एवं वाई-फाई* (Panchayati Raj Dept, UP)
3. Every project cites its official tracking portal and verified snapshot date.

### Step 5: Review Missing Documents & Ration Checklist
1. Tap the **"मेरा परिवार (My Family)"** or **"राशन गाइड (Ration Guide)"** tile.
2. View the per-member mandatory document checklist:
   - **Ramesh Kumar (Self, Farmer):** Missing Aadhaar, Bank passbook seeding
   - **Pooja Kumar (Daughter):** Birth Certificate / Aadhaar
3. The interactive checklist guides the user on how to obtain missing papers without agent fees.

### Step 6: Export Grounded Hindi PDF & Plain Text
1. Tap the **"📄 PDF"** button in the header bar.
2. The browser downloads a formatted A4 PDF (`graam_gyaan_summary_hi.pdf`) generated with **Noto Sans Devanagari**:
   - Clean Hindi typography (no missing glyph boxes `[]`).
   - Every fact grounded with official source URL and verification date.
   - **Strict PII Masking:** Only masked identifiers appear (`XXXX-XXXX-4589`), ensuring privacy.
3. Tap **"📋 Text"** to copy a concise WhatsApp/SMS-ready summary.

---

## 🗂️ Knowledge Base & Data File Inventory

All data in GRAAM-GYAAN is loaded from authoritative government sources without hardcoding:

| Data File Path | Description | Official `source_url` | Verified Date |
| :--- | :--- | :--- | :--- |
| `data/real/schemes/sukanya_samriddhi.yaml` | Sukanya Samriddhi Scheme & Rules | `https://www.nsiindia.gov.in` | `2026-03-01` |
| `data/real/schemes/pm_kisan.yaml` | PM-Kisan Samman Nidhi Rules | `https://pmkisan.gov.in` | `2026-03-01` |
| `data/real/schemes/ayushman_bharat.yaml` | PM-JAY Health Benefit Criteria | `https://pmjay.gov.in` | `2026-03-01` |
| `data/real/schemes/mgnrega.yaml` | 100-Day Wage Employment Rules | `https://nrega.nic.in` | `2026-03-01` |
| `data/real/schemes/pmay_g.yaml` | Rural Housing Subsidy Rules | `https://pmayg.nic.in` | `2026-03-01` |
| `data/real/projects/varanasi_rural_projects.yaml` | Varanasi Centre & State Projects | `https://varanasi.nic.in/development` | `2026-03-15` |
| `data/real/guides/banking_guide.yaml` | Aadhaar-DBT Bank Account Guide | `https://www.npci.org.in` | `2026-02-15` |
| `data/real/guides/aadhaar_pan_guide.yaml` | UIDAI / PAN Card Linking Guide | `https://uidai.gov.in` | `2026-02-15` |
| `data/real/guides/ration_guide.yaml` | NFSA Ration Card & e-KYC Guide | `https://fcs.up.gov.in` | `2026-02-15` |
| `data/real/guides/new_schemes_guide.yaml` | New Schemes Registration Guide | `https://www.myscheme.gov.in` | `2026-02-15` |
| `data/real/guides/family_guide.yaml` | Family Member Addition Guide | `https://edistrict.up.gov.in` | `2026-02-15` |
| `data/personas/test_household_01.yaml` | Synthetic Test Household Persona | `Local Test Persona` | `2026-10-09` |

---

## 🛡️ Offline & Cache Mode (`DEMO_CACHE=1`)

To guarantee smooth operation in venues with poor internet or conference Wi-Fi failures:
1. **Deterministic Cache Files (`demo_cache/`)**:
   - `demo_cache/doc_notice_extract.json`
   - `demo_cache/doc_ration_extract.json`
   - `demo_cache/stt_beti_scheme.json`
   - `demo_cache/tts_beti_scheme.json`
2. **Transparent Labelling**:
   When cached demo responses are served, the system logs `[SARVAM DEMO_CACHE]` and tags response payloads with `"note": "cached demo response"`. Nothing is faked silently.
3. **Live Mode Verification**:
   Running with `SARVAM_API_KEY=<key> DEMO_CACHE=0 SARVAM_MOCK=false` makes live HTTPS API calls directly to Sarvam AI endpoints.

---

## 🧪 Automated Gate Verification

Run the complete test suite and demo runner verification:

```bash
# 1. Run all 23 unit tests
python -m pytest -v

# 2. Run no-hardcoding validator
python scripts/check_hardcoded.py

# 3. Run the automated end-to-end demo scenario script
python scripts/run_demo_scenario.py
```
