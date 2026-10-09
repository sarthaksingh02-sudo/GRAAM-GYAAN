"""
backend/exporter.py — PDF, Plain Text, and JSON Report Generators for GRAAM-GYAAN.

Features:
  - Devanagari font rendering (Noto Sans Devanagari) configured via config/export.yaml
  - Strict PII masking: No full Aadhaar/PAN/Bank/Ration card number ever exported
  - Fact-level source grounding: Every scheme and project cites source_url and verified_date
  - Templates loaded from config/export.yaml and templates/export_template.txt
"""

from __future__ import annotations

import datetime
import io
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from backend.assistant import get_user_profile_data
from backend.config_loader import (
    get_all_projects,
    get_all_schemes,
    load_text,
    load_yaml,
)
from backend.eligibility_engine import evaluate_scheme_eligibility
from backend.privacy import mask_value_by_type

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
TEMPLATES_DIR = BASE_DIR / "templates"

_FONT_REGISTERED = False


def _register_font() -> str:
    """Register Devanagari TTF font with ReportLab."""
    global _FONT_REGISTERED
    export_cfg = load_yaml(CONFIG_DIR / "export.yaml")
    font_name = export_cfg.get("fonts", {}).get("devanagari_font_name", "NotoSansDevanagari")
    font_rel = export_cfg.get("fonts", {}).get("devanagari_font_file", "assets/fonts/NotoSansDevanagari-Regular.ttf")
    font_path = BASE_DIR / font_rel

    if font_path.exists():
        try:
            pdfmetrics.registerFont(TTFont(font_name, str(font_path)))
            _FONT_REGISTERED = True
            return font_name
        except Exception as e:
            log.warning("Could not register TTF font %s: %s", font_path, e)

    return "Helvetica"


def get_export_data(user_id: int, lang: str = "hi-IN") -> dict[str, Any]:
    """Assemble complete export payload with masking and source grounding."""
    prof = get_user_profile_data(user_id)
    h = prof.get("household", {})
    members = prof.get("familyMembers", [])

    # Mask all member identifiers defensively
    sanitized_members = []
    for m in members:
        sanitized_members.append({
            "id": m.get("id"),
            "name": m.get("name"),
            "dob": m.get("dob"),
            "ageYears": m.get("ageYears"),
            "gender": m.get("gender"),
            "relation": m.get("relation"),
            "occupation": m.get("occupation"),
            "caste_category": m.get("caste_category"),
            "land_acres": m.get("land_acres"),
            "documentsHeld": [mask_value_by_type(d) for d in m.get("documentsHeld", [])],
            "missingDocuments": m.get("missingDocuments", []),
        })

    # Evaluate schemes
    all_schemes = get_all_schemes()
    evaluated_schemes = []
    for s in all_schemes:
        ev = evaluate_scheme_eligibility(s, prof)
        if ev["status"] in ("ELIGIBLE", "POSSIBLE"):
            evaluated_schemes.append({
                "id": s.get("id"),
                "name": s.get("name_hi" if lang.startswith("hi") else "name", s.get("name")),
                "status": ev["status"],
                "benefit": s.get("benefit_hi" if lang.startswith("hi") else "benefit", s.get("benefit")),
                "reasons": ev.get("reasons", []),
                "missingFields": ev.get("missingFields", []),
                "sourceUrl": s.get("source_url"),
                "verifiedDate": s.get("verified_date"),
                "matchedMember": ev.get("matchedMember"),
            })

    # Regional projects
    projects_data = [p for p in get_all_projects() if all(str(p.get(k, "")).casefold() == str(h.get(k) or "").casefold() for k in ("district", "state"))]
    centre_projects = []
    state_projects = []
    proj_source = None
    if projects_data:
        p_file = projects_data[0]
        proj_source = {"url": p_file.get("source_url"), "date": p_file.get("verified_date")}
        p_dict = p_file.get("projects", {})
        centre_projects = p_dict.get("centre", [])
        state_projects = p_dict.get("state", [])

    return {
        "generated_date": datetime.date.today().isoformat(),
        "household": h,
        "familyMembers": sanitized_members,
        "eligibleSchemes": evaluated_schemes,
        "centreProjects": centre_projects,
        "stateProjects": state_projects,
        "projectsSource": proj_source,
    }


# ---------------------------------------------------------------------------
# 1. Plain Text Export
# ---------------------------------------------------------------------------
def generate_text_export(user_id: int, lang: str = "hi-IN") -> str:
    export_cfg = load_yaml(CONFIG_DIR / "export.yaml")
    tmpl_text = load_text(TEMPLATES_DIR / "export_template.txt")
    data = get_export_data(user_id, lang=lang)

    h = data["household"]
    members = data["familyMembers"]
    schemes = data["eligibleSchemes"]

    # Format members
    mem_lines = []
    for idx, m in enumerate(members, 1):
        age_str = f", {m['ageYears']} वर्ष" if m.get("ageYears") is not None else ""
        occ_str = f", {m['occupation']}" if m.get("occupation") else ""
        mem_lines.append(f"  {idx}. {m['name']} ({m['relation']}{age_str}{occ_str})")
        if m.get("missingDocuments"):
            miss_titles = [md["title"] for md in m["missingDocuments"] if md.get("mandatory")]
            if miss_titles:
                mem_lines.append(f"     [बाकी दस्तावेज़: {', '.join(miss_titles)}]")
    members_block = "\n".join(mem_lines) if mem_lines else "  कोई सदस्य दर्ज नहीं है।"

    # Format schemes
    scheme_lines = []
    for idx, s in enumerate(schemes, 1):
        scheme_lines.append(f"  {idx}. [{s['status']}] {s['name']}")
        scheme_lines.append(f"     लाभ: {s['benefit']}")
        scheme_lines.append(f"     स्रोत: {s['sourceUrl']} (सत्यापित: {s['verifiedDate']})")
    schemes_block = "\n".join(scheme_lines) if scheme_lines else "  कोई पात्र योजना उपलब्ध नहीं है।"

    # Missing docs block
    all_missing = []
    for m in members:
        for md in m.get("missingDocuments", []):
            if md.get("mandatory"):
                all_missing.append(f"  - {m['name']} ({m['relation']}): {md['title']}")
    missing_docs_block = "\n".join(all_missing) if all_missing else "  सभी अनिवार्य दस्तावेज़ पूर्ण हैं।"

    # Projects block
    proj_lines = []
    if data["centreProjects"]:
        proj_lines.append("  [केंद्र सरकार / Central Projects]:")
        for p in data["centreProjects"]:
            p_name = p.get("name_hi" if lang.startswith("hi") else "name", p.get("name"))
            proj_lines.append(f"   * {p_name} ({p.get('status')}) - {p.get('agency')}")
    if data["stateProjects"]:
        proj_lines.append("  [राज्य सरकार / State Projects]:")
        for p in data["stateProjects"]:
            p_name = p.get("name_hi" if lang.startswith("hi") else "name", p.get("name"))
            proj_lines.append(f"   * {p_name} ({p.get('status')}) - {p.get('agency')}")
    projects_block = "\n".join(proj_lines) if proj_lines else "  परियोजनाओं का विवरण उपलब्ध नहीं है।"

    header_text = export_cfg.get("headers", {}).get(lang) or export_cfg.get("headers", {}).get("hi-IN", "GRAAM-GYAAN Summary")
    footer_text = export_cfg.get("footers", {}).get(lang) or export_cfg.get("footers", {}).get("hi-IN", "")
    disclaimer_text = export_cfg.get("disclaimer", {}).get(lang) or export_cfg.get("disclaimer", {}).get("hi-IN", "")

    return tmpl_text.format(
        header=header_text,
        generated_date=data["generated_date"],
        household_id=h.get("id", user_id),
        village=h.get("village", "-"),
        panchayat=h.get("panchayat", "-"),
        district=h.get("district", "-"),
        state=h.get("state", "-"),
        member_count=len(members),
        family_members_block=members_block,
        schemes_block=schemes_block,
        missing_docs_block=missing_docs_block,
        projects_block=projects_block,
        disclaimer=disclaimer_text,
        footer=footer_text,
    )


# ---------------------------------------------------------------------------
# 2. JSON Export
# ---------------------------------------------------------------------------
def generate_json_export(user_id: int, lang: str = "hi-IN") -> dict[str, Any]:
    return get_export_data(user_id, lang=lang)


# ---------------------------------------------------------------------------
# 3. PDF Export (ReportLab with Devanagari Font)
# ---------------------------------------------------------------------------
def generate_pdf_export(user_id: int, lang: str = "hi-IN") -> bytes:
    font_name = _register_font()
    export_cfg = load_yaml(CONFIG_DIR / "export.yaml")
    data = get_export_data(user_id, lang=lang)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitle",
        fontName=font_name,
        fontSize=18,
        leading=22,
        textColor=HexColor("#1B5E20"),
        alignment=1,  # Center
        spaceAfter=10,
    )
    meta_style = ParagraphStyle(
        "MetaStyle",
        fontName=font_name,
        fontSize=10,
        leading=14,
        textColor=HexColor("#424242"),
        spaceAfter=12,
    )
    h2_style = ParagraphStyle(
        "SectionHeading",
        fontName=font_name,
        fontSize=12,
        leading=16,
        textColor=HexColor("#E65100"),
        spaceBefore=10,
        spaceAfter=6,
        keepWithNext=True,
    )
    body_style = ParagraphStyle(
        "BodyStyle",
        fontName=font_name,
        fontSize=9,
        leading=13,
        textColor=HexColor("#212121"),
    )
    badge_style = ParagraphStyle(
        "BadgeStyle",
        fontName=font_name,
        fontSize=8,
        leading=11,
        textColor=HexColor("#1B5E20"),
    )
    cite_style = ParagraphStyle(
        "CiteStyle",
        fontName=font_name,
        fontSize=7,
        leading=9,
        textColor=HexColor("#757575"),
    )
    disclaimer_style = ParagraphStyle(
        "DisclaimerStyle",
        fontName=font_name,
        fontSize=7,
        leading=10,
        textColor=HexColor("#616161"),
        alignment=1,
    )

    story = []

    # Title
    header_text = export_cfg.get("headers", {}).get(lang) or export_cfg.get("headers", {}).get("hi-IN", "GRAAM-GYAAN Report")
    story.append(Paragraph(f"<b>{header_text}</b>", title_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=HexColor("#1B5E20"), spaceAfter=8))

    # Household metadata
    h = data["household"]
    meta_text = (
        f"<b>दिनांक:</b> {data['generated_date']} | "
        f"<b>गाँव:</b> {h.get('village', '-')} | "
        f"<b>पंचायत:</b> {h.get('panchayat', '-')} | "
        f"<b>जिला:</b> {h.get('district', '-')} ({h.get('state', '-')})"
    )
    story.append(Paragraph(meta_text, meta_style))

    # Section 1: Family Members
    story.append(Paragraph("<b>1. पारिवारिक विवरण (Family Members)</b>", h2_style))
    mem_table_data = [
        [
            Paragraph("<b>नाम / Name</b>", body_style),
            Paragraph("<b>संबंध / Relation</b>", body_style),
            Paragraph("<b>आयु / Age</b>", body_style),
            Paragraph("<b>व्यवसाय / Occupation</b>", body_style),
            Paragraph("<b>दस्तावेज़ स्थिति / Status</b>", body_style),
        ]
    ]

    for m in data["familyMembers"]:
        miss_count = len([md for md in m.get("missingDocuments", []) if md.get("mandatory")])
        status_str = "पूर्ण (Complete)" if miss_count == 0 else f"{miss_count} बाकी (Pending)"
        mem_table_data.append([
            Paragraph(m.get("name", "-"), body_style),
            Paragraph(m.get("relation", "-"), body_style),
            Paragraph(f"{m.get('ageYears', '-')} वर्ष" if m.get("ageYears") is not None else "-", body_style),
            Paragraph(m.get("occupation") or "-", body_style),
            Paragraph(status_str, body_style),
        ])

    t_mem = Table(mem_table_data, colWidths=[110, 80, 60, 110, 160])
    t_mem.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HexColor("#E8F5E9")),
        ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#BDBDBD")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t_mem)
    story.append(Spacer(1, 10))

    # Section 2: Eligible Schemes
    story.append(Paragraph("<b>2. पात्र एवं संभावित सरकारी कल्याण योजनाएं (Eligible Schemes)</b>", h2_style))
    for s in data["eligibleSchemes"]:
        tag = "पात्र (ELIGIBLE)" if s["status"] == "ELIGIBLE" else "संभावित (POSSIBLE)"
        p_name = Paragraph(f"<b>{s['name']}</b> — <i>[{tag}]</i>", badge_style)
        p_ben = Paragraph(f"<b>लाभ:</b> {s['benefit']}", body_style)
        p_cite = Paragraph(f"स्रोत: {s['sourceUrl']} • सत्यापित: {s['verifiedDate']}", cite_style)
        story.append(p_name)
        story.append(p_ben)
        story.append(p_cite)
        story.append(Spacer(1, 4))

    story.append(Spacer(1, 6))

    # Section 3: Missing Documents Checklist
    story.append(Paragraph("<b>3. अनिवार्य दस्तावेज़ चेकलिस्ट (Pending Mandatory Documents)</b>", h2_style))
    missing_items = []
    for m in data["familyMembers"]:
        for md in m.get("missingDocuments", []):
            if md.get("mandatory"):
                missing_items.append(f"• <b>{m['name']} ({m['relation']}):</b> {md['title']}")
    if missing_items:
        for item in missing_items:
            story.append(Paragraph(item, body_style))
    else:
        story.append(Paragraph("आपके परिवार के सभी आवश्यक दस्तावेज़ पूर्ण हैं।", body_style))

    story.append(Spacer(1, 10))

    # Section 4: Local Projects
    story.append(Paragraph("<b>4. क्षेत्र में विकास कार्य (Local Development Projects)</b>", h2_style))
    if data["centreProjects"]:
        for p in data["centreProjects"][:2]:
            p_name = p.get("name_hi" if lang.startswith("hi") else "name", p.get("name"))
            story.append(Paragraph(f"• [केंद्र] <b>{p_name}</b> ({p.get('status')}) — {p.get('agency')}", body_style))
    if data["stateProjects"]:
        for p in data["stateProjects"][:2]:
            p_name = p.get("name_hi" if lang.startswith("hi") else "name", p.get("name"))
            story.append(Paragraph(f"• [राज्य] <b>{p_name}</b> ({p.get('status')}) — {p.get('agency')}", body_style))

    story.append(Spacer(1, 14))
    story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#BDBDBD"), spaceAfter=6))

    # Disclaimer & Footer
    disclaimer_text = export_cfg.get("disclaimer", {}).get(lang) or export_cfg.get("disclaimer", {}).get("hi-IN", "")
    footer_text = export_cfg.get("footers", {}).get(lang) or export_cfg.get("footers", {}).get("hi-IN", "")
    story.append(Paragraph(disclaimer_text, disclaimer_style))
    story.append(Spacer(1, 3))
    story.append(Paragraph(footer_text, disclaimer_style))

    doc.build(story)
    return buffer.getvalue()
