// frontend/public/app.js — GRAAM-GYAAN PWA Frontend Logic

let currentLang = "hi-IN";
let currentSessionId = "sess-" + Math.random().toString(36).substring(2, 10);
let pendingAssistantAction = null;
let currentJobId = null;
let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;
let userProfile = null;

document.addEventListener("DOMContentLoaded", () => {
  initPWA();
  loadUserProfile();
  loadHomeTiles();
  loadIntentsChips();
  setupEventListeners();
});

function initPWA() {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker
      .register("/sw.js")
      .then((reg) => console.log("[PWA] Service Worker registered:", reg.scope))
      .catch((err) => console.log("[PWA] SW registration failed:", err));
  }
}

function setupEventListeners() {
  const langSel = document.getElementById("langSelector");
  if (langSel) {
    langSel.addEventListener("change", (e) => {
      currentLang = e.target.value;
      loadHomeTiles();
      loadIntentsChips();
      loadUserProfile();
      showToast("भाषा बदली गई / Language updated");
    });
  }

  const pttBtn = document.getElementById("pttButton");
  if (pttBtn) {
    pttBtn.addEventListener("click", () => openVoiceAssistant());
  }

  const exportBtn = document.getElementById("exportMenuBtn");
  if (exportBtn) {
    exportBtn.addEventListener("click", () => openExportModal());
  }
}

function showToast(msg) {
  const t = document.getElementById("toast");
  if (!t) return;
  t.innerText = msg;
  t.classList.remove("hidden");
  setTimeout(() => t.classList.add("hidden"), 3000);
}

// ---------------------------------------------------------------------------
// 1. User Profile & Location Management
// ---------------------------------------------------------------------------
async function loadUserProfile() {
  try {
    const res = await fetch(`/api/profile?lang=${currentLang}`);
    if (!res.ok) return;
    const data = await res.json();
    userProfile = data;

    const h = data.household || {};
    const village = h.village || "Nayapara";
    const district = h.district || "Varanasi";
    const bannerText = `${village}, ${district}`;

    const bannerEl = document.getElementById("bannerVillageName");
    if (bannerEl) {
      bannerEl.innerText = bannerText;
    }

    // Populate inputs in profile modal
    if (document.getElementById("locVillage")) document.getElementById("locVillage").value = h.village || "";
    if (document.getElementById("locPanchayat")) document.getElementById("locPanchayat").value = h.panchayat || "";
    if (document.getElementById("locDistrict")) document.getElementById("locDistrict").value = h.district || "";
    if (document.getElementById("locState")) document.getElementById("locState").value = h.state || "";
  } catch (e) {
    console.warn("Could not load user profile:", e);
  }
}

function openProfileModal() {
  document.getElementById("profileModal").classList.remove("hidden");
}

function closeProfileModal() {
  document.getElementById("profileModal").classList.add("hidden");
}

async function saveLocationProfile() {
  const village = document.getElementById("locVillage").value.trim() || "Nayapara";
  const panchayat = document.getElementById("locPanchayat").value.trim() || "Rampur Gram Panchayat";
  const district = document.getElementById("locDistrict").value.trim() || "Varanasi";
  const state = document.getElementById("locState").value.trim() || "Uttar Pradesh";

  try {
    const res = await fetch("/api/consent", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        village: village,
        panchayat: panchayat,
        district: district,
        state: state,
        language_pref: currentLang,
        consent: true,
      }),
    });

    if (res.ok) {
      closeProfileModal();
      showToast("📍 स्थान सफलतापूर्वक अपडेट किया गया! / Location Saved!");
      await loadUserProfile();
      loadHomeTiles();
    } else {
      showToast("त्रुटि: स्थान अपडेट नहीं हो सका");
    }
  } catch (e) {
    console.error("Save location error:", e);
    showToast("त्रुटि: सर्वर से संपर्क नहीं हो पाया");
  }
}

// ---------------------------------------------------------------------------
// 2. Home Screen Tiles & Intents
// ---------------------------------------------------------------------------
async function loadHomeTiles() {
  const grid = document.getElementById("homeTilesGrid");
  if (!grid) return;

  try {
    const res = await fetch(`/api/home-tiles?lang=${currentLang}`);
    const data = await res.json();
    grid.innerHTML = "";

    const iconMap = {
      Mic: "🎙️",
      Camera: "📷",
      Users: "👨‍👩‍👧‍👦",
      Award: "🏆",
      MapPin: "📍",
      Landmark: "🏦",
      CreditCard: "💳",
      ShoppingBag: "🌾",
      Sparkles: "✨",
      FileText: "📜",
    };

    (data.tiles || []).forEach((tile) => {
      const el = document.createElement("div");
      el.className = "home-tile";
      el.onclick = () => handleTileClick(tile);

      const emoji = iconMap[tile.icon] || "📄";
      const badgeHtml = tile.badge ? `<span class="tile-badge">${tile.badge}</span>` : "";

      el.innerHTML = `
        ${badgeHtml}
        <div class="tile-icon-circle" style="background: ${tile.color}15; color: ${tile.color}">
          ${emoji}
        </div>
        <span class="tile-label">${tile.label}</span>
      `;
      grid.appendChild(el);
    });
  } catch (e) {
    console.error("Error loading home tiles:", e);
  }
}

async function loadIntentsChips() {
  const container = document.getElementById("chipsContainer");
  if (!container) return;

  try {
    const res = await fetch(`/api/intents?lang=${currentLang}`);
    const data = await res.json();
    container.innerHTML = "";

    (data.chips || []).forEach((chip) => {
      const btn = document.createElement("button");
      btn.className = "chip";
      btn.innerText = chip.text;
      btn.onclick = () => handleChipClick(chip.text);
      container.appendChild(btn);
    });
  } catch (e) {
    console.error("Error loading chips:", e);
  }
}

function handleTileClick(tile) {
  if (tile.id === "talk") {
    openVoiceAssistant();
  } else if (tile.id === "scan_document") {
    openScanModal();
  } else if (tile.id === "my_family") {
    openFamilyViewer();
  } else if (tile.id === "schemes") {
    openSchemesViewer();
  } else if (tile.id === "projects") {
    openProjectsViewer();
  } else if (tile.guideTopic) {
    openGuideViewer(tile.guideTopic);
  }
}

// ---------------------------------------------------------------------------
// 3. Voice Assistant (PTT, Audio & Text Chat)
// ---------------------------------------------------------------------------
function openVoiceAssistant(initialQuery = "") {
  document.getElementById("voiceModal").classList.remove("hidden");
  const inputEl = document.getElementById("voiceTextInput");
  if (inputEl) inputEl.value = "";

  document.getElementById("voiceStatusText").innerText = "सहायक तैयार है / Assistant Ready";
  document.getElementById("assistantResponseText").innerText = "नमस्ते! आप बोलकर या लिखकर सरकारी योजनाओं के बारे में पूछ सकते हैं।";
  document.getElementById("sourcesBox").innerHTML = "";

  setMicRecordingUI(false);

  if (initialQuery) {
    sendTextMessage(initialQuery);
  }
}

function closeVoiceModal() {
  document.getElementById("voiceModal").classList.add("hidden");
  stopAudioRecording();
}

function handleChipClick(queryText) {
  openVoiceAssistant(queryText);
}

function sendVoiceTypedMessage() {
  const inputEl = document.getElementById("voiceTextInput");
  if (!inputEl) return;
  const text = inputEl.value.trim();
  if (!text) return;
  inputEl.value = "";
  sendTextMessage(text);
}

async function sendTextMessage(text) {
  document.getElementById("userTranscriptText").innerText = `"${text}"`;
  document.getElementById("voiceStatusText").innerText = "सोच रहा हूँ (Processing)...";
  document.getElementById("assistantResponseText").innerText = "जानकारी खोजी जा रही है...";

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sessionId: currentSessionId,
        message: text,
        lang: currentLang,
        confirmAction: pendingAssistantAction,
      }),
    });

    const data = await res.json();
    displayAssistantResponse(data);
  } catch (e) {
    document.getElementById("assistantResponseText").innerText = "त्रुटि: सर्वर से संपर्क नहीं हो पाया।";
  }
}

function displayAssistantResponse(data) {
  document.getElementById("voiceStatusText").innerText = "सहायक का उत्तर / Assistant:";
  document.getElementById("assistantResponseText").innerText = data.text;

  // Sources tags
  const sourcesBox = document.getElementById("sourcesBox");
  sourcesBox.innerHTML = "";
  (data.sources || []).forEach((src) => {
    const tag = document.createElement("span");
    tag.className = "source-tag";
    tag.innerText = `🔍 ${src.name || "सरकारी स्रोत"}`;
    sourcesBox.appendChild(tag);
  });

  // Audio playback
  const audioPlayer = document.getElementById("ttsAudioPlayer");
  if (data.audioUrl && audioPlayer) {
    audioPlayer.src = data.audioUrl;
    audioPlayer.classList.remove("hidden");
    audioPlayer.play().catch((err) => {
      console.log("Audio autoplay prevented by browser:", err);
    });
  }

  // Confirmation gate
  pendingAssistantAction = data.pendingAction;
  const btnConfirm = document.getElementById("btnVoiceConfirm");
  const btnCancel = document.getElementById("btnVoiceCancel");
  if (data.requiresConfirmation) {
    btnConfirm.classList.remove("hidden");
    btnCancel.classList.remove("hidden");
  } else {
    btnConfirm.classList.add("hidden");
    btnCancel.classList.add("hidden");
  }
}

function confirmAssistantAction(confirmed) {
  const reply = confirmed ? "हाँ, पुष्टि करें" : "नहीं, रद्द करें";
  sendTextMessage(reply);
}

function toggleVoiceRecording() {
  if (isRecording) {
    stopAudioRecording();
  } else {
    startAudioRecording();
  }
}

function setMicRecordingUI(recording) {
  isRecording = recording;
  const btn = document.getElementById("btnRecordToggle");
  const icon = document.getElementById("btnMicIcon");
  const label = document.getElementById("btnMicLabel");
  const visualizer = document.getElementById("voiceVisualizer");
  const pulse = document.getElementById("voicePulseDot");

  if (recording) {
    if (btn) btn.classList.add("recording");
    if (icon) icon.innerText = "⏹️";
    if (label) label.innerText = "बोलना बंद करें (Stop)";
    if (visualizer) visualizer.style.opacity = "1";
    if (pulse) pulse.style.background = "#d32f2f";
    document.getElementById("voiceStatusText").innerText = "🎙️ सुन रहा हूँ... बोलिए (Listening)";
  } else {
    if (btn) btn.classList.remove("recording");
    if (icon) icon.innerText = "🎙️";
    if (label) label.innerText = "बोलना शुरू करें (Speak)";
    if (visualizer) visualizer.style.opacity = "0.4";
    if (pulse) pulse.style.background = "#2e7d32";
  }
}

function startAudioRecording() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    document.getElementById("voiceStatusText").innerText = "माइक्रोफ़ोन उपलब्ध नहीं है। आप नीचे टाइप कर सकते हैं।";
    return;
  }

  navigator.mediaDevices
    .getUserMedia({ audio: true })
    .then((stream) => {
      setMicRecordingUI(true);
      mediaRecorder = new MediaRecorder(stream);
      audioChunks = [];

      mediaRecorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) {
          audioChunks.push(e.data);
        }
      };

      mediaRecorder.onstop = () => {
        setMicRecordingUI(false);
        // Stop all audio tracks
        stream.getTracks().forEach((track) => track.stop());
        uploadVoiceAudio();
      };

      mediaRecorder.start();

      // Auto stop after 6 seconds max
      setTimeout(() => {
        if (mediaRecorder && mediaRecorder.state === "recording") {
          mediaRecorder.stop();
        }
      }, 6000);
    })
    .catch((err) => {
      console.warn("Microphone access denied or error:", err);
      setMicRecordingUI(false);
      document.getElementById("voiceStatusText").innerText = "माइक्रोफ़ोन अनुमति नहीं मिली। कृपया नीचे टाइप करें।";
      showToast("माइक्रोफ़ोन अनुमति नहीं मिली");
    });
}

function stopAudioRecording() {
  if (mediaRecorder && mediaRecorder.state === "recording") {
    mediaRecorder.stop();
  }
  setMicRecordingUI(false);
}

async function uploadVoiceAudio() {
  if (!audioChunks || audioChunks.length === 0) {
    return;
  }

  const audioBlob = new Blob(audioChunks, { type: "audio/wav" });
  const formData = new FormData();
  formData.append("file", audioBlob, "voice_query.wav");
  formData.append("sessionId", currentSessionId);
  formData.append("lang", currentLang);

  document.getElementById("voiceStatusText").innerText = "Saaras STT ट्रांसक्रिप्शन एवं उत्तर तैयार हो रहा है...";

  try {
    const res = await fetch("/api/voice", {
      method: "POST",
      body: formData,
    });
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }
    const data = await res.json();
    document.getElementById("userTranscriptText").innerText = `"${data.transcript}"`;
    displayAssistantResponse(data.assistant);
  } catch (e) {
    console.error("Voice upload error:", e);
    document.getElementById("voiceStatusText").innerText = "ऑडियो समझने में त्रुटि हुई। कृपया दोबारा बोलें या टाइप करें।";
  }
}

// ---------------------------------------------------------------------------
// 4. Document Scanning & OCR
// ---------------------------------------------------------------------------
function openScanModal() {
  document.getElementById("scanModal").classList.remove("hidden");
  document.getElementById("scanProgressBox").classList.add("hidden");
  document.getElementById("extractionReviewBox").classList.add("hidden");
}

function closeScanModal() {
  document.getElementById("scanModal").classList.add("hidden");
}

async function handleDocFileUpload(event) {
  const file = event.target.files[0];
  if (!file) return;

  const formData = new FormData();
  formData.append("file", file);
  formData.append("lang", currentLang);

  document.getElementById("scanProgressBox").classList.remove("hidden");
  document.getElementById("scanProgressText").innerText = "दस्तावेज़ अपलोड एवं Sarvam Vision OCR निष्कर्षण जारी...";

  try {
    const res = await fetch("/api/documents", {
      method: "POST",
      body: formData,
    });
    const data = await res.json();
    currentJobId = data.jobId;
    pollDocumentJob(currentJobId);
  } catch (e) {
    showToast("दस्तावेज़ अपलोड में त्रुटि");
  }
}

async function pollDocumentJob(jobId) {
  const interval = setInterval(async () => {
    try {
      const res = await fetch(`/api/documents/${jobId}`);
      const data = await res.json();

      if (data.status === "ready") {
        clearInterval(interval);
        showExtractionReview(data);
      } else if (data.status === "failed") {
        clearInterval(interval);
        document.getElementById("scanProgressText").innerText = "त्रुटि: दस्तावेज़ निष्कर्षण विफल रहा।";
      }
    } catch (e) {
      clearInterval(interval);
    }
  }, 2000);
}

function showExtractionReview(jobData) {
  document.getElementById("scanProgressBox").classList.add("hidden");
  const reviewBox = document.getElementById("extractionReviewBox");
  reviewBox.classList.remove("hidden");

  const list = document.getElementById("extractedFieldsList");
  list.innerHTML = "";

  if (jobData.extractedFields && jobData.extractedFields.length > 0) {
    jobData.extractedFields.forEach((f) => {
      const row = document.createElement("div");
      row.className = "content-card";
      row.innerHTML = `
        <strong>${f.label}:</strong>
        <p>${typeof f.value === "object" ? JSON.stringify(f.value) : f.value || "—"}</p>
      `;
      list.appendChild(row);
    });
  } else if (jobData.noticeDetails) {
    const n = jobData.noticeDetails;
    list.innerHTML = `
      <div class="content-card">
        <strong>सारांश (Summary):</strong>
        <p>${n.summary || "—"}</p>
        <p><strong>अंतिम तिथि (Deadline):</strong> ${n.deadline || "दस्तावेज़ में उल्लिखित नहीं"}</p>
      </div>
    `;
  }
}

async function confirmExtractedDocument() {
  if (!currentJobId) return;

  try {
    const res = await fetch(`/api/documents/${currentJobId}/confirm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ createFamilyMembers: true, fields: [] }),
    });
    const data = await res.json();
    closeScanModal();
    showToast("दस्तावेज़ सफलतापूर्वक प्रोफाइल से जोड़ा गया! ✓");
    loadUserProfile();
  } catch (e) {
    showToast("पुष्टि में त्रुटि");
  }
}

// ---------------------------------------------------------------------------
// 5. Content Viewers (Schemes, Projects, Guides, Family)
// ---------------------------------------------------------------------------
function openContentModal(title, contentHtml) {
  document.getElementById("contentModalTitle").innerText = title;
  document.getElementById("contentModalBody").innerHTML = contentHtml;
  document.getElementById("contentModal").classList.remove("hidden");
}

function closeContentModal() {
  document.getElementById("contentModal").classList.add("hidden");
}

async function openSchemesViewer() {
  try {
    const res = await fetch(`/api/schemes?lang=${currentLang}`);
    const data = await res.json();

    let html = `<h4>पात्र एवं संभावित योजनाएं (${data.count || 0})</h4>`;
    (data.schemes || []).forEach((s) => {
      const statusClass =
        s.eligibility && s.eligibility.status === "ELIGIBLE"
          ? "badge-eligible"
          : s.eligibility && s.eligibility.status === "POSSIBLE"
          ? "badge-possible"
          : "badge-not-eligible";

      const statusText = s.eligibility ? s.eligibility.status : s.status || "ELIGIBLE";

      html += `
        <div class="content-card">
          <div class="content-card-header">
            <strong>${s.name}</strong>
            <span class="badge-status ${statusClass}">${statusText}</span>
          </div>
          <p><strong>लाभ:</strong> ${s.benefit}</p>
          <small style="color:#666">स्रोत: ${s.sourceUrl} (${s.verifiedDate})</small>
        </div>
      `;
    });

    openContentModal("सरकारी योजनाएं (Welfare Schemes)", html);
  } catch (e) {
    showToast("योजनाएं लोड करने में विफल");
  }
}

async function openProjectsViewer() {
  try {
    const res = await fetch(`/api/projects?lang=${currentLang}`);
    const data = await res.json();

    let html = `<h4>क्षेत्र में विकास कार्य (${data.district}, ${data.stateName})</h4>`;

    html += `<h5 style="color: #1b5e20; margin-top: 10px;">🇮🇳 केंद्र सरकार परियोजनाएं (Centre):</h5>`;
    (data.centre || []).forEach((p) => {
      html += `
        <div class="content-card">
          <strong>${p.name}</strong>
          <p>${p.description}</p>
          <small>विभाग: ${p.agency} • स्थिति: ${p.status}</small>
        </div>
      `;
    });

    html += `<h5 style="color: #e65100; margin-top: 14px;">🏛️ राज्य सरकार परियोजनाएं (State):</h5>`;
    (data.state || []).forEach((p) => {
      html += `
        <div class="content-card">
          <strong>${p.name}</strong>
          <p>${p.description}</p>
          <small>विभाग: ${p.agency} • स्थिति: ${p.status}</small>
        </div>
      `;
    });

    openContentModal("क्षेत्र के विकास कार्य (Projects)", html);
  } catch (e) {
    showToast("प्रोजेक्ट लोड करने में विफल");
  }
}

async function openGuideViewer(topic) {
  try {
    const res = await fetch(`/api/guides/${topic}?lang=${currentLang}`);
    const data = await res.json();

    let html = `<h4>${data.title}</h4>`;
    if (data.audioUrl) {
      html += `<audio controls src="${data.audioUrl}" style="width: 100%; margin: 10px 0;"></audio>`;
    }

    (data.steps || []).forEach((s, idx) => {
      html += `
        <div class="content-card">
          <strong>${idx + 1}. ${s.title}</strong>
          <p>${s.description}</p>
        </div>
      `;
    });

    html += `<small style="color: #666;">सत्यापित स्रोत: ${data.sourceUrl} (${data.verifiedDate})</small>`;
    openContentModal("मार्गदर्शिका (Citizen Guide)", html);
  } catch (e) {
    showToast("मार्गदर्शिका लोड करने में विफल");
  }
}

async function openFamilyViewer() {
  try {
    const res = await fetch(`/api/profile?lang=${currentLang}`);
    const data = await res.json();

    let html = `<h4>परिवार के सदस्य (${(data.familyMembers || []).length})</h4>`;
    (data.familyMembers || []).forEach((m) => {
      const missTitles = (m.missingDocuments || [])
        .filter((d) => d.mandatory)
        .map((d) => d.title)
        .join(", ");

      html += `
        <div class="content-card">
          <strong>${m.name} (${m.relation})</strong>
          <p>आयु: ${m.ageYears !== null && m.ageYears !== undefined ? m.ageYears + " वर्ष" : "—"} | व्यवसाय: ${m.occupation || "—"}</p>
          <p style="color: #c62828; font-size: 12px;"><strong>बाकी दस्तावेज़:</strong> ${missTitles || "कोई नहीं (सभी पूर्ण)"}</p>
        </div>
      `;
    });

    openContentModal("मेरा परिवार (My Family)", html);
  } catch (e) {
    showToast("परिवार लोड करने में विफल");
  }
}

// ---------------------------------------------------------------------------
// 6. Exports (PDF, Text, JSON)
// ---------------------------------------------------------------------------
function openExportModal() {
  document.getElementById("exportModal").classList.remove("hidden");
}

function closeExportModal() {
  document.getElementById("exportModal").classList.add("hidden");
}

function downloadPdfExport() {
  window.open(`/api/export/pdf?lang=${currentLang}`, "_blank");
  closeExportModal();
  showToast("PDF रिपोर्ट डाउनलोड हो रही है...");
}

async function copyTextExport() {
  try {
    const res = await fetch(`/api/export/text?lang=${currentLang}`);
    const text = await res.text();
    await navigator.clipboard.writeText(text);
    closeExportModal();
    showToast("टेक्स्ट सारांश क्लिपबोर्ड पर कॉपी हो गया! 📋");
  } catch (e) {
    showToast("कॉपी करने में त्रुटि");
  }
}

async function downloadJsonExport() {
  window.open(`/api/export/json?lang=${currentLang}`, "_blank");
  closeExportModal();
}
