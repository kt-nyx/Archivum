"""Shared helpers for draft generation."""

from __future__ import annotations

import re
from typing import Any

WORD_RE = re.compile(r"\b[\w']+\b")


def normalize_questline_criteria_breakdowns(body: dict[str, Any]) -> None:
    """Coerce LLM ``criteria_breakdown`` rows to ``dict[str, int]`` for Pydantic contracts."""
    for bucket in (
        "major_questlines_alliance",
        "major_questlines_horde",
        "major_questlines_shared",
    ):
        cards = body.get(bucket)
        if not isinstance(cards, list):
            continue
        for card in cards:
            if not isinstance(card, dict):
                continue
            inc = card.get("inclusion_decision")
            if not isinstance(inc, dict):
                continue
            raw = inc.get("criteria_breakdown")
            if isinstance(raw, list):
                merged: dict[str, int] = {}
                for row in raw:
                    if not isinstance(row, dict):
                        continue
                    criterion = str(row.get("criterion", "")).strip()
                    score = row.get("score")
                    if criterion and isinstance(score, int) and 0 <= score <= 2:
                        merged[criterion] = score
                inc["criteria_breakdown"] = merged


def word_count(value: str) -> int:
    return len(WORD_RE.findall(value))


def min_pointers(text: str) -> int:
    words = word_count(text)
    if words <= 120:
        return 1
    if words <= 240:
        return 2
    return 3


def pointer(source_id: str, revision_id: str, locator: str, excerpt_hash: str) -> dict[str, str]:
    return {
        "source_id": source_id,
        "locator": locator,
        "revision_id": revision_id,
        "excerpt_hash": excerpt_hash,
    }


def pointer_from_fact_item(item: dict[str, Any], *, entity_id: str) -> dict[str, str]:
    fields = ("source_id", "revision_id", "locator", "excerpt_hash")
    values: dict[str, str] = {}
    for field in fields:
        raw_value = item.get(field)
        if not isinstance(raw_value, str) or not raw_value.strip():
            raise RuntimeError(
                f"draft provenance for entity '{entity_id}' is missing required "
                f"fact_item field '{field}'"
            )
        values[field] = raw_value.strip()
    return pointer(
        values["source_id"],
        values["revision_id"],
        values["locator"],
        values["excerpt_hash"],
    )


def pick_pointers(
    fact_items: list[dict[str, Any]],
    min_count: int,
    *,
    entity_id: str,
) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    if not fact_items and min_count > 0:
        raise RuntimeError(
            f"draft provenance for entity '{entity_id}' requires source fact_items "
            "but none were provided"
        )
    if not fact_items:
        return output
    for idx in range(max(min_count, 1)):
        item = fact_items[idx % len(fact_items)]
        output.append(pointer_from_fact_item(item, entity_id=entity_id))
    return output


def source_entries(fact_pack: dict[str, Any]) -> list[dict[str, str]]:
    source_ids = [str(value) for value in fact_pack["source_ids"]]
    revision_ids = [str(value) for value in fact_pack["revision_ids"]]
    raw_source_urls = fact_pack.get("source_urls", {})
    if not isinstance(raw_source_urls, dict):
        raise RuntimeError("fact pack missing source_urls mapping")
    source_urls = {str(key): str(value) for key, value in raw_source_urls.items()}
    entries: list[dict[str, str]] = []
    for idx in range(min(len(source_ids), len(revision_ids))):
        source_id = source_ids[idx]
        source_url = source_urls.get(source_id, "").strip()
        if not source_url:
            raise RuntimeError(f"fact pack missing source_url for source_id '{source_id}'")
        entries.append(
            {
                "source_id": source_id,
                "url": source_url,
                "revision_id": revision_ids[idx],
            }
        )
    return entries


def claims_text(fact_pack: dict[str, Any], *, limit: int = 12) -> str:
    claims = [str(claim) for claim in fact_pack.get("claims", [])]
    return "\n".join(f"- {claim}" for claim in claims[:limit])


def entity_header(fact_pack: dict[str, Any]) -> str:
    return (
        f"Entity: {fact_pack['name']} ({fact_pack['slug']})\nEntity id: {fact_pack['entity_id']}\n"
    )


def filter_claims_for_keywords(
    fact_pack: dict[str, Any],
    keywords: list[str],
    *,
    fallback_limit: int = 8,
) -> str:
    claims = [str(c) for c in fact_pack.get("claims", [])]
    if not keywords:
        return "\n".join(f"- {c}" for c in claims[:fallback_limit])
    lowered = [k.lower() for k in keywords if k.strip()]
    matched = [c for c in claims if any(k in c.lower() for k in lowered)]
    picked = matched[:fallback_limit] if matched else claims[:fallback_limit]
    return "\n".join(f"- {c}" for c in picked)


def assign_questline_factions(body: dict[str, Any]) -> None:
    for bucket, faction in (
        ("major_questlines_alliance", "alliance"),
        ("major_questlines_horde", "horde"),
        ("major_questlines_shared", "shared"),
    ):
        cards = body.get(bucket, [])
        if not isinstance(cards, list):
            raise RuntimeError(f"draft missing {bucket} list")
        for card in cards:
            if isinstance(card, dict):
                card["faction"] = faction
