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

## 4. Audio Playback

### `GET /api/documents/audio/:filename`
Streams the generated Bulbul TTS WAV audio file for official notice summaries.
