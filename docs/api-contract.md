# GRAAM-GYAAN API Contract (Phase 1)

## Overview
All endpoints accept and return `application/json` (except `/api/documents` which accepts `multipart/form-data`).
Identifiers (Aadhaar, PAN, Bank Account, Consumer No, Ration Card) are strictly masked at extraction time (last 4 characters preserved, e.g. `XXXX-XXXX-1234` or `XXXXXX1234`).
Aadhaar numbers are never stored in database or logs.

---

## 1. Consent & Profile Initialization

### `POST /api/consent`
Creates or confirms user consent. Required before any document upload.

**Request Body:**
```json
{
  "village": "Rampur",
  "panchayat": "Rampur Gram Panchayat",
  "district": "Varanasi",
  "state": "Uttar Pradesh",
  "language_pref": "hi-IN",
  "consent": true
}
```

**Response (200 OK):**
```json
{
  "userId": 1,
  "village": "Rampur",
  "panchayat": "Rampur Gram Panchayat",
  "district": "Varanasi",
  "state": "Uttar Pradesh",
  "language_pref": "hi-IN",
  "consentGiven": true,
  "consentAt": "2026-10-09T05:30:00Z"
}
```

---

## 2. Document Upload & Extraction

### `POST /api/documents`
Uploads a document (camera photo JPG/PNG/HEIC or PDF up to 10 pages). Downscales images before processing.

**Headers:**
- `X-User-Id`: Optional user ID (defaults to 1 if authenticated/single-user session).

**Multipart Form:**
- `file`: Binary file data
- `lang`: Target language code (e.g. `hi-IN`, default `hi-IN`)

**Response (202 Accepted):**
```json
{
  "jobId": "doc-job-a1b2c3d4"
}
```

**Error Responses:**
- `403 Forbidden`: `{"error": "CONSENT_REQUIRED", "message": "User consent must be recorded before uploading documents."}`
- `400 Bad Request`: `{"error": "INVALID_FILE_TYPE", "message": "Unsupported file format."}`
- `400 Bad Request`: `{"error": "PDF_PAGE_LIMIT_EXCEEDED", "message": "PDF exceeds 10 page limit."}`
- `400 Bad Request`: `{"error": "FILE_TOO_LARGE", "message": "File exceeds 10MB limit."}`

---

### `GET /api/documents/:jobId`
Polls the status of the Document AI job.

**Response (200 OK):**
```json
{
  "jobId": "doc-job-a1b2c3d4",
  "status": "ready",
  "docType": "ration_card",
  "category": "id_benefit",
  "extractedFields": [
    {
      "key": "head_of_family",
      "label": "Head of Family Name",
      "value": "Ramesh Kumar",
      "confidence": 0.96,
      "masked": false
    },
    {
      "key": "ration_card_number",
      "label": "Ration Card Number",
      "value": "XXXXXXXX4589",
      "confidence": 0.99,
      "masked": true
    }
  ],
  "noticeDetails": null,
  "error": null,
  "isMock": false
}
```

*For Official Notice / Other:*
```json
{
  "jobId": "doc-job-e5f6g7h8",
  "status": "ready",
  "docType": "official_notice",
  "category": "notice_other",
  "extractedFields": [],
  "noticeDetails": {
    "summary": "ग्राम पंचायत रामपुर में e-KYC शिविर...",
    "whatToDo": [
      "पंचायत भवन में उपस्थित होकर बायोमेट्रिक e-KYC पूर्ण कराएं"
    ],
    "deadline": "2026-11-10",
    "documentsNeeded": [
      "आधार कार्ड",
      "बैंक पासबुक"
    ],
    "audioUrl": "/api/documents/audio/doc-job-e5f6g7h8.wav",
    "audioAvailable": true
  },
  "error": null,
  "isMock": false
}
```

---

### `POST /api/documents/:jobId/confirm`
Approves extracted fields, binds document to family member, and recomputes missing documents.

**Request Body:**
```json
{
  "memberId": 1,
  "createFamilyMembers": true,
  "fields": [
    {
      "key": "name",
      "value": "Ramesh Kumar"
    },
    {
      "key": "dob",
      "value": "1984-05-14"
    }
  ]
}
```

**Response (200 OK):**
```json
{
  "success": true,
  "documentId": 1,
  "member": {
    "id": 1,
    "name": "Ramesh Kumar",
    "dob": "1984-05-14",
    "ageYears": 42,
    "gender": "male",
    "relation": "self",
    "documentsHeld": ["ration_card", "aadhaar"],
    "missingDocuments": [
      {
        "doc_type": "bank_passbook",
        "title": "Bank Passbook",
        "mandatory": true
      }
    ]
  },
  "createdMembers": []
}
```

---

## 3. Profile & Family Management

### `GET /api/profile`
Returns household metadata, all family members with computed `ageYears` and `missingDocuments`, and uploaded documents list.

### `PUT /api/profile`
Updates household village, panchayat, district, state, language_pref.

### `POST /api/family`
Adds a new family member to the household.

**Request Body:**
```json
{
  "name": "Sunita Devi",
  "dob": "1988-08-20",
  "gender": "female",
  "relation": "spouse",
  "education_level": "middle",
  "occupation": "homemaker",
  "caste_category": "obc",
  "is_disabled": false,
  "land_acres": 0.0
}
```

### `PUT /api/family/:memberId`
Updates a family member.

### `DELETE /api/family/:memberId`
Removes a family member.

### `DELETE /api/data`
Completely wipes user profile, family members, document records, and removes all uploaded files from disk.

---

## 4. Voice & Chat Conversation (Phase 2)

### `POST /api/chat`
Sends a text query to the assistant and receives a short, spoken-friendly grounded answer with source citations and synthesized Bulbul TTS audio.

**Request Body:**
```json
{
  "sessionId": "sess-a1b2c3d4",
  "message": "मेरी बेटी के लिए कौन सी सरकारी योजना है?",
  "lang": "hi-IN",
  "confirmAction": null
}
```

**Response (200 OK):**
```json
{
  "sessionId": "sess-a1b2c3d4",
  "text": "आपकी बेटी के लिए मुख्य योजना 'सुकन्या समृद्धि योजना' है। इसके तहत 8.2% वार्षिक ब्याज दर के साथ बचत खाता खुलता है।",
  "audioUrl": "/api/documents/audio/conv_12345.wav",
  "audioAvailable": true,
  "sources": [
    {
      "name": "Sukanya Samriddhi Yojana (SSY)",
      "url": "https://www.nsiindia.gov.in",
      "verified_date": "2026-03-01"
    }
  ],
  "requiresConfirmation": false,
  "pendingAction": null,
  "isMock": false
}
```

---

### `POST /api/voice`
Push-to-Talk voice endpoint. Uploads an audio clip, runs Saaras STT transcription, executes the grounded intent/tool, and returns Bulbul TTS synthesized audio.

**Multipart Form:**
- `file`: Binary audio WAV/MP3/M4A file
- `sessionId`: Optional session UUID
- `lang`: Target language code (default `hi-IN`)

**Response (200 OK):**
```json
{
  "transcript": "मेरे परिवार के लिए कौन सी योजनाएं हैं?",
  "assistant": {
    "sessionId": "sess-a1b2c3d4",
    "text": "आपके लिए मुख्य योजना 'प्रधानमंत्री किसान सम्मान निधि' है। इसके तहत प्रति वर्ष ₹6,000 तीन किस्तों में मिलते हैं।",
    "audioUrl": "/api/documents/audio/conv_67890.wav",
    "audioAvailable": true,
    "sources": [
      {
        "name": "PM Kisan Samman Nidhi",
        "url": "https://pmkisan.gov.in",
        "verified_date": "2026-03-01"
      }
    ],
    "requiresConfirmation": false,
    "pendingAction": null,
    "isMock": false
  }
}
```

---

### `GET /api/conversations/:sessionId`
Returns the full turn-by-turn history of a voice/text conversation session.

**Response (200 OK):**
```json
{
  "sessionId": "sess-a1b2c3d4",
  "turns": [
    {
      "id": 1,
      "turn": 1,
      "role": "user",
      "text": "मेरे गाँव में कौन से प्रोजेक्ट चल रहे हैं?",
      "audioUrl": null,
      "language": "hi-IN",
      "createdAt": "2026-10-09T05:30:00Z"
    },
    {
      "id": 2,
      "turn": 2,
      "role": "assistant",
      "text": "आपके जिले में केंद्र सरकार की ओर से जल जीवन मिशन तथा राज्य सरकार की ओर से सोलर स्ट्रीट लाइट योजना पर कार्य चल रहा है।",
      "audioUrl": "/api/documents/audio/conv_abcdef.wav",
      "language": "hi-IN",
      "createdAt": "2026-10-09T05:30:02Z"
    }
  ]
}
```

---

### `GET /api/intents`
Returns quick-question chips and supported intents from `config/intents.yaml`.

---

### `GET /api/languages`
Returns supported languages, STT codes, and TTS voice names from `config/languages.yaml`.

---

## 5. Audio Playback

### `GET /api/documents/audio/:filename`
Streams the generated Bulbul TTS WAV audio file.
