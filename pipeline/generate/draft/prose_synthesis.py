"""Constrained LLM prose synthesis workers for draft page assembly."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from pipeline.ai.config import load_ai_settings
from pipeline.common.text_normalize import clean_wiki_snippet
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
from pipeline.generate.draft.faction_lint import trim_faction_summary
from pipeline.generate.draft.llm import llm_json_with_retry
from pipeline.generate.draft.prose_election import (
    history_heading_from_role,
    precompress_at_a_glance_evidence,
)
from pipeline.generate.draft.prose_gate import detect_source_passthrough
from pipeline.generate.draft.prose_lint import (
    MAX_HISTORY_SECTIONS,
    lint_history_sections,
    past_marker_score,
    trim_words,
    word_count,
)


def _snippet_rank_key(row: dict[str, Any]) -> tuple[int, int]:
    snippet = str(row.get("snippet", ""))
    return past_marker_score(snippet), word_count(snippet)


def _format_evidence_block(items: list[dict[str, Any]], *, max_items: int = 8) -> str:
    lines: list[str] = []
    for index, item in enumerate(items[:max_items], start=1):
        snippet = clean_wiki_snippet(str(item.get("snippet", "")))
        if not snippet:
            continue
        source_id = str(item.get("source_id", f"ev-{index}"))
        lines.append(f"[{source_id}] {snippet}")
    return "\n".join(lines)


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


def enforce_non_passthrough(
    result: dict[str, Any],
    *,
    call: Callable[[str], dict[str, Any]],
    extract_bodies: Callable[[dict[str, Any]], list[str]],
    source_snippets: list[str],
    label: str = "",
    lint_reasons: Callable[[dict[str, Any]], list[str]] | None = None,
) -> dict[str, Any]:
    """Re-prompt once with corrective feedback when the first synthesis attempt is sub-par.

    ``call(reinforce)`` runs one synthesis attempt; ``reinforce`` is a feedback string appended to
    the task ("" for the first attempt). Two failure modes trigger the one retry:

    * **Copying** — a body reproduces the source (:func:`detect_source_passthrough`, contiguous-run
      copies, not just set overlap). Feedback: :data:`PARAPHRASE_REINFORCE`.
    * **Lint** — when ``lint_reasons`` is supplied, the first attempt failing an editorial check
      (e.g. a history section that slipped into present tense) feeds those reasons back via
      :func:`lint_reinforce`. This fixes-and-keeps the section at the source instead of letting the
      finalize layer drop it.

    The retry runs at most once (bounded cost). The *better* of the two attempts is kept — fewer
    combined problems (copies + lint hits) wins; a tie keeps the original. If both attempts are still
    flawed, the caller's finalize-level gate/salvage handles the residue gracefully rather than this
    raising and aborting the draft stage.
    """

    def _copies(payload: dict[str, Any]) -> bool:
        return bool(source_snippets) and any(
            body and detect_source_passthrough(body, source_snippets)
            for body in extract_bodies(payload)
        )

    def _lint(payload: dict[str, Any]) -> list[str]:
        return lint_reasons(payload) if lint_reasons else []

    first_copied = _copies(result)
    first_lint = _lint(result)
    if not first_copied and not first_lint:
        finalize_trace.record(
            f"{label}.synth_guard",
            first_attempt_copied=False,
            first_attempt_lint=[],
            retried=False,
        )
        return result

    feedback = ""
    if first_copied:
        feedback += PARAPHRASE_REINFORCE
    if first_lint:
        feedback += lint_reinforce(first_lint)
    retried = call(feedback)
    retry_copied = _copies(retried)
    retry_lint = _lint(retried)
    # Keep the better attempt: fewer combined problems wins, tie keeps the original (no needless churn).
    retry_score = int(retry_copied) + len(retry_lint)
    first_score = int(first_copied) + len(first_lint)
    chosen = retried if retry_score < first_score else result
    finalize_trace.record(
        f"{label}.synth_guard",
        first_attempt_copied=first_copied,
        first_attempt_lint=first_lint,
        retried=True,
        retry_still_copied=retry_copied,
        retry_lint=retry_lint,
        kept_retry=chosen is retried,
    )
    return chosen


def synthesize_at_a_glance(
    items: list[dict[str, Any]], *, max_words: int = 45, subject: str | None = None
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
        best = max(prepared, key=_snippet_rank_key)
        return trim_words(clean_wiki_snippet(str(best.get("snippet", ""))), max_words), [
            str(best.get("source_id", ""))
        ]
    if subject:
        system_prompt = instance_system_prompt(
            field_voice=INSTANCE_AT_A_GLANCE_VOICE,
            task_lines=(
                f"Write a concise at-a-glance caption for instance '{subject}' using ONLY the "
                f"evidence snippets. Maximum {max_words} words. Do not list bosses, factions, or "
                "wings. No extrapolation."
            ),
        )
    else:
        system_prompt = zone_system_prompt(
            field_voice=AT_A_GLANCE_VOICE,
            task_lines=(
                f"Write an evocative zone at-a-glance summary using ONLY the evidence snippets. "
                f"Maximum {max_words} words. Lead with the zone's defining identity and fate in one "
                "vivid sentence rather than a dry gazetteer line. Name the precise faction or actor "
                "when the evidence specifies it (e.g. 'Forsaken', not the generic 'Horde'; "
                "'the Scourge', not 'the undead'). "
                "Do not list locations, characters, factions, or patch/reputation meta. "
                "No extrapolation."
            ),
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
        user_prompt=f"Evidence:\n{_format_evidence_block(prepared, max_items=12)}",
        response_schema_name="wiki_first_at_a_glance",
        substep="wiki_first_at_a_glance",
    )
    summary = trim_words(clean_wiki_snippet(str(result.get("summary", ""))), max_words)
    used = [str(value) for value in result.get("used_evidence_ids", []) if str(value).strip()]
    if not summary:
        best = max(prepared, key=_snippet_rank_key)
        summary = trim_words(clean_wiki_snippet(str(best.get("snippet", ""))), max_words)
        used = [str(best.get("source_id", ""))]
    return summary, used


def synthesize_currently(
    items: list[dict[str, Any]], *, max_words: int = 120
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
                "Name the precise faction or actor the evidence specifies (e.g. 'Forsaken', not the "
                "generic 'Horde'; 'Scarlet Crusade', not 'humans'). "
                "Do not write quest walkthrough steps, reputation/achievement meta, adjacent-zone geography hubs, "
                "or out-of-universe player instructions."
            ),
        ),
        user_prompt=f"Evidence:\n{_format_evidence_block(items)}",
        response_schema_name="wiki_first_currently",
        substep="wiki_first_currently",
    )
    summary = trim_words(clean_wiki_snippet(str(result.get("summary", ""))), max_words)
    used = [str(value) for value in result.get("used_evidence_ids", []) if str(value).strip()]
    if not summary:
        best = max(items, key=lambda row: word_count(str(row.get("snippet", ""))))
        summary = trim_words(clean_wiki_snippet(str(best.get("snippet", ""))), max_words)
        used = [str(best.get("source_id", ""))]
    return summary, used


def synthesize_history_sections(
    items: list[dict[str, Any]], *, max_sections: int = MAX_HISTORY_SECTIONS
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
            used.append(str(item.get("source_id", "")))
        return sections, used
    history_task = (
        "Produce chronological historical arc sections from evidence only. "
        f"Up to {max_sections} sections. "
        "Each heading must be a short (2–5 word) thematic title that names the event or "
        "turning point described in that section's body (e.g. 'Scourging of Lordaeron', "
        "'Coming of the Argent Dawn', 'Battle for Andorhal'). Never use bare expansion or "
        "era labels as headings (no 'History', 'World of Warcraft', 'Cataclysm', 'Legion', "
        "'Exploring Azeroth'). "
        "Do not list locations. Cover only background that happened before the player enters "
        "the current content; do not narrate the current storyline's events, outcomes, or later "
        "off-screen reports."
    )

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
            user_prompt=f"Evidence:\n{_format_evidence_block(items, max_items=max_sections)}",
            response_schema_name="wiki_first_history",
            substep="wiki_first_history",
        )

    def _history_lint(payload: dict[str, Any]) -> list[str]:
        rows = [
            row for row in (payload.get("sections") or []) if isinstance(row, dict)
        ][:max_sections]
        return lint_history_sections(rows, max_sections=max_sections)

    result = enforce_non_passthrough(
        _call(""),
        call=_call,
        extract_bodies=lambda payload: [
            str(row.get("body", ""))
            for row in (payload.get("sections") or [])
            if isinstance(row, dict)
        ],
        source_snippets=_evidence_snippets(items),
        label="history",
        lint_reasons=_history_lint,
    )
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
    used = [str(value) for value in result.get("used_evidence_ids", []) if str(value).strip()]
    if not sections_out:
        # The LLM returned no usable sections; borrow verbatim snippets (rejected later by the
        # finalize gate in a live run). Recorded so an empty history is attributable to "LLM empty".
        finalize_trace.record("history.synth", path="llm_empty_fallback")
        sections = []
        used_ids: list[str] = []
        for item in items[:max_sections]:
            snippet = clean_wiki_snippet(str(item.get("snippet", "")))
            if not snippet:
                continue
            heading = history_heading_from_role(
                str(item.get("section_role", "other")),
                str(item.get("raw_section_role", "")),
            )
            sections.append({"heading": heading, "body": snippet, "source_refs": []})
            used_ids.append(str(item.get("source_id", "")))
        return sections, used_ids
    finalize_trace.record("history.synth", path="llm", section_count=len(sections_out))
    return sections_out, used


# Headings that are bare wiki TOC / expansion-era labels rather than thematic event titles.
# These describe *when* a section sits in the timeline, not *what* it narrates, so they read as
# noise next to a content-derived title ("Scourging of Lordaeron"). Detected case-insensitively;
# era tokens (cataclysm, legion, …) come from the shared draft vocab so the list stays single-source.
_GENERIC_HISTORY_HEADINGS = frozenset(
    {
        "history",
        "lore",
        "background",
        "story",
        "overview",
        "introduction",
        "historical era",
        "world of warcraft",
        "exploring azeroth",
        "classic",
        "vanilla",
        "the burning crusade",
        "burning crusade",
        "wrath of the lich king",
        "cataclysm",
        "mists of pandaria",
        "warlords of draenor",
        "legion",
        "battle for azeroth",
        "shadowlands",
        "dragonflight",
        "the war within",
        "war within",
    }
)


def _heading_is_generic(heading: str) -> bool:
    """True for bare TOC / expansion-era labels (matched as the *whole* heading).

    Matched against the full lowered heading only — never as a substring — so thematic gold
    titles that happen to contain an era word ("Battle for Andorhal", "Wrath of the Lich King"
    is itself an expansion and stays listed, but "Battle for Andorhal" must NOT match
    "battle_for") are preserved.
    """
    lowered = heading.strip().lower()
    if not lowered:
        return True
    return lowered in _GENERIC_HISTORY_HEADINGS


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
                "Title Case (e.g. 'Before the Scourge', 'Coming of the Argent Dawn', "
                "'Rise of the Dead', 'Battle for Andorhal'). Ground the title strictly in that "
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
    max_words: int = 40,
    subregion_tokens: list[str] | None = None,
    instance_name: str | None = None,
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
        )
    if instance_name:
        system_prompt = instance_system_prompt(
            field_voice=INSTANCE_FACTION_VOICE,
            task_lines=(
                f"Write a faction-role summary for faction '{faction_name}' in instance "
                f"'{instance_name}' using ONLY evidence. Maximum {max_words} words. "
                "Write from the entry-state perspective: present tense for active roles, past "
                "tense only for older identity context, and no current-storyline outcomes."
            ),
        )
    else:
        system_prompt = (
            f"Write a zone-role summary for faction '{faction_name}' in zone '{zone_name}' using ONLY evidence. "
            f"Maximum {max_words} words. Describe what this faction does in this zone only. "
            "Write from the entry-state perspective: present tense for active roles, past tense "
            "only for older identity context, and no current-storyline outcomes. "
            "Do not copy generic faction wiki ledes, geography lists, reputation/achievement meta, or out-of-zone plot."
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
        user_prompt=f"Evidence:\n{_format_evidence_block(items)}",
        response_schema_name="wiki_first_faction_summary",
        substep="wiki_first_faction_summary",
    )
    summary = trim_faction_summary(clean_wiki_snippet(str(result.get("summary", ""))), max_words)
    used = [str(value) for value in result.get("used_evidence_ids", []) if str(value).strip()]
    if not summary:
        from pipeline.generate.draft.faction_scoring import fallback_faction_summary

        return fallback_faction_summary(
            items,
            max_words=max_words,
            zone_name=zone_name,
            subregion_tokens=subregion_tokens,
        )
    return summary, used


def synthesize_location_summary(
    items: list[dict[str, Any]],
    *,
    location_name: str,
    zone_name: str,
    max_words: int = 50,
) -> tuple[str, list[str]]:
    if not items:
        return "", []
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
                return summary, [str(item.get("source_id", ""))]
        return "", []
    from pipeline.generate.draft.location_lint import trim_location_summary

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
            f"Write an in-zone landmark summary for '{location_name}' in zone '{zone_name}' using ONLY evidence. "
            f"Maximum {max_words} words. Describe what this place is and does within this zone. "
            "Use encyclopedic tone. Do not copy generic wiki ledes, faction lists, adjacent-zone geography, "
            "dating conventions, reputation/achievement meta, or out-of-zone plot."
        ),
        user_prompt=f"Evidence:\n{_format_evidence_block(items)}",
        response_schema_name="wiki_first_location_summary",
        substep="wiki_first_location_summary",
    )
    summary = trim_location_summary(clean_wiki_snippet(str(result.get("summary", ""))), max_words)
    used = [str(value) for value in result.get("used_evidence_ids", []) if str(value).strip()]
    if not summary:
        ranked = sorted(
            items, key=lambda row: word_count(str(row.get("snippet", ""))), reverse=True
        )
        for item in ranked:
            snippet = trim_location_summary(
                clean_wiki_snippet(str(item.get("snippet", ""))), max_words
            )
            if snippet:
                return snippet, [str(item.get("source_id", ""))]
    return summary, used


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
        user_prompt=f"Evidence:\n{_format_evidence_block(items)}",
        response_schema_name="wiki_first_location_significance",
        substep="wiki_first_location_significance",
    )
    significance = trim_location_summary(
        clean_wiki_snippet(str(result.get("significance", ""))), max_words
    )
    used = [str(value) for value in result.get("used_evidence_ids", []) if str(value).strip()]
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
        user_prompt=f"Evidence:\n{_format_evidence_block(early_pool, max_items=2)}",
        response_schema_name="wiki_first_questline_cta_hook",
        substep="wiki_first_questline_cta_hook",
    )
    summary = finalize_cta_hook(
        trim_words(clean_wiki_snippet(str(result.get("summary", ""))), max_words),
        max_words=max_words,
    )
    used = [str(value) for value in result.get("used_evidence_ids", []) if str(value).strip()]
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
                _format_evidence_block(items, max_items=1).split("]", 1)[-1].strip()
            ),
            max_words,
        )
        return best, [str(items[0].get("source_id", ""))]
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
        user_prompt=f"Evidence:\n{_format_evidence_block(items)}",
        response_schema_name="wiki_first_card_summary",
        substep="wiki_first_card_summary",
    )
    summary = trim_words(clean_wiki_snippet(str(result.get("summary", ""))), max_words)
    used = [str(value) for value in result.get("used_evidence_ids", []) if str(value).strip()]
    return summary, used


def synthesize_instance_overview(
    items: list[dict[str, Any]],
    *,
    instance_name: str,
    max_words: int | None = None,
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
            user_prompt=f"Evidence:\n{_format_evidence_block(items, max_items=12)}",
            response_schema_name="wiki_first_instance_overview",
            substep="wiki_first_instance_overview",
        )

    result = enforce_non_passthrough(
        _call(""),
        call=_call,
        extract_bodies=lambda payload: [str(payload.get("summary", ""))],
        source_snippets=_evidence_snippets(items),
        label="overview",
    )
    summary = trim_instance_overview(
        clean_wiki_snippet(str(result.get("summary", ""))), max_words=max_words
    )
    used = [str(value) for value in result.get("used_evidence_ids", []) if str(value).strip()]
    if not summary:
        finalize_trace.record("overview.synth", path="llm_empty_fallback")
        return fallback_instance_overview(items, instance_name=instance_name, max_words=max_words)
    finalize_trace.record("overview.synth", path="llm", words=word_count(summary))
    return summary, used


def synthesize_key_character_summary(
    items: list[dict[str, Any]],
    *,
    boss_name: str,
    instance_name: str,
    structural_role: str = "",
    max_words: int = 50,
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
            task_lines=(
                f"Write a key-character card summary for '{boss_name}' in instance "
                f"'{instance_name}' using ONLY evidence. Maximum {max_words} words. "
                f"Align with the precomputed structural role '{structural_role or 'uncertain'}' "
                "without using meta labels as prose. Describe why the character is present here "
                "at entry state. No generic stubs, no current-storyline outcomes."
            ),
        ),
        user_prompt=f"Evidence:\n{_format_evidence_block(items)}",
        response_schema_name="wiki_first_key_character_summary",
        substep="wiki_first_key_character_summary",
    )
    summary = trim_key_character_summary(
        clean_wiki_snippet(str(result.get("summary", ""))), max_words=max_words
    )
    used = [str(value) for value in result.get("used_evidence_ids", []) if str(value).strip()]
    if not summary:
        return fallback_key_character_summary(
            items,
            boss_name=boss_name,
            instance_name=instance_name,
            max_words=max_words,
        )
    return summary, used
