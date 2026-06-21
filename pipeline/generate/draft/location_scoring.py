"""Zone-agnostic location candidate collection, relevance scoring, and election."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from pipeline.discovery.entity_typing import normalize_title, should_reject_location_title

MIN_LOCATION_CARDS = 3
MAX_LOCATION_CARDS = 8
MIN_SCORE = 2.0

_INCLUDE_CLASSIFICATIONS = frozenset({"city", "starter_area", "major_location_candidate"})
_LEDE_ROLES = frozenset({"lead", "introduction"})
_HIGH_WEIGHT_ROLES = frozenset({"maps_subregions", "geography_edit", "geography", "subregion"})
_MEDIUM_WEIGHT_ROLES = frozenset({"history_edit", "history"})
_SECTION_WEIGHTS = {
    "maps_subregions": 0.35,
    "geography_edit": 0.25,
    "geography": 0.2,
    "history_edit": 0.15,
    "notable_characters": 0.05,
}


@dataclass
class LocationCandidate:
    location_id: str
    name: str
    wiki_url: str
    profile_items: list[dict[str, Any]] = field(default_factory=list)
    seed_mentions: list[dict[str, Any]] = field(default_factory=list)
    decision: str = "defer"
    classification: str = ""
    source_section_role: str = "other"
    score: float = 0.0
    zone_relevant: bool = False
    lede_only: bool = False
    rejected: bool = False
    reject_reasons: list[str] = field(default_factory=list)


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


def _name_in_text(name: str, text: str) -> bool:
    if not name or not text:
        return False
    pattern = rf"\b{re.escape(name)}\b"
    return bool(re.search(pattern, text, re.IGNORECASE))


def extract_subregion_tokens(
    location_seed_pool: list[dict[str, Any]], *, zone_name: str = ""
) -> list[str]:
    tokens: list[str] = []
    zone_norm = normalize_title(zone_name)
    for item in location_seed_pool:
        role = _normalize_role(str(item.get("section_role", "")))
        if not any(hint in role for hint in ("maps", "subregion", "geography")):
            continue
        snippet = str(item.get("snippet", "")).strip()
        if not snippet:
            continue
        for part in re.split(r"[,;•\n]|(?:\s+and\s+)", snippet):
            token = part.strip(" .-–—")
            if len(token) < 3:
                continue
            token_norm = normalize_title(token)
            if zone_norm and token_norm == zone_norm:
                continue
            if token_norm not in {normalize_title(value) for value in tokens}:
                tokens.append(token)
    return tokens


def location_zone_relevant(
    text: str,
    *,
    zone_name: str,
    subregion_tokens: list[str],
) -> bool:
    cleaned = text.strip()
    if not cleaned:
        return False
    if zone_name and _name_in_text(zone_name, cleaned):
        return True
    for token in subregion_tokens:
        if _name_in_text(token, cleaned):
            return True
    return False


def _profile_items_for_location(
    location_pool: list[dict[str, Any]],
    location_id: str,
    name: str,
) -> list[dict[str, Any]]:
    scoped = [
        item
        for item in location_pool
        if str(item.get("location_id", "")).strip() == location_id and location_id
    ]
    if scoped:
        return scoped
    return [
        item
        for item in location_pool
        if _name_in_text(name, str(item.get("source_title", "")))
        or _name_in_text(name, str(item.get("snippet", "")))
    ]


def _seed_mentions_for_location(
    name: str,
    location_seed_pool: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    mentions: list[dict[str, Any]] = []
    for item in location_seed_pool:
        snippet = str(item.get("snippet", "")).strip()
        if snippet and _name_in_text(name, snippet):
            mentions.append(item)
    return mentions


def _is_lede_only_profile(candidate: LocationCandidate) -> bool:
    if not candidate.profile_items:
        return False
    roles = {_normalize_role(str(item.get("section_role", ""))) for item in candidate.profile_items}
    return roles.issubset(_LEDE_ROLES) and len(candidate.profile_items) <= 2


def collect_location_candidates(
    *,
    zone_id: str,
    zone_name: str,
    location_rows: list[dict[str, Any]],
    location_candidate_map: dict[str, dict[str, Any]],
    location_decision_map: dict[str, dict[str, Any]],
    pools: dict[str, list[dict[str, Any]]],
    location_profile_targets: list[dict[str, Any]] | None = None,
) -> list[LocationCandidate]:
    location_pool = pools.get("location_pool") or []
    location_seed_pool = pools.get("location_seed_pool") or []
    subregion_tokens = extract_subregion_tokens(location_seed_pool, zone_name=zone_name)

    by_id: dict[str, LocationCandidate] = {}

    def _ensure_candidate(
        location_id: str,
        name: str,
        *,
        source_link: str = "",
        classification: str = "major_location_candidate",
        source_section_role: str = "other",
    ) -> LocationCandidate:
        if location_id not in by_id:
            candidate_map_row = location_candidate_map.get(location_id, {})
            link = source_link or str(candidate_map_row.get("source_link", "")).strip()
            by_id[location_id] = LocationCandidate(
                location_id=location_id,
                name=name,
                wiki_url=_wiki_url_from_link(link) if link else _wiki_url_from_link(name),
                classification=classification,
                source_section_role=source_section_role,
            )
        else:
            row = by_id[location_id]
            if not row.classification:
                row.classification = classification
            if source_section_role != "other":
                row.source_section_role = source_section_role
        return by_id[location_id]

    for row in location_rows:
        if str(row.get("zone_id", "")).strip() != zone_id:
            continue
        location_id = str(row.get("location_id", "")).strip()
        if not location_id:
            continue
        classification = str(row.get("classification", "")).strip()
        if classification == "reject" or classification not in _INCLUDE_CLASSIFICATIONS:
            continue
        typing = row.get("typing_signals") or {}
        source_section_role = str(
            typing.get("source_section_role", row.get("source_section_role", "other"))
        ).strip()
        candidate = _ensure_candidate(
            location_id,
            str(row.get("name", location_id)).strip(),
            classification=classification,
            source_section_role=source_section_role,
        )
        candidate_map_row = location_candidate_map.get(location_id, {})
        link = str(candidate_map_row.get("source_link", "")).strip()
        if link:
            candidate.wiki_url = _wiki_url_from_link(link)

    for target in location_profile_targets or []:
        if str(target.get("zone_id", "")).strip() != zone_id:
            continue
        location_id = str(target.get("location_id", "")).strip()
        name = str(target.get("name", "")).strip()
        if not location_id or not name:
            continue
        _ensure_candidate(
            location_id,
            name,
            source_link=str(target.get("source_link", "")).strip(),
            source_section_role=str(target.get("source_section_role", "other")).strip(),
        )

    for item in location_pool:
        location_id = str(item.get("location_id", "")).strip()
        if not location_id:
            continue
        name = str(item.get("location_name", "")).strip() or location_id
        _ensure_candidate(location_id, name)

    for location_id, candidate in by_id.items():
        decision_row = location_decision_map.get(location_id, {})
        candidate.decision = str(decision_row.get("final_decision", "defer")).strip() or "defer"
        reject, reasons = should_reject_location_title(
            candidate.name,
            zone_name=zone_name,
            source_section_role=candidate.source_section_role,
        )
        if reject:
            candidate.rejected = True
            candidate.reject_reasons = reasons
            continue
        candidate.profile_items = _profile_items_for_location(
            location_pool, location_id, candidate.name
        )
        candidate.seed_mentions = _seed_mentions_for_location(candidate.name, location_seed_pool)
        evidence_text = " ".join(
            str(item.get("snippet", ""))
            for item in candidate.profile_items + candidate.seed_mentions
        )
        candidate.zone_relevant = location_zone_relevant(
            evidence_text,
            zone_name=zone_name,
            subregion_tokens=subregion_tokens,
        )

    return list(by_id.values())


def score_location_candidate(candidate: LocationCandidate) -> LocationCandidate:
    if candidate.rejected:
        candidate.score = 0.0
        return candidate
    if candidate.decision != "include":
        candidate.score = 0.0
        return candidate

    score = float(_SECTION_WEIGHTS.get(_normalize_role(candidate.source_section_role), 0.0))

    for item in candidate.seed_mentions:
        role = _normalize_role(str(item.get("section_role", "")))
        if role in _HIGH_WEIGHT_ROLES or any(
            hint in role for hint in ("maps", "subregion", "geography")
        ):
            score += 3.0
        elif role in _MEDIUM_WEIGHT_ROLES or role.startswith("history"):
            score += 1.5
        else:
            score += 1.0

    if candidate.profile_items:
        score += 2.0

    candidate.lede_only = _is_lede_only_profile(candidate)
    if candidate.lede_only and not candidate.seed_mentions:
        candidate.score = 0.0
        return candidate

    if not candidate.zone_relevant and not candidate.seed_mentions:
        candidate.score = 0.0
        return candidate

    if candidate.zone_relevant:
        score += 1.5

    candidate.score = score
    return candidate


def rank_location_candidates(candidates: list[LocationCandidate]) -> list[LocationCandidate]:
    scored = [score_location_candidate(candidate) for candidate in candidates]
    return sorted(
        scored,
        key=lambda row: (
            -row.score,
            -len(row.profile_items),
            0 if _normalize_role(row.source_section_role) == "maps_subregions" else 1,
            row.name.lower(),
        ),
    )


def _candidate_is_finalize_eligible(candidate: LocationCandidate) -> bool:
    if candidate.rejected or candidate.decision != "include":
        return False
    if candidate.lede_only and not candidate.seed_mentions:
        return False
    if not candidate.zone_relevant and not candidate.seed_mentions and not candidate.profile_items:
        return False
    return candidate.score > 0 or bool(candidate.profile_items or candidate.seed_mentions)


def _is_electable(candidate: LocationCandidate) -> bool:
    if candidate.rejected or candidate.decision != "include":
        return False
    if candidate.lede_only and not candidate.seed_mentions:
        return False
    return candidate.score >= MIN_SCORE


def select_location_cards(candidates: list[LocationCandidate]) -> list[LocationCandidate]:
    ranked = rank_location_candidates(candidates)
    eligible = [candidate for candidate in ranked if _is_electable(candidate)]
    if not eligible:
        thin = [candidate for candidate in ranked if _candidate_is_finalize_eligible(candidate)]
        return thin[:MAX_LOCATION_CARDS]
    return eligible[:MAX_LOCATION_CARDS]


def candidates_for_finalize(
    candidates: list[LocationCandidate],
) -> tuple[int, list[LocationCandidate]]:
    ranked = rank_location_candidates(candidates)
    target_count = len(select_location_cards(candidates))
    has_eligible = any(_is_electable(candidate) for candidate in ranked)
    if has_eligible:
        queue = [candidate for candidate in ranked if _is_electable(candidate)]
    else:
        queue = [candidate for candidate in ranked if _candidate_is_finalize_eligible(candidate)]
    return target_count, queue


def finalize_evidence_pools(candidate: LocationCandidate) -> list[list[dict[str, Any]]]:
    pools: list[list[dict[str, Any]]] = []
    if candidate.profile_items:
        pools.append(candidate.profile_items)
    if candidate.seed_mentions and (
        not candidate.profile_items or candidate.seed_mentions != candidate.profile_items
    ):
        pools.append(candidate.seed_mentions)
    return pools


def _decision_reason_codes(
    location_id: str,
    location_decision_map: dict[str, dict[str, Any]],
) -> list[str]:
    decision_row = location_decision_map.get(location_id, {})
    reason_codes = decision_row.get("reason_codes")
    if isinstance(reason_codes, list):
        cleaned = [str(code).strip() for code in reason_codes if str(code).strip()]
        if cleaned:
            return cleaned
    final_decision = str(decision_row.get("final_decision", "")).strip()
    if final_decision == "include":
        return ["include"]
    return [final_decision or "include"]
