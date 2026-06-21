"""Shared location significance scoring for discovery workflow and enrich."""

from __future__ import annotations

import re
from typing import Any

from pipeline.common.discovery_vocab import location_hard_reject_tokens, location_rpg_tokens

LOCATION_INCLUDE_MIN = 0.7

LOCATION_INCLUDE_SECTION_WEIGHTS: dict[str, float] = {
    "maps_subregions": 0.35,
    "instances_or_dungeons": 0.1,
    "quests_or_storyline": 0.2,
    "history": 0.2,
    "other": 0.0,
}

# WS-C: externalized to pipeline/data/discovery_classification_vocab.v1.json (D-6).
# These score location candidates by name pre-fetch (no category available yet);
# S3's category check in pipeline/common/retail.py is the authoritative post-fetch
# retail signal.
HARD_REJECT_MARKERS = location_hard_reject_tokens()

_RPG_MARKERS = location_rpg_tokens()
_TITLE_CASE_TOKEN_RE = re.compile(r"^[A-Z][a-z]+(?:[''][a-z]+)?$")


def _normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip()).lower()


def is_named_place_title(name: str) -> bool:
    tokens = [token for token in re.split(r"[^A-Za-z']+", name.strip()) if token]
    if len(tokens) < 2:
        return False
    title_case = sum(1 for token in tokens if _TITLE_CASE_TOKEN_RE.match(token))
    return title_case >= max(2, len(tokens) - 1)


def name_in_seed_text(name: str, seed_text: str) -> bool:
    if not name.strip() or not seed_text.strip():
        return False
    return _normalize_name(name) in _normalize_name(seed_text)


def classify_location_candidate(name: str, *, hard_reject_reasons: list[str]) -> str:
    if hard_reject_reasons:
        return "reject"
    name_lowered = _normalize_name(name)
    if "city" in name_lowered:
        return "city"
    if "starter" in name_lowered:
        return "starter_area"
    return "major_location_candidate"


def hard_reject_markers(name: str) -> list[str]:
    name_lowered = _normalize_name(name)
    return [marker for marker in HARD_REJECT_MARKERS if marker in name_lowered]


def score_location_candidate(
    candidate: dict[str, Any],
    *,
    seed_text: str = "",
) -> tuple[float, str, list[str]]:
    name = str(candidate.get("name", ""))
    name_lowered = _normalize_name(name)
    hard_reject_reasons = hard_reject_markers(name)
    location_class = classify_location_candidate(name, hard_reject_reasons=hard_reject_reasons)
    source_section_role = str(candidate.get("source_section_role", "other"))
    base_score = 0.15
    if location_class in {"city", "starter_area"}:
        base_score += 0.6
    else:
        base_score += 0.25
    base_score += LOCATION_INCLUDE_SECTION_WEIGHTS.get(source_section_role, 0.0)
    if name_in_seed_text(name, seed_text):
        base_score += 0.15
    if is_named_place_title(name) and location_class == "major_location_candidate":
        base_score += 0.15
    if any(marker in name_lowered for marker in _RPG_MARKERS):
        base_score -= 0.35
    if len(name_lowered.split()) <= 1:
        base_score -= 0.1
    score = max(0.0, min(1.0, base_score))
    rounded_score = round(score, 2)
    final_decision = (
        "exclude"
        if hard_reject_reasons
        else ("include" if rounded_score >= LOCATION_INCLUDE_MIN else "defer")
    )
    reason_codes = (
        ["hard_reject"]
        if hard_reject_reasons
        else ["score_based", f"source_role:{source_section_role}"]
    )
    if name_in_seed_text(name, seed_text) and "seed_mention" not in reason_codes:
        reason_codes.append("seed_mention")
    if is_named_place_title(name):
        reason_codes.append("named_place")
    borderline = 0.45 <= rounded_score <= 0.65
    if borderline and rounded_score >= 0.5 and final_decision == "defer":
        final_decision = "include"
        reason_codes.append("borderline_include")
    return score, final_decision, reason_codes


def build_zone_seed_text(snapshots: list[dict[str, Any]], zone_id: str) -> str:
    from pipeline.common.text_normalize import clean_wiki_snippet

    seed_roles = {
        "maps_subregions",
        "history",
        "geography_edit",
        "geography",
        "quests_or_storyline",
    }
    parts: list[str] = []
    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            continue
        if str(snapshot.get("entity_id", "")).strip() != zone_id:
            continue
        if str(snapshot.get("entity_type", "")).strip() != "zone":
            continue
        if str(snapshot.get("auxiliary_role", "")).strip():
            continue
        section_blocks = snapshot.get("section_blocks", [])
        if not isinstance(section_blocks, list):
            continue
        for block in section_blocks:
            if not isinstance(block, dict):
                continue
            raw_role = (
                re.sub(r"\s+", " ", str(block.get("section_role", "")).strip())
                .lower()
                .replace(" ", "_")
            )
            if raw_role not in seed_roles and "history" not in raw_role:
                continue
            snippet = clean_wiki_snippet(str(block.get("text", "")))
            if snippet:
                parts.append(snippet)
    return " ".join(parts)


def build_location_decision_row(
    candidate: dict[str, Any],
    *,
    run_id: str,
    algorithm_version: str,
    seed_text: str = "",
) -> dict[str, Any]:
    name = str(candidate.get("name", ""))
    hard_reject_reasons = hard_reject_markers(name)
    source_section_role = str(candidate.get("source_section_role", "other"))
    score, final_decision, reason_codes = score_location_candidate(candidate, seed_text=seed_text)
    rounded_score = round(score, 2)
    borderline = 0.45 <= rounded_score <= 0.65
    return {
        "subject_id": candidate["location_id"],
        "subject_type": "location",
        "run_id": run_id,
        "algorithm_version": algorithm_version,
        "features": {
            "keyword_density": 1 if score > 0.6 else 0,
            "has_hard_reject": bool(hard_reject_reasons),
            "source_section_role": source_section_role,
            "seed_mention": name_in_seed_text(name, seed_text),
            "named_place": is_named_place_title(name),
        },
        "hard_reject": bool(hard_reject_reasons),
        "hard_reject_reasons": hard_reject_reasons,
        "score": score,
        "thresholds": {
            "include_min": LOCATION_INCLUDE_MIN,
            "borderline_min": 0.45,
            "borderline_max": 0.65,
        },
        "borderline_adjudication": (
            {
                "prompt_class": "location_significance_borderline",
                "ruling": "include" if rounded_score >= 0.5 else "exclude",
            }
            if borderline
            else None
        ),
        "final_decision": final_decision,
        "reason_codes": reason_codes,
    }
