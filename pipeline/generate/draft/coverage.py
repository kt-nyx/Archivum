"""Coverage-aware history synthesis support (Slice 7).

History synthesis caps the number of sections and lets the LLM choose which evidence to narrate,
so an eligible ``history_setup_bridge`` claim can silently disappear from the final history even
though the entry-state contract depends on it (the WPL Hearthglen / Argent Crusade gap).

This module plans deterministic *coverage units* from a claim-level history pool, validates which
units the synthesized sections actually represent, and lets the finalizer append a concise
setup-bridge card when a required unit was dropped. It is intentionally claim-level only: a
paragraph-only history pool (no claim sidecar) produces no units, so the legacy paragraph path is
left unchanged for rollout compatibility.

Provenance stays source/paragraph based (clarification question 3): coverage decisions reference
claim IDs for audit, but the appended bridge card still points at the source paragraph.
"""

from __future__ import annotations

from typing import Any

from pipeline.common.text_normalize import clean_wiki_snippet
from pipeline.generate.draft.prose_election import history_heading_from_role
from pipeline.generate.draft.temporal import HISTORY_SETUP_BRIDGE

SETUP_BRIDGE_BUCKET = "setup_bridge"
BACKGROUND_BUCKET = "background"


def _is_claim_view(item: Any) -> bool:
    return isinstance(item, dict) and bool(item.get("is_claim_view"))


def _block_index(item: dict[str, Any]) -> int:
    try:
        return int(item.get("block_index", 0))
    except (TypeError, ValueError):
        return 0


def plan_history_coverage(history_pool: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group a claim-level history pool into source-ordered coverage units.

    Each unit collects one source's history-eligible claims. A unit is ``required`` when any of its
    claims is a ``history_setup_bridge`` claim, per the confirmed decision in clarification
    question 3. Returns ``[]`` when the pool has no claim views, so paragraph-only history keeps its
    existing behavior.
    """
    units_by_source: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in history_pool:
        if not _is_claim_view(item):
            continue
        source_id = str(item.get("source_id", "")).strip()
        if not source_id:
            continue
        unit = units_by_source.get(source_id)
        if unit is None:
            unit = {
                "source_id": source_id,
                "claim_ids": [],
                "claim_texts": [],
                "section_role": str(item.get("section_role", "")).strip(),
                "raw_section_role": str(item.get("raw_section_role", "")).strip(),
                "source_order": _block_index(item),
                "has_setup_bridge": False,
                # First claim view for this source, kept so a deterministic bridge card can hash the
                # source paragraph for a correct provenance pointer (provenance stays source-based).
                "representative_item": item,
            }
            units_by_source[source_id] = unit
            order.append(source_id)
        claim_id = str(item.get("claim_id", "")).strip()
        if claim_id and claim_id not in unit["claim_ids"]:
            unit["claim_ids"].append(claim_id)
        text = clean_wiki_snippet(str(item.get("claim_text") or item.get("snippet", "")))
        if text and text not in unit["claim_texts"]:
            unit["claim_texts"].append(text)
        if str(item.get("history_eligibility", "")).strip() == HISTORY_SETUP_BRIDGE:
            unit["has_setup_bridge"] = True
        unit["source_order"] = min(unit["source_order"], _block_index(item))

    ordered_sources = sorted(order, key=lambda sid: (units_by_source[sid]["source_order"], sid))
    units: list[dict[str, Any]] = []
    for index, source_id in enumerate(ordered_sources, start=1):
        raw = units_by_source[source_id]
        required = bool(raw["has_setup_bridge"])
        units.append(
            {
                "coverage_id": f"coverage-{index:02d}",
                "source_id": source_id,
                "claim_ids": list(raw["claim_ids"]),
                "claim_texts": list(raw["claim_texts"]),
                "required": required,
                "reason": HISTORY_SETUP_BRIDGE if required else "history_background",
                "suggested_heading": history_heading_from_role(
                    raw["section_role"] or "other", raw["raw_section_role"]
                ),
                "temporal_bucket": SETUP_BRIDGE_BUCKET if required else BACKGROUND_BUCKET,
                "source_order": raw["source_order"],
                "representative_item": raw["representative_item"],
            }
        )
    return units


def covered_coverage_ids(
    units: list[dict[str, Any]],
    used_source_ids: list[str],
) -> set[str]:
    """Coverage IDs whose source produced a used history section.

    Coverage is validated at source-paragraph granularity: a unit is covered when its source
    contributed at least one section, matching the existing history provenance model (``used``
    drives the section's source pointers). This avoids inventing a second, fuzzier coverage truth
    from rewritten body text.
    """
    used = {str(value).strip() for value in used_source_ids if str(value).strip()}
    return {unit["coverage_id"] for unit in units if unit["source_id"] in used}


def missing_required_units(
    units: list[dict[str, Any]],
    covered_ids: set[str],
) -> list[dict[str, Any]]:
    return [
        unit
        for unit in units
        if unit["required"] and unit["coverage_id"] not in covered_ids
    ]


def required_event_texts(units: list[dict[str, Any]]) -> list[str]:
    """Flattened claim texts for required units, for an LLM coverage-retry hint."""
    texts: list[str] = []
    for unit in units:
        for text in unit["claim_texts"]:
            if text and text not in texts:
                texts.append(text)
    return texts


def setup_bridge_body(unit: dict[str, Any]) -> str:
    """Concise bridge body from a required unit's safe claim text."""
    return " ".join(text for text in unit["claim_texts"] if text).strip()


def build_section_coverage_decisions(
    subject_id: str,
    units: list[dict[str, Any]],
    covered_ids: set[str],
    appended_ids: set[str],
) -> list[dict[str, Any]]:
    """One non-public sidecar row per subject describing history coverage.

    Records every coverage unit, whether required units were covered by synthesis, and whether a
    deterministic setup-bridge card had to be appended. An eligible setup bridge is never omitted
    without a reason captured here.
    """
    if not units:
        return []
    unit_rows: list[dict[str, Any]] = []
    for unit in units:
        covered = unit["coverage_id"] in covered_ids
        unit_rows.append(
            {
                "coverage_id": unit["coverage_id"],
                "source_id": unit["source_id"],
                "claim_ids": list(unit["claim_ids"]),
                "required": unit["required"],
                "reason": unit["reason"],
                "temporal_bucket": unit["temporal_bucket"],
                "source_order": unit["source_order"],
                "covered": covered,
                "deterministic_bridge_appended": unit["coverage_id"] in appended_ids,
            }
        )
    required_units = [unit for unit in units if unit["required"]]
    return [
        {
            "subject_id": subject_id,
            "coverage_unit_count": len(units),
            "required_unit_count": len(required_units),
            "required_covered_count": sum(
                1 for unit in required_units if unit["coverage_id"] in covered_ids
            ),
            "deterministic_bridge_count": len(appended_ids),
            "coverage_units": unit_rows,
        }
    ]
