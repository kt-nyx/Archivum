"""Zone-agnostic faction candidate collection, scoring, and election for major_factions."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from pipeline.common.draft_vocab import era_section_role_tokens
from pipeline.generate.draft.faction_lint import trim_faction_summary
from pipeline.generate.draft.prose_lint import has_currently_meta, word_count

MIN_FACTION_CARDS = 2
MAX_FACTION_CARDS = 6
MIN_SCORE = 2.0
ALLIANCE_HORDE_CONFLICT_THRESHOLD = 2

_ALLIANCE_HORDE_IDS = frozenset({"faction-alliance", "faction-horde"})

# WS-C: era tokens externalized + de-duplicated (shared with prose_election) in
# pipeline/data/draft_classification_vocab.v1.json (D-6).
_ERA_TOKENS = era_section_role_tokens()

_HIGH_WEIGHT_ROLES = frozenset({"quests_edit", "quests", "quests_or_storyline"})
_LEDE_ROLES = frozenset({"lead", "introduction"})

_BINDING_BY_FACTION_ID: dict[str, frozenset[str]] = {
    "faction-alliance": frozenset({"alliance"}),
    "faction-horde": frozenset({"horde"}),
    "faction-forsaken": frozenset({"horde", "neutral", "shared"}),
}

MAX_FACTION_SUMMARY_WORDS = 40


@dataclass
class FactionCandidate:
    faction_id: str
    name: str
    wiki_url: str
    profile_items: list[dict[str, Any]] = field(default_factory=list)
    seed_mentions: list[dict[str, Any]] = field(default_factory=list)
    quest_binding_count: int = 0
    score: float = 0.0
    has_high_weight_seed: bool = False
    lede_only: bool = False


def _normalize_role(section_role: str) -> str:
    return re.sub(r"\s+", " ", section_role.strip()).lower().replace(" ", "_")


def _wiki_url_from_link(link: str) -> str:
    link = link.strip()
    if link.startswith("http"):
        return link
    if link.startswith("/wiki/"):
        return f"https://warcraft.wiki.gg{link}"
    slug = link.replace(" ", "_")
    return f"https://warcraft.wiki.gg/wiki/{slug}"


def _wiki_url_from_name(name: str) -> str:
    slug = name.strip().replace(" ", "_")
    return f"https://warcraft.wiki.gg/wiki/{slug}"


def _name_in_text(name: str, text: str) -> bool:
    if not name or not text:
        return False
    pattern = rf"\b{re.escape(name)}\b"
    return bool(re.search(pattern, text, re.IGNORECASE))


def _bindings_for_faction_id(faction_id: str) -> frozenset[str]:
    if faction_id in _BINDING_BY_FACTION_ID:
        return _BINDING_BY_FACTION_ID[faction_id]
    slug = faction_id.removeprefix("faction-").replace("-", " ")
    return frozenset({slug, "shared", "neutral"})


def _count_quest_bindings(faction_id: str, v3_rows: list[dict[str, Any]], zone_id: str) -> int:
    bindings = _bindings_for_faction_id(faction_id)
    count = 0
    for row in v3_rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("zone_id", "")) != zone_id:
            continue
        if str(row.get("node_type", "")) != "quest":
            continue
        binding = str(row.get("faction_binding", "shared")).strip().lower()
        if binding in bindings:
            count += 1
    return count


def _targets_for_zone(
    faction_profile_targets: list[dict[str, Any]] | None,
    zone_id: str,
) -> dict[str, dict[str, Any]]:
    targets: dict[str, dict[str, Any]] = {}
    for row in faction_profile_targets or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("zone_id", "")).strip() != zone_id:
            continue
        faction_id = str(row.get("faction_id", "")).strip()
        if not faction_id:
            continue
        targets[faction_id] = row
    return targets


def _candidates_from_evidence(
    evidence_rows: list[dict[str, Any]],
    zone_id: str,
) -> dict[str, dict[str, str]]:
    discovered: dict[str, dict[str, str]] = {}
    for row in evidence_rows:
        if str(row.get("field_name", "")) != "faction_pool":
            continue
        build_meta = row.get("build_meta") or {}
        subject_zone = str(build_meta.get("subject_zone_id", row.get("subject_id", ""))).strip()
        if subject_zone and subject_zone != zone_id:
            continue
        faction_id = str(build_meta.get("faction_id", "")).strip()
        if not faction_id:
            continue
        name = str(build_meta.get("faction_name", "")).strip()
        if not name:
            items = row.get("evidence_items") or []
            if items and isinstance(items[0], dict):
                name = str(items[0].get("source_title", "")).strip()
        discovered[faction_id] = {
            "name": name or faction_id.removeprefix("faction-").replace("-", " ").title(),
            "wiki_url": "",
        }
    return discovered


def _discover_candidates_from_v3_bindings(
    v3_rows: list[dict[str, Any]] | None,
    zone_id: str,
) -> dict[str, str]:
    discovered: dict[str, str] = {}
    if not v3_rows:
        return discovered
    for faction_id, display_name in (
        ("faction-alliance", "Alliance"),
        ("faction-horde", "Horde"),
    ):
        if _count_quest_bindings(faction_id, v3_rows, zone_id) >= ALLIANCE_HORDE_CONFLICT_THRESHOLD:
            discovered[faction_id] = display_name
    return discovered


def _is_high_weight_seed_item(item: dict[str, Any]) -> bool:
    role = _normalize_role(str(item.get("section_role", "")))
    field_name = str(item.get("field_name", "")).strip()
    if field_name == "currently_input":
        return True
    if role in _HIGH_WEIGHT_ROLES:
        return True
    if role.endswith("_edit") and any(token in role for token in _ERA_TOKENS):
        return True
    return False


def _candidate_is_finalize_eligible(candidate: FactionCandidate) -> bool:
    if candidate.lede_only or candidate.score <= 0:
        return False
    return _alliance_horde_conflict_met(candidate)


def collect_faction_candidates(
    *,
    zone_id: str,
    evidence_rows: list[dict[str, Any]],
    pools: dict[str, list[dict[str, Any]]],
    faction_profile_targets: list[dict[str, Any]] | None = None,
    v3_rows: list[dict[str, Any]] | None = None,
) -> list[FactionCandidate]:
    target_map = _targets_for_zone(faction_profile_targets, zone_id)
    discovered = _candidates_from_evidence(evidence_rows, zone_id)
    faction_pool = pools.get("faction_pool", [])
    faction_role_pool = pools.get("faction_role_pool", [])

    candidate_ids = set(target_map) | set(discovered)
    v3_discovered = _discover_candidates_from_v3_bindings(v3_rows, zone_id)
    candidate_ids.update(v3_discovered)

    candidates: list[FactionCandidate] = []
    for faction_id in sorted(candidate_ids):
        target = target_map.get(faction_id, {})
        meta = discovered.get(faction_id, {})
        name = str(
            target.get("name")
            or meta.get("name")
            or v3_discovered.get(faction_id)
            or ""
        ).strip()
        if not name:
            name = faction_id.removeprefix("faction-").replace("-", " ").title()
        link = str(target.get("source_link", "")).strip()
        wiki_url = _wiki_url_from_link(link) if link else _wiki_url_from_name(name)

        profile_items = [
            item
            for item in faction_pool
            if str(item.get("faction_id", "")).strip() == faction_id
            or (
                not str(item.get("faction_id", "")).strip()
                and name.lower() in str(item.get("source_title", "")).lower()
            )
        ]
        seed_mentions = [
            item
            for item in faction_role_pool
            if _name_in_text(name, str(item.get("snippet", "")))
        ]

        candidates.append(
            FactionCandidate(
                faction_id=faction_id,
                name=name,
                wiki_url=wiki_url,
                profile_items=profile_items,
                seed_mentions=seed_mentions,
                quest_binding_count=_count_quest_bindings(faction_id, v3_rows or [], zone_id),
            )
        )

    return candidates


def _is_lede_only_profile(candidate: FactionCandidate) -> bool:
    if candidate.seed_mentions:
        return False
    if not candidate.profile_items:
        return False
    roles = {_normalize_role(str(item.get("section_role", ""))) for item in candidate.profile_items}
    return roles.issubset(_LEDE_ROLES) and len(candidate.profile_items) <= 2


def alliance_horde_conflict_met(
    *,
    faction_id: str,
    quest_binding_count: int,
    seed_mentions: list[dict[str, Any]],
) -> bool:
    if faction_id not in _ALLIANCE_HORDE_IDS:
        return True
    if quest_binding_count >= ALLIANCE_HORDE_CONFLICT_THRESHOLD:
        return True
    for item in seed_mentions:
        snippet = str(item.get("snippet", ""))
        if has_currently_meta(snippet):
            continue
        if _is_high_weight_seed_item(item):
            return True
    return False


def _alliance_horde_conflict_met(candidate: FactionCandidate) -> bool:
    return alliance_horde_conflict_met(
        faction_id=candidate.faction_id,
        quest_binding_count=candidate.quest_binding_count,
        seed_mentions=candidate.seed_mentions,
    )


def score_faction_candidate(
    candidate: FactionCandidate,
    *,
    zone_name: str = "",
    subregion_tokens: list[str] | None = None,
) -> FactionCandidate:
    score = 0.0
    has_high = False
    tokens = subregion_tokens or []

    for item in candidate.seed_mentions:
        snippet = str(item.get("snippet", ""))
        if has_currently_meta(snippet):
            continue
        role = _normalize_role(str(item.get("section_role", "")))
        field_name = str(item.get("field_name", ""))
        zone_hit = _name_in_text(zone_name, snippet) or any(_name_in_text(token, snippet) for token in tokens)
        if _is_high_weight_seed_item(item):
            score += 3.0 + (1.5 if zone_hit else 0.0)
            has_high = True
        elif field_name in {"currently_input", "history_digest"} or role.startswith("history"):
            score += 1.5 + (1.0 if zone_hit else 0.0)
        else:
            score += 0.75 + (0.5 if zone_hit else 0.0)

    if candidate.profile_items:
        profile_zone_hit = any(
            _name_in_text(zone_name, str(item.get("snippet", "")))
            or any(_name_in_text(token, str(item.get("snippet", ""))) for token in tokens)
            for item in candidate.profile_items
        )
        score += 2.0 if profile_zone_hit else 1.0

    if candidate.quest_binding_count:
        score += min(candidate.quest_binding_count * 1.5, 4.5)

    candidate.has_high_weight_seed = has_high
    candidate.lede_only = _is_lede_only_profile(candidate)

    if candidate.lede_only and not candidate.seed_mentions and candidate.quest_binding_count == 0:
        lede_has_zone = any(
            _name_in_text(zone_name, str(item.get("snippet", "")))
            or any(_name_in_text(token, str(item.get("snippet", ""))) for token in tokens)
            for item in candidate.profile_items
        )
        if not lede_has_zone:
            candidate.score = 0.0
            return candidate

    if candidate.faction_id in _ALLIANCE_HORDE_IDS and not _alliance_horde_conflict_met(candidate):
        candidate.score = min(score, 1.0)
        return candidate

    candidate.score = score
    return candidate


def rank_faction_candidates(
    candidates: list[FactionCandidate],
    *,
    zone_name: str = "",
    subregion_tokens: list[str] | None = None,
) -> list[FactionCandidate]:
    scored = [
        score_faction_candidate(candidate, zone_name=zone_name, subregion_tokens=subregion_tokens)
        for candidate in candidates
    ]
    return sorted(
        scored,
        key=lambda row: (
            -row.score,
            -len(row.profile_items),
            row.name.lower(),
        ),
    )


def select_major_factions(
    candidates: list[FactionCandidate],
    *,
    zone_name: str = "",
    subregion_tokens: list[str] | None = None,
) -> list[FactionCandidate]:
    ranked = rank_faction_candidates(candidates, zone_name=zone_name, subregion_tokens=subregion_tokens)
    eligible = [candidate for candidate in ranked if candidate.score >= MIN_SCORE and not candidate.lede_only]
    if not eligible:
        thin = [candidate for candidate in ranked if _candidate_is_finalize_eligible(candidate)]
        return thin[:MAX_FACTION_CARDS]
    if len(eligible) <= MIN_FACTION_CARDS:
        return eligible[:MAX_FACTION_CARDS]
    return eligible[:MAX_FACTION_CARDS]


def candidates_for_finalize(
    candidates: list[FactionCandidate],
    *,
    zone_name: str = "",
    subregion_tokens: list[str] | None = None,
) -> tuple[int, list[FactionCandidate]]:
    ranked = rank_faction_candidates(candidates, zone_name=zone_name, subregion_tokens=subregion_tokens)
    target_count = len(select_major_factions(candidates, zone_name=zone_name, subregion_tokens=subregion_tokens))
    has_eligible = any(
        candidate.score >= MIN_SCORE and not candidate.lede_only for candidate in ranked
    )
    if has_eligible:
        queue = [
            candidate
            for candidate in ranked
            if candidate.score >= MIN_SCORE
            and not candidate.lede_only
            and _alliance_horde_conflict_met(candidate)
        ]
    else:
        queue = [candidate for candidate in ranked if _candidate_is_finalize_eligible(candidate)]
    return target_count, queue


def finalize_evidence_pools(candidate: FactionCandidate) -> list[list[dict[str, Any]]]:
    pools: list[list[dict[str, Any]]] = []
    if candidate.profile_items:
        pools.append(candidate.profile_items)
    if candidate.seed_mentions and (
        not candidate.profile_items or candidate.seed_mentions != candidate.profile_items
    ):
        pools.append(candidate.seed_mentions)
    return pools


def fallback_faction_summary(
    items: list[dict[str, Any]],
    *,
    max_words: int = MAX_FACTION_SUMMARY_WORDS,
    zone_name: str = "",
    subregion_tokens: list[str] | None = None,
) -> tuple[str, list[str]]:
    if not items:
        return "", []
    tokens = subregion_tokens or []

    def _zone_rank(item: dict[str, Any]) -> tuple[int, int]:
        snippet = str(item.get("snippet", ""))
        zone_hit = _name_in_text(zone_name, snippet) or any(_name_in_text(token, snippet) for token in tokens)
        return (1 if zone_hit else 0, word_count(snippet))

    ranked = sorted(items, key=_zone_rank, reverse=True)
    for item in ranked:
        snippet = str(item.get("snippet", "")).strip()
        if has_currently_meta(snippet):
            continue
        summary = trim_faction_summary(snippet, max_words)
        if summary:
            source_id = str(item.get("source_id", "")).strip()
            return summary, [source_id] if source_id else []
    return "", []
