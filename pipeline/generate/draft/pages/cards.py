"""Shared faction/location/history section card finalizers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pipeline.common.text_normalize import clean_wiki_snippet
from pipeline.common.wiki_evidence_filters import cap_history_pool
from pipeline.contracts.models import PAGE_HISTORY_SECTION_BUDGET_RULE
from pipeline.generate.draft import finalize_trace
from pipeline.generate.draft.coverage import (
    build_section_coverage_decisions,
    covered_coverage_ids,
    missing_required_units,
    plan_history_coverage,
    required_event_texts,
    setup_bridge_body,
)
from pipeline.generate.draft.faction_lint import (
    MAX_FACTION_SUMMARY_WORDS,
    ensure_sentence_terminator,
    lint_faction_summary,
)
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
from pipeline.generate.draft.prose_gate import prose_gate_violations
from pipeline.generate.draft.prose_lint import (
    MAX_HISTORY_SECTIONS,
    MIN_HISTORY_SECTIONS,
    lint_history_sections,
    split_sentences,
    word_count,
)
from pipeline.generate.draft.prose_synthesis import (
    FIELD_STATUS_NO_EVIDENCE,
    FIELD_STATUS_OFFLINE_FALLBACK,
    FIELD_STATUS_OK,
    FIELD_STATUS_SYNTHESIS_FAILED,
    SYNTHESIS_MAX_ATTEMPTS,
    llm_synthesis_active,
    passthrough_corpus,
    relabel_history_headings,
    synthesize_faction_summary,
    synthesize_history_sections,
    synthesize_location_summary,
    synthesize_with_validation,
)
from pipeline.generate.draft.temporal import HISTORY_SETUP_BRIDGE

# Per-section history word budget, derived from the same contracts BudgetRule validate
# enforces (Slice 2). The deterministic trim/absorb pass keeps sections inside it, and any
# section it cannot repair becomes a synthesis retry reason via ``_history_budget_reasons``.
_HISTORY_SECTION_MIN_WORDS = PAGE_HISTORY_SECTION_BUDGET_RULE.min_words
_HISTORY_SECTION_MAX_WORDS = PAGE_HISTORY_SECTION_BUDGET_RULE.max_words


def _history_budget_reasons(sections: list[dict[str, Any]]) -> list[str]:
    """Out-of-budget history sections as actionable synthesis retry reasons (Slice 2).

    Runs after the deterministic trim/absorb pass, so a reason here means that pass could
    not repair the section (a sub-floor section whose neighbor is too full to absorb it).
    """
    reasons: list[str] = []
    for index, section in enumerate(sections):
        if not isinstance(section, dict):
            continue
        words = word_count(str(section.get("body", "")))
        if words < _HISTORY_SECTION_MIN_WORDS:
            reasons.append(
                f"history section {index + 1} is {words} words; each section must be "
                f"{_HISTORY_SECTION_MIN_WORDS}-{_HISTORY_SECTION_MAX_WORDS} words — merge it "
                "into an adjacent section or expand it with adjacent evidence"
            )
        elif words > _HISTORY_SECTION_MAX_WORDS:
            reasons.append(
                f"history section {index + 1} is {words} words; each section must be "
                f"{_HISTORY_SECTION_MIN_WORDS}-{_HISTORY_SECTION_MAX_WORDS} words — split it "
                "or condense it"
            )
    return reasons


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


def _consolidate_history_views(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse routed history claim views into one paragraph-sized unit per source paragraph.

    Claim-level routing keeps history spoiler/temporal-safe by filtering individual claims, but it
    leaves the synthesis pool as atomic claim fragments. Multi-section history synthesis needs
    coherent, paragraph-sized material — fed fragments it collapses to empty/sparse output (a
    live-only failure: offline ``NO_LLM`` runs have no claim views and already synthesize from whole
    paragraphs). We group the already-filtered history claim views by ``canonical_evidence_id`` and
    join their claim texts in source order, so the synthesizer sees paragraph-sized, still-filtered
    units WITHOUT re-introducing the outcome/post-active claims routing dropped. Items that are not
    claim views (offline paragraph fallback) pass through unchanged. ``plan_history_coverage`` still
    runs on the raw claim-view pool, so per-claim setup-bridge detection is unaffected.
    """
    result: list[dict[str, Any]] = []
    slot_by_canonical: dict[str, dict[str, Any]] = {}
    for item in items:
        canonical_id = str(item.get("canonical_evidence_id", "")).strip()
        claim_text = clean_wiki_snippet(str(item.get("claim_text", "")))
        is_view = bool(item.get("is_claim_view") or item.get("claim_id") or claim_text)
        if not is_view or not canonical_id:
            result.append(item)
            continue
        slot = slot_by_canonical.get(canonical_id)
        if slot is None:
            # Drop claim-only metadata so the consolidated paragraph carries no internal claim
            # identifiers (``source_refs`` nests a ``claim_id``). Paragraph-level provenance is
            # rebuilt downstream from ``source_id``/``canonical_evidence_id``/``source_url``.
            slot = {
                key: value
                for key, value in item.items()
                if key
                not in {
                    "claim_id",
                    "claim_text",
                    "is_claim_view",
                    "_claim_views",
                    "source_refs",
                    "source_sentence_indexes",
                    "claim_type",
                    "entities",
                }
            }
            slot["_history_texts"] = []
            slot["_history_seen"] = set()
            slot["_history_setup_bridge"] = False
            slot_by_canonical[canonical_id] = slot
            result.append(slot)
        if claim_text and claim_text not in slot["_history_seen"]:
            slot["_history_seen"].add(claim_text)
            sentences = item.get("source_sentence_indexes") or []
            first = (
                sentences[0]
                if isinstance(sentences, list) and sentences and isinstance(sentences[0], int)
                else len(slot["_history_texts"])
            )
            slot["_history_texts"].append((first, claim_text))
        if str(item.get("history_eligibility", "")).strip() == HISTORY_SETUP_BRIDGE:
            slot["_history_setup_bridge"] = True
    for slot in slot_by_canonical.values():
        joined = " ".join(text for _, text in sorted(slot["_history_texts"], key=lambda pair: pair[0]))
        slot["snippet"] = joined or clean_wiki_snippet(str(slot.get("source_excerpt", "")))
        if slot.pop("_history_setup_bridge", False):
            slot["history_eligibility"] = HISTORY_SETUP_BRIDGE
        del slot["_history_texts"]
        del slot["_history_seen"]
    return result


def _draft_history_pool(history_pool: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    max_history = history_section_cap(history_pool)
    if max_history <= 0:
        return [], 0
    return cap_history_pool(history_pool, max_history), max_history


def prepare_history_synthesis_pool(
    raw_history_pool: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Build the capped history *synthesis* pool from the raw routed history pool.

    Claim views are consolidated to paragraph-sized units BEFORE ``select_history_pool`` — whose
    per-item word-count minimum is sized for paragraphs and would otherwise drop every short atomic
    claim view, leaving history empty (a live-only, length-dependent failure that offline NO_LLM
    runs never hit because they synthesize from whole paragraphs). Callers keep the raw claim-view
    pool separately as the coverage pool so claim-level setup-bridge planning still works.
    """
    selected = select_history_pool(_consolidate_history_views(raw_history_pool))
    return _draft_history_pool(selected)


def _finalize_history_sections(
    *,
    history_pool: list[dict[str, Any]],
    evidence_rows: list[dict[str, Any]],
    max_history: int,
    coverage_pool: list[dict[str, Any]] | None = None,
    subject_id: str = "",
    coverage_sink: list[dict[str, Any]] | None = None,
    coverage_pointer_builder: Callable[[dict[str, Any], int], dict[str, str] | None] | None = None,
) -> tuple[list[dict[str, Any]], list[str], str]:
    """History sections: synthesize with validation-driven retries, else explicit failure.

    Live path: the shared synthesis driver retries with concrete lint/copy feedback; if the final
    attempt still fails as a batch, individually-clean LLM sections are salvaged (still LLM prose,
    never a borrow). Below the salvage minimum the field fails explicitly — the verbatim
    ``fallback_history_sections`` / pool borrows are reserved for offline NO_LLM runs.
    Returns ``(sections, used_source_ids, field_status)``.
    """
    if not history_pool:
        return [], [], FIELD_STATUS_NO_EVIDENCE
    section_cap = max_history or MIN_HISTORY_SECTIONS
    lint_cap = max_history or MAX_HISTORY_SECTIONS
    # Source-aware passthrough corpus: reject history bodies that copy their evidence paragraph
    # verbatim (the licensing exposure). None offline, where borrowing source prose is sanctioned.
    pool_snippets = passthrough_corpus(history_pool)
    status = FIELD_STATUS_OK

    def _postprocess(raw_sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return _apply_history_section_budget(_merge_consecutive_history_headings(raw_sections))

    def _batch_reasons(
        candidate_sections: list[dict[str, Any]], *, enforce_budget: bool = True
    ) -> list[str]:
        # Word budget as a retry trigger (Slice 2): validate hard-fails an out-of-budget
        # section, so the live driver must repair it, never ship it. Live-only
        # (``enforce_budget=False`` on the offline ladder): the sanctioned NO_LLM borrow has
        # no retry lever, and a thin wiki paragraph beats an empty history on a smoke run —
        # validate still reports the violation on its artifacts.
        reasons = list(lint_history_sections(candidate_sections, max_sections=lint_cap))
        if enforce_budget:
            reasons.extend(_history_budget_reasons(candidate_sections))
        reasons.extend(_section_gate_reasons(candidate_sections, pool_snippets))
        return reasons

    if llm_synthesis_active():

        def _call(reinforce: str) -> dict[str, Any]:
            raw_sections, used_ids = synthesize_history_sections(
                history_pool, max_sections=section_cap, reinforce=reinforce
            )
            return {"sections": _postprocess(raw_sections), "used": used_ids}

        result = synthesize_with_validation(
            call=_call,
            extract_bodies=lambda payload: [
                str(row.get("body", ""))
                for row in (payload.get("sections") or [])
                if isinstance(row, dict)
            ],
            validate=lambda payload: _batch_reasons(list(payload.get("sections") or [])),
            # The driver's own copy check is redundant with _section_gate_reasons (which is
            # source-aware per section); pass None so copy failures surface as gate reasons.
            source_snippets=None,
            label="history",
        )
        sections = list(result.payload.get("sections") or [])
        used = list(result.payload.get("used") or [])
        outcome = "llm"
        salvaged_count: int | None = None
        if not result.ok:
            # Per-section salvage: keep the individually-clean LLM sections (still synthesized
            # prose) rather than discarding a mostly-good batch over one bad section.
            kept = [
                section
                for section in sections
                if not lint_history_sections([section], max_sections=1)
                and not _history_budget_reasons([section])
                and not _sections_trip_gate([section], pool_snippets)
            ]
            if len(kept) >= MIN_HISTORY_SECTIONS:
                sections = kept[:section_cap]
                used = list(result.payload.get("used") or [])
                salvaged_count = len(sections)
                outcome = "llm_salvaged"
            else:
                sections, used = [], []
                outcome = "failed"
                status = FIELD_STATUS_SYNTHESIS_FAILED
        finalize_trace.record(
            "history.finalize",
            outcome=outcome,
            gate_active=pool_snippets is not None,
            attempts=result.attempts,
            reject_reasons=result.reasons[:8],
            llm_salvaged_count=salvaged_count,
        )
    else:
        # Offline NO_LLM: the deterministic borrow ladder is the sanctioned path.
        sections, used = synthesize_history_sections(history_pool, max_sections=section_cap)
        sections = _postprocess(sections)
        outcome = "no_llm"
        if _batch_reasons(sections, enforce_budget=False):
            kept = [
                section
                for section in sections
                if not lint_history_sections([section], max_sections=1)
            ]
            if len(kept) >= MIN_HISTORY_SECTIONS:
                sections = kept[:section_cap]
                outcome = "no_llm_salvaged"
            else:
                sections, used = fallback_history_sections(history_pool, max_sections=section_cap)
                sections = _postprocess(sections)
                outcome = "no_llm_fallback"
                if _batch_reasons(sections, enforce_budget=False):
                    sections, used = [], []
                    outcome = "rejected"
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
                candidate_sections = _postprocess(kept_sections or pool_sections)
                if not _batch_reasons(candidate_sections, enforce_budget=False):
                    sections = candidate_sections[:section_cap]
                    used = pool_used
                    outcome = "pool"
        status = (
            FIELD_STATUS_OFFLINE_FALLBACK if sections else FIELD_STATUS_SYNTHESIS_FAILED
        )
        finalize_trace.record(
            "history.finalize",
            outcome=outcome if sections else "empty",
            gate_active=False,
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
    if sections and status == FIELD_STATUS_SYNTHESIS_FAILED:
        # Coverage appended a deterministic bridge card to an otherwise-failed history.
        status = FIELD_STATUS_OK if llm_synthesis_active() else FIELD_STATUS_OFFLINE_FALLBACK
    return sections, used, status


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
        # the capped synthesis pool may not contain it at all. Consolidate its claim views to
        # paragraph-sized units first (same reason as the primary synthesis pool), then build the
        # anti-verbatim gate corpus from that same consolidated pool, or a retry body copying a
        # pre-cap-only paragraph would slip past the gate (a licensing exposure).
        coverage_synth_pool = _consolidate_history_views(coverage_pool)
        coverage_snippets = passthrough_corpus(coverage_synth_pool)
        retry_sections, retry_used = synthesize_history_sections(
            coverage_synth_pool,
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
            and not _history_budget_reasons(retry_sections)
            and not _sections_trip_gate(retry_sections, coverage_snippets)
        ):
            retry_covered = covered_coverage_ids(units, retry_used)
            if not missing_required_units(units, retry_covered):
                sections, used = retry_sections, retry_used
                covered = retry_covered
                missing = []
    if missing and pool_snippets is not None:
        # Live-path anti-borrow: a deterministic bridge body is built from claim texts, and
        # sentence-level claims are verbatim source sentences. Never append a bridge card whose
        # body reproduces the source; the gap stays recorded as uncovered in the coverage sink.
        missing = [
            unit
            for unit in missing
            if not _sections_trip_gate(
                [{"heading": "bridge", "body": setup_bridge_body(unit)}], pool_snippets
            )
        ]
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
            # At the hard ceiling: fold the bridge into the last section rather than dropping it,
            # carrying its provenance pointer onto that section so the source is still credited.
            last = dict(sections[-1])
            last_body = str(last.get("body", "")).strip()
            last["body"] = " ".join(part for part in (last_body, body) if part)
            if pointer:
                last_refs = list(last.get("source_refs") or [])
                if pointer not in last_refs:
                    last_refs.append(pointer)
                last["source_refs"] = last_refs
            sections[-1] = last
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
    """Keep every history section inside the shared validate word budget.

    Over-long sections (e.g. several wiki paragraphs merged under one subsection heading)
    are trimmed to whole leading sentences; a section that is still below the floor is
    absorbed into the previous section when the merge stays in budget, otherwise kept
    as-is — where the LLM path turns it into a synthesis retry reason
    (``_history_budget_reasons``) instead of shipping a ``budget.history_section`` hard-fail.
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
    # budget) — e.g. a one-line era blurb folded into the prior era. Absorption may reduce
    # the section count below MIN_HISTORY_SECTIONS: validate's own floor is one section, and
    # shipping a budget-violating section is the worse outcome (Slice 2). Content is never
    # dropped: a short section that can't be absorbed in-budget is kept as-is (and surfaces
    # as a synthesis retry reason via ``_history_budget_reasons`` on the LLM path).
    result: list[dict[str, Any]] = []
    for out in trimmed:
        if result and word_count(str(out["body"])) < _HISTORY_SECTION_MIN_WORDS:
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
    """Faction card: synthesize with validation-driven retries; failure drops the card.

    Live path never borrows a source snippet — a candidate whose summary cannot pass validation
    after retries is dropped (recorded in the finalize trace) rather than shipped as copy. The
    offline NO_LLM ladder keeps the sanctioned deterministic borrow.
    """
    pools_to_try = finalize_evidence_pools(candidate)
    if not pools_to_try:
        return None, [], []

    def _reasons(summary: str, pool_snippets: list[str] | None) -> list[str]:
        reasons = list(
            lint_faction_summary(
                summary,
                zone_name=zone_name,
                subregion_tokens=subregion_tokens,
                faction_name=candidate.name,
            )
        )
        reasons.extend(prose_gate_violations(summary, source_snippets=pool_snippets))
        return reasons

    def _card(summary: str) -> dict[str, Any]:
        return {
            "id": candidate.faction_id,
            "name": candidate.name,
            "summary": summary,
            "wiki_url": candidate.wiki_url,
        }

    live = llm_synthesis_active()
    for pool_index, pool in enumerate(pools_to_try):
        pool_snippets = passthrough_corpus(pool)
        if not live:
            summary, used = synthesize_faction_summary(
                pool,
                faction_name=candidate.name,
                zone_name=zone_name,
                max_words=MAX_FACTION_SUMMARY_WORDS,
                subregion_tokens=subregion_tokens,
                instance_name=instance_name,
            )
            summary = ensure_sentence_terminator(summary)
            if summary and not _reasons(summary, pool_snippets):
                return _card(summary), used, pool
            summary, used = fallback_faction_summary(
                pool,
                zone_name=zone_name,
                subregion_tokens=subregion_tokens,
                faction_name=candidate.name,
            )
            summary = ensure_sentence_terminator(summary)
            if summary and not _reasons(summary, pool_snippets):
                return _card(summary), used, pool
            continue

        def _call(reinforce: str, pool: list[dict[str, Any]] = pool) -> dict[str, Any]:
            summary, used = synthesize_faction_summary(
                pool,
                faction_name=candidate.name,
                zone_name=zone_name,
                max_words=MAX_FACTION_SUMMARY_WORDS,
                subregion_tokens=subregion_tokens,
                instance_name=instance_name,
                reinforce=reinforce,
            )
            return {"text": ensure_sentence_terminator(summary), "used": used}

        def _validate(
            payload: dict[str, Any], snippets: list[str] | None = pool_snippets
        ) -> list[str]:
            return _reasons(str(payload.get("text", "")), snippets)

        result = synthesize_with_validation(
            call=_call,
            extract_bodies=lambda payload: [str(payload.get("text", ""))],
            validate=_validate,
            # Copy detection runs inside _reasons via the source-aware gate.
            source_snippets=None,
            label=f"faction.{candidate.faction_id}",
            # Full retries on the primary pool; a single attempt on each rescue pool.
            max_attempts=SYNTHESIS_MAX_ATTEMPTS if pool_index == 0 else 1,
        )
        if result.ok:
            return (
                _card(str(result.payload.get("text", ""))),
                list(result.payload.get("used", [])),
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

    def _reasons(summary: str, pool_snippets: list[str] | None) -> list[str]:
        reasons = list(
            lint_location_summary(summary, zone_name=zone_name, location_name=candidate.name)
        )
        reasons.extend(prose_gate_violations(summary, source_snippets=pool_snippets))
        return reasons

    def _built(
        summary: str, pool: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        return _build_location_card_body(
            candidate,
            summary=summary,
            pool=pool,
            zone_name=zone_name,
            reason_codes=reason_codes,
        )

    live = llm_synthesis_active()
    for pool_index, pool in enumerate(pools_to_try):
        pool_snippets = passthrough_corpus(pool)
        if not live:
            summary, used = synthesize_location_summary(
                pool,
                location_name=candidate.name,
                zone_name=zone_name,
                max_words=50,
            )
            summary = ensure_location_sentence_terminator(summary)
            if summary and not _reasons(summary, pool_snippets):
                return _built(summary, pool), used, pool
            summary, used = fallback_location_summary(
                pool,
                zone_name=zone_name,
                location_name=candidate.name,
            )
            summary = ensure_location_sentence_terminator(summary)
            if summary and not _reasons(summary, pool_snippets):
                return _built(summary, pool), used, pool
            continue

        def _call(reinforce: str, pool: list[dict[str, Any]] = pool) -> dict[str, Any]:
            summary, used = synthesize_location_summary(
                pool,
                location_name=candidate.name,
                zone_name=zone_name,
                max_words=50,
                reinforce=reinforce,
            )
            return {"text": ensure_location_sentence_terminator(summary), "used": used}

        def _validate(
            payload: dict[str, Any], snippets: list[str] | None = pool_snippets
        ) -> list[str]:
            return _reasons(str(payload.get("text", "")), snippets)

        result = synthesize_with_validation(
            call=_call,
            extract_bodies=lambda payload: [str(payload.get("text", ""))],
            validate=_validate,
            source_snippets=None,
            label=f"location.{candidate.location_id}",
            max_attempts=SYNTHESIS_MAX_ATTEMPTS if pool_index == 0 else 1,
        )
        if result.ok:
            return (
                _built(str(result.payload.get("text", "")), pool),
                list(result.payload.get("used", [])),
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
