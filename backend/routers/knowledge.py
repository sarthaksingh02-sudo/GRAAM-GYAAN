"""
backend/routers/knowledge.py — Knowledge layer endpoints for Schemes, Regional Projects, Guides, and Home Tiles.
"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any, List, Optional

from backend.active_user import get_active_user_id

from fastapi import APIRouter, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.assistant import get_user_profile_data
from backend.config_loader import (
    get_all_projects,
    get_all_schemes,
    get_app_config,
    get_doc_schema,
    get_i18n_message,
    get_needs_guide,
    load_yaml,
)
from backend.eligibility_engine import evaluate_scheme_eligibility
from backend.sarvam_client import SarvamClient

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Knowledge Layer"])

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = BASE_DIR / "config"


def _get_sectors_config() -> dict[str, Any]:
    return load_yaml(CONFIG_DIR / "sectors.yaml").get("sectors", {})


def _get_home_tiles_config() -> list[dict[str, Any]]:
    return load_yaml(CONFIG_DIR / "home_tiles.yaml").get("tiles", [])


@router.get("/home-tiles")
def get_home_tiles(lang: str = "hi-IN") -> dict[str, Any]:
    """Return home screen icon tiles with localized labels."""
    tiles = _get_home_tiles_config()
    result = []
    for t in tiles:
        lbl_key = t.get("label_key", "")
        localized_label = get_i18n_message(lbl_key, lang)
        result.append({
            "id": t.get("id"),
            "icon": t.get("icon"),
            "label": localized_label,
            "route": t.get("route"),
            "color": t.get("color"),
            "guideTopic": t.get("guide_topic"),
            "badge": t.get("badge"),
        })
    return {"language": lang, "tiles": result}


@router.get("/schemes")
def get_schemes(
    category: Optional[str] = None,
    x_user_id: Optional[str] = Header(default=None),
    lang: str = "hi-IN",
) -> dict[str, Any]:
    """
    List all welfare schemes with deterministic eligibility evaluation for the active user.
    """
    schemes = get_all_schemes()
    if not schemes:
        return {
            "schemes": [],
            "missing_data": True,
            "message": get_i18n_message("INFO_NOT_AVAILABLE", lang),
        }

    sectors = _get_sectors_config()

    user_id = get_active_user_id(x_user_id)
    profile = get_user_profile_data(user_id)

    evaluated_list = []
    for s in schemes:
        if category and s.get("category") != category:
            continue

        eval_res = evaluate_scheme_eligibility(s, profile)
        cat_id = s.get("category", "")
        sec_info = sectors.get(cat_id, {})

        name_display = s.get("name_hi" if lang.startswith("hi") else "name", s.get("name"))
        benefit_display = s.get("benefit_hi" if lang.startswith("hi") else "benefit", s.get("benefit"))

        evaluated_list.append({
            "id": s.get("id"),
            "name": name_display,
            "category": cat_id,
            "status": eval_res.get("status"),
            "sector": {
                "name": sec_info.get("name_hi" if lang.startswith("hi") else "name", cat_id),
                "icon": sec_info.get("icon", "Award"),
                "color": sec_info.get("color", "#F57C00"),
            },
            "benefit": benefit_display,
            "targetGroup": s.get("target_group"),
            "sourceUrl": s.get("source_url"),
            "verifiedDate": s.get("verified_date"),
            "eligibility": eval_res,
            "documentsRequired": s.get("documents_required", []),
            "steps": s.get("steps", []),
        })

    # Sort: ELIGIBLE first, then POSSIBLE, then NOT_ELIGIBLE
    status_order = {"ELIGIBLE": 0, "POSSIBLE": 1, "NOT_ELIGIBLE": 2}
    evaluated_list.sort(key=lambda x: status_order.get(x["eligibility"]["status"], 3))

    return {
        "count": len(evaluated_list),
        "schemes": evaluated_list,
        "missing_data": False,
    }


@router.get("/schemes/{scheme_id}")
def get_scheme_detail(
    scheme_id: str,
    x_user_id: Optional[str] = Header(default=None),
    lang: str = "hi-IN",
) -> dict[str, Any]:
    """Get single scheme details with rules and evaluation."""
    schemes = get_all_schemes()
    match = next((s for s in schemes if s.get("id") == scheme_id), None)
    if not match:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "SCHEME_NOT_FOUND",
                "message": get_i18n_message("INFO_NOT_AVAILABLE", lang),
                "missing_file": f"data/real/schemes/{scheme_id}.yaml",
            },
        )

    user_id = get_active_user_id(x_user_id)
    profile = get_user_profile_data(user_id)
    eval_res = evaluate_scheme_eligibility(match, profile)

    sectors = _get_sectors_config()
    cat_id = match.get("category", "")
    sec_info = sectors.get(cat_id, {})

    return {
        "id": match.get("id"),
        "name": match.get("name_hi" if lang.startswith("hi") else "name", match.get("name")),
        "category": cat_id,
        "sector": {
            "name": sec_info.get("name_hi" if lang.startswith("hi") else "name", cat_id),
            "icon": sec_info.get("icon", "Award"),
            "color": sec_info.get("color", "#F57C00"),
        },
        "benefit": match.get("benefit_hi" if lang.startswith("hi") else "benefit", match.get("benefit")),
        "targetGroup": match.get("target_group"),
        "sourceUrl": match.get("source_url"),
        "verifiedDate": match.get("verified_date"),
        "eligibility": eval_res,
        "documentsRequired": match.get("documents_required", []),
        "steps": match.get("steps", []),
    }


@router.get("/projects")
def get_projects(
    district: Optional[str] = None,
    state: Optional[str] = None,
    x_user_id: Optional[str] = Header(default=None),
    lang: str = "hi-IN",
) -> dict[str, Any]:
    """
    Get regional projects with Centre and State shown separately.
    """
    user_id = get_active_user_id(x_user_id)
    profile = get_user_profile_data(user_id)

    user_dist = district or profile.get("household", {}).get("district")
    user_state = state or profile.get("household", {}).get("state")

    projects_list = get_all_projects()
    if not projects_list:
        return {
            "centre": [],
            "state": [],
            "missing_data": True,
            "district": user_dist,
            "stateName": user_state,
            "message": get_i18n_message("INFO_NOT_AVAILABLE", lang),
            "missing_file": "data/real/projects/*.yaml",
        }

    p_data = next((p for p in projects_list if
        str(p.get("district", "")).casefold() == str(user_dist or "").casefold()
        and str(p.get("state", "")).casefold() == str(user_state or "").casefold()), None)
    if not p_data:
        return {"district": user_dist, "stateName": user_state, "centre": [], "state": [],
                "missing_data": True, "message": get_i18n_message("INFO_NOT_AVAILABLE", lang)}
    p_dict = p_data.get("projects", {})
    centre_raw = p_dict.get("centre", [])
    state_raw = p_dict.get("state", [])

    def _format_project(p):
        return {
            "id": p.get("id"),
            "name": p.get("name_hi" if lang.startswith("hi") else "name", p.get("name")),
            "agency": p.get("agency"),
            "status": p.get("status"),
            "completionTarget": p.get("completion_target"),
            "description": p.get("description_hi" if lang.startswith("hi") else "description", p.get("description")),
        }

    return {
        "district": p_data.get("district", user_dist),
        "stateName": p_data.get("state", user_state),
        "sourceUrl": p_data.get("source_url"),
        "verifiedDate": p_data.get("verified_date"),
        "centre": [_format_project(p) for p in centre_raw],
        "state": [_format_project(p) for p in state_raw],
        "missing_data": False,
    }


@router.get("/guides")
def get_all_need_guides(lang: str = "hi-IN") -> dict[str, Any]:
    """List all 5 need-guides as icon cards with source and date."""
    guide_topics = ["banking", "aadhaar_pan", "ration", "new_schemes", "family", "health", "livelihood"]
    tiles = {t.get("guide_topic"): t for t in _get_home_tiles_config() if t.get("guide_topic")}

    result = []
    for top in guide_topics:
        g = get_needs_guide(top)
        tile_meta = tiles.get(top, {})

        if not g:
            result.append({
                "topic": top,
                "title": top,
                "missing_data": True,
                "message": get_i18n_message("INFO_NOT_AVAILABLE", lang),
            })
            continue

        title = g.get("title_hi" if lang.startswith("hi") else "title", g.get("title", top))
        steps = g.get("steps", [])

        result.append({
            "topic": top,
            "title": title,
            "icon": tile_meta.get("icon", "FileText"),
            "color": tile_meta.get("color", "#00796B"),
            "sourceUrl": g.get("source_url"),
            "verifiedDate": g.get("verified_date"),
            "stepsCount": len(steps),
            "missing_data": False,
        })

    return {"guides": result}


@router.get("/guides/{topic}")
def get_guide_detail(topic: str, lang: str = "hi-IN", audio: bool = False) -> dict[str, Any]:
    """Get specific need-guide with voice synthesis."""
    g = get_needs_guide(topic)
    if not g:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "GUIDE_NOT_FOUND",
                "missing_data": True,
                "message": get_i18n_message("INFO_NOT_AVAILABLE", lang),
                "missing_file": f"data/real/guides/{topic}_guide.yaml",
            },
        )

    title = g.get("title_hi" if lang.startswith("hi") else "title", g.get("title", topic))
    steps = g.get("steps", [])

    formatted_steps = [
        {
            "id": s.get("id"),
            "title": s.get("title_hi" if lang.startswith("hi") else "title", s.get("title", "")),
            "description": s.get("description_hi" if lang.startswith("hi") else "description", s.get("description", "")),
        }
        for s in steps
    ]

    # Generate Bulbul TTS audio for guide summary
    audio_url = None
    if formatted_steps and audio:
        summary_spoken = f"{title}. " + " ".join(s["title"] for s in formatted_steps[:2])
        client = SarvamClient()
        try:
            tts_res = client.synthesize(summary_spoken, language_code=lang)
            if tts_res.get("audio_b64"):
                from backend.config_loader import get_app_config
                conv_dir = BASE_DIR / get_app_config().get("audio_output_dir", "uploads/audio")
                conv_dir.mkdir(parents=True, exist_ok=True)
                audio_fn = f"guide_{topic}_{lang}.wav"
                (conv_dir / audio_fn).write_bytes(base64.b64decode(tts_res["audio_b64"]))
                audio_url = f"/api/documents/audio/{audio_fn}"
        except Exception as e:
            log.warning("Guide TTS error: %s", e)

    return {
        "topic": topic,
        "title": title,
        "sourceUrl": g.get("source_url"),
        "verifiedDate": g.get("verified_date"),
        "audioUrl": audio_url,
        "steps": formatted_steps,
        "missing_data": False,
    }


@router.get("/missing-documents")
def get_all_missing_documents(x_user_id: Optional[str] = Header(default=None)) -> dict[str, Any]:
    """Get per-member missing documents checklist."""
    user_id = get_active_user_id(x_user_id)
    profile = get_user_profile_data(user_id)

    members = profile.get("familyMembers", [])
    checklist = []
    total_missing = 0

    for m in members:
        m_missing = m.get("missingDocuments", [])
        total_missing += len([md for md in m_missing if md.get("mandatory")])
        checklist.append({
            "memberId": m.get("id"),
            "name": m.get("name"),
            "relation": m.get("relation"),
            "documentsHeld": m.get("documentsHeld", []),
            "missingDocuments": m_missing,
        })

    return {
        "householdId": profile.get("household", {}).get("id", user_id),
        "totalMissingMandatory": total_missing,
        "members": checklist,
    }


@router.get("/catalog/schemes")
def public_scheme_catalog(lang: str = "hi-IN"):
    """Public snapshots only: safe to cache offline, never household eligibility."""
    return {"count": len(get_all_schemes()), "catalogOnly": True, "schemes": [
        {"id": s["id"], "name": s.get("name_hi" if lang.startswith("hi") else "name"),
         "benefit": s.get("benefit_hi" if lang.startswith("hi") else "benefit"),
         "status": "NOT_EVALUATED", "eligibility": {"status": "NOT_EVALUATED", "reasons": [], "missingFields": []},
         "sourceUrl": s.get("source_url"), "verifiedDate": s.get("verified_date"),
         "documentsRequired": s.get("documents_required", []), "steps": s.get("steps", [])}
        for s in get_all_schemes()]}


@router.get("/suggestions")
def suggestions(query: str = "", lang: str = "hi-IN", x_user_id: Optional[str] = Header(default=None)):
    from backend.recommendations import rank_schemes
    user_id = get_active_user_id(x_user_id)
    ranked = rank_schemes(get_all_schemes(), get_user_profile_data(user_id), query)
    return {"ranking": "local_tfidf_cosine_after_eligibility", "suggestions": [
        {"id": r["scheme"]["id"], "name": r["scheme"].get("name_hi" if lang.startswith("hi") else "name"),
         "eligibility": r["eligibility"], "score": r["score"], "steps": r["scheme"].get("steps", []),
         "sourceUrl": r["scheme"].get("source_url"), "verifiedDate": r["scheme"].get("verified_date")}
        for r in ranked]}


@router.get("/region-feed")
def region_feed(refresh: bool = False, x_user_id: Optional[str] = Header(default=None)):
    from backend.live_knowledge import feed
    from backend.assistant import get_user_profile_data
    return feed(get_user_profile_data(get_active_user_id(x_user_id))["household"], force=refresh)
