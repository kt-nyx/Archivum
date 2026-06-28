"""Shared faction/location/history section card finalizers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pipeline.common.wiki_evidence_filters import cap_history_pool
from pipeline.generate.draft import finalize_trace
from pipeline.generate.draft.coverage import (
    build_section_coverage_decisions,
    covered_coverage_ids,
    missing_required_units,
    plan_history_coverage,
    required_event_texts,
    setup_bridge_body,
)
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
)
from pipeline.generate.draft.prose_gate import prose_gate_rejects, prose_gate_violations
from pipeline.generate.draft.prose_lint import (
    MAX_HISTORY_SECTIONS,
    MIN_HISTORY_SECTIONS,
    lint_history_sections,
    split_sentences,
    word_count,
)
from pipeline.generate.draft.prose_synthesis import (
    passthrough_corpus,
    relabel_history_headings,
    synthesize_faction_summary,
    synthesize_history_sections,
    synthesize_location_summary,
)

# Per-section history word budget enforced by validate (budget.py: 40 <= words <= 110).
# The draft keeps merged/deterministic sections inside it so a run can't hard-fail on
# an over-long merged section or a too-short wiki paragraph.
_HISTORY_SECTION_MIN_WORDS = 40
_HISTORY_SECTION_MAX_WORDS = 110


def _section_gate_reasons(
    sections: list[dict[str, Any]], source_snippets: list[str] | None = None
) -> list[str]:
    """Prose-gate violation reasons across all section bodies (deduped, for diagnostics).

    Pass ``source_snippets`` (the history evidence pool) so a body that is a near-verbatim copy of
    its source paragraph is flagged — otherwise the deterministic history fallback shipped whole
    wiki paragraphs verbatim (the licensing exposure the LLM-synth guard alone did not cover).
    """
    reasons: list[str] = []
    for section in sections:
        if isinstance(section, dict):
            for issue in prose_gate_violations(
                str(section.get("body", "")), source_snippets=source_snippets
            ):
                if issue not in reasons:
                    reasons.append(issue)
    return reasons


def _sections_trip_gate(
    sections: list[dict[str, Any]], source_snippets: list[str] | None = None
) -> bool:
    """True when any history section body fails the deterministic prose gate."""
    return bool(_section_gate_reasons(sections, source_snippets))


def _history_sections_from_pool(
    history_pool: list[dict[str, Any]],
    *,
    evidence_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    pool = history_pool
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
    coverage_pool: list[dict[str, Any]] | None = None,
    subject_id: str = "",
    coverage_sink: list[dict[str, Any]] | None = None,
    coverage_pointer_builder: Callable[[dict[str, Any], int], dict[str, str] | None] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    section_cap = max_history or MIN_HISTORY_SECTIONS
    lint_cap = max_history or MAX_HISTORY_SECTIONS
    # Source-aware passthrough corpus: reject history bodies that copy their evidence paragraph
    # verbatim, from the LLM synth or either deterministic fallback (the licensing exposure). Active
    # only in a live LLM run (None offline, where borrowing source prose is the accepted fallback).
    pool_snippets = passthrough_corpus(history_pool)
    sections, used = synthesize_history_sections(history_pool, max_sections=section_cap)
    sections = _apply_history_section_budget(_merge_consecutive_history_headings(sections))
    # Capture why each stage is (or is not) accepted so an empty history is attributable.
    synth_count = len(sections)
    synth_lint = lint_history_sections(sections, max_sections=lint_cap)
    synth_gate = _section_gate_reasons(sections, pool_snippets)
    outcome = "llm"
    salvaged_count: int | None = None
    fallback_count: int | None = None
    fallback_lint: list[str] = []
    fallback_gate: list[str] = []
    pool_count: int | None = None
    if synth_lint or synth_gate:
        # Per-section salvage: a single failing section must not discard the whole clean LLM batch
        # and force the verbatim deterministic fallback (which the gate then rejects → empty). Keep
        # the sections that individually pass BOTH lint and the source-aware prose gate — so a
        # verbatim section is still dropped, preserving the anti-verbatim guarantee — and only fall
        # to the deterministic fallback when fewer than the minimum survive. Mirrors the pool path.
        kept = [
            section
            for section in sections
            if not lint_history_sections([section], max_sections=1)
            and not _sections_trip_gate([section], pool_snippets)
        ]
        if len(kept) >= MIN_HISTORY_SECTIONS:
            sections = kept[:section_cap]
            salvaged_count = len(sections)
            outcome = "llm_salvaged"
        else:
            sections, used = fallback_history_sections(history_pool, max_sections=section_cap)
            sections = _apply_history_section_budget(_merge_consecutive_history_headings(sections))
            fallback_count = len(sections)
            fallback_lint = lint_history_sections(sections, max_sections=lint_cap)
            fallback_gate = _section_gate_reasons(sections, pool_snippets)
            if fallback_lint or fallback_gate:
                sections, used = [], []
                outcome = "rejected"
            else:
                outcome = "deterministic_fallback"
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
            if not lint_history_sections(
                candidate_sections, max_sections=lint_cap
            ) and not _sections_trip_gate(candidate_sections, pool_snippets):
                sections = candidate_sections[:section_cap]
                used = pool_used
                pool_count = len(sections)
                outcome = "pool"
    if not sections:
        outcome = "empty"
    finalize_trace.record(
        "history.finalize",
        outcome=outcome,
        gate_active=pool_snippets is not None,
        llm_section_count=synth_count,
        llm_lint=synth_lint,
        llm_gate=synth_gate,
        llm_salvaged_count=salvaged_count,
        fallback_section_count=fallback_count,
        fallback_lint=fallback_lint,
        fallback_gate=fallback_gate,
        pool_section_count=pool_count,
    )
    # Re-title bare era/TOC headings ("World of Warcraft", "Cataclysm") with thematic, body-derived
    # titles. Runs whichever path produced the bodies, so wiki-fallback sections still get LLM
    # headings; offline this is a no-op (deterministic label is kept).
    sections = relabel_history_headings(sections)
    sections, used = _apply_history_coverage(
        sections,
        used,
        coverage_pool=coverage_pool if coverage_pool is not None else history_pool,
        pool_snippets=pool_snippets,
        section_cap=section_cap,
        lint_cap=lint_cap,
        subject_id=subject_id,
        coverage_sink=coverage_sink,
        pointer_builder=coverage_pointer_builder,
    )
    return sections, used


def _apply_history_coverage(
    sections: list[dict[str, Any]],
    used: list[str],
    *,
    coverage_pool: list[dict[str, Any]],
    pool_snippets: list[str] | None,
    section_cap: int,
    lint_cap: int,
    subject_id: str,
    coverage_sink: list[dict[str, Any]] | None,
    pointer_builder: Callable[[dict[str, Any], int], dict[str, str] | None] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Guarantee eligible setup-bridge claims survive into final history (Slice 7).

    Coverage planning is claim-level only: ``plan_history_coverage`` returns no units for a
    paragraph-only pool, so the legacy path is untouched. When a required setup-bridge unit is
    dropped, a live run first retries synthesis with explicit bridge hints; if that still omits the
    unit (or offline, where the retry is a no-op), a concise deterministic bridge card is appended.
    """
    units = plan_history_coverage(coverage_pool)
    if not units:
        return sections, used
    covered = covered_coverage_ids(units, used)
    missing = missing_required_units(units, covered)
    appended_ids: set[str] = set()
    if missing and pool_snippets is not None:
        # Retry from the pre-cap coverage pool so the dropped setup-bridge source is in evidence;
        # the capped synthesis pool may not contain it at all.
        retry_sections, retry_used = synthesize_history_sections(
            coverage_pool,
            max_sections=section_cap,
            required_event_texts=required_event_texts(missing),
        )
        retry_sections = _apply_history_section_budget(
            _merge_consecutive_history_headings(retry_sections)
        )
        retry_sections = relabel_history_headings(retry_sections)
        if (
            retry_sections
            and not lint_history_sections(retry_sections, max_sections=lint_cap)
            and not _sections_trip_gate(retry_sections, pool_snippets)
        ):
            retry_covered = covered_coverage_ids(units, retry_used)
            if not missing_required_units(units, retry_covered):
                sections, used = retry_sections, retry_used
                covered = retry_covered
                missing = []
    if missing:
        sections, used, appended_ids = _append_setup_bridge_cards(
            sections, used, missing, pointer_builder=pointer_builder
        )
        covered = covered_coverage_ids(units, used)
    if appended_ids:
        finalize_trace.record(
            "history.coverage",
            subject_id=subject_id,
            required=sum(1 for unit in units if unit["required"]),
            appended=len(appended_ids),
        )
    if coverage_sink is not None:
        coverage_sink.extend(
            build_section_coverage_decisions(subject_id, units, covered, appended_ids)
        )
    return sections, used


def _append_setup_bridge_cards(
    sections: list[dict[str, Any]],
    used: list[str],
    missing: list[dict[str, Any]],
    *,
    pointer_builder: Callable[[dict[str, Any], int], dict[str, str] | None] | None = None,
) -> tuple[list[dict[str, Any]], list[str], set[str]]:
    """Append concise setup-bridge cards for required units missing from synthesis.

    The cap may merge a bridge into the previous section (``_apply_history_section_budget`` absorbs
    a sub-floor card), but the cap never justifies dropping a required setup bridge: the hard
    ``MAX_HISTORY_SECTIONS`` ceiling is only exceeded long enough for the budget pass to fold the
    card into adjacent context. Provenance stays on the source paragraph: ``used`` carries the
    source id, and (when a ``pointer_builder`` is supplied) the bridge card gets an explicit
    ``source_refs`` pointer so the positional ref attachment downstream does not mis-credit it.
    """
    appended_ids: set[str] = set()
    sections = list(sections)
    used = list(used)
    for unit in missing:
        body = setup_bridge_body(unit)
        if not body:
            continue
        pointer = None
        representative = unit.get("representative_item")
        if pointer_builder is not None and isinstance(representative, dict):
            pointer = pointer_builder(representative, len(sections) + 1)
        if len(sections) < MAX_HISTORY_SECTIONS or not sections:
            sections.append(
                {
                    "heading": unit["suggested_heading"],
                    "body": body,
                    "source_refs": [pointer] if pointer else [],
                }
            )
        else:
            # At the hard ceiling: fold the bridge into the last section rather than dropping it.
            last = sections[-1]
            last_body = str(last.get("body", "")).strip()
            last["body"] = " ".join(part for part in (last_body, body) if part)
        if unit["source_id"]:
            used.append(unit["source_id"])
        appended_ids.add(unit["coverage_id"])
    if not appended_ids:
        return sections, used, appended_ids
    sections = _apply_history_section_budget(_merge_consecutive_history_headings(sections))
    return sections, used, appended_ids


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
            faction_name=candidate.name,
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
        if not pointers:
            # The summary's reported used-ids resolved to no pointer — either none were
            # reported, or they reference a related-lore source absent from the page's
            # revision_map (e.g. a deterministic fallback that borrowed a snippet from a linked
            # "abomination" page). Fall back to any pool item the card was synthesized from whose
            # source *is* resolvable, so an emitted card always carries >=1 provenance pointer —
            # the release gate hard-fails (provenance.missing_card_pointers) without one.
            pool_source_ids = [
                str(item.get("source_id", ""))
                for item in pool
                if str(item.get("source_id", "")).strip()
            ]
            pointers = _cap_card_pointers(
                _pointers_for_source_ids(pool, pool_source_ids, revision_map)
            )
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
    significance_tag = candidate.significance_tag or "major_location"
    return {
        "id": candidate.location_id,
        "name": candidate.name,
        "summary": summary,
        "wiki_url": candidate.wiki_url,
        "location_type": location_type,
        "significance_tag": significance_tag,
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
