"""Constrained LLM prose synthesis workers for draft page assembly."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pipeline.ai.config import load_ai_settings
from pipeline.common.section_registry import is_generic_history_heading
from pipeline.common.text_normalize import clean_wiki_snippet
from pipeline.contracts.models import (
    INSTANCE_BUDGET_RULES,
    ZONE_PAGE_BUDGET_RULES,
    LocationType,
)
from pipeline.generate.draft import finalize_trace
from pipeline.generate.draft.card_lint import finalize_cta_hook
from pipeline.generate.draft.compendium_voice import (
    AT_A_GLANCE_VOICE,
    COMPENDIUM_VOICE_CORE,
    CURRENTLY_VOICE,
    HISTORY_VOICE,
    INSTANCE_AT_A_GLANCE_VOICE,
    INSTANCE_FACTION_VOICE,
    INSTANCE_OVERVIEW_VOICE,
    KEY_CHARACTER_VOICE,
    QUESTLINE_CTA_VOICE,
    instance_system_prompt,
    zone_system_prompt,
)
from pipeline.generate.draft.evidence_identity import (
    evidence_id_for_item,
    translate_used_evidence_ids,
)
from pipeline.generate.draft.faction_lint import (
    MAX_FACTION_SUMMARY_WORDS,
    strip_faction_label_prefix,
    trim_faction_summary,
)
from pipeline.generate.draft.llm import llm_json_with_retry
from pipeline.generate.draft.prose_election import (
    history_heading_from_role,
    precompress_at_a_glance_evidence,
)
from pipeline.generate.draft.prose_gate import detect_source_passthrough
from pipeline.generate.draft.prose_lint import (
    MAX_AT_A_GLANCE_WORDS,
    MAX_HISTORY_SECTIONS,
    has_present_state_framing,
    past_marker_score,
    trim_words,
    word_count,
)


def _snippet_rank_key(row: dict[str, Any]) -> tuple[int, int]:
    snippet = str(row.get("snippet", ""))
    return past_marker_score(snippet), word_count(snippet)


def _present_state_rank_key(row: dict[str, Any]) -> tuple[int, int]:
    """Rank key for the at_a_glance identity caption: prefer present-state framing, then length."""
    snippet = str(row.get("snippet", ""))
    return int(has_present_state_framing(snippet)), word_count(snippet)


# A key-character card draws on a curated per-figure profile pool, so it gets a larger evidence
# window than the default short fields. The default 8 starved rich figures (Lilian Voss routed 27
# safe claim views): the cap fell before the motivation that explains the figure's presence, leaving
# the model to pad with atmosphere. Pairs with the presence-first ordering in key_characters.py so
# the kept window holds the claims that matter.
KEY_CHARACTER_EVIDENCE_ITEM_LIMIT = 14

# Upper bound on beats shown to the salience ranker, so its prompt stays small on figures with a
# large route-safe pool (Lilian Voss routes dozens of atomized biography claims). The deterministic
# era-balanced selection trims to this before the LLM ranks within it.
KEY_CHARACTER_RANKER_INPUT_LIMIT = 28


def _wiki_first_no_llm() -> bool:
    return os.environ.get("WOW_LORE_WIKI_FIRST_NO_LLM", "").lower() in {"1", "true", "yes"}


def select_salient_key_character_beats_llm(
    items: list[dict[str, Any]],
    *,
    boss_name: str,
    instance_name: str,
    limit: int = KEY_CHARACTER_EVIDENCE_ITEM_LIMIT,
    reference_arc: str = "",
) -> list[dict[str, Any]] | None:
    """Pick the most significant biography beats to fit the evidence budget (option B).

    Wiki biographies atomize into many valid-but-uneven micro-claims. Rather than let a mechanical
    cap keep whichever beats sort first, this asks the model to select the beats that most define who
    the character is and why they are present here, dropping low-significance detail (minor
    acquaintances, training minutiae, one-off errands). It only *selects* from the already
    route-filtered pool — it introduces no new evidence and cannot resurface filtered content.

    ``reference_arc`` (the Adventure Guide blurb) names the arc points the game itself treats as
    defining; when present it steers the ranker toward beats that develop those points, but it is
    only a salience hint — it never enters the kept beats or the card text.

    Returns the selected subset (same dict objects; the caller orders them), or ``None`` when the LLM
    is unavailable, errors, or the pool already fits — so the caller falls back to deterministic
    selection. Paragraph-fallback pools (no claim views) also return ``None``.
    """
    claim_views = [item for item in items if isinstance(item, dict) and item.get("is_claim_view")]
    if limit <= 0 or len(items) <= limit or not claim_views:
        return None
    settings = load_ai_settings()
    if not settings.openai_ready or _wiki_first_no_llm():
        return None

    indexed = list(enumerate(items))
    beat_lines = "\n".join(
        f"[{index}] ({view.get('raw_section_role') or view.get('section_role') or 'unknown'}) "
        f"{clean_wiki_snippet(str(view.get('claim_text') or view.get('snippet', '')))}"
        for index, view in indexed
    )
    system_prompt = (
        "You curate a compact lore-compendium card for a single character a player is about "
        "to encounter in a World of Warcraft dungeon or raid. From the numbered biography "
        "beats, select the MOST significant ones that together convey who this character is "
        "and why they are present here, within a tight word budget.\n"
        "Keep: origin and defining nature; pivotal transformations (death, being raised, "
        "corruption, redemption); core motivation and allegiance; the turning points of "
        "their arc; and the beat that explains their presence in this place.\n"
        "Drop: minor acquaintances, routine training or study details, one-off errands, "
        "incidental appearances, and granular play-by-play that does not change who they "
        "are.\n"
        "Prefer coverage of the whole arc over many beats from a single period. Return only "
        f"the ids to keep, most important first, at most {limit}."
    )
    user_prompt = f"Character: {boss_name}\nInstance: {instance_name}\n\nBeats:\n{beat_lines}"
    if reference_arc.strip():
        user_prompt += (
            "\n\nThe game's own account emphasizes these arc points (use only to judge which beats "
            f"matter; do not add them as beats):\n{reference_arc.strip()}"
        )
    try:
        result = llm_json_with_retry(
            required_keys=("keep_ids",),
            response_json_schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["keep_ids"],
                "properties": {
                    "keep_ids": {"type": "array", "items": {"type": "integer"}},
                },
            },
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_schema_name="wiki_first_key_character_beats",
            substep="wiki_first_key_character_beats",
        )
    except Exception:  # pragma: no cover - provider failures fall back to deterministic selection
        return None

    keep_ids: list[int] = []
    for value in result.get("keep_ids", []):
        try:
            keep_ids.append(int(value))
        except (TypeError, ValueError):
            continue
    valid = {index for index, _ in indexed}
    # Dedupe valid ids, preserving the model's importance order, then cap to the budget.
    keep_set: set[int] = set()
    for index in keep_ids:
        if index in valid and index not in keep_set:
            keep_set.add(index)
            if len(keep_set) >= limit:
                break
    if not keep_set:
        return None
    return [item for index, item in indexed if index in keep_set]


def _format_evidence_block(
    items: list[dict[str, Any]], *, max_items: int = 8
) -> tuple[str, dict[str, str]]:
    """Format an evidence pool for a synthesis prompt (Slice 7: paragraph-unique labels).

    Each emitted line is labeled with a short paragraph alias (``[p1]``, ``[p2]``, …), so the
    model's ``used_evidence_ids`` cite *paragraphs* — every paragraph of a wiki page shares one
    ``source_id``, which made source-labeled citations indistinguishable. Returns the block text
    plus the translation map for :func:`translate_used_evidence_ids`: each alias maps to its
    item's paragraph-level evidence id (``canonical_evidence_id``, or ``source_id`` for synthetic
    one-per-source items), the items' own ids map to themselves, and a ``source_id`` shared by
    several emitted paragraphs is omitted because it no longer identifies one.

    When a claim view carries ``_route_safe_excerpt`` (Fix 1), the atomized claims of a source
    paragraph are collapsed into that one coherent, spoiler-filtered excerpt — so the model reads
    connected prose instead of fragments, and ``max_items`` then counts paragraphs, not fragments.
    Items without a reconstructed excerpt (offline/paragraph pools) format one line each as before.
    """
    lines: list[str] = []
    alias_map: dict[str, str] = {}
    evidence_ids_by_source: dict[str, set[str]] = {}
    seen_paragraphs: set[str] = set()
    for item in items:
        if len(lines) >= max_items:
            break
        canonical_id = str(item.get("canonical_evidence_id", "")).strip()
        route_excerpt = str(item.get("_route_safe_excerpt", "")).strip()
        if route_excerpt and canonical_id:
            if canonical_id in seen_paragraphs:
                continue
            seen_paragraphs.add(canonical_id)
            snippet = clean_wiki_snippet(route_excerpt)
        else:
            snippet = clean_wiki_snippet(str(item.get("snippet", "")))
        if not snippet:
            continue
        alias = f"p{len(lines) + 1}"
        evidence_id = evidence_id_for_item(item)
        alias_map[alias] = evidence_id
        if evidence_id:
            alias_map.setdefault(evidence_id, evidence_id)
            source_id = str(item.get("source_id", "")).strip()
            if source_id:
                evidence_ids_by_source.setdefault(source_id, set()).add(evidence_id)
        lines.append(f"[{alias}] {snippet}")
    # A bare source id still translates when it names exactly one emitted paragraph (offline
    # fallbacks and older mocks cite source ids); an ambiguous one is dropped — it does not
    # identify a paragraph, and guessing would fabricate provenance.
    for source_id, evidence_ids in evidence_ids_by_source.items():
        if len(evidence_ids) == 1:
            alias_map.setdefault(source_id, next(iter(evidence_ids)))
    return "\n".join(lines), alias_map


# Appended to a synthesis task on the *retry* after the first attempt reproduced source runs.
# The base prompts already say "never copy source phrasing"; the model still copies under the
# "from evidence only" pressure, so the retry escalates with a concrete word-run constraint.
PARAPHRASE_REINFORCE = (
    " Your previous attempt reproduced the evidence too closely. Rewrite it completely in your "
    "own words: change the sentence structure and wording so that no run of five or more "
    "consecutive words matches the evidence. Preserve only the facts, names, and chronology."
)


def lint_reinforce(reasons: list[str]) -> str:
    """Corrective feedback appended to a synthesis retry after the first attempt failed editorial lint.

    Mirrors :data:`PARAPHRASE_REINFORCE` for copying: the base prompt already states the rule (e.g.
    `HISTORY_VOICE` says "Past tense only"), but the model occasionally slips on a section, so the
    retry feeds the *specific* failed checks back. Generic across zones — it echoes the lint reasons
    and a tense directive, never zone vocabulary.
    """
    if not reasons:
        return ""
    joined = "; ".join(reasons[:6])
    return (
        " Your previous attempt failed these editorial checks: "
        f"{joined}. Rewrite so every section passes them — in particular, narrate all historical "
        "events in the past tense, never the present, and keep the sections that were already fine."
    )


def _evidence_snippets(items: list[dict[str, Any]]) -> list[str]:
    """Cleaned source snippets used as the anti-verbatim comparison corpus."""
    return [
        snippet
        for item in items
        if (snippet := clean_wiki_snippet(str(item.get("snippet", ""))))
    ]


def llm_synthesis_active() -> bool:
    """True when a real LLM run is in effect (OpenAI ready and not forced offline).

    The anti-verbatim passthrough gate keys off this: a live LLM run *can* paraphrase, so copying
    source text is a licensing exposure that must gate-fail. An offline/`WOW_LORE_WIKI_FIRST_NO_LLM`
    run has no LLM to paraphrase, so the deterministic fallbacks legitimately borrow source prose and
    the gate must stay disabled (else every offline page would fail).
    """
    settings = load_ai_settings()
    if os.environ.get("WOW_LORE_WIKI_FIRST_NO_LLM", "").lower() in {"1", "true", "yes"}:
        return False
    return bool(getattr(settings, "openai_ready", False))


def passthrough_corpus(items: list[dict[str, Any]]) -> list[str] | None:
    """Source snippets for the finalize-level anti-verbatim gate, or ``None`` when inactive.

    Returns the evidence snippets only in a live LLM run (see :func:`llm_synthesis_active`); offline
    it returns ``None`` so callers pass no corpus and the passthrough check is skipped.
    """
    if not llm_synthesis_active():
        return None
    return [str(item.get("snippet", "")) for item in items]


# One initial synthesis attempt + up to two corrective retries. This is the single owner of
# "how many content-level attempts a prose field gets" (JSON/schema retries live inside
# ``llm_json_with_retry`` per call). Bounded so a stubborn field costs at most 3 LLM calls.
SYNTHESIS_MAX_ATTEMPTS = 3

# Failure-status vocabulary for the per-field ``field_status`` map on draft pages.
FIELD_STATUS_OK = "ok"
FIELD_STATUS_SYNTHESIS_FAILED = "synthesis_failed"
FIELD_STATUS_NO_EVIDENCE = "no_evidence"
FIELD_STATUS_OFFLINE_FALLBACK = "offline_fallback"

_COPY_REASON = "near-verbatim copy of source evidence"
_EMPTY_REASON = "empty synthesis output"


@dataclass(frozen=True)
class SynthesisAttemptResult:
    """Outcome of the shared synthesize→validate→retry loop.

    ``payload`` is the best attempt's raw payload even on failure, so field-specific salvage
    (e.g. keeping individually-clean history sections) can inspect it. ``reasons`` are the best
    attempt's outstanding validation failures (empty when ``ok``). ``last_payload`` and
    ``last_reasons`` preserve the final rejected attempt for audit records that need to show what
    actually exhausted the retry budget. ``soft_reasons`` are the accepted attempt's outstanding
    *soft* failures (Slice 7 citation shortfall): they triggered retries but never fail a field,
    so an ``ok`` result may still carry them for the caller's decision record.
    """

    ok: bool
    payload: dict[str, Any]
    reasons: list[str]
    attempts: int
    last_payload: dict[str, Any] = field(default_factory=dict)
    last_reasons: list[str] = field(default_factory=list)
    soft_reasons: list[str] = field(default_factory=list)


def synthesize_with_validation(
    *,
    call: Callable[[str], dict[str, Any]],
    extract_bodies: Callable[[dict[str, Any]], list[str]],
    validate: Callable[[dict[str, Any]], list[str]] | None = None,
    validate_soft: Callable[[dict[str, Any]], list[str]] | None = None,
    source_snippets: list[str] | None = None,
    label: str = "",
    max_attempts: int = SYNTHESIS_MAX_ATTEMPTS,
) -> SynthesisAttemptResult:
    """Shared synthesis contract: synthesize → validate → re-prompt with reasons → explicit failure.

    ``call(reinforce)`` runs one synthesis attempt ("" for the first); each retry's ``reinforce``
    carries the previous attempt's concrete failure reasons (:data:`PARAPHRASE_REINFORCE` for
    copying, :func:`lint_reinforce` for editorial failures). An attempt passes only when it is
    non-empty, copies nothing from ``source_snippets`` (contiguous-run check via
    :func:`detect_source_passthrough`; pass ``None`` to disable, e.g. offline), and ``validate``
    returns no reasons.

    ``validate_soft`` reasons (Slice 7: the citation shortfall) trigger retries like hard reasons
    but never fail the field: if retries exhaust with an attempt that is hard-clean but still
    soft-flagged, that attempt is returned ``ok`` with ``soft_reasons`` set and the shortfall
    recorded in the synth_guard trace — the real (short) result ships; nothing is fabricated to
    satisfy the check.

    On exhaustion of hard reasons this returns an explicit failure — it never borrows source prose
    or substitutes a template. Callers map failure to the page's ``field_status`` sentinel (the
    field becomes ``null``); the deterministic borrow paths are reserved for offline NO_LLM runs
    where no LLM exists to paraphrase.
    """

    def _reasons_for(payload: dict[str, Any]) -> tuple[list[str], bool]:
        bodies = [body for body in extract_bodies(payload)]
        reasons: list[str] = []
        copied = False
        if not any(str(body).strip() for body in bodies):
            reasons.append(_EMPTY_REASON)
        elif source_snippets:
            copied = any(
                body and detect_source_passthrough(body, source_snippets) for body in bodies
            )
            if copied:
                reasons.append(_COPY_REASON)
        if validate is not None:
            reasons.extend(validate(payload))
        return reasons, copied

    best_payload: dict[str, Any] = {}
    best_reasons: list[str] | None = None
    acceptable_payload: dict[str, Any] | None = None
    acceptable_soft: list[str] = []
    last_payload: dict[str, Any] = {}
    last_reasons: list[str] = []
    feedback = ""
    attempts = 0
    for attempt in range(1, max(1, max_attempts) + 1):
        attempts = attempt
        payload = call(feedback)
        reasons, copied = _reasons_for(payload)
        soft_reasons = list(validate_soft(payload)) if validate_soft is not None else []
        last_payload, last_reasons = payload, reasons + soft_reasons
        if not reasons and not soft_reasons:
            finalize_trace.record(
                f"{label}.synth_guard",
                outcome="ok",
                attempts=attempt,
            )
            return SynthesisAttemptResult(True, payload, [], attempt, payload, [])
        if not reasons:
            # Hard-clean but soft-flagged: keep the best such attempt (fewest soft reasons) and
            # retry for a fully-clean one; on exhaustion it ships with the shortfall recorded.
            if acceptable_payload is None or len(soft_reasons) < len(acceptable_soft):
                acceptable_payload, acceptable_soft = payload, soft_reasons
        elif best_reasons is None or len(reasons) < len(best_reasons):
            best_payload, best_reasons = payload, reasons
        feedback = ""
        if copied:
            feedback += PARAPHRASE_REINFORCE
        lint_only = [reason for reason in reasons if reason != _COPY_REASON] + soft_reasons
        if lint_only:
            feedback += lint_reinforce(lint_only)
    if acceptable_payload is not None:
        finalize_trace.record(
            f"{label}.synth_guard",
            outcome="ok_soft",
            attempts=attempts,
            soft_reasons=acceptable_soft[:8],
        )
        return SynthesisAttemptResult(
            True,
            acceptable_payload,
            [],
            attempts,
            last_payload,
            last_reasons,
            acceptable_soft,
        )
    finalize_trace.record(
        f"{label}.synth_guard",
        outcome="failed",
        attempts=attempts,
        reasons=(best_reasons or [])[:8],
    )
    return SynthesisAttemptResult(
        False,
        best_payload,
        best_reasons or [],
        attempts,
        last_payload,
        last_reasons,
    )


def synthesize_at_a_glance(
    items: list[dict[str, Any]],
    *,
    max_words: int = MAX_AT_A_GLANCE_WORDS,
    subject: str | None = None,
    reference_framing: str = "",
    reinforce: str = "",
) -> tuple[str, list[str]]:
    if not items:
        return "", []
    prepared = precompress_at_a_glance_evidence(items)
    settings = load_ai_settings()
    if not settings.openai_ready or os.environ.get("WOW_LORE_WIKI_FIRST_NO_LLM", "").lower() in {
        "1",
        "true",
        "yes",
    }:
        best = max(prepared, key=_present_state_rank_key)
        return trim_words(clean_wiki_snippet(str(best.get("snippet", ""))), max_words), [
            str(best.get("source_id", ""))
        ]
    if subject:
        system_prompt = instance_system_prompt(
            field_voice=INSTANCE_AT_A_GLANCE_VOICE,
            task_lines=(
                f"Write a punchy, direct at-a-glance caption for instance '{subject}' using ONLY the "
                f"evidence snippets. Maximum {max_words} words, in one or two short sentences with "
                "plain, concrete language and few adjectives. Name what the place is and why it "
                "matters; do not list bosses, factions, or wings. No extrapolation."
            )
            + reinforce,
        )
    else:
        system_prompt = zone_system_prompt(
            field_voice=AT_A_GLANCE_VOICE,
            task_lines=(
                f"Write a punchy, direct at-a-glance caption using ONLY the evidence snippets. "
                f"Maximum {max_words} words, in one or two short sentences. Capture the zone's "
                "atmosphere and vibe — what it feels like to stand here — with plain, concrete "
                "language and few adjectives, not a report of current events. Do NOT name factions, "
                "leaders, or characters, do NOT say who holds or contests the zone, and do NOT list "
                "towns, keeps, or landmarks; that detail belongs in other fields. You may reference "
                "the force whose legacy haunts the land (e.g. 'the Hollow Court') only as atmosphere, "
                "never as an actor acting now. No patch/reputation meta. No extrapolation."
            )
            + reinforce,
        )
    evidence_block, alias_map = _format_evidence_block(prepared, max_items=12)
    at_a_glance_user_prompt = f"Evidence:\n{evidence_block}"
    if subject and reference_framing.strip():
        # Tone reference only (the game's intro for this place); never copied, and the voice already
        # bars naming factions/leaders here, so it informs register, not content.
        at_a_glance_user_prompt += (
            "\n\nReference (tone only — do not copy or name any factions/characters from it):\n"
            f"{reference_framing.strip()}"
        )
    result = llm_json_with_retry(
        required_keys=("summary", "used_evidence_ids"),
        response_json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["summary", "used_evidence_ids"],
            "properties": {
                "summary": {"type": "string"},
                "used_evidence_ids": {"type": "array", "items": {"type": "string"}},
            },
        },
        system_prompt=system_prompt,
        user_prompt=at_a_glance_user_prompt,
        response_schema_name="wiki_first_at_a_glance",
        substep="wiki_first_at_a_glance",
    )
    summary = trim_words(clean_wiki_snippet(str(result.get("summary", ""))), max_words)
    used = translate_used_evidence_ids(result.get("used_evidence_ids", []), alias_map)
    # Empty result = failed attempt; the finalize-level synthesis driver retries or fails
    # explicitly. Never borrow a source snippet on the live path.
    return summary, used


def synthesize_currently(
    items: list[dict[str, Any]],
    *,
    max_words: int = ZONE_PAGE_BUDGET_RULES["currently"].max_words,
    reinforce: str = "",
) -> tuple[str, list[str]]:
    if not items:
        return "", []
    settings = load_ai_settings()
    if not settings.openai_ready or os.environ.get("WOW_LORE_WIKI_FIRST_NO_LLM", "").lower() in {
        "1",
        "true",
        "yes",
    }:
        best = max(items, key=lambda row: word_count(str(row.get("snippet", ""))))
        return trim_words(clean_wiki_snippet(str(best.get("snippet", ""))), max_words), [
            str(best.get("source_id", ""))
        ]
    evidence_block, alias_map = _format_evidence_block(items)
    result = llm_json_with_retry(
        required_keys=("summary", "used_evidence_ids"),
        response_json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["summary", "used_evidence_ids"],
            "properties": {
                "summary": {"type": "string"},
                "used_evidence_ids": {"type": "array", "items": {"type": "string"}},
            },
        },
        system_prompt=zone_system_prompt(
            field_voice=CURRENTLY_VOICE,
            task_lines=(
                f"Write a 'currently' zone summary using ONLY evidence snippets. "
                f"Maximum {max_words} words. Describe active conflict or state. "
                "Name the precise faction or actor the evidence specifies (e.g. 'the Emberwake "
                "Pact', not the generic 'Horde'; 'the Hollow Court', not 'cultists'). "
                "Do not write quest walkthrough steps, reputation/achievement meta, adjacent-zone geography hubs, "
                "or out-of-universe player instructions."
            )
            + reinforce,
        ),
        user_prompt=f"Evidence:\n{evidence_block}",
        response_schema_name="wiki_first_currently",
        substep="wiki_first_currently",
    )
    summary = trim_words(clean_wiki_snippet(str(result.get("summary", ""))), max_words)
    used = translate_used_evidence_ids(result.get("used_evidence_ids", []), alias_map)
    # Empty result = failed attempt; the finalize-level driver retries or fails explicitly.
    return summary, used


def synthesize_history_sections(
    items: list[dict[str, Any]],
    *,
    max_sections: int = MAX_HISTORY_SECTIONS,
    required_event_texts: list[str] | None = None,
    reinforce: str = "",
) -> tuple[list[dict[str, Any]], list[str]]:
    if not items:
        return [], []
    settings = load_ai_settings()
    if not settings.openai_ready or os.environ.get("WOW_LORE_WIKI_FIRST_NO_LLM", "").lower() in {
        "1",
        "true",
        "yes",
    }:
        finalize_trace.record("history.synth", path="no_llm")
        sections: list[dict[str, Any]] = []
        used: list[str] = []
        for item in items[:max_sections]:
            snippet = clean_wiki_snippet(str(item.get("snippet", "")))
            if not snippet:
                continue
            heading = history_heading_from_role(
                str(item.get("section_role", "other")),
                str(item.get("raw_section_role", "")),
            )
            sections.append({"heading": heading, "body": snippet, "source_refs": []})
            # Paragraph-level identity so offline coverage bookkeeping matches the live path.
            evidence_id = evidence_id_for_item(item)
            if evidence_id:
                used.append(evidence_id)
        return sections, used
    history_task = (
        "Produce chronological historical arc sections from evidence only. "
        f"Up to {max_sections} sections. "
        "Each heading must be a short (2–5 word) thematic title that names the event or "
        "turning point described in that section's body (e.g. 'Breaking of Vellmire', "
        "'Coming of the Lantern Wardens', \"Battle for Maelor's Crossing\"). Never use bare expansion or "
        "era labels as headings (no 'History', 'World of Warcraft', 'Cataclysm', 'Legion', "
        "'Exploring Azeroth'). "
        "Do not list locations. Cover only background that happened before the player enters "
        "the current content; do not narrate the current storyline's events, outcomes, or later "
        "off-screen reports. "
        "Order the sections chronologically. If the most recent evidence describes the zone's current, "
        "ongoing state — the condition in which the zone currently stands in the content, whether an "
        "ongoing recovery or an unresolved, still-active conflict — write that one final section in "
        "present tense, as the chronicle reaching that current state, and keep every earlier section "
        "in past tense; a reference to a finished past event stays past tense even within that final "
        "section. 'Current' here means the state this zone's content presents, not the latest point "
        "in the wider timeline. If there is no such current-state material, keep all sections in past "
        "tense. "
        "Stay in-world: describe the state of the place itself, never framed by 'the player' or "
        "'adventurers' arriving, and never in second person."
    )
    if required_event_texts:
        # Coverage retry (Slice 7): an eligible setup-bridge claim was dropped on the first pass.
        # Require the model to represent each listed setup fact in some section so the entry-state
        # bridge is not silently omitted.
        bridge_lines = "; ".join(text for text in required_event_texts if text)
        if bridge_lines:
            history_task += (
                " You must represent each of the following setup facts in at least one section, "
                f"combining them with adjacent context where natural: {bridge_lines}."
            )

    evidence_block, alias_map = _format_evidence_block(items, max_items=max_sections)

    def _call(reinforce: str) -> dict[str, Any]:
        return llm_json_with_retry(
            required_keys=("sections", "used_evidence_ids"),
            response_json_schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["sections", "used_evidence_ids"],
                "properties": {
                    "sections": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["heading", "body"],
                            "properties": {
                                "heading": {"type": "string"},
                                "body": {"type": "string"},
                            },
                        },
                    },
                    "used_evidence_ids": {"type": "array", "items": {"type": "string"}},
                },
            },
            system_prompt=zone_system_prompt(
                field_voice=HISTORY_VOICE,
                task_lines=history_task + reinforce,
            ),
            user_prompt=f"Evidence:\n{evidence_block}",
            response_schema_name="wiki_first_history",
            substep="wiki_first_history",
        )

    result = _call(reinforce)
    sections_out: list[dict[str, Any]] = []
    raw_sections = result.get("sections", [])
    if isinstance(raw_sections, list):
        for row in raw_sections[:max_sections]:
            if not isinstance(row, dict):
                continue
            heading = clean_wiki_snippet(str(row.get("heading", "")))
            body = clean_wiki_snippet(str(row.get("body", "")))
            if heading and body:
                sections_out.append({"heading": heading, "body": body, "source_refs": []})
    used = translate_used_evidence_ids(result.get("used_evidence_ids", []), alias_map)
    # An empty LLM result is a failed attempt for the finalize-level synthesis driver to retry —
    # never borrow verbatim snippets on the live path (licensing exposure).
    finalize_trace.record(
        "history.synth",
        path="llm" if sections_out else "llm_empty",
        section_count=len(sections_out),
    )
    return sections_out, used


def _heading_is_generic(heading: str) -> bool:
    """True for bare wiki-TOC / expansion-era labels rather than thematic event titles.

    Delegates to the section registry's ``is_generic_history_heading`` (Slice 14 single-home): the
    generic container headings, every expansion display name, and adaptation ('media') headings read
    as noise next to a content-derived title. It matches the *whole* heading — never a substring —
    so a thematic title that merely contains an era word ("Battle for Andorhal") is preserved.
    """
    return is_generic_history_heading(heading)


def relabel_history_headings(
    sections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Replace bare era/TOC history headings with thematic, body-derived titles via the LLM.

    The body text may come from LLM synthesis *or* the deterministic wiki-snippet fallback; either
    way the heading frequently echoes the raw wiki subsection label ("World of Warcraft",
    "Cataclysm", "Historical era"). This runs a single batched LLM call to re-title only the generic
    headings from each section's body content, so the published titles read like the gold fixtures
    ("Before the Scourge", "Rise of the Dead"). Headings already thematic are left untouched.

    Offline / no-OpenAI: returns the sections unchanged (deterministic path keeps the cleaned label).
    """
    if not sections:
        return sections
    targets = [
        index
        for index, section in enumerate(sections)
        if isinstance(section, dict)
        and str(section.get("body", "")).strip()
        and _heading_is_generic(str(section.get("heading", "")))
    ]
    if not targets:
        return sections
    settings = load_ai_settings()
    if not settings.openai_ready or os.environ.get("WOW_LORE_WIKI_FIRST_NO_LLM", "").lower() in {
        "1",
        "true",
        "yes",
    }:
        return sections
    body_lines = "\n\n".join(
        f"[{position}] {clean_wiki_snippet(str(sections[index].get('body', '')))}"
        for position, index in enumerate(targets, start=1)
    )
    result = llm_json_with_retry(
        required_keys=("headings",),
        response_json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["headings"],
            "properties": {
                "headings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["index", "heading"],
                        "properties": {
                            "index": {"type": "integer"},
                            "heading": {"type": "string"},
                        },
                    },
                }
            },
        },
        system_prompt=zone_system_prompt(
            field_voice=HISTORY_VOICE,
            task_lines=(
                "You are titling history sections. For each numbered body, write a short (2–5 word) "
                "thematic title that names the central event or turning point it narrates, in "
                "Title Case (e.g. 'Before the Hollow Court', 'Coming of the Lantern Wardens', "
                "'Rise of the Curse-Bound', \"Battle for Maelor's Crossing\"). Ground the title strictly in that "
                "body's content. Never return a bare expansion or era label "
                "('History', 'World of Warcraft', 'Cataclysm', 'Legion', 'Exploring Azeroth'). "
                "Return one heading per input index."
            ),
        ),
        user_prompt=f"Bodies:\n{body_lines}",
        response_schema_name="wiki_first_history_headings",
        substep="wiki_first_history_headings",
    )
    relabeled = [dict(section) for section in sections]
    raw = result.get("headings", [])
    if isinstance(raw, list):
        for row in raw:
            if not isinstance(row, dict):
                continue
            try:
                position = int(row.get("index", 0))
            except (TypeError, ValueError):
                continue
            heading = clean_wiki_snippet(str(row.get("heading", "")))
            if not heading or position < 1 or position > len(targets):
                continue
            if _heading_is_generic(heading):
                continue
            relabeled[targets[position - 1]]["heading"] = heading
    return relabeled


def synthesize_faction_summary(
    items: list[dict[str, Any]],
    *,
    faction_name: str,
    zone_name: str,
    max_words: int = MAX_FACTION_SUMMARY_WORDS,
    subregion_tokens: list[str] | None = None,
    instance_name: str | None = None,
    reinforce: str = "",
) -> tuple[str, list[str]]:
    if not items:
        return "", []
    settings = load_ai_settings()
    if not settings.openai_ready or os.environ.get("WOW_LORE_WIKI_FIRST_NO_LLM", "").lower() in {
        "1",
        "true",
        "yes",
    }:
        from pipeline.generate.draft.faction_scoring import fallback_faction_summary

        return fallback_faction_summary(
            items,
            max_words=max_words,
            zone_name=zone_name,
            subregion_tokens=subregion_tokens,
            faction_name=faction_name,
        )
    if instance_name:
        system_prompt = instance_system_prompt(
            field_voice=INSTANCE_FACTION_VOICE,
            task_lines=(
                f"Write a faction-role summary for faction '{faction_name}' in instance "
                f"'{instance_name}' using ONLY evidence. Maximum {max_words} words. "
                "Write from the entry-state perspective: present tense for active roles, past "
                "tense only for older identity context, and no current-storyline outcomes."
            )
            + reinforce,
        )
    else:
        system_prompt = (
            f"Write a zone-role summary for faction '{faction_name}' in zone '{zone_name}' using ONLY evidence. "
            f"Maximum {max_words} words. Describe what this faction does in this zone only. "
            "Write from the entry-state perspective: present tense for active roles, past tense "
            "only for older identity context, and no current-storyline outcomes. "
            "Do not copy generic faction wiki ledes, geography lists, reputation/achievement meta, or out-of-zone plot."
            + reinforce
        )
    evidence_block, alias_map = _format_evidence_block(items)
    result = llm_json_with_retry(
        required_keys=("summary", "used_evidence_ids"),
        response_json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["summary", "used_evidence_ids"],
            "properties": {
                "summary": {"type": "string"},
                "used_evidence_ids": {"type": "array", "items": {"type": "string"}},
            },
        },
        system_prompt=system_prompt,
        user_prompt=f"Evidence:\n{evidence_block}",
        response_schema_name="wiki_first_faction_summary",
        substep="wiki_first_faction_summary",
    )
    summary = trim_faction_summary(
        strip_faction_label_prefix(
            clean_wiki_snippet(str(result.get("summary", ""))), faction_name
        ),
        max_words,
    )
    used = translate_used_evidence_ids(result.get("used_evidence_ids", []), alias_map)
    # Empty result = failed attempt; the finalize-level driver retries or drops the card.
    return summary, used


def synthesize_location_summary(
    items: list[dict[str, Any]],
    *,
    location_name: str,
    zone_name: str,
    max_words: int = 50,
    reinforce: str = "",
) -> tuple[str, list[str], str, str]:
    """Return ``(summary, used_evidence_ids, location_type, significance_tag)``.

    The classification enums ride this existing LLM call (Slice 10): the model classifies the
    place's type and significance from the evidence, and the card builder folds them into the
    wiki-category → infobox → LLM → default precedence. Offline / no-LLM leaves both enums empty
    so the deterministic card typing never depends on keyword guesses.
    """
    from pipeline.generate.draft.location_scoring import SIGNIFICANCE_TAGS

    if not items:
        return "", [], "", ""
    settings = load_ai_settings()
    if not settings.openai_ready or os.environ.get("WOW_LORE_WIKI_FIRST_NO_LLM", "").lower() in {
        "1",
        "true",
        "yes",
    }:
        from pipeline.generate.draft.location_lint import trim_location_summary

        ranked = sorted(
            items, key=lambda row: word_count(str(row.get("snippet", ""))), reverse=True
        )
        for item in ranked:
            snippet = clean_wiki_snippet(str(item.get("snippet", "")))
            if not snippet:
                continue
            summary = trim_location_summary(snippet, max_words)
            if summary:
                return summary, [str(item.get("source_id", ""))], "", ""
        return "", [], "", ""
    from pipeline.generate.draft.location_lint import trim_location_summary

    location_type_values = sorted(member.value for member in LocationType)
    significance_values = sorted(SIGNIFICANCE_TAGS)
    evidence_block, alias_map = _format_evidence_block(items)
    result = llm_json_with_retry(
        required_keys=("summary", "used_evidence_ids", "location_type", "significance_tag"),
        response_json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": [
                "summary",
                "used_evidence_ids",
                "location_type",
                "significance_tag",
            ],
            "properties": {
                "summary": {"type": "string"},
                "used_evidence_ids": {"type": "array", "items": {"type": "string"}},
                "location_type": {"type": "string", "enum": location_type_values},
                "significance_tag": {"type": "string", "enum": significance_values},
            },
        },
        system_prompt=(
            f"Write an in-zone landmark summary for '{location_name}' in zone '{zone_name}' using ONLY evidence. "
            f"Maximum {max_words} words. Describe what this place is and does within this zone. "
            "Use encyclopedic tone. Do not copy generic wiki ledes, faction lists, adjacent-zone geography, "
            "dating conventions, reputation/achievement meta, or out-of-zone plot. Also classify, from the "
            f"evidence, this place's 'location_type' (one of: {', '.join(location_type_values)}) and its "
            f"'significance_tag' — why it matters to the zone (one of: {', '.join(significance_values)})."
            + reinforce
        ),
        user_prompt=f"Evidence:\n{evidence_block}",
        response_schema_name="wiki_first_location_summary",
        substep="wiki_first_location_summary",
    )
    summary = trim_location_summary(clean_wiki_snippet(str(result.get("summary", ""))), max_words)
    used = translate_used_evidence_ids(result.get("used_evidence_ids", []), alias_map)
    location_type = str(result.get("location_type", "")).strip().lower()
    significance_tag = str(result.get("significance_tag", "")).strip().lower()
    # Empty result = failed attempt; the finalize-level driver retries or drops the card.
    return summary, used, location_type, significance_tag


def _readable_location_type(location_type: str) -> str:
    return location_type.replace("_", " ") if location_type else "location"


def synthesize_location_significance(
    items: list[dict[str, Any]],
    *,
    location_name: str,
    zone_name: str,
    location_type: str = "",
    max_words: int = 40,
) -> tuple[str, list[str]]:
    """One-sentence significance ("why this place matters to the zone's story").

    Distinct from the descriptive ``summary``: this names the place's role/importance. Never emits
    the routing classification enum. Offline, derives a grounded sentence from the most historical
    evidence snippet, then a templated name/type sentence so the required field is always non-empty.
    """
    from pipeline.generate.draft.location_lint import trim_location_summary

    def _fallback() -> tuple[str, list[str]]:
        ranked = sorted(items, key=_snippet_rank_key, reverse=True)
        for item in ranked:
            snippet = clean_wiki_snippet(str(item.get("snippet", "")))
            if not snippet:
                continue
            sentence = snippet.split(". ")[0].strip().rstrip(".")
            text = trim_location_summary(f"{sentence}.", max_words)
            if text and word_count(text) >= 4:
                return text, [str(item.get("source_id", ""))]
        readable = _readable_location_type(location_type)
        zone_clause = f" of {zone_name}" if zone_name else ""
        return f"{location_name} is a notable {readable}{zone_clause}.", []

    if not items:
        readable = _readable_location_type(location_type)
        zone_clause = f" of {zone_name}" if zone_name else ""
        return f"{location_name} is a notable {readable}{zone_clause}.", []
    settings = load_ai_settings()
    if not settings.openai_ready or os.environ.get("WOW_LORE_WIKI_FIRST_NO_LLM", "").lower() in {
        "1",
        "true",
        "yes",
    }:
        return _fallback()
    evidence_block, alias_map = _format_evidence_block(items)
    result = llm_json_with_retry(
        required_keys=("significance", "used_evidence_ids"),
        response_json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["significance", "used_evidence_ids"],
            "properties": {
                "significance": {"type": "string"},
                "used_evidence_ids": {"type": "array", "items": {"type": "string"}},
            },
        },
        system_prompt=(
            f"Write a single sentence on why '{location_name}' matters to the story of zone "
            f"'{zone_name}' using ONLY evidence. Maximum {max_words} words. Name its role, the events "
            "tied to it, or who held it — not a generic description. Encyclopedic tone; do not copy "
            "wiki ledes, faction lists, reputation/achievement meta, or out-of-zone plot."
        ),
        user_prompt=f"Evidence:\n{evidence_block}",
        response_schema_name="wiki_first_location_significance",
        substep="wiki_first_location_significance",
    )
    significance = trim_location_summary(
        clean_wiki_snippet(str(result.get("significance", ""))), max_words
    )
    used = translate_used_evidence_ids(result.get("used_evidence_ids", []), alias_map)
    if significance and word_count(significance) >= 4:
        return significance, used
    return _fallback()


def _early_chain_ref_limit(chain_refs: list[str], *, arc_title: str) -> int:
    return min(2, len(chain_refs)) if chain_refs else 0


def filter_early_chain_evidence_pool(
    items: list[dict[str, Any]],
    chain_refs: list[str],
    *,
    arc_title: str = "",
) -> list[dict[str, Any]]:
    if not items:
        return []
    limit = _early_chain_ref_limit(chain_refs, arc_title=arc_title)
    if limit <= 0:
        return items[:2]
    early_ids = set(chain_refs[:limit])
    scoped = [item for item in items if str(item.get("quest_node_id", "")).strip() in early_ids]
    if scoped:
        return scoped[:limit]
    return items[:limit]


def synthesize_questline_cta_hook(
    items: list[dict[str, Any]],
    *,
    arc_title: str,
    start_anchor: str,
    faction: str,
    chain_refs: list[str] | None = None,
    quest_descriptions: dict[str, str] | None = None,
    max_words: int = 35,
) -> tuple[str, list[str]]:
    refs = list(chain_refs or [])
    early_pool = filter_early_chain_evidence_pool(items, refs, arc_title=arc_title)
    if quest_descriptions and refs:
        limit = _early_chain_ref_limit(refs, arc_title=arc_title)
        for node_id in refs[:limit]:
            description = clean_wiki_snippet(str(quest_descriptions.get(node_id, "")))
            if description and word_count(description) >= 6:
                early_pool.insert(
                    0,
                    {
                        "source_id": node_id,
                        "quest_node_id": node_id,
                        "snippet": description,
                        "section_role": "quest_start_description",
                        "raw_section_role": "quest_start_description",
                    },
                )
    if not early_pool:
        return "", []
    faction_addendum = ""
    if faction == "alliance":
        faction_addendum = " Name the Horde as the opposing faction when evidence supports it."
    elif faction == "horde":
        faction_addendum = " Name the Alliance as the opposing faction when evidence supports it."
    settings = load_ai_settings()
    if not settings.openai_ready or os.environ.get("WOW_LORE_WIKI_FIRST_NO_LLM", "").lower() in {
        "1",
        "true",
        "yes",
    }:
        ranked = sorted(
            early_pool, key=lambda row: word_count(str(row.get("snippet", ""))), reverse=True
        )
        for item in ranked:
            snippet = trim_words(clean_wiki_snippet(str(item.get("snippet", ""))), max_words)
            if snippet and snippet.lower() != arc_title.strip().lower():
                return finalize_cta_hook(snippet, max_words=max_words), [
                    str(item.get("source_id", ""))
                ]
        return "", []
    evidence_block, alias_map = _format_evidence_block(early_pool, max_items=2)
    result = llm_json_with_retry(
        required_keys=("summary", "used_evidence_ids"),
        response_json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["summary", "used_evidence_ids"],
            "properties": {
                "summary": {"type": "string"},
                "used_evidence_ids": {"type": "array", "items": {"type": "string"}},
            },
        },
        system_prompt=(
            f"{COMPENDIUM_VOICE_CORE} {QUESTLINE_CTA_VOICE}"
            f" Write a questline card hook for arc '{arc_title}' starting at '{start_anchor}'."
            f" Max {max_words} words. Write as an in-universe call for help at the questline's "
            f"opening situation. Do not describe late-chain events or outcomes.{faction_addendum}"
        ),
        user_prompt=f"Evidence:\n{evidence_block}",
        response_schema_name="wiki_first_questline_cta_hook",
        substep="wiki_first_questline_cta_hook",
    )
    summary = finalize_cta_hook(
        trim_words(clean_wiki_snippet(str(result.get("summary", ""))), max_words),
        max_words=max_words,
    )
    used = translate_used_evidence_ids(result.get("used_evidence_ids", []), alias_map)
    if summary and summary.lower() != arc_title.strip().lower():
        return summary, used
    ranked = sorted(
        early_pool, key=lambda row: word_count(str(row.get("snippet", ""))), reverse=True
    )
    for item in ranked:
        snippet = finalize_cta_hook(
            trim_words(clean_wiki_snippet(str(item.get("snippet", ""))), max_words),
            max_words=max_words,
        )
        if snippet:
            return snippet, [str(item.get("source_id", ""))]
    return "", []


def synthesize_card_summary(
    items: list[dict[str, Any]],
    *,
    subject: str,
    max_words: int = 40,
    faction: str = "shared",
) -> tuple[str, list[str]]:
    if not items:
        return "", []
    faction_addendum = ""
    if faction == "alliance":
        faction_addendum = " Use an imperative verb and name the Horde as the opposing faction when evidence supports it."
    elif faction == "horde":
        faction_addendum = " Use an imperative verb and name the Alliance as the opposing faction when evidence supports it."
    settings = load_ai_settings()
    if not settings.openai_ready or os.environ.get("WOW_LORE_WIKI_FIRST_NO_LLM", "").lower() in {
        "1",
        "true",
        "yes",
    }:
        best = trim_words(
            clean_wiki_snippet(
                _format_evidence_block(items, max_items=1)[0].split("]", 1)[-1].strip()
            ),
            max_words,
        )
        return best, [str(items[0].get("source_id", ""))]
    evidence_block, alias_map = _format_evidence_block(items)
    result = llm_json_with_retry(
        required_keys=("summary", "used_evidence_ids"),
        response_json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["summary", "used_evidence_ids"],
            "properties": {
                "summary": {"type": "string"},
                "used_evidence_ids": {"type": "array", "items": {"type": "string"}},
            },
        },
        system_prompt=(
            f"Write a 1-2 sentence summary for '{subject}' using ONLY evidence. Max {max_words} words."
            f"{faction_addendum}"
        ),
        user_prompt=f"Evidence:\n{evidence_block}",
        response_schema_name="wiki_first_card_summary",
        substep="wiki_first_card_summary",
    )
    summary = trim_words(clean_wiki_snippet(str(result.get("summary", ""))), max_words)
    used = translate_used_evidence_ids(result.get("used_evidence_ids", []), alias_map)
    return summary, used


def synthesize_instance_overview(
    items: list[dict[str, Any]],
    *,
    instance_name: str,
    max_words: int | None = None,
    reference_framing: str = "",
    reinforce: str = "",
) -> tuple[str, list[str]]:
    if not items:
        return "", []
    from pipeline.generate.draft.instance_lint import (
        MAX_OVERVIEW_WORDS,
        MIN_OVERVIEW_WORDS,
        fallback_instance_overview,
        trim_instance_overview,
    )

    # Default + prompt target must match the ``lint_overview`` cap. The old "Target 170-320 words"
    # prompt (max_words=320) could never satisfy ``lint_overview`` (<= MAX_OVERVIEW_WORDS=160), so
    # every LLM overview was rejected and the page fell back to a verbatim borrow. Bound the target
    # to the lint range so synthesis can actually pass.
    if max_words is None:
        max_words = MAX_OVERVIEW_WORDS
    settings = load_ai_settings()
    if not settings.openai_ready or os.environ.get("WOW_LORE_WIKI_FIRST_NO_LLM", "").lower() in {
        "1",
        "true",
        "yes",
    }:
        finalize_trace.record("overview.synth", path="no_llm")
        return fallback_instance_overview(items, instance_name=instance_name, max_words=max_words)
    overview_task = (
        f"Write an in-universe story-context overview for instance '{instance_name}' "
        f"using ONLY evidence. Target {MIN_OVERVIEW_WORDS}-{max_words} words."
    )
    reference_block = ""
    if reference_framing.strip():
        # The game's own Adventure Guide intro for this instance: reference for framing/emphasis
        # only, never copied (the finalize-level passthrough gate includes it in its corpus). It
        # must not dictate the overview's length, tone, or structure.
        overview_task += (
            " A REFERENCE block follows the evidence: the game's own intro for this place. Use it "
            "only to anchor what the place is and why it matters; do NOT quote or paraphrase it, and "
            "do NOT match its length, tone, or structure — build the overview from the Evidence."
        )
        reference_block = f"\n\nReference (framing only — do not copy):\n{reference_framing.strip()}"

    evidence_block, alias_map = _format_evidence_block(items, max_items=12)

    def _call(reinforce: str) -> dict[str, Any]:
        return llm_json_with_retry(
            required_keys=("summary", "used_evidence_ids"),
            response_json_schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["summary", "used_evidence_ids"],
                "properties": {
                    "summary": {"type": "string"},
                    "used_evidence_ids": {"type": "array", "items": {"type": "string"}},
                },
            },
            system_prompt=instance_system_prompt(
                field_voice=INSTANCE_OVERVIEW_VOICE,
                task_lines=overview_task + reinforce,
            ),
            user_prompt=f"Evidence:\n{evidence_block}{reference_block}",
            response_schema_name="wiki_first_instance_overview",
            substep="wiki_first_instance_overview",
        )

    result = _call(reinforce)
    summary = trim_instance_overview(
        clean_wiki_snippet(str(result.get("summary", ""))), max_words=max_words
    )
    used = translate_used_evidence_ids(result.get("used_evidence_ids", []), alias_map)
    # An empty LLM result is a failed attempt for the finalize-level synthesis driver to retry —
    # never borrow verbatim/templated prose on the live path.
    finalize_trace.record(
        "overview.synth",
        path="llm" if summary else "llm_empty",
        words=word_count(summary),
    )
    return summary, used


def synthesize_key_character_summary(
    items: list[dict[str, Any]],
    *,
    boss_name: str,
    instance_name: str,
    structural_role: str = "",
    max_words: int = INSTANCE_BUDGET_RULES["key_characters_card_summary"].max_words,
    avoid_hints: list[str] | None = None,
    reference_framing: str = "",
    evidence_item_limit: int = KEY_CHARACTER_EVIDENCE_ITEM_LIMIT,
    reinforce: str = "",
) -> tuple[str, list[str]]:
    if not items:
        return "", []
    from pipeline.generate.draft.instance_lint import (
        fallback_key_character_summary,
        trim_key_character_summary,
    )

    settings = load_ai_settings()
    if not settings.openai_ready or os.environ.get("WOW_LORE_WIKI_FIRST_NO_LLM", "").lower() in {
        "1",
        "true",
        "yes",
    }:
        return fallback_key_character_summary(
            items,
            boss_name=boss_name,
            instance_name=instance_name,
            max_words=max_words,
        )
    task_lines = (
        f"Write a key-character card summary for '{boss_name}' in instance "
        f"'{instance_name}' using ONLY evidence. Maximum {max_words} words. "
        f"Align with the precomputed structural role '{structural_role or 'uncertain'}' "
        "without using meta labels as prose. Trace the chain from who this character is to why they "
        f"are present in '{instance_name}' now — foreground the history and motivations that explain "
        "their presence here, and leave out unrelated later-life roles or honors the evidence "
        "mentions. No generic stubs, no current-storyline outcomes."
    )
    if avoid_hints:
        # Spoiler exclusion hints (Slice 9): encounter mechanics / outcome claims a newly arriving
        # player has not yet seen. Pass them as things to avoid, never as usable content.
        joined = "; ".join(hint for hint in avoid_hints if hint)
        if joined:
            task_lines += (
                " Do not state, imply, or hint at these in-encounter mechanics or outcomes: "
                f"{joined}."
            )
    evidence_block, alias_map = _format_evidence_block(items, max_items=evidence_item_limit)
    user_prompt = f"Evidence:\n{evidence_block}"
    if reference_framing.strip():
        # The game's own Adventure Guide framing: high-quality context for *which arc points matter*
        # and for anchoring identity/role facts. It is reference, NOT evidence — the card is
        # synthesized from the Evidence beats above; the passthrough gate at the call site rejects
        # any run copied from this block. It must not dictate the card's length, tone, or structure.
        task_lines += (
            " A REFERENCE block follows the evidence: the game's own account of this character's "
            "backstory and role. Use it only to judge which parts of their arc matter and to anchor "
            "identity and role facts. Do NOT quote or paraphrase it, and do NOT match its length, "
            "tone, register, or structure; write the summary at its own target length from the "
            "Evidence beats."
        )
        user_prompt += f"\n\nReference (framing only — do not copy):\n{reference_framing.strip()}"
    result = llm_json_with_retry(
        required_keys=("summary", "used_evidence_ids"),
        response_json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["summary", "used_evidence_ids"],
            "properties": {
                "summary": {"type": "string"},
                "used_evidence_ids": {"type": "array", "items": {"type": "string"}},
            },
        },
        system_prompt=instance_system_prompt(
            field_voice=KEY_CHARACTER_VOICE,
            task_lines=task_lines + reinforce,
        ),
        user_prompt=user_prompt,
        response_schema_name="wiki_first_key_character_summary",
        substep="wiki_first_key_character_summary",
    )
    summary = trim_key_character_summary(
        clean_wiki_snippet(str(result.get("summary", ""))), max_words=max_words
    )
    used = translate_used_evidence_ids(result.get("used_evidence_ids", []), alias_map)
    # Empty result = failed attempt; the finalize-level driver retries or drops the candidate.
    return summary, used
