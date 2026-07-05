"""Coverage-aware history synthesis support (Slice 7).

History synthesis caps the number of sections and lets the LLM choose which evidence to narrate,
so an eligible ``history_setup_bridge`` claim can silently disappear from the final history even
though the entry-state contract depends on it (the WPL Hearthglen / Argent Crusade gap).

This module plans deterministic *coverage units* from a history pool, validates which units the
synthesized sections actually represent, and lets the finalizer append a concise setup-bridge card
when a required unit was dropped. Units are keyed by ``canonical_evidence_id`` — the
paragraph-level evidence identity — never by ``source_id``: every paragraph of a wiki page shares
one source id, so source-keyed units collapse to one per page and the setup-bridge guarantee
becomes vacuous (the Scholomance "Gandling retreat / Last Holdout" beat vanished while coverage
reported ``covered: true``). There is one coverage path: claim-view pools and paragraph-only pools
form units the same way, and a history-pool item without a ``canonical_evidence_id`` is a contract
violation, not a case to degrade around.

Provenance stays source/paragraph based: coverage decisions reference claim IDs for audit, and the
appended bridge card points at the source paragraph.
"""

from __future__ import annotations

from typing import Any

from pipeline.common.text_normalize import clean_wiki_snippet
from pipeline.generate.draft.prose_election import history_heading_from_role
from pipeline.generate.draft.temporal import HISTORY_SETUP_BRIDGE

SETUP_BRIDGE_BUCKET = "setup_bridge"
BACKGROUND_BUCKET = "background"


def _block_index(item: dict[str, Any]) -> int:
    try:
        return int(item.get("block_index", 0))
    except (TypeError, ValueError):
        return 0


def plan_history_coverage(history_pool: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group a history pool into paragraph-keyed, source-ordered coverage units.

    Each unit collects one paragraph's history-eligible material (all claim views of a claim-level
    pool share their paragraph's ``canonical_evidence_id``; a paragraph-only item is its own unit).
    A unit is ``required`` when any of its items is a ``history_setup_bridge`` claim. Raises
    ``ValueError`` when a pool item carries no ``canonical_evidence_id`` — paragraph identity is
    the coverage contract, and an assembling path that drops it must be fixed, not degraded around.
    """
    units_by_paragraph: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in history_pool:
        if not isinstance(item, dict):
            continue
        canonical_id = str(item.get("canonical_evidence_id", "")).strip()
        if not canonical_id:
            raise ValueError(
                "history coverage pool item is missing canonical_evidence_id "
                f"(source_id={str(item.get('source_id', '')).strip() or 'unknown'!r}); "
                "paragraph-level evidence identity is a contract requirement — fix the "
                "assembling path that produced this item"
            )
        unit = units_by_paragraph.get(canonical_id)
        if unit is None:
            unit = {
                "canonical_evidence_id": canonical_id,
                "source_id": str(item.get("source_id", "")).strip(),
                "claim_ids": [],
                "claim_texts": [],
                "section_role": str(item.get("section_role", "")).strip(),
                "raw_section_role": str(item.get("raw_section_role", "")).strip(),
                "source_order": _block_index(item),
                "has_setup_bridge": False,
                # First item for this paragraph, kept so a deterministic bridge card can hash the
                # source paragraph for a correct provenance pointer (provenance stays source-based).
                "representative_item": item,
            }
            units_by_paragraph[canonical_id] = unit
            order.append(canonical_id)
        claim_id = str(item.get("claim_id", "")).strip()
        if claim_id and claim_id not in unit["claim_ids"]:
            unit["claim_ids"].append(claim_id)
        text = clean_wiki_snippet(str(item.get("claim_text") or item.get("snippet", "")))
        if text and text not in unit["claim_texts"]:
            unit["claim_texts"].append(text)
        if str(item.get("history_eligibility", "")).strip() == HISTORY_SETUP_BRIDGE:
            unit["has_setup_bridge"] = True
        unit["source_order"] = min(unit["source_order"], _block_index(item))

    ordered_paragraphs = sorted(
        order, key=lambda cid: (units_by_paragraph[cid]["source_order"], cid)
    )
    units: list[dict[str, Any]] = []
    for index, canonical_id in enumerate(ordered_paragraphs, start=1):
        raw = units_by_paragraph[canonical_id]
        required = bool(raw["has_setup_bridge"])
        units.append(
            {
                "coverage_id": f"coverage-{index:02d}",
                "canonical_evidence_id": canonical_id,
                "source_id": raw["source_id"],
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
    used_evidence_ids: list[str],
) -> set[str]:
    """Coverage IDs whose paragraph was actually cited by the synthesized history.

    ``used_evidence_ids`` are the paragraph-level ids the synthesis reported using (translated
    ``canonical_evidence_id`` values). A unit is covered only when its own paragraph was used —
    never because a sibling paragraph of the same source page was (the source-id collapse that
    made the setup-bridge guarantee vacuous in production).
    """
    used = {str(value).strip() for value in used_evidence_ids if str(value).strip()}
    return {unit["coverage_id"] for unit in units if unit["canonical_evidence_id"] in used}


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
                "canonical_evidence_id": unit["canonical_evidence_id"],
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
