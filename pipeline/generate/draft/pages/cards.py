"""Shared faction/location/history section card finalizers."""

from __future__ import annotations

from typing import Any

from pipeline.common.wiki_evidence_filters import cap_history_pool
from pipeline.generate.draft.faction_lint import ensure_sentence_terminator, lint_faction_summary
from pipeline.generate.draft.faction_scoring import (
    MAX_FACTION_CARDS,
    FactionCandidate,
    candidates_for_finalize,
    collect_faction_candidates,
    fallback_faction_summary,
    finalize_evidence_pools,
)
from pipeline.generate.draft.location_lint import (
    ensure_sentence_terminator as ensure_location_sentence_terminator,
)
from pipeline.generate.draft.location_lint import (
    fallback_location_summary,
    lint_location_summary,
)
from pipeline.generate.draft.location_scoring import (
    MAX_LOCATION_CARDS,
    LocationCandidate,
    _decision_reason_codes,
    collect_location_candidates,
    extract_subregion_tokens,
    location_type_from_signals,
)
from pipeline.generate.draft.location_scoring import (
    candidates_for_finalize as location_candidates_for_finalize,
)
from pipeline.generate.draft.location_scoring import (
    finalize_evidence_pools as finalize_location_evidence_pools,
)
from pipeline.generate.draft.pages.assembly import (
    _cap_card_pointers,
    _iter_evidence_items,
    _pointers_for_source_ids,
    _word_count,
)
from pipeline.generate.draft.prose_election import (
    fallback_history_sections,
    history_section_cap,
    select_history_pool,
)
from pipeline.generate.draft.prose_gate import prose_gate_rejects
from pipeline.generate.draft.prose_lint import (
    MAX_HISTORY_SECTIONS,
    MIN_HISTORY_SECTIONS,
    lint_history_sections,
    split_sentences,
    word_count,
)
from pipeline.generate.draft.prose_synthesis import (
    relabel_history_headings,
    synthesize_faction_summary,
    synthesize_history_sections,
    synthesize_location_significance,
    synthesize_location_summary,
)

# Per-section history word budget enforced by validate (budget.py: 40 <= words <= 110).
# The draft keeps merged/deterministic sections inside it so a run can't hard-fail on
# an over-long merged section or a too-short wiki paragraph.
_HISTORY_SECTION_MIN_WORDS = 40
_HISTORY_SECTION_MAX_WORDS = 110


def _sections_trip_gate(sections: list[dict[str, Any]]) -> bool:
    """True when any history section body fails the deterministic prose gate."""
    return any(
        isinstance(section, dict) and prose_gate_rejects(str(section.get("body", "")))
        for section in sections
    )


def _history_sections_from_pool(
    history_pool: list[dict[str, Any]],
    *,
    evidence_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    pool = history_pool or select_history_pool(
        _iter_evidence_items(evidence_rows, {"history_digest"})
    )
    cap = history_section_cap(pool) or MIN_HISTORY_SECTIONS
    draft_pool = cap_history_pool(pool, cap)
    sections, used = fallback_history_sections(draft_pool, max_sections=cap)
    if sections:
        return sections, used
    return [], []


def _draft_history_pool(history_pool: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    max_history = history_section_cap(history_pool)
    if max_history <= 0:
        return [], 0
    return cap_history_pool(history_pool, max_history), max_history


def _finalize_history_sections(
    *,
    history_pool: list[dict[str, Any]],
    evidence_rows: list[dict[str, Any]],
    max_history: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    section_cap = max_history or MIN_HISTORY_SECTIONS
    lint_cap = max_history or MAX_HISTORY_SECTIONS
    sections, used = synthesize_history_sections(history_pool, max_sections=section_cap)
    sections = _apply_history_section_budget(_merge_consecutive_history_headings(sections))
    if lint_history_sections(sections, max_sections=lint_cap) or _sections_trip_gate(sections):
        sections, used = fallback_history_sections(history_pool, max_sections=section_cap)
        sections = _apply_history_section_budget(_merge_consecutive_history_headings(sections))
        if lint_history_sections(sections, max_sections=lint_cap) or _sections_trip_gate(sections):
            sections, used = [], []
    if not sections:
        pool_sections, pool_used = _history_sections_from_pool(
            history_pool, evidence_rows=evidence_rows
        )
        if pool_sections:
            kept_sections = [
                section
                for section in pool_sections
                if not lint_history_sections([section], max_sections=1)
            ]
            candidate_sections = _apply_history_section_budget(
                _merge_consecutive_history_headings(kept_sections or pool_sections)
            )
            if not lint_history_sections(candidate_sections, max_sections=lint_cap):
                sections = candidate_sections[:section_cap]
                used = pool_used
    # Re-title bare era/TOC headings ("World of Warcraft", "Cataclysm") with thematic, body-derived
    # titles. Runs whichever path produced the bodies, so wiki-fallback sections still get LLM
    # headings; offline this is a no-op (deterministic label is kept).
    sections = relabel_history_headings(sections)
    return sections, used


def _source_ref_key(ref: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(ref.get("source_id", "")),
        str(ref.get("locator", "")),
        str(ref.get("excerpt_hash", "")),
    )


def _merge_consecutive_history_headings(
    sections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Collapse runs of consecutive sections that share a heading into one section.

    The deterministic/LLM history builders emit one section per evidence block, so
    several paragraphs under the same wiki subsection ("Scourging of Lordaeron",
    "Historical era") each become their own section with an identical heading. Merge
    consecutive same-heading sections (case-insensitive) by joining their bodies and
    unioning their source_refs, so a theme renders as a single coherent section.
    """
    merged: list[dict[str, Any]] = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        heading = str(section.get("heading", "")).strip()
        if merged and str(merged[-1].get("heading", "")).strip().lower() == heading.lower():
            prev = merged[-1]
            prev_body = str(prev.get("body", "")).strip()
            next_body = str(section.get("body", "")).strip()
            prev["body"] = " ".join(part for part in (prev_body, next_body) if part)
            prev_refs = list(prev.get("source_refs") or [])
            seen = {_source_ref_key(ref) for ref in prev_refs if isinstance(ref, dict)}
            for ref in section.get("source_refs") or []:
                if isinstance(ref, dict) and _source_ref_key(ref) not in seen:
                    prev_refs.append(ref)
                    seen.add(_source_ref_key(ref))
            prev["source_refs"] = prev_refs
            continue
        merged.append(dict(section))
    return merged


def _trim_body_to_word_budget(body: str, max_words: int) -> str:
    """Trim a body to <= max_words on sentence boundaries (keep whole leading sentences)."""
    if word_count(body) <= max_words:
        return body
    kept: list[str] = []
    running = 0
    for sentence in split_sentences(body):
        sentence_words = word_count(sentence)
        if kept and running + sentence_words > max_words:
            break
        kept.append(sentence)
        running += sentence_words
    return " ".join(kept).strip() if kept else body


def _apply_history_section_budget(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep every history section inside the validate word budget (40..110).

    Over-long sections (e.g. several wiki paragraphs merged under one subsection heading)
    are trimmed to whole leading sentences; a section that is still below the floor is
    absorbed into the previous section when that stays in budget, otherwise dropped — so
    the deterministic path can't ship a section that hard-fails ``budget.history_section``.
    """
    # Pass 1: trim every section to whole leading sentences within the word cap.
    trimmed: list[dict[str, Any]] = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        out = dict(section)
        out["body"] = _trim_body_to_word_budget(
            str(out.get("body", "")).strip(), _HISTORY_SECTION_MAX_WORDS
        )
        trimmed.append(out)
    # Pass 2: absorb a sub-floor section into the previous one (when the result stays in
    # budget) — e.g. a one-line era blurb folded into the prior era — but never reduce the
    # section count below the minimum, so legitimate multi-section history isn't collapsed.
    # Content is never dropped: a short section that can't be absorbed is kept as-is.
    absorb_budget = max(0, len(trimmed) - MIN_HISTORY_SECTIONS)
    result: list[dict[str, Any]] = []
    for out in trimmed:
        if absorb_budget > 0 and result and word_count(str(out["body"])) < _HISTORY_SECTION_MIN_WORDS:
            prev = result[-1]
            combined = " ".join(
                part
                for part in (str(prev.get("body", "")).strip(), str(out["body"]).strip())
                if part
            )
            if word_count(combined) <= _HISTORY_SECTION_MAX_WORDS:
                prev["body"] = combined
                prev_refs = list(prev.get("source_refs") or [])
                seen = {_source_ref_key(ref) for ref in prev_refs if isinstance(ref, dict)}
                for ref in out.get("source_refs") or []:
                    if isinstance(ref, dict) and _source_ref_key(ref) not in seen:
                        prev_refs.append(ref)
                        seen.add(_source_ref_key(ref))
                prev["source_refs"] = prev_refs
                absorb_budget -= 1
                continue
        result.append(out)
    return result


def _first_snippet(
    evidence_rows: list[dict[str, Any]],
    fields: set[str],
    min_words: int = 1,
) -> str:
    item = _first_item(evidence_rows, fields, min_words=min_words)
    if item is None:
        return ""
    return str(item["snippet"])


def _first_item(
    evidence_rows: list[dict[str, Any]],
    fields: set[str],
    min_words: int = 1,
) -> dict[str, Any] | None:
    items = _iter_evidence_items(evidence_rows, fields)
    if not items:
        return None
    for item in items:
        snippet = str(item["snippet"])
        lowered = snippet.lower()
        if "(lore)" in lowered and _word_count(snippet) < 10:
            continue
        if _word_count(snippet) >= min_words:
            return item
    return items[0]


def _finalize_faction_card(
    candidate: FactionCandidate,
    *,
    zone_name: str,
    subregion_tokens: list[str],
    instance_name: str | None = None,
) -> tuple[dict[str, Any] | None, list[str], list[dict[str, Any]]]:
    pools_to_try = finalize_evidence_pools(candidate)
    if not pools_to_try:
        return None, [], []

    for pool in pools_to_try:
        summary, used = synthesize_faction_summary(
            pool,
            faction_name=candidate.name,
            zone_name=zone_name,
            max_words=40,
            subregion_tokens=subregion_tokens,
            instance_name=instance_name,
        )
        summary = ensure_sentence_terminator(summary)
        if not lint_faction_summary(
            summary, zone_name=zone_name, subregion_tokens=subregion_tokens
        ) and not prose_gate_rejects(summary):
            return (
                {
                    "id": candidate.faction_id,
                    "name": candidate.name,
                    "summary": summary,
                    "wiki_url": candidate.wiki_url,
                },
                used,
                pool,
            )
        summary, used = fallback_faction_summary(
            pool,
            zone_name=zone_name,
            subregion_tokens=subregion_tokens,
        )
        summary = ensure_sentence_terminator(summary)
        if not lint_faction_summary(
            summary, zone_name=zone_name, subregion_tokens=subregion_tokens
        ) and not prose_gate_rejects(summary):
            return (
                {
                    "id": candidate.faction_id,
                    "name": candidate.name,
                    "summary": summary,
                    "wiki_url": candidate.wiki_url,
                },
                used,
                pool,
            )
    return None, [], []


def build_major_factions(
    *,
    zone_id: str,
    zone_name: str,
    evidence_rows: list[dict[str, Any]],
    pools: dict[str, list[dict[str, Any]]],
    questline_rows: list[dict[str, Any]],
    revision_map: dict[str, str],
    faction_profile_targets: list[dict[str, Any]] | None = None,
    instance_name: str | None = None,
    extra_subregion_tokens: list[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, str]]]]:
    subregion_tokens = extract_subregion_tokens(
        pools.get("location_seed_pool", []), zone_name=zone_name
    )
    # Extra anchor tokens (e.g. the parent zone + the instance's own notable places) let a faction
    # summary satisfy the zone-anchor lint without naming the instance verbatim — instances carry no
    # location_seed_pool, so without this an instance-native faction whose 40-word summary describes
    # its role but omits the instance name is wrongly dropped (WS-8).
    for token in extra_subregion_tokens or []:
        if token and token not in subregion_tokens:
            subregion_tokens.append(token)
    candidates = collect_faction_candidates(
        zone_id=zone_id,
        evidence_rows=evidence_rows,
        pools=pools,
        faction_profile_targets=faction_profile_targets,
        v3_rows=questline_rows,
    )
    target_count, queue = candidates_for_finalize(
        candidates,
        zone_name=zone_name,
        subregion_tokens=subregion_tokens,
    )
    cards: list[dict[str, Any]] = []
    provenance_map: dict[str, list[dict[str, str]]] = {}
    for candidate in queue:
        if len(cards) >= MAX_FACTION_CARDS:
            break
        card, used, pool = _finalize_faction_card(
            candidate,
            zone_name=zone_name,
            subregion_tokens=subregion_tokens,
            instance_name=instance_name,
        )
        if card is None:
            continue
        cards.append(card)
        pointers = _cap_card_pointers(_pointers_for_source_ids(pool, used, revision_map))
        if pointers:
            provenance_map[str(card["id"])] = pointers
        if target_count and len(cards) >= target_count:
            break
    return cards, provenance_map


def _finalize_location_card(
    candidate: LocationCandidate,
    *,
    zone_name: str,
    location_decision_map: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[str], list[dict[str, Any]]]:
    pools_to_try = finalize_location_evidence_pools(candidate)
    if not pools_to_try:
        return None, [], []
    reason_codes = _decision_reason_codes(candidate.location_id, location_decision_map)

    for pool in pools_to_try:
        summary, used = synthesize_location_summary(
            pool,
            location_name=candidate.name,
            zone_name=zone_name,
            max_words=50,
        )
        summary = ensure_location_sentence_terminator(summary)
        if not lint_location_summary(
            summary, zone_name=zone_name, location_name=candidate.name
        ) and not prose_gate_rejects(summary):
            return (
                _build_location_card_body(
                    candidate,
                    summary=summary,
                    pool=pool,
                    zone_name=zone_name,
                    reason_codes=reason_codes,
                ),
                used,
                pool,
            )
        summary, used = fallback_location_summary(
            pool,
            zone_name=zone_name,
            location_name=candidate.name,
        )
        summary = ensure_location_sentence_terminator(summary)
        if (
            summary
            and not lint_location_summary(
                summary, zone_name=zone_name, location_name=candidate.name
            )
            and not prose_gate_rejects(summary)
        ):
            return (
                _build_location_card_body(
                    candidate,
                    summary=summary,
                    pool=pool,
                    zone_name=zone_name,
                    reason_codes=reason_codes,
                ),
                used,
                pool,
            )
    return None, [], []


def _location_evidence_text(pool: list[dict[str, Any]]) -> str:
    """Concatenate the pool's snippets for deterministic type/significance signal detection."""
    return " ".join(str(item.get("snippet", "")) for item in pool if item.get("snippet"))


def _build_location_card_body(
    candidate: LocationCandidate,
    *,
    summary: str,
    pool: list[dict[str, Any]],
    zone_name: str,
    reason_codes: list[str],
) -> dict[str, Any]:
    # Real place type from the location's own categories + name + evidence (not the routing enum).
    evidence_text = _location_evidence_text(pool)
    location_type = location_type_from_signals(
        candidate.name, evidence_text, candidate.categories
    )
    # Grounded one-sentence significance; never the routing enum (schema requires non-empty).
    significance, _ = synthesize_location_significance(
        pool,
        location_name=candidate.name,
        zone_name=zone_name,
        location_type=location_type,
    )
    significance = ensure_location_sentence_terminator(significance)
    return {
        "id": candidate.location_id,
        "name": candidate.name,
        "summary": summary,
        "wiki_url": candidate.wiki_url,
        "location_type": location_type,
        "significance": significance,
        "decision_reason_codes": reason_codes,
    }


def build_location_cards(
    *,
    zone_id: str,
    zone_name: str,
    location_rows: list[dict[str, Any]],
    location_candidate_map: dict[str, dict[str, Any]],
    location_decision_map: dict[str, dict[str, Any]],
    pools: dict[str, list[dict[str, Any]]],
    revision_map: dict[str, str],
    location_profile_targets: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, str]]]]:
    candidates = collect_location_candidates(
        zone_id=zone_id,
        zone_name=zone_name,
        location_rows=location_rows,
        location_candidate_map=location_candidate_map,
        location_decision_map=location_decision_map,
        pools=pools,
        location_profile_targets=location_profile_targets,
    )
    target_count, queue = location_candidates_for_finalize(candidates)
    cards: list[dict[str, Any]] = []
    provenance_map: dict[str, list[dict[str, str]]] = {}
    for candidate in queue:
        if len(cards) >= MAX_LOCATION_CARDS:
            break
        card_body, used_ids, source_pool = _finalize_location_card(
            candidate,
            zone_name=zone_name,
            location_decision_map=location_decision_map,
        )
        if card_body is None:
            continue
        card = {
            **card_body,
            "zone_id": zone_id,
            "ui_hints": {"render_as": card_body.get("location_type", "major_location")},
            "provenance": [],
        }
        cards.append(card)
        pointers = _cap_card_pointers(_pointers_for_source_ids(source_pool, used_ids, revision_map))
        if pointers:
            provenance_map[candidate.location_id] = pointers
        if len(cards) >= target_count and target_count > 0:
            break
    return cards, provenance_map
