"""
backend/eligibility_engine.py — Generic, deterministic welfare scheme eligibility rule evaluator.

NO scheme-specific code: All rules are purely data read from scheme YAML files.
Evaluates rules against household profile and family members.
Returns:
  - status: 'ELIGIBLE' | 'POSSIBLE' | 'NOT_ELIGIBLE'
  - reasons: matching / failure explanations
  - missingFields: list of unrecorded fields with questions to ask the citizen
  - matchedMember: member fulfilling individual criteria if applicable
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


def _evaluate_condition(actual: Any, op: str, expected: Any) -> bool:
    """Evaluate a single rule operator."""
    if actual is None:
        return False

    try:
        if op == "==":
            return str(actual).lower().strip() == str(expected).lower().strip()
        elif op == "!=":
            return str(actual).lower().strip() != str(expected).lower().strip()
        elif op == "in":
            if isinstance(expected, list):
                expected_set = [str(x).lower().strip() for x in expected]
                return str(actual).lower().strip() in expected_set
            return str(actual).lower().strip() in str(expected).lower().strip()
        elif op == "not_in":
            if isinstance(expected, list):
                expected_set = [str(x).lower().strip() for x in expected]
                return str(actual).lower().strip() not in expected_set
            return str(actual).lower().strip() not in str(expected).lower().strip()
        elif op == ">":
            return float(actual) > float(expected)
        elif op == ">=":
            return float(actual) >= float(expected)
        elif op == "<":
            return float(actual) < float(expected)
        elif op == "<=":
            return float(actual) <= float(expected)
    except Exception as e:
        log.debug("Condition eval error (%s %s %s): %s", actual, op, expected, e)
        return False

    return False


def _evaluate_saved_rules(
    scheme: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    """
    Generic evaluator for a single scheme against a household profile.
    """
    rules = scheme.get("rules", [])
    if not rules:
        return {
            "schemeId": scheme.get("id"),
            "status": "ELIGIBLE",
            "reasons": ["No restrictive eligibility conditions specified."],
            "missingFields": [],
            "matchedMember": None,
        }

    household = profile.get("household", {})
    members = profile.get("familyMembers", [])

    # If no members registered yet, check if rules can evaluate or return POSSIBLE
    if not members and any(r.get("field") in ("gender", "ageYears", "occupation") for r in rules):
        missing = [
            {"field": r.get("field"), "question": r.get("question_if_missing", f"What is your {r.get('field')}?")}
            for r in rules
            if r.get("question_if_missing")
        ]
        return {
            "schemeId": scheme.get("id"),
            "status": "POSSIBLE",
            "reasons": ["Family member details are needed to verify eligibility."],
            "missingFields": missing,
            "matchedMember": None,
        }

    # Identify if rule set is member-specific or household-wide
    member_fields = {"gender", "ageYears", "occupation", "is_disabled", "education_level"}
    has_member_rules = any(r.get("field") in member_fields for r in rules)

    if has_member_rules:
        # Check if ANY member in the family qualifies
        best_status = "NOT_ELIGIBLE"
        best_reasons = []
        best_missing = []
        best_member = None

        for m in members:
            # Combined context for this member + household
            ctx = {**household, **m}
            m_status, m_reasons, m_missing = _evaluate_context_rules(rules, ctx)

            if m_status == "ELIGIBLE":
                return {
                    "schemeId": scheme.get("id"),
                    "status": "ELIGIBLE",
                    "reasons": m_reasons,
                    "missingFields": [],
                    "matchedMember": {"id": m.get("id"), "name": m.get("name"), "relation": m.get("relation")},
                }
            elif m_status == "POSSIBLE" and best_status != "ELIGIBLE":
                best_status = "POSSIBLE"
                best_reasons = m_reasons
                best_missing = m_missing
                best_member = {"id": m.get("id"), "name": m.get("name"), "relation": m.get("relation")}
            elif best_status == "NOT_ELIGIBLE":
                best_reasons = m_reasons

        return {
            "schemeId": scheme.get("id"),
            "status": best_status,
            "reasons": best_reasons,
            "missingFields": best_missing,
            "matchedMember": best_member,
        }
    else:
        # Household-only rules (e.g. land_acres, caste_category, state)
        ctx = {**household}
        # If head member has land or caste
        if members:
            ctx.update({k: v for k, v in members[0].items() if k in ("land_acres", "caste_category") and v is not None})

        h_status, h_reasons, h_missing = _evaluate_context_rules(rules, ctx)
        return {
            "schemeId": scheme.get("id"),
            "status": h_status,
            "reasons": h_reasons,
            "missingFields": h_missing,
            "matchedMember": None,
        }


def _evaluate_context_rules(
    rules: list[dict[str, Any]],
    ctx: dict[str, Any],
) -> tuple[str, list[str], list[dict[str, Any]]]:
    """Evaluate rule list on a single dictionary context."""
    reasons = []
    missing_fields = []
    failed = False

    for r in rules:
        field = r.get("field", "")
        op = r.get("operator", "==")
        expected = r.get("value")
        question = r.get("question_if_missing")

        actual = ctx.get(field)

        # Missing field check
        if actual is None:
            if question:
                missing_fields.append({"field": field, "question": question})
            else:
                missing_fields.append({"field": field, "question": f"Please provide {field}."})
            continue

        is_passed = _evaluate_condition(actual, op, expected)
        if is_passed:
            reasons.append(f"Recorded {field.replace('_', ' ')}: {actual}.")
        else:
            failed = True
            reasons.append(f"The saved {field.replace('_', ' ')} does not match this scheme’s recorded requirements.")

    if failed:
        return "NOT_ELIGIBLE", reasons, []
    if missing_fields:
        return "POSSIBLE", reasons, missing_fields
    return "ELIGIBLE", reasons, []


def evaluate_scheme_eligibility(scheme, profile):
    result = _evaluate_saved_rules(scheme, profile)
    if scheme.get("rules_complete") is False and result["status"] == "ELIGIBLE":
        result["status"] = "POSSIBLE"
        result["reasons"].append("Saved checks match, but official eligibility verification is still required.")
        result["missingFields"].append({"field": "official_verification", "question": "Please verify complete eligibility with the responsible office or official portal."})
    result["preliminary"] = scheme.get("rules_complete") is False
    return result
