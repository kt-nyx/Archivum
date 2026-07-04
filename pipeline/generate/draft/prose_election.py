"""Zone-agnostic evidence election for wiki-first zone prose workers."""

from __future__ import annotations

import re
from typing import Any

from pipeline.common.draft_vocab import era_section_role_tokens
from pipeline.common.wiki_evidence_filters import should_exclude_from_history
from pipeline.contracts.models import ZONE_PAGE_BUDGET_RULES
from pipeline.generate.draft.claim_routing import prefer_entry_state_first
from pipeline.generate.draft.prose_lint import (
    MAX_AT_A_GLANCE_WORDS,
    MAX_HISTORY_SECTIONS,
    has_currently_meta,
    has_geography_hub_in_text,
    has_historical_framing,
    has_location_list_dump,
    has_player_directive,
    has_present_state_framing,
    trim_words,
    word_count,
)

# WS-C: expansion-name era tokens externalized + de-duplicated (also used by
# faction_scoring) in pipeline/data/draft_classification_vocab.v1.json (D-6).
_ERA_TOKENS = era_section_role_tokens()

_CURRENTLY_QUEST_ROLES = frozenset({"quests_edit", "quests", "quests_or_storyline"})

_HISTORY_EXCLUDED_ROLES = frozenset(
    {
        "geography_edit",
        "geography",
        "maps_subregions",
        "getting_there_edit",
        "getting_there",
        "resources_edit",
        "resources",
        "in_the_rpg_edit",
        "in_the_rpg",
    }
)

_AT_A_GLANCE_MAX_ITEMS = 16
_HISTORY_MIN_WORDS = 25
_HISTORY_BUMP_WORDS = 800


def _normalize_role(section_role: str) -> str:
    return re.sub(r"\s+", " ", section_role.strip()).lower().replace(" ", "_")


def _role_sort_key(section_role: str) -> tuple[int, int, str]:
    role = _normalize_role(section_role)
    if role in {"lead", "introduction"}:
        return (0, 0, role)
    if role.startswith("history"):
        return (1, 0, role)
    era_rank = next((index for index, token in enumerate(_ERA_TOKENS) if token in role), 99)
    if role.endswith("_edit") or any(token in role for token in _ERA_TOKENS):
        return (2, era_rank, role)
    return (3, 0, role)


def _is_excluded_currently_snippet(snippet: str, *, zone_name: str = "") -> bool:
    text = snippet.strip()
    if not text:
        return True
    if has_currently_meta(text):
        return True
    if has_player_directive(text):
        return True
    if has_historical_framing(text):
        return True
    if has_geography_hub_in_text(text):
        return True
    if zone_name and zone_name.lower() in text.lower() and word_count(text) < 16:
        return False
    return False


def _is_present_state_lore(snippet: str) -> bool:
    """A lore snippet describing the zone's ongoing present state (present-tense active framing).

    Tolerates named landmarks within the narrative (rejecting only an actual location *list dump*),
    since present-state lore legitimately names where the recovery and conflict are happening.
    """
    text = snippet.strip()
    if not text or not has_present_state_framing(text):
        return False
    if has_currently_meta(text) or has_player_directive(text):
        return False
    if has_historical_framing(text) or has_location_list_dump(text):
        return False
    return True


def _tier_present_state_lore(items: list[dict[str, Any]], *, zone_name: str) -> list[dict[str, Any]]:
    """Promote present-state lore above quest-objective evidence.

    A zone whose evidence carries genuine present-state lore ("the Argent Crusade is still active...
    Mardenholde Keep has become a training ground") should surface that instead of a player-facing
    quest directive. Present-state snippets are moved to the front; the remaining safe (non-excluded)
    items are kept as a tail so the claim-reorder contract — promote, never drop a safe claim — holds
    even when a present-state verb falls outside the framing lexicon.
    """
    present = [item for item in items if _is_present_state_lore(str(item.get("snippet", "")))]
    if not present:
        return []
    rest = [
        item
        for item in items
        if item not in present
        and not _is_excluded_currently_snippet(str(item.get("snippet", "")), zone_name=zone_name)
    ]
    return present + rest


def _dedupe_items(items: list[dict[str, Any]], *, max_items: int) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in items:
        snippet = str(item.get("snippet", "")).strip().lower()
        if not snippet:
            continue
        key = snippet[:120]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
        if len(deduped) >= max_items:
            break
    return deduped


def select_at_a_glance_pool(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not items:
        return []
    ranked = sorted(
        items,
        key=lambda row: (
            _role_sort_key(str(row.get("section_role", "other"))),
            -word_count(str(row.get("snippet", ""))),
        ),
    )
    # Slice 8 task 2: prefer entry-state identity claims over older origin claims when both are
    # present. Claim-only and stable, so paragraph-fallback pools are unchanged.
    ranked = prefer_entry_state_first(ranked)
    return _dedupe_items(ranked, max_items=_AT_A_GLANCE_MAX_ITEMS)


def precompress_at_a_glance_evidence(
    items: list[dict[str, Any]], *, max_items: int = 12
) -> list[dict[str, Any]]:
    """Deterministically trim a large at-a-glance pool before LLM synthesis."""
    if (
        len(items) <= max_items
        and sum(word_count(str(row.get("snippet", ""))) for row in items) <= 600
    ):
        return items
    compressed: list[dict[str, Any]] = []
    for index, item in enumerate(items[:max_items], start=1):
        snippet = trim_words(str(item.get("snippet", "")), 60)
        if not snippet:
            continue
        compressed.append(
            {
                **item,
                "snippet": f"{index}. {snippet}",
            }
        )
    return compressed or items[:max_items]


def _tier_expansion_edit(items: list[dict[str, Any]], *, zone_name: str) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for item in items:
        role = _normalize_role(str(item.get("section_role", "")))
        if not any(token in role for token in _ERA_TOKENS):
            continue
        if role in _HISTORY_EXCLUDED_ROLES:
            continue
        snippet = str(item.get("snippet", ""))
        if _is_excluded_currently_snippet(snippet, zone_name=zone_name):
            continue
        selected.append(item)
    return selected


def _tier_quests_edit(items: list[dict[str, Any]], *, zone_name: str) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for item in items:
        role = _normalize_role(str(item.get("section_role", "")))
        if role not in _CURRENTLY_QUEST_ROLES:
            continue
        snippet = str(item.get("snippet", ""))
        if _is_excluded_currently_snippet(snippet, zone_name=zone_name):
            continue
        selected.append(item)
    return selected


def _tier_cluster_lore(
    pools: dict[str, list[dict[str, Any]]], *, zone_name: str
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen_clusters: set[str] = set()
    for item in pools.get("quest_cluster_lore_pool", []):
        cluster_id = str(item.get("cluster_id", "")).strip()
        if cluster_id and cluster_id in seen_clusters:
            continue
        snippet = str(item.get("snippet", ""))
        if _is_excluded_currently_snippet(snippet, zone_name=zone_name):
            continue
        if cluster_id:
            seen_clusters.add(cluster_id)
        selected.append(item)
    return selected


def _zone_has_expansion_new_signal(currently_items: list[dict[str, Any]]) -> bool:
    for item in currently_items:
        role = _normalize_role(str(item.get("section_role", "")))
        if any(token in role for token in _ERA_TOKENS):
            return True
    return False


def _tier_latest_era_history(
    history_items: list[dict[str, Any]],
    *,
    zone_name: str,
    currently_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not _zone_has_expansion_new_signal(currently_items):
        return []
    era_items = [
        item
        for item in history_items
        if any(token in _normalize_role(str(item.get("section_role", ""))) for token in _ERA_TOKENS)
    ]
    if not era_items:
        return []
    last_item = era_items[-1]
    snippet = str(last_item.get("snippet", ""))
    if _is_excluded_currently_snippet(snippet, zone_name=zone_name):
        return []
    return [last_item]


def select_currently_pool(
    pools: dict[str, list[dict[str, Any]]],
    *,
    zone_name: str = "",
) -> list[dict[str, Any]]:
    currently_items = list(pools.get("currently_pool", []))
    for tier in (
        lambda: _tier_expansion_edit(currently_items, zone_name=zone_name),
        lambda: _tier_present_state_lore(currently_items, zone_name=zone_name),
        lambda: _tier_quests_edit(currently_items, zone_name=zone_name),
        lambda: _tier_cluster_lore(pools, zone_name=zone_name),
        lambda: _tier_latest_era_history(
            pools.get("history_pool", []),
            zone_name=zone_name,
            currently_items=currently_items,
        ),
    ):
        selected = tier()
        if selected:
            # Slice 8 task 1: prefer entry-state / safe-entry-context claims before older background
            # so the current summary anchors on the present. Claim-only and stable (no-op offline).
            return _dedupe_items(prefer_entry_state_first(selected), max_items=12)
    fallback = [
        item
        for item in currently_items
        if not _is_excluded_currently_snippet(str(item.get("snippet", "")), zone_name=zone_name)
    ]
    return _dedupe_items(prefer_entry_state_first(fallback), max_items=12)


def _history_sort_key(row: dict[str, Any]) -> tuple[int, str]:
    block_index = row.get("block_index", 0)
    try:
        index = int(block_index)
    except (TypeError, ValueError):
        index = 0
    return (index, str(row.get("source_id", "")))


def select_history_pool(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for item in items:
        role = _normalize_role(str(item.get("section_role", "")))
        if role in _HISTORY_EXCLUDED_ROLES or role == "in_the_rpg":
            continue
        if should_exclude_from_history(item):
            continue
        snippet = str(item.get("snippet", "")).strip()
        if word_count(snippet) < _HISTORY_MIN_WORDS:
            continue
        selected.append(item)
    return sorted(selected, key=_history_sort_key)


def history_section_cap(items: list[dict[str, Any]]) -> int:
    eligible = len(items)
    if eligible <= 0:
        return 0
    total_words = sum(word_count(str(item.get("snippet", ""))) for item in items)
    cap = min(MAX_HISTORY_SECTIONS, max(3, eligible))
    if total_words > _HISTORY_BUMP_WORDS:
        cap = MAX_HISTORY_SECTIONS
    return min(cap, eligible)


# Generic subsection slugs that name the parent section itself, not a distinct era;
# titling these adds no variety, so fall through to the canonical role / constant.
_GENERIC_HISTORY_SUBSECTIONS = frozenset(
    {"history", "lore", "background", "story", "lead", "introduction", "other"}
)


def history_heading_from_role(section_role: str, raw_section_role: str = "") -> str:
    """Derive a history-section heading.

    Prefer the actual wiki subsection heading (``raw_section_role``, e.g.
    ``"the_scourging_edit"`` -> ``"The Scourging"``) so distinct history subsections get
    distinct headings instead of the single ``"Historical era"`` constant (#8). Fall back
    to the canonical section-role label, then to the constant when nothing usable remains.
    """
    raw = _normalize_role(raw_section_role).replace("_edit", "").strip("_")
    if raw and raw not in _GENERIC_HISTORY_SUBSECTIONS:
        label = raw.replace("_", " ").strip()
        if label:
            return label.title()
    role = _normalize_role(section_role)
    if not role or role == "other":
        return "Historical era"
    label = role.replace("_edit", "").replace("_", " ").strip()
    if not label:
        return "Historical era"
    return label.title()


def ranked_at_a_glance_candidates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pool items in borrow-preference order for the offline at_a_glance ladder (best first).

    at_a_glance is a present-tense identity caption, so a snippet that frames the zone's present
    state ("is/remains a ...") outranks one that merely narrates the past; ties fall back to length.
    The offline finalizer walks this order until a candidate passes validation, so a lint-clean
    lead snippet still ships when the longest snippet reads as past-tense narration.
    """
    return sorted(
        items,
        key=lambda row: (
            has_present_state_framing(str(row.get("snippet", ""))),
            word_count(str(row.get("snippet", ""))),
        ),
        reverse=True,
    )


def fallback_at_a_glance(items: list[dict[str, Any]]) -> tuple[str, list[str]]:
    if not items:
        return "", []
    best = ranked_at_a_glance_candidates(items)[0]
    summary = trim_words(str(best.get("snippet", "")), MAX_AT_A_GLANCE_WORDS)
    source_id = str(best.get("source_id", "")).strip()
    return summary, [source_id] if source_id else []


def fallback_currently(
    items: list[dict[str, Any]],
    *,
    max_words: int = ZONE_PAGE_BUDGET_RULES["currently"].max_words,
) -> tuple[str, list[str]]:
    if not items:
        return "", []
    # Don't borrow the blindly-longest snippet: a player-facing quest directive ("Adventurers are
    # tasked with...") is usually the longest item in a quest-derived pool and reads as walkthrough
    # text. Drop directive / meta snippets, then prefer present-state lore framing over raw length.
    clean = [
        item
        for item in items
        if not has_player_directive(str(item.get("snippet", "")))
        and not has_currently_meta(str(item.get("snippet", "")))
    ]
    pool = clean or items
    best = max(
        pool,
        key=lambda row: (
            has_present_state_framing(str(row.get("snippet", ""))),
            word_count(str(row.get("snippet", ""))),
        ),
    )
    summary = trim_words(str(best.get("snippet", "")), max_words)
    source_id = str(best.get("source_id", "")).strip()
    return summary, [source_id] if source_id else []


def fallback_history_sections(
    items: list[dict[str, Any]],
    *,
    max_sections: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    sections: list[dict[str, Any]] = []
    used: list[str] = []
    for item in items[:max_sections]:
        snippet = str(item.get("snippet", "")).strip()
        if not snippet:
            continue
        heading = history_heading_from_role(
            str(item.get("section_role", "other")),
            str(item.get("raw_section_role", "")),
        )
        sections.append({"heading": heading, "body": snippet, "source_refs": []})
        source_id = str(item.get("source_id", "")).strip()
        if source_id:
            used.append(source_id)
    return sections, used
