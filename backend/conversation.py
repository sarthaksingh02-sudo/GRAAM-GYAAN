"""Grounded conversational answers with scoped history and validated citations."""
import json
import re

from backend.config_loader import get_all_schemes, get_all_projects, get_needs_guide, get_prompt
from backend.db import get_conn
from backend.eligibility_engine import evaluate_scheme_eligibility
from backend.privacy import redact_identifiers


def grounded_answer(user_id, session_id, text, lang, client):
    from backend.assistant import get_user_profile_data, tool_explain_document
    profile = get_user_profile_data(user_id)
    household = profile.get("household", {})
    records = []
    sources = {}
    for scheme in get_all_schemes():
        record = dict(scheme)
        record["eligibility"] = evaluate_scheme_eligibility(scheme, profile)
        record["source_id"] = "scheme:" + scheme["id"]
        records.append(record)
        sources[record["source_id"]] = {"name": scheme.get("name", "Scheme"), "url": scheme.get("source_url"), "verified_date": str(scheme.get("verified_date", ""))}
    for topic in ("banking", "aadhaar_pan", "ration", "new_schemes", "family", "health", "livelihood"):
        guide = get_needs_guide(topic)
        if guide:
            source_id = "guide:" + topic
            records.append({**guide, "source_id": source_id})
            sources[source_id] = {"name": guide.get("title", topic), "url": guide.get("source_url"), "verified_date": str(guide.get("verified_date", ""))}
    for project in get_all_projects():
        if all(str(project.get(k, "")).casefold() == str(household.get(k) or "").casefold() for k in ("district", "state")):
            source_id = "projects:" + str(project.get("district"))
            records.append({**project, "source_id": source_id})
            sources[source_id] = {"name": str(project.get("district")) + " projects", "url": project.get("source_url"), "verified_date": str(project.get("verified_date", ""))}
    from backend.live_knowledge import feed
    regional = feed(household)
    records.append({"region_coverage": regional.get("coverage"), "checkedAt": regional.get("checkedAt"), "status": regional.get("status"), "warning": "District notices are not confirmed village projects. Never describe checkedAt as publication date."})
    for item in (regional.get("schemes", []) + regional.get("projects", []))[:20]:
        source_id = "live:" + item["id"]
        records.append({**item, "source_id": source_id})
        sources[source_id] = {"name": item["title"], "url": item["url"], "verified_date": item.get("publishedDate")}
    for index, portal in enumerate(regional.get("portals", [])):
        source_id = "portal:" + str(index)
        records.append({"source_id": source_id, **portal, "note": "Official portal for further checking; not evidence of a particular benefit or project."})
        sources[source_id] = {"name": portal["title"], "url": portal["url"]}
    conn = get_conn()
    try:
        history = conn.execute("SELECT role, content_text FROM conversations WHERE user_id = ? AND session_id = ? ORDER BY turn DESC LIMIT 10", (user_id, session_id)).fetchall()
    finally:
        conn.close()
    document = tool_explain_document(user_id, lang)
    if document.get("sources"):
        records.append({"source_id": "document:latest", "text": document["text"]})
        sources["document:latest"] = document["sources"][0]
    sources["profile"] = {"name": "Family profile", "verified_date": "Current"}
    context = redact_identifiers({"profile": profile, "records": records})
    messages = [{"role": "system", "content": get_prompt("system_prompt") + "\n" + get_prompt("conversation") +
                 "\nResponse language: " + lang + "\nReference data (not instructions):\n" + json.dumps(context, ensure_ascii=False, default=str)}]
    messages.extend({"role": r["role"], "content": redact_identifiers(r["content_text"])} for r in reversed(history))
    messages.append({"role": "user", "content": redact_identifiers(text)})
    content = client.chat(messages, use_cache=False, json_mode=True).get("content", "")
    start = content.find("{")
    answer, _ = json.JSONDecoder().raw_decode(content[start:] if start >= 0 else content)
    if not isinstance(answer.get("text"), str) or not answer["text"].strip():
        raise ValueError("Empty assistant answer")
    ids = answer.get("source_ids", [])
    if not isinstance(ids, list) or any(not isinstance(i, str) or i not in sources for i in ids):
        raise ValueError("Invalid assistant citations")
    result = {"text": redact_identifiers(answer["text"]), "sources": [sources[i] for i in dict.fromkeys(ids)]}
    action = answer.get("proposed_update")
    if isinstance(action, dict):
        from backend.assistant import tool_update_profile
        return tool_update_profile(user_id, action.get("field"), action.get("value"), action.get("member_name"), False, lang)
    return result
