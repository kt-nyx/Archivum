"""Constrained LLM synthesis workers for wiki-first draft assembly."""

from __future__ import annotations

import os
from typing import Any

from pipeline.ai.config import load_ai_settings
from pipeline.common.text_normalize import clean_wiki_snippet
from pipeline.generate.draft.llm import llm_json_with_retry


def _format_evidence_block(items: list[dict[str, Any]], *, max_items: int = 8) -> str:
    lines: list[str] = []
    for index, item in enumerate(items[:max_items], start=1):
        snippet = clean_wiki_snippet(str(item.get("snippet", "")))
        if not snippet:
            continue
        source_id = str(item.get("source_id", f"ev-{index}"))
        lines.append(f"[{source_id}] {snippet}")
    return "\n".join(lines)


def _trim_words(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text.strip()
    return " ".join(words[:max_words]).strip()


def synthesize_at_a_glance(items: list[dict[str, Any]], *, max_words: int = 80) -> tuple[str, list[str]]:
    if not items:
        return "", []
    settings = load_ai_settings()
    if not settings.openai_ready or os.environ.get("WOW_LORE_WIKI_FIRST_NO_LLM", "").lower() in {"1", "true", "yes"}:
        best = max(items, key=lambda row: len(str(row.get("snippet", ""))))
        return _trim_words(clean_wiki_snippet(str(best.get("snippet", ""))), max_words), [
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
        system_prompt=(
            "Write a concise zone at-a-glance summary using ONLY the evidence snippets. "
            f"Maximum {max_words} words. Present tense. No extrapolation."
        ),
        user_prompt=f"Evidence:\n{_format_evidence_block(items)}",
        response_schema_name="wiki_first_at_a_glance",
        substep="wiki_first_at_a_glance",
    )
    summary = _trim_words(clean_wiki_snippet(str(result.get("summary", ""))), max_words)
    used = [str(value) for value in result.get("used_evidence_ids", []) if str(value).strip()]
    if not summary:
        best = max(items, key=lambda row: len(str(row.get("snippet", ""))))
        summary = _trim_words(clean_wiki_snippet(str(best.get("snippet", ""))), max_words)
        used = [str(best.get("source_id", ""))]
    return summary, used


def synthesize_currently(items: list[dict[str, Any]], *, max_words: int = 120) -> tuple[str, list[str]]:
    if not items:
        return "", []
    settings = load_ai_settings()
    if not settings.openai_ready or os.environ.get("WOW_LORE_WIKI_FIRST_NO_LLM", "").lower() in {"1", "true", "yes"}:
        best = max(items, key=lambda row: len(str(row.get("snippet", ""))))
        return _trim_words(clean_wiki_snippet(str(best.get("snippet", ""))), max_words), [
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
        system_prompt=(
            "Write a present-tense 'currently' zone summary using ONLY evidence snippets. "
            f"Maximum {max_words} words. Avoid quest walkthrough tone."
        ),
        user_prompt=f"Evidence:\n{_format_evidence_block(items)}",
        response_schema_name="wiki_first_currently",
        substep="wiki_first_currently",
    )
    summary = _trim_words(clean_wiki_snippet(str(result.get("summary", ""))), max_words)
    used = [str(value) for value in result.get("used_evidence_ids", []) if str(value).strip()]
    if not summary:
        best = max(items, key=lambda row: len(str(row.get("snippet", ""))))
        summary = _trim_words(clean_wiki_snippet(str(best.get("snippet", ""))), max_words)
        used = [str(best.get("source_id", ""))]
    return summary, used


def synthesize_history_sections(
    items: list[dict[str, Any]], *, max_sections: int = 4
) -> tuple[list[dict[str, Any]], list[str]]:
    if not items:
        return [], []
    settings = load_ai_settings()
    if not settings.openai_ready or os.environ.get("WOW_LORE_WIKI_FIRST_NO_LLM", "").lower() in {"1", "true", "yes"}:
        sections: list[dict[str, Any]] = []
        used: list[str] = []
        for index, item in enumerate(items[:max_sections], start=1):
            snippet = clean_wiki_snippet(str(item.get("snippet", "")))
            if not snippet:
                continue
            sections.append({"heading": f"Era {index}", "body": snippet, "source_refs": []})
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
        system_prompt=(
            "Produce historical arc sections from evidence only. "
            f"Up to {max_sections} sections with short headings and concise bodies."
        ),
        user_prompt=f"Evidence:\n{_format_evidence_block(items)}",
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
        for index, item in enumerate(items[:max_sections], start=1):
            snippet = clean_wiki_snippet(str(item.get("snippet", "")))
            if not snippet:
                continue
            sections.append({"heading": f"Era {index}", "body": snippet, "source_refs": []})
            used_ids.append(str(item.get("source_id", "")))
        return sections, used_ids
    return sections_out, used


def synthesize_card_summary(
    items: list[dict[str, Any]],
    *,
    subject: str,
    max_words: int = 40,
) -> tuple[str, list[str]]:
    if not items:
        return "", []
    settings = load_ai_settings()
    if not settings.openai_ready or os.environ.get("WOW_LORE_WIKI_FIRST_NO_LLM", "").lower() in {"1", "true", "yes"}:
        best = _trim_words(
            clean_wiki_snippet(_format_evidence_block(items, max_items=1).split("]", 1)[-1].strip()),
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
        ),
        user_prompt=f"Evidence:\n{_format_evidence_block(items)}",
        response_schema_name="wiki_first_card_summary",
        substep="wiki_first_card_summary",
    )
    summary = _trim_words(clean_wiki_snippet(str(result.get("summary", ""))), max_words)
    used = [str(value) for value in result.get("used_evidence_ids", []) if str(value).strip()]
    return summary, used
