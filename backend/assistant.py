"""
backend/assistant.py — Multilingual Voice & Text Assistant with tool execution and strict data grounding.

Implements tools:
  1. get_profile
  2. update_profile (with spoken read-back and confirmation)
  3. explain_document
  4. find_schemes (answering strictly from data/real/schemes)
  5. get_regional_projects (answering strictly from data/real/projects)
  6. get_needs_guide (answering strictly from data/real/guides)
  7. export_summary

Answers ONLY from profile and /data/real; if missing, uses i18n INFO_NOT_AVAILABLE.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

from backend.config_loader import (
    get_all_projects,
    get_all_schemes,
    get_app_config,
    get_i18n_message,
    get_intents_config,
    get_languages_config,
    get_models_config,
    get_needs_guide,
    get_prompt,
)
from backend.db import get_conn
from backend.document_processor import calculate_missing_documents, compute_age_years
from backend.privacy import mask_value_by_type, redact_identifiers
from backend.sarvam_client import SarvamClient

log = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent.parent


def get_user_profile_data(user_id: int) -> dict[str, Any]:
    """Fetch complete household and family data."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        u = cur.fetchone()
        if not u:
            return {}

        cur.execute("SELECT * FROM family_members WHERE user_id = ? ORDER BY id ASC", (user_id,))
        m_rows = cur.fetchall()

        cur.execute("SELECT * FROM documents WHERE user_id = ? ORDER BY id ASC", (user_id,))
        d_rows = cur.fetchall()

        members = []
        for m in m_rows:
            mem_id = m["id"]
            held_docs = [d["doc_type"] for d in d_rows if d["member_id"] == mem_id]
            missing_docs = calculate_missing_documents(m["relation"], held_docs)
            members.append({
                "id": mem_id,
                "name": m["name"],
                "dob": m["dob"],
                "ageYears": compute_age_years(m["dob"]),
                "gender": m["gender"],
                "relation": m["relation"],
                "occupation": m["occupation"],
                "education_level": m["education_level"],
                "caste_category": m["caste_category"],
                "is_disabled": bool(m["is_disabled"]),
                "land_acres": m["land_acres"],
                "documentsHeld": held_docs,
                "missingDocuments": missing_docs,
            })

        return {
            "household": {
                "id": u["id"],
                "village": u["village"],
                "panchayat": u["panchayat"],
                **{k: u[k] for k in ("block", "tehsil", "village_code")},
                "district": u["district"],
                "state": u["state"],
                "language_pref": u["language_pref"],
            },
            "familyMembers": members,
            "documents": [
                {"id": d["id"], "doc_type": d["doc_type"], "status": d["status"]}
                for d in d_rows
            ],
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Tool Implementations
# ---------------------------------------------------------------------------

def tool_get_profile(user_id: int, lang: str = "hi-IN") -> dict[str, Any]:
    """Tool: get_profile"""
    prof = get_user_profile_data(user_id)
    if not prof:
        return {
            "text": get_i18n_message("CONSENT_REQUIRED", lang),
            "sources": [],
            "data": None,
        }

    h = prof["household"]
    members = prof["familyMembers"]
    m_count = len(members)

    # Missing docs count
    missing_items = []
    for m in members:
        for md in m.get("missingDocuments", []):
            if md.get("mandatory"):
                missing_items.append(f"{m['name']}: {md['title']}")

    if lang.startswith("hi"):
        spoken = (
            f"आपके परिवार में कुल {m_count} सदस्य दर्ज हैं (गाँव {h.get('village', '')})। "
        )
        if missing_items:
            spoken += f"मुख्य रूप से {len(missing_items)} अनिवार्य दस्तावेज़ जैसे {missing_items[0]} अभी छूटे हुए हैं।"
        else:
            spoken += "आपके परिवार के सभी आवश्यक दस्तावेज़ पूर्ण हैं।"
    else:
        spoken = (
            f"Your household in village {h.get('village', '')} has {m_count} registered members. "
        )
        if missing_items:
            spoken += f"There are {len(missing_items)} mandatory documents pending, such as {missing_items[0]}."
        else:
            spoken += "All essential documents for your household are complete."

    return {
        "text": spoken,
        "sources": [{"name": "Family Profile (SQLite)", "verified_date": "Current"}],
        "data": prof,
    }


def tool_update_profile(
    user_id: int,
    field: str,
    value: Any,
    member_name: str | None = None,
    confirmed: bool = False,
    lang: str = "hi-IN",
) -> dict[str, Any]:
    """Tool: update_profile with spoken read-back and confirmation gate."""
    allowed = {"name", "dob", "gender", "occupation", "education_level", "relation"} if member_name else {"village", "panchayat", "district", "state", "language_pref"}
    if field not in allowed or not isinstance(value, str) or not value.strip() or len(value) > 200:
        return {"text": "Invalid profile field or value.", "sources": []}
    value = redact_identifiers(value)
    target_desc = f"{member_name} का {field}" if member_name else field

    if not confirmed:
        prefix = get_i18n_message("CONFIRM_PROMPT_PREFIX", lang)
        suffix = get_i18n_message("CONFIRM_PROMPT_SUFFIX", lang)
        prompt_text = f"{prefix}{target_desc} = '{value}'? {suffix}"

        return {
            "text": prompt_text,
            "requiresConfirmation": True,
            "pendingAction": {
                "tool": "update_profile",
                "field": field,
                "value": value,
                "member_name": member_name,
            },
            "sources": [],
        }

    # Execute DB update
    conn = get_conn()
    try:
        cur = conn.cursor()
        now_iso = datetime.now(timezone.utc).isoformat()
        if member_name:
            cur.execute(
                f"UPDATE family_members SET {field} = ?, updated_at = ? WHERE user_id = ? AND name LIKE ?",
                (value, now_iso, user_id, f"%{member_name}%"),
            )
        else:
            cur.execute(
                f"UPDATE users SET {field} = ?, updated_at = ? WHERE id = ?",
                (value, now_iso, user_id),
            )
        if cur.rowcount == 0:
            return {"text": "No matching family member was found. Please check the name.", "sources": []}
        conn.commit()

        success_msg = get_i18n_message("CONFIRMED_SUCCESS", lang)
        return {
            "text": success_msg,
            "requiresConfirmation": False,
            "sources": [{"name": "Profile Database", "verified_date": "Updated Now"}],
        }
    except Exception as e:
        log.error("Profile update failed: %s", e)
        return {"text": f"Error updating profile: {e}", "sources": []}
    finally:
        conn.close()


def tool_find_schemes(user_id: int, query: str | None = None, lang: str = "hi-IN") -> dict[str, Any]:
    """Tool: find_schemes (searches strictly in data/real/schemes/*.yaml)."""
    schemes = get_all_schemes()
    if not schemes:
        return {
            "text": get_i18n_message("INFO_NOT_AVAILABLE", lang),
            "sources": [],
            "missing_file": "data/real/schemes/*.yaml",
        }

    q = (query or "").lower().strip()
    scored_schemes = []

    for s in schemes:
        score = 0
        s_id = s.get("id", "").lower()
        s_name = (s.get("name_hi", "") + " " + s.get("name", "")).lower()
        s_cat = s.get("category", "").lower()
        s_target = s.get("target_group", "").lower()
        s_benefit = (s.get("benefit_hi", "") + " " + s.get("benefit", "")).lower()

        # Keyword mapping
        if any(w in q for w in ["किसान", "kisan", "farmer", "खेती", "कृषि", "fasal"]):
            if s_cat == "agriculture" or "kisan" in s_id:
                score += 10
        if any(w in q for w in ["बेटी", "लड़की", "daughter", "girl", "sukanya", "कन्या"]):
            if "daughter" in s_cat or "girl" in s_cat or "sukanya" in s_id:
                score += 10
        if any(w in q for w in ["आवास", "घर", "मकान", "house", "housing", "awas"]):
            if s_cat == "housing" or "pmay" in s_id:
                score += 10
        if any(w in q for w in ["स्वास्थ्य", "इलाज", "अस्पताल", "health", "ayushman", "दवा"]):
            if s_cat == "health" or "ayushman" in s_id:
                score += 10
        if any(w in q for w in ["रोजगार", "मनरेगा", "मजदूरी", "nrega", "mgnrega", "काम"]):
            if s_cat == "social_security" or "mgnrega" in s_id:
                score += 10

        # Substring / token matches
        for word in q.split():
            if len(word) >= 3:
                if word in s_name:
                    score += 5
                if word in s_id:
                    score += 5
                if word in s_target or word in s_benefit:
                    score += 2

        scored_schemes.append((score, s))

    # Sort by score descending
    scored_schemes.sort(key=lambda x: x[0], reverse=True)
    matched = [s for score, s in scored_schemes if score > 0]
    if not matched:
        if not q or any(w in q for w in ["scheme", "योजना"]):
            matched = schemes
        else:
            return {"text": get_i18n_message("INFO_NOT_AVAILABLE", lang), "sources": []}
    from backend.eligibility_engine import evaluate_scheme_eligibility
    profile = get_user_profile_data(user_id)
    evaluations = {s["id"]: evaluate_scheme_eligibility(s, profile) for s in matched}
    matched.sort(key=lambda s: {"ELIGIBLE": 0, "POSSIBLE": 1, "NOT_ELIGIBLE": 2}[evaluations[s["id"]]["status"]])

    sources = [
        {"name": m.get("name", "Scheme"), "url": m.get("source_url"), "verified_date": m.get("verified_date")}
        for m in matched
    ]

    top = matched[0]
    top_name = top.get("name_hi" if lang.startswith("hi") else "name", top.get("name"))
    top_benefit = top.get("benefit_hi" if lang.startswith("hi") else "benefit", top.get("benefit"))

    if lang.startswith("hi"):
        spoken = f"आपके लिए मुख्य योजना '{top_name}' है। इसके तहत {top_benefit}"
        if len(matched) > 1:
            second_name = matched[1].get("name_hi", matched[1].get("name"))
            spoken += f" इसके अलावा '{second_name}' का लाभ भी उपलब्ध है।"
    else:
        spoken = f"The primary scheme for you is '{top_name}'. It offers: {top_benefit}"
        if len(matched) > 1:
            second_name = matched[1].get("name")
            spoken += f" You can also explore '{second_name}'."

    evaluation = evaluations[top["id"]]
    spoken += (" पात्रता: " if lang.startswith("hi") else " Eligibility: ") + evaluation["status"]
    if evaluation.get("missingFields"):
        spoken += ". " + " ".join(item.get("question", "") for item in evaluation["missingFields"][:2])
    return {
        "text": spoken,
        "sources": sources,
        "schemes": matched,
    }


def tool_get_regional_projects(user_id: int, lang: str = "hi-IN") -> dict[str, Any]:
    """Tool: get_regional_projects (from data/real/projects/*.yaml)."""
    prof = get_user_profile_data(user_id)
    dist = prof.get("household", {}).get("district", "Varanasi")
    projects_data = get_all_projects()

    if not projects_data:
        return {
            "text": get_i18n_message("INFO_NOT_AVAILABLE", lang),
            "sources": [],
            "missing_file": "data/real/projects/varanasi_rural_projects.yaml",
        }

    state = prof.get("household", {}).get("state", "")
    p_file = next((p for p in projects_data if str(p.get("district", "")).casefold() == str(dist or "").casefold()
                   and str(p.get("state", "")).casefold() == str(state or "").casefold()), None)
    if not p_file:
        return {"text": get_i18n_message("INFO_NOT_AVAILABLE", lang), "sources": []}
    p_dict = p_file.get("projects", {})
    centre_list = p_dict.get("centre", [])
    state_list = p_dict.get("state", [])

    sources = [{"name": f"{dist} Projects Portal", "url": p_file.get("source_url"), "verified_date": p_file.get("verified_date")}]

    c_name = centre_list[0].get("name_hi" if lang.startswith("hi") else "name", "") if centre_list else ""
    s_name = state_list[0].get("name_hi" if lang.startswith("hi") else "name", "") if state_list else ""

    if lang.startswith("hi"):
        spoken = f"आपके जिले में केंद्र सरकार की ओर से '{c_name}' तथा राज्य सरकार की ओर से '{s_name}' पर कार्य चल रहा है।"
    else:
        spoken = f"In your district, active Central projects include '{c_name}' and State projects include '{s_name}'."

    return {
        "text": spoken,
        "sources": sources,
        "centre_projects": centre_list,
        "state_projects": state_list,
    }


def tool_get_needs_guide(topic: str, lang: str = "hi-IN") -> dict[str, Any]:
    """Tool: get_needs_guide (from data/real/guides/*.yaml)."""
    guide = get_needs_guide(topic)
    if not guide:
        return {
            "text": get_i18n_message("INFO_NOT_AVAILABLE", lang),
            "sources": [],
            "missing_file": f"data/real/guides/{topic}_guide.yaml",
        }

    title = guide.get("title_hi" if lang.startswith("hi") else "title", guide.get("title", topic))
    steps = guide.get("steps", [])
    first_step = steps[0] if steps else {}
    step_desc = first_step.get("description_hi" if lang.startswith("hi") else "description", "")

    sources = [{"name": title, "url": guide.get("source_url"), "verified_date": guide.get("verified_date")}]

    if lang.startswith("hi"):
        spoken = f"{title} के अनुसार: {step_desc[:180]}"
    else:
        spoken = f"According to the {title}: {step_desc[:180]}"

    return {
        "text": spoken,
        "sources": sources,
        "guide": guide,
    }


def tool_explain_document(user_id: int, lang: str = "hi-IN") -> dict[str, Any]:
    """Tool: explain_document (from confirmed / uploaded document in DB)."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        # 1. Check latest ready document job for notices
        cur.execute(
            """
            SELECT * FROM document_jobs
            WHERE user_id = ? AND status = 'ready'
            ORDER BY created_at DESC LIMIT 1
            """,
            (user_id,),
        )
        job_row = cur.fetchone()

        if job_row and job_row["result_json"]:
            try:
                res_json = json.loads(job_row["result_json"])
                notice = res_json.get("noticeDetails")
                if notice and notice.get("summary"):
                    return {
                        "text": notice["summary"],
                        "sources": [{"name": notice.get("issuing_authority", "Official Notice"), "verified_date": notice.get("date", "Latest")}],
                        "doc_type": "official_notice",
                    }
            except Exception:
                pass

        # 2. Check documents table for notices or other uploaded documents
        cur.execute(
            """
            SELECT d.*, ef.field_value as summary_val, ef_auth.field_value as auth_val
            FROM documents d
            LEFT JOIN extracted_fields ef ON d.id = ef.document_id AND ef.field_name = 'summary'
            LEFT JOIN extracted_fields ef_auth ON d.id = ef_auth.document_id AND ef_auth.field_name = 'issuing_authority'
            WHERE d.user_id = ?
            ORDER BY (d.doc_type = 'official_notice') DESC, d.id DESC LIMIT 1
            """,
            (user_id,),
        )
        row = cur.fetchone()
        if not row:
            return {
                "text": get_i18n_message("NO_DOCUMENTS_FOUND", lang),
                "sources": [],
            }

        doc_type = row["doc_type"]
        summary = row["summary_val"]
        auth = row["auth_val"] or f"Document ({doc_type})"

        if not summary:
            summary = f"यह आपका {doc_type} दस्तावेज़ है जो सफलतापूर्वक सत्यापित किया जा चुका है।"

        return {
            "text": summary,
            "sources": [{"name": auth, "verified_date": "Uploaded"}],
            "doc_type": doc_type,
        }
    finally:
        conn.close()


def tool_export_summary(user_id: int, lang: str = "hi-IN") -> dict[str, Any]:
    """Tool: export_summary."""
    prof = get_user_profile_data(user_id)
    schemes_res = tool_find_schemes(user_id, lang=lang)

    h = prof.get("household", {})
    members = prof.get("familyMembers", [])

    if lang.startswith("hi"):
        spoken = f"गाँव {h.get('village', '')} के परिवार का विवरण: कुल {len(members)} सदस्य, मुख्य योजना: {schemes_res.get('text', '')[:120]}"
    else:
        spoken = f"Summary for household in {h.get('village', '')}: {len(members)} members registered. Eligible schemes: {schemes_res.get('text', '')[:120]}"

    return {
        "text": spoken,
        "sources": [{"name": "GRAAM-GYAAN Summary Export", "verified_date": "Current"}],
        "profile": prof,
    }


# ---------------------------------------------------------------------------
# Router & Dialog Manager
# ---------------------------------------------------------------------------

def execute_assistant_turn(
    user_id: int,
    session_id: str,
    user_text: str,
    lang: str = "hi-IN",
    client: SarvamClient | None = None,
    confirm_action: dict | None = None,
    include_audio: bool = True,
) -> dict[str, Any]:
    """
    Main assistant orchestration:
      - Checks confirmation responses
      - Matches user intent from config/intents.yaml
      - Executes grounded tool
      - Synthesizes Bulbul TTS audio in target language
      - Saves turn in SQLite conversations table
    """
    client = client or SarvamClient()
    user_text = redact_identifiers(user_text)
    user_text_clean = user_text.strip()
    user_text_lower = user_text_clean.lower()

    # Pending changes belong to this household/session and expire after 15 minutes.
    conn = get_conn()
    try:
        row = conn.execute("SELECT action_json FROM pending_actions WHERE user_id=? AND session_id=? AND created_at > datetime('now', '-15 minutes')", (user_id, session_id)).fetchone()
        stored_action = json.loads(row["action_json"]) if row else None
    finally:
        conn.close()
    if stored_action and confirm_action and any(confirm_action.get(k) != v for k, v in stored_action.items()):
        from fastapi import HTTPException
        raise HTTPException(409, "The proposed change was modified. Please request it again.")
    action = stored_action or confirm_action
    if action and action.get("tool") == "update_profile":
        negative = any(w in user_text_lower for w in ["नहीं", "रद्द", "cancel", "mat karo"]) or bool(re.search(r"\b(no|not|don't)\b", user_text_lower))
        affirmative = any(w in user_text_lower for w in ["हाँ", "हां", "theek hai", "sahi", "कर दो"]) or bool(re.search(r"\b(yes|confirm)\b", user_text_lower))
        if negative or (stored_action and affirmative):
            conn = get_conn()
            try:
                conn.execute("DELETE FROM pending_actions WHERE user_id=? AND session_id=?", (user_id, session_id))
                conn.commit()
            finally:
                conn.close()
        if negative:
            return _finalize_turn(user_id, session_id, user_text, {"text": get_i18n_message("CANCELLED", lang), "sources": []}, lang, client, include_audio)
        tool_res = tool_update_profile(user_id, action.get("field", ""), action.get("value"),
                                       action.get("member_name"), bool(stored_action and affirmative), lang)
        return _finalize_turn(user_id, session_id, user_text, tool_res, lang, client, include_audio)

    # Live answers use grounded records and this household's conversation history.
    if not client.mock and not client.demo_cache:
        from backend.conversation import grounded_answer
        try:
            tool_res = grounded_answer(user_id, session_id, user_text, lang, client)
        except Exception:
            log.exception("Live assistant failed")
            if any(w in user_text_lower for w in ("scheme", "योजना", "kisan", "mgnrega", "pension")):
                tool_res = tool_find_schemes(user_id, query=user_text_clean, lang=lang)
            elif any(w in user_text_lower for w in ("project", "road", "area", "विकास", "सड़क")):
                tool_res = tool_get_regional_projects(user_id, lang=lang)
            else:
                tool_res = {"text": "कृपया प्रश्न फिर भेजें, या योजनाएँ और क्षेत्रीय स्रोत खोलें।" if lang.startswith("hi") else "Please retry your question, or open Schemes and Official regional updates to browse the available sources.", "sources": []}
            prefix = "AI से अभी संपर्क नहीं हो पाया। नीचे सहेजे गए स्रोतों से जानकारी है; यह नया AI उत्तर नहीं है। " if lang.startswith("hi") else "The AI service could not complete this answer. The information below comes from saved sources; this is a limited fallback. "
            tool_res["text"] = prefix + tool_res["text"]
            tool_res["mode"] = "fallback"
        return _finalize_turn(user_id, session_id, user_text, tool_res, lang, client, include_audio)

    if user_text_lower in ("hi", "hello", "नमस्ते", "नमस्कार"):
        text = "नमस्ते! योजनाओं, परिवार, दस्तावेज़ या अपने क्षेत्र के काम के बारे में पूछें।" if lang.startswith("hi") else "Hello! Ask me about schemes, family documents, or local projects."
        return _finalize_turn(user_id, session_id, user_text, {"text": text, "sources": []}, lang, client, include_audio)

    # 2. Check intent matching from config/intents.yaml
    intents = get_intents_config()
    matched_intent = None

    for intent in intents:
        examples = intent.get("examples", {}).get(lang, []) + intent.get("examples", {}).get("hi-IN", [])
        if any(ex.lower() in user_text_lower for ex in examples):
            matched_intent = intent
            break

    # Execute matched tool or fallback
    tool_name = matched_intent.get("tool") if matched_intent else None

    if tool_name == "find_schemes":
        q = matched_intent.get("default_query") or user_text_clean
        tool_res = tool_find_schemes(user_id, query=q, lang=lang)
    elif tool_name == "get_profile":
        tool_res = tool_get_profile(user_id, lang=lang)
    elif tool_name == "get_regional_projects":
        tool_res = tool_get_regional_projects(user_id, lang=lang)
    elif tool_name == "get_needs_guide":
        topic = matched_intent.get("topic", "banking")
        tool_res = tool_get_needs_guide(topic=topic, lang=lang)
    elif tool_name == "explain_document":
        tool_res = tool_explain_document(user_id, lang=lang)
    elif tool_name == "export_summary":
        tool_res = tool_export_summary(user_id, lang=lang)
    else:
        # LLM based routing / Q&A using system prompt and tool definitions
        if any(w in user_text_lower for w in ["योजना", "scheme", "पैसा", "लाभ", "beti", "kisan", "बेटी", "किसान"]):
            tool_res = tool_find_schemes(user_id, query=user_text_clean, lang=lang)
        elif any(w in user_text_lower for w in ["प्रोफाइल", "परिवार", "कागज़", "दस्तावेज़", "profile", "family", "missing"]):
            tool_res = tool_get_profile(user_id, lang=lang)
        elif any(w in user_text_lower for w in ["विकास", "प्रोजेक्ट", "गाँव", "सड़क", "पानी", "project", "area"]):
            tool_res = tool_get_regional_projects(user_id, lang=lang)
        elif any(w in user_text_lower for w in ["डीबीटी", "बैंक", "खाता", "dbt", "bank", "seeding"]):
            tool_res = tool_get_needs_guide("banking", lang=lang)
        elif any(w in user_text_lower for w in ["राशन", "ration", "कोटेदार", "ekyc"]):
            tool_res = tool_get_needs_guide("ration", lang=lang)
        elif any(w in user_text_lower for w in ["नोटिस", "दस्तावेज समझाओ", "notice", "explain"]):
            tool_res = tool_explain_document(user_id, lang=lang)
        else:
            # General grounded answer
            tool_res = {"text": get_i18n_message("INFO_NOT_AVAILABLE", lang), "sources": []}

    return _finalize_turn(user_id, session_id, user_text, tool_res, lang, client, include_audio)


def _finalize_turn(
    user_id: int,
    session_id: str,
    user_text: str,
    tool_res: dict[str, Any],
    lang: str,
    client: SarvamClient,
    include_audio: bool = True,
) -> dict[str, Any]:
    """Generate audio, save conversation turns, and build response payload."""
    spoken_text = redact_identifiers(tool_res.get("text", ""))
    sources = tool_res.get("sources", [])
    requires_confirmation = tool_res.get("requiresConfirmation", False)
    pending_action = tool_res.get("pendingAction")

    if requires_confirmation and pending_action:
        conn = get_conn()
        try:
            conn.execute("INSERT OR REPLACE INTO pending_actions(user_id,session_id,action_json) VALUES(?,?,?)",
                         (user_id, session_id, json.dumps(pending_action)))
            conn.commit()
        finally:
            conn.close()

    # Generate Bulbul TTS Audio
    audio_url = None
    audio_available = False
    audio_error = None
    try:
        tts_res = client.synthesize(spoken_text, language_code=lang) if include_audio else {}
        if tts_res.get("audio_b64"):
            conv_dir = BASE_DIR / get_app_config().get("audio_output_dir", "uploads/audio")
            conv_dir.mkdir(parents=True, exist_ok=True)
            import uuid
            audio_fn = f"conv_{uuid.uuid4().hex[:10]}.wav"
            audio_path = conv_dir / audio_fn
            audio_bytes = base64.b64decode(tts_res["audio_b64"])
            audio_path.write_bytes(audio_bytes)
            audio_url = f"/api/documents/audio/{audio_fn}"
            audio_available = True
    except Exception as e:
        audio_error = "Audio could not be generated. You can still read the answer."
        log.warning("Assistant TTS synthesis error: %s", type(e).__name__)

    # Record in SQLite conversations table
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT MAX(turn) as max_turn FROM conversations WHERE session_id = ?", (session_id,))
        r = cur.fetchone()
        next_turn = (r["max_turn"] or 0) + 1
        now_iso = datetime.now(timezone.utc).isoformat()

        # User turn
        cur.execute(
            """
            INSERT INTO conversations (user_id, session_id, turn, role, content_text, language, is_mock, created_at)
            VALUES (?, ?, ?, 'user', ?, ?, ?, ?)
            """,
            (user_id, session_id, next_turn, user_text, lang, 1 if client.mock else 0, now_iso),
        )

        # Assistant turn
        cur.execute(
            """
            INSERT INTO conversations (user_id, session_id, turn, role, content_text, audio_path, language, is_mock, created_at, metadata_json)
            VALUES (?, ?, ?, 'assistant', ?, ?, ?, ?, ?, ?)
            """,
            (user_id, session_id, next_turn + 1, spoken_text, audio_url, lang, 1 if client.mock else 0, now_iso, json.dumps({"sources": sources, "mode": tool_res.get("mode", client.mode), "audioError": audio_error}, default=str)),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "sessionId": session_id,
        "text": spoken_text,
        "audioUrl": audio_url,
        "audioAvailable": audio_available,
        "sources": sources,
        "requiresConfirmation": requires_confirmation,
        "pendingAction": pending_action,
        "isMock": client.mock,
        "mode": tool_res.get("mode", client.mode),
        "audioError": audio_error,
    }
