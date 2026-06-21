"""Constrained LLM prose synthesis workers for draft page assembly."""

from __future__ import annotations

import os
from typing import Any

from pipeline.ai.config import load_ai_settings
from pipeline.common.text_normalize import clean_wiki_snippet
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
from pipeline.generate.draft.prose_lint import (
    MAX_HISTORY_SECTIONS,
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
                f"Write a concise zone at-a-glance summary using ONLY the evidence snippets. "
                f"Maximum {max_words} words. Do not list locations, characters, factions, or patch/reputation meta. "
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
        sections: list[dict[str, Any]] = []
        used: list[str] = []
        for item in items[:max_sections]:
            snippet = clean_wiki_snippet(str(item.get("snippet", "")))
            if not snippet:
                continue
            heading = history_heading_from_role(str(item.get("section_role", "other")))
            sections.append({"heading": heading, "body": snippet, "source_refs": []})
            used.append(str(item.get("source_id", "")))
        return sections, used
    result = llm_json_with_retry(
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
            task_lines=(
                "Produce chronological historical arc sections from evidence only. "
                f"Up to {max_sections} sections with short era headings. "
                "Do not list locations. Cover through the latest era in evidence."
            ),
        ),
        user_prompt=f"Evidence:\n{_format_evidence_block(items, max_items=max_sections)}",
        response_schema_name="wiki_first_history",
        substep="wiki_first_history",
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
        sections = []
        used_ids: list[str] = []
        for item in items[:max_sections]:
            snippet = clean_wiki_snippet(str(item.get("snippet", "")))
            if not snippet:
                continue
            heading = history_heading_from_role(str(item.get("section_role", "other")))
            sections.append({"heading": heading, "body": snippet, "source_refs": []})
            used_ids.append(str(item.get("source_id", "")))
        return sections, used_ids
    return sections_out, used


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
                "Use present tense for active roles; past tense for defunct leadership when "
                "evidence is historical."
            ),
        )
    else:
        system_prompt = (
            f"Write a zone-role summary for faction '{faction_name}' in zone '{zone_name}' using ONLY evidence. "
            f"Maximum {max_words} words. Describe what this faction does in this zone only. "
            "Use present tense for active roles; past tense for defunct leadership when evidence is historical. "
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


def _early_chain_ref_limit(chain_refs: list[str], *, arc_title: str) -> int:
    if "andorhal" in arc_title.lower():
        return 6
    return 4 if len(chain_refs) <= 8 else 6


def filter_early_chain_evidence_pool(
    items: list[dict[str, Any]],
    chain_refs: list[str],
    *,
    arc_title: str = "",
) -> list[dict[str, Any]]:
    if not items:
        return []
    limit = _early_chain_ref_limit(chain_refs, arc_title=arc_title)
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
                hook = finalize_cta_hook(trim_words(description, max_words), max_words=max_words)
                if hook and hook.lower() != arc_title.strip().lower():
                    return hook, [node_id]
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
            f" Max {max_words} words.{faction_addendum}"
        ),
        user_prompt=f"Evidence:\n{_format_evidence_block(early_pool, max_items=6)}",
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
    max_words: int = 320,
) -> tuple[str, list[str]]:
    if not items:
        return "", []
    from pipeline.generate.draft.instance_lint import (
        fallback_instance_overview,
        trim_instance_overview,
    )

    settings = load_ai_settings()
    if not settings.openai_ready or os.environ.get("WOW_LORE_WIKI_FIRST_NO_LLM", "").lower() in {
        "1",
        "true",
        "yes",
    }:
        return fallback_instance_overview(items, instance_name=instance_name, max_words=max_words)
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
            field_voice=INSTANCE_OVERVIEW_VOICE,
            task_lines=(
                f"Write an in-universe story-context overview for instance '{instance_name}' "
                f"using ONLY evidence. Target 170-{max_words} words."
            ),
        ),
        user_prompt=f"Evidence:\n{_format_evidence_block(items, max_items=12)}",
        response_schema_name="wiki_first_instance_overview",
        substep="wiki_first_instance_overview",
    )
    summary = trim_instance_overview(
        clean_wiki_snippet(str(result.get("summary", ""))), max_words=max_words
    )
    used = [str(value) for value in result.get("used_evidence_ids", []) if str(value).strip()]
    if not summary:
        return fallback_instance_overview(items, instance_name=instance_name, max_words=max_words)
    return summary, used


def synthesize_key_character_summary(
    items: list[dict[str, Any]],
    *,
    boss_name: str,
    instance_name: str,
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
                "No generic stubs."
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
