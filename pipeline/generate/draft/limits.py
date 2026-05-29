"""Configurable output caps for draft generation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

# Must match ``QuestlineCard.story_beats`` max_length in pipeline.contracts.models.
CANONICAL_MAX_STORY_BEATS = 3


def _int_env(name: str, default: int, *, minimum: int = 0) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    stripped = raw.strip()
    if not stripped:
        return default
    return max(minimum, int(stripped))


@dataclass(frozen=True)
class DraftLimits:
    """Upper bounds applied after LLM generation (stitcher / legacy post-process)."""

    max_questlines_per_bucket: int
    max_story_beats: int
    max_link_cards: int
    max_glossary_terms: int


def load_draft_limits() -> DraftLimits:
    return DraftLimits(
        max_questlines_per_bucket=_int_env(
            "WOW_LORE_DRAFT_MAX_QUESTLINES_PER_BUCKET", 6, minimum=0
        ),
        max_story_beats=min(
            _int_env(
                "WOW_LORE_DRAFT_MAX_STORY_BEATS",
                CANONICAL_MAX_STORY_BEATS,
                minimum=1,
            ),
            CANONICAL_MAX_STORY_BEATS,
        ),
        max_link_cards=_int_env("WOW_LORE_DRAFT_MAX_LINK_CARDS", 12, minimum=0),
        max_glossary_terms=_int_env("WOW_LORE_DRAFT_MAX_GLOSSARY_TERMS", 24, minimum=0),
    )


def cap_prompt_hint(limits: DraftLimits | None = None) -> str:
    """Short cap reminder for LLM user prompts."""
    lim = limits or load_draft_limits()
    return (
        f"Caps: at most {lim.max_questlines_per_bucket} questline cards per faction bucket, "
        f"{lim.max_story_beats} story_beats per card, "
        f"{lim.max_link_cards} link cards per section, "
        f"{lim.max_glossary_terms} glossary term_ids."
    )


def apply_body_caps(body: dict[str, Any], limits: DraftLimits | None = None) -> None:
    """Trim lists in a draft body dict in place."""
    lim = limits or load_draft_limits()
    for bucket in (
        "major_questlines_alliance",
        "major_questlines_horde",
        "major_questlines_shared",
    ):
        cards = body.get(bucket)
        if isinstance(cards, list) and lim.max_questlines_per_bucket >= 0:
            trimmed_cards = cards[: lim.max_questlines_per_bucket]
            body[bucket] = trimmed_cards
            for card in trimmed_cards:
                if isinstance(card, dict):
                    beats = card.get("story_beats")
                    if isinstance(beats, list):
                        card["story_beats"] = beats[: lim.max_story_beats]
    for section in ("major_characters", "instances", "major_landmarks", "key_characters"):
        items = body.get(section)
        if isinstance(items, list) and lim.max_link_cards >= 0:
            body[section] = items[: lim.max_link_cards]
    glossary = body.get("glossary")
    if isinstance(glossary, list) and lim.max_glossary_terms >= 0:
        body["glossary"] = glossary[: lim.max_glossary_terms]
