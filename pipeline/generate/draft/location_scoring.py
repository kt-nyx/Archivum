"""Zone-agnostic location candidate collection, relevance scoring, and election."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from pipeline.contracts.models import LocationType
from pipeline.discovery.entity_typing import normalize_title, should_reject_location_title
from pipeline.generate.draft.temporal import strict_generation_category_signal

MIN_LOCATION_CARDS = 3
MAX_LOCATION_CARDS = 8
MIN_SCORE = 2.0

# Published LocationType values usable directly as a discovery classification token.
_TYPED_CLASSIFICATIONS = frozenset(
    member.value for member in LocationType if member is not LocationType.MAJOR_LOCATION
)
# "major_location_candidate" is the no-match default; it maps to MAJOR_LOCATION.
_INCLUDE_CLASSIFICATIONS = _TYPED_CLASSIFICATIONS | {"major_location_candidate"}


def classification_to_location_type(classification: str) -> str:
    """Map a discovery classification token to a published LocationType value."""
    if classification in _TYPED_CLASSIFICATIONS:
        return classification
    return LocationType.MAJOR_LOCATION.value


# Name-token → LocationType, checked in priority order (most specific first). The discovery
# *classification* enum is a routing signal, not a real place type, so the published card type is
# derived from the place's own name + evidence instead (WS-3). Matched as whole words.
_TYPE_NAME_TOKENS: tuple[tuple[str, frozenset[str]], ...] = (
    (LocationType.LANDMARK.value, frozenset(
        {"tomb", "grave", "crypt", "barrow", "monument", "shrine", "statue", "obelisk",
         "memorial", "tower"}
    )),
    (LocationType.FORTRESS.value, frozenset(
        {"keep", "fortress", "citadel", "bastion", "stronghold", "spire", "hold"}
    )),
    (LocationType.CITY.value, frozenset({"city", "capital"})),
    (LocationType.TOWN.value, frozenset({"town", "village", "hamlet", "burg", "borough"})),
    (LocationType.OUTPOST.value, frozenset(
        {"outpost", "camp", "post", "garrison", "encampment", "farm", "field", "fields",
         "mill", "orchard", "stead", "village area"}
    )),
    (LocationType.NATURAL_FEATURE.value, frozenset(
        {"river", "lake", "hill", "hills", "woods", "wood", "forest", "cave", "glade", "vale",
         "valley", "peak", "isle", "island", "dell", "grove", "pass", "marsh", "swamp",
         "mountain", "ridge", "haunt", "cove", "shore", "lakeshore"}
    )),
)

# Evidence-text markers that override a generic name (a "keep" described as ruined is ruins).
_RUINS_TEXT_RE = re.compile(
    r"\b(ruin|ruins|ruined|razed|destroyed|abandoned|rubble|crumbling|derelict|burned[- ]out|"
    r"shattered remains|in ruins)\b",
    re.IGNORECASE,
)
_TOWN_TEXT_RE = re.compile(
    r"\b(seat of|town of|village of|settlement|populated|inhabitants|townsfolk|"
    r"regional administration|the capital of)\b",
    re.IGNORECASE,
)


def _name_has_token(name: str, tokens: frozenset[str]) -> bool:
    words = set(re.findall(r"[a-z]+", name.lower()))
    return bool(words & tokens)


# MediaWiki category substrings → published LocationType. The page's own categories are the most
# authoritative type signal (INGEST-CAT); checked in priority order so an explicit destruction
# category ("Destroyed settlements") wins over a co-tagged settlement category ("Cities").
_CATEGORY_TYPE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (LocationType.RUINS.value, ("destroyed settlement", "ruins", "razed")),
    (LocationType.LANDMARK.value, ("tomb", "grave", "monument", "memorial", "shrine")),
    (LocationType.CITY.value, ("cities", "capital")),
    (LocationType.TOWN.value, ("towns", "villages")),
    (LocationType.FORTRESS.value, ("keeps", "forts", "fortress", "citadel", "bastion")),
    (LocationType.OUTPOST.value, ("camps", "farms", "outpost", "garrison")),
    (LocationType.NATURAL_FEATURE.value, (
        "islands", "lakes", "rivers", "mountains", "hills", "forests", "caves", "valley",
    )),
)
# Category buckets that name a *current settlement*; trusted over contextual ruin words in the
# surrounding prose (a town described next to plagued ruins is still a town).
_CURRENT_SETTLEMENT_TYPES = frozenset({LocationType.CITY.value, LocationType.TOWN.value})
SIGNIFICANCE_TAGS = frozenset(
    {
        "active_quest_hub",
        "faction_stronghold",
        "historical_turning_point",
        "instance_anchor",
        "sacred_landmark",
        "battlefield",
        "settlement_hub",
        "villain_base",
        "restoration_site",
        "major_location",
    }
)


def _category_type(categories: list[str] | None) -> str:
    lowered = " ".join(str(category).lower() for category in categories or [])
    if not lowered:
        return ""
    for location_type, markers in _CATEGORY_TYPE_RULES:
        if any(marker in lowered for marker in markers):
            return location_type
    return ""


def location_type_from_signals(
    name: str, evidence_text: str = "", categories: list[str] | None = None
) -> str:
    """Derive a published LocationType from the place's own categories, name, and evidence.

    Priority: a Tomb-named place is a landmark even in ruins; then the page's own wiki categories
    (authoritative — an explicit destruction category reads ``ruins``, a current-settlement category
    is trusted over contextual ruin words); then self-referential ruination in the evidence overrides
    a non-settlement category (a "keep" described as ruined is ruins); then name tokens and town-text;
    finally ``major_location`` when nothing is distinctive.
    """
    # Strong name signals that ruination should not override (a Tomb is a landmark even in ruins).
    for location_type, tokens in _TYPE_NAME_TOKENS[:1]:
        if _name_has_token(name, tokens):
            return location_type
    cat_type = _category_type(categories)
    if cat_type == LocationType.RUINS.value:
        return cat_type
    if cat_type in _CURRENT_SETTLEMENT_TYPES:
        return cat_type
    if evidence_text and _RUINS_TEXT_RE.search(evidence_text):
        return LocationType.RUINS.value
    if cat_type:
        return cat_type
    for location_type, tokens in _TYPE_NAME_TOKENS[1:]:
        if _name_has_token(name, tokens):
            return location_type
    if evidence_text and _TOWN_TEXT_RE.search(evidence_text):
        return LocationType.TOWN.value
    return LocationType.MAJOR_LOCATION.value
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
    # True when the place is named in the zone's history/lore narrative (a marquee landmark) rather
    # than only the maps/travel gazetteer. Set from discovery (workflow._zone_lore_body_text).
    lore_significant: bool = False
    # The location page's own MediaWiki categories (authoritative type signal); empty when the page
    # was not traversed/snapshotted. Populated from the snapshot map in draft_writer.
    categories: list[str] = field(default_factory=list)
    significance_tag: str = "major_location"


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


def _category_text(categories: list[str] | None) -> str:
    return " ".join(str(category).replace("_", " ").casefold() for category in categories or [])


def location_significance_tag(candidate: LocationCandidate, evidence_text: str = "") -> str:
    """Controlled reason a location is significant enough for a card."""
    role = _normalize_role(candidate.source_section_role)
    combined = f"{_category_text(candidate.categories)} {role.replace('_', ' ')} {evidence_text}".casefold()
    if "instance" in combined or "dungeon" in combined or "raid" in combined:
        return "instance_anchor"
    if role in {"quests", "quests_edit", "quests_or_storyline"} or "quest hub" in combined:
        return "active_quest_hub"
    if any(token in combined for token in ("battle", "war", "battlefield", "battleground")):
        return "battlefield"
    if any(token in combined for token in ("tomb", "grave", "shrine", "memorial", "sacred")):
        return "sacred_landmark"
    if any(token in combined for token in ("fort", "fortress", "keep", "stronghold", "bastion", "citadel")):
        return "faction_stronghold"
    if any(token in combined for token in ("cult", "scourge", "demon", "legion", "necromanc", "villain")):
        return "villain_base"
    if any(token in combined for token in ("restore", "restoration", "reclaimed", "healed", "recovery")):
        return "restoration_site"
    if any(token in combined for token in ("city", "town", "village", "settlement", "capital")):
        return "settlement_hub"
    if candidate.lore_significant or role.startswith("history"):
        return "historical_turning_point"
    return "major_location"


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
                lore_significant=bool(candidate_map_row.get("lore_significant", False)),
                categories=[
                    str(category)
                    for category in (candidate_map_row.get("categories") or [])
                    if str(category).strip()
                ],
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
        category_signal = strict_generation_category_signal(candidate.categories)
        if category_signal.disposition in {"strong_drop", "soft_drop"}:
            candidate.rejected = True
            candidate.reject_reasons = list(category_signal.reasons) or [
                "strict_generation_category_exclusion"
            ]
            continue
        candidate.significance_tag = location_significance_tag(candidate, evidence_text)
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

    # Diminishing returns per role bucket: a place merely listed several times in the same
    # maps/subregions table is not more important than one listed once, while a landmark woven
    # through the zone's *history* across multiple sections is marquee. The first mention in a
    # bucket scores full weight; repeats score half. (WS-3: stops maps-list farms out-scoring
    # history-prominent landmarks like Hearthglen / Caer Darrow / Uther's Tomb.)
    bucket_counts = {"maps": 0, "history": 0, "other": 0}
    for item in candidate.seed_mentions:
        role = _normalize_role(str(item.get("section_role", "")))
        if role in _HIGH_WEIGHT_ROLES or any(
            hint in role for hint in ("maps", "subregion", "geography")
        ):
            bucket, weight = "maps", 3.0
        elif role in _MEDIUM_WEIGHT_ROLES or role.startswith("history"):
            bucket, weight = "history", 2.0
        else:
            bucket, weight = "other", 1.0
        score += weight if bucket_counts[bucket] == 0 else weight * 0.5
        bucket_counts[bucket] += 1

    # Narrative-prominence bonus: each additional history section a place appears in compounds its
    # importance, so a landmark woven through the zone's story overtakes a farm merely repeated in
    # one maps table.
    if bucket_counts["history"] >= 2:
        score += 2.0 * (bucket_counts["history"] - 1)

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
            0 if row.lore_significant else 1,  # marquee (lore-named) landmarks first
            -row.score,
            -len(row.profile_items),
            0 if _normalize_role(row.source_section_role) == "maps_subregions" else 1,
            row.name.lower(),
        ),
    )


def _lore_significant_pool(candidates: list[LocationCandidate]) -> list[LocationCandidate]:
    """Marquee landmarks: places named in the zone's history/lore narrative, not maps-only chrome."""
    return [
        candidate
        for candidate in candidates
        if candidate.lore_significant
        and not candidate.rejected
        and (candidate.profile_items or candidate.seed_mentions)
    ]


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


_CONTAINED_LOCATION_NAME_TOKENS = frozenset(
    {
        "camp",
        "chamber",
        "chapel",
        "farm",
        "field",
        "hall",
        "hold",
        "inn",
        "keep",
        "mill",
        "orchard",
        "outpost",
        "post",
        "stead",
        "tower",
        "wing",
    }
)


def _candidate_evidence_text(candidate: LocationCandidate) -> str:
    parts = [candidate.name, candidate.source_section_role]
    for item in candidate.profile_items + candidate.seed_mentions:
        parts.append(str(item.get("source_title", "")))
        parts.append(str(item.get("snippet", "")))
        parts.append(str(item.get("section_role", "")))
    return " ".join(part for part in parts if part)


def _is_contained_location(child: LocationCandidate, parent: LocationCandidate) -> bool:
    if child.location_id == parent.location_id:
        return False
    if not parent.lore_significant:
        return False
    if not _name_in_text(parent.name, _candidate_evidence_text(child)):
        return False
    if child.significance_tag in {"active_quest_hub", "instance_anchor"}:
        return False
    role = _normalize_role(child.source_section_role)
    return role in _HIGH_WEIGHT_ROLES or _name_has_token(
        child.name, _CONTAINED_LOCATION_NAME_TOKENS
    )


def _suppress_contained_locations(
    selected: list[LocationCandidate],
) -> list[LocationCandidate]:
    kept: list[LocationCandidate] = []
    for candidate in selected:
        if any(_is_contained_location(candidate, parent) for parent in selected):
            continue
        kept.append(candidate)
    return kept


def select_location_cards(candidates: list[LocationCandidate]) -> list[LocationCandidate]:
    ranked = rank_location_candidates(candidates)
    # When the zone's lore narrative names enough landmarks, those ARE the location cards — the
    # maps/travel gazetteer (farms, lakes, travel hubs) is gameplay chrome, not compendium content.
    lore = _lore_significant_pool(ranked)
    if len(lore) >= MIN_LOCATION_CARDS:
        return _suppress_contained_locations(lore[:MAX_LOCATION_CARDS])
    eligible = [candidate for candidate in ranked if _is_electable(candidate)]
    if not eligible:
        thin = [candidate for candidate in ranked if _candidate_is_finalize_eligible(candidate)]
        return _suppress_contained_locations(thin[:MAX_LOCATION_CARDS])
    return _suppress_contained_locations(eligible[:MAX_LOCATION_CARDS])


def candidates_for_finalize(
    candidates: list[LocationCandidate],
) -> tuple[int, list[LocationCandidate]]:
    ranked = rank_location_candidates(candidates)
    target_count = len(select_location_cards(candidates))
    lore = _lore_significant_pool(ranked)
    if len(lore) >= MIN_LOCATION_CARDS:
        return target_count, _suppress_contained_locations(lore)
    has_eligible = any(_is_electable(candidate) for candidate in ranked)
    if has_eligible:
        queue = [candidate for candidate in ranked if _is_electable(candidate)]
    else:
        queue = [candidate for candidate in ranked if _candidate_is_finalize_eligible(candidate)]
    return target_count, _suppress_contained_locations(queue)


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
