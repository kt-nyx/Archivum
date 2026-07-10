"""Zone-agnostic location candidate collection, relevance scoring, and election."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import unquote

from pipeline.contracts.models import LocationType
from pipeline.discovery.entity_typing import (
    normalize_title,
)
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
_VALID_LOCATION_TYPES = frozenset(member.value for member in LocationType)
# Infobox keys carrying a place-type hint, compared case-insensitively against the
# wiki-cased labels ``parse_infobox`` preserves ("Type"). Populated on snapshots since
# the Slice 12 re-crawl; the type precedence below simply skips a missing field.
_INFOBOX_TYPE_KEYS = ("type", "location_type")


def _category_type(categories: list[str] | None) -> str:
    lowered = " ".join(str(category).lower() for category in categories or [])
    if not lowered:
        return ""
    for location_type, markers in _CATEGORY_TYPE_RULES:
        if any(marker in lowered for marker in markers):
            return location_type
    return ""


def _infobox_location_type(infobox: dict[str, Any] | None) -> str:
    """A published LocationType read directly from an infobox ``type`` field, when present.

    Keys are matched case-insensitively: ``parse_infobox`` preserves the wiki's own
    label casing ("Type"). Returns ``""`` when there is no infobox or no recognized
    value — a snapshot without an infobox simply skips this step.
    """
    for raw_key, raw_value in (infobox or {}).items():
        if str(raw_key).strip().lower() not in _INFOBOX_TYPE_KEYS:
            continue
        value = str(raw_value).strip().lower().replace(" ", "_")
        if value in _VALID_LOCATION_TYPES:
            return value
    return ""


def location_type_from_signals(
    categories: list[str] | None = None,
    *,
    infobox: dict[str, Any] | None = None,
    llm_type: str = "",
) -> str:
    """Publish a LocationType from structured signals only (Slice 10 — no keyword ladders).

    Precedence: the page's own MediaWiki categories (authoritative wiki structure), then an
    infobox ``type`` field when the snapshot carries one (Slice 12), then the LLM's own
    classification riding the summary call, then ``major_location`` when nothing is distinctive.
    Name/evidence-text keyword ladders were retired here; the routing *classification* enum
    remains a discovery signal, never the published card type.
    """
    cat_type = _category_type(categories)
    if cat_type:
        return cat_type
    infobox_type = _infobox_location_type(infobox)
    if infobox_type:
        return infobox_type
    if llm_type in _VALID_LOCATION_TYPES:
        return llm_type
    return LocationType.MAJOR_LOCATION.value


def location_significance_from_signals(*, llm_tag: str = "") -> str:
    """Publish a significance tag from structured signals only (Slice 10 — no keyword ladders).

    Neither a MediaWiki category nor an infobox field maps onto the significance vocabulary
    (categories/infobox type describe *what* a place is, not *why it matters*), so significance
    is the LLM's own classification riding the summary call, else the ``major_location`` default.
    Offline this is always the default — never a keyword guess.
    """
    if llm_tag in SIGNIFICANCE_TAGS:
        return llm_tag
    return "major_location"


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
    # The location page's own infobox fields (type/affiliation), when the snapshot carries one.
    # Empty until the Slice 12 re-crawl; the type/significance precedence skips a missing infobox.
    infobox: dict[str, Any] = field(default_factory=dict)
    significance_tag: str = "major_location"
    # Set from Slice 1's entity-kind decision artifact. Unknown is deliberately
    # non-renderable: source-section context and a title cannot promote it.
    entity_kind: str = "unknown"
    entity_kind_decision_id: str = ""


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
    profile_source_id: str,
) -> list[dict[str, Any]]:
    """Return only evidence whose recorded subject and source match the selected place."""
    return [
        item
        for item in location_pool
        if str(item.get("location_id", "")).strip() == location_id
        and str(item.get("source_id", "")).strip() == profile_source_id
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
    location_selection_decisions: list[dict[str, Any]],
    pools: dict[str, list[dict[str, Any]]],
) -> list[LocationCandidate]:
    location_pool = pools.get("location_pool") or []
    location_seed_pool = pools.get("location_seed_pool") or []
    candidates: list[LocationCandidate] = []
    for row in location_selection_decisions:
        if str(row.get("zone_id", "")).strip() != zone_id:
            continue
        if str(row.get("state", "")).strip() != "selected":
            continue
        location_id = str(row.get("location_id", "")).strip()
        profile_source_id = str(row.get("profile_source_id", "")).strip()
        name = str(row.get("name", "")).strip()
        if (
            not location_id
            or not profile_source_id
            or not name
            or str(row.get("entity_kind", "")).strip() != "place"
            or str(row.get("zone_record", "")).strip() != "on_zone"
        ):
            continue
        candidate = LocationCandidate(
            location_id=location_id,
            name=name,
            wiki_url=_wiki_url_from_link(str(row.get("source_link", ""))),
            classification="direct_profile",
            source_section_role=str(row.get("source_relation", "other")),
            categories=[str(category) for category in row.get("categories", []) if str(category).strip()],
            infobox={
                str(key): str(value)
                for key, value in (row.get("infobox") or {}).items()
                if str(key).strip() and str(value).strip()
            },
            entity_kind="place",
            entity_kind_decision_id=str(row.get("entity_kind_decision_id", "")),
            decision="include",
            zone_relevant=True,
        )
        candidate.profile_items = _profile_items_for_location(
            location_pool, location_id, profile_source_id
        )
        # A seed-page mention is relational support only. It cannot replace or supplement the
        # selected page as the primary card-evidence pool.
        candidate.seed_mentions = _seed_mentions_for_location(candidate.name, location_seed_pool)
        if not candidate.profile_items:
            candidate.rejected = True
            candidate.reject_reasons = ["direct_profile_identity_mismatch"]
            continue
        category_signal = strict_generation_category_signal(candidate.categories)
        if category_signal.disposition in {"strong_drop", "soft_drop"}:
            candidate.rejected = True
            candidate.reject_reasons = list(category_signal.reasons) or [
                "strict_generation_category_exclusion"
            ]
        candidates.append(candidate)
    return candidates


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
    if not candidate.zone_relevant:
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
    if not candidate.zone_relevant or not candidate.profile_items:
        return False
    return candidate.score > 0 or bool(candidate.profile_items or candidate.seed_mentions)


def _is_electable(candidate: LocationCandidate) -> bool:
    if candidate.rejected or candidate.decision != "include":
        return False
    return candidate.score >= MIN_SCORE


# Lead-paragraph section roles (a location's defining sentence carries its parent link).
_LEAD_LINK_ROLES = frozenset({"lead", "introduction"})


def _wiki_path_key(value: str) -> str:
    """Normalize a wiki href/URL/title to a comparable bare title key ('/wiki/Hearthglen' -> 'hearthglen')."""
    text = str(value).strip()
    if "/wiki/" in text:
        text = text.split("/wiki/", 1)[1]
    text = text.split("#", 1)[0].split("?", 1)[0].strip().strip("/")
    return unquote(text).replace("_", " ").strip().lower()


def _candidate_path_key(candidate: LocationCandidate) -> str:
    key = _wiki_path_key(candidate.wiki_url)
    return key or normalize_title(candidate.name)


def _item_is_lead(item: dict[str, Any]) -> bool:
    return any(
        str(item.get(field_name, "")).strip().lower() in _LEAD_LINK_ROLES
        for field_name in ("content_role", "raw_section_role", "section_role")
    )


def _lead_link_path_keys(candidate: LocationCandidate) -> set[str]:
    """Wiki-path keys the candidate's *lead paragraph* links to (its structural parent signal)."""
    keys: set[str] = set()
    for item in candidate.profile_items:
        if not _item_is_lead(item):
            continue
        for link in item.get("links") or []:
            href = str(link.get("href", "")).strip()
            if href:
                keys.add(_wiki_path_key(href))
    return keys


def _is_contained_location(child: LocationCandidate, parent: LocationCandidate) -> bool:
    """True when the child's own lead paragraph links to the parent (structural containment).

    Cause 1a: replaces the old "any landmark name appears anywhere in the child's evidence"
    substring test — which wrongly folded independent towns (Andorhal, whose profile merely
    mentions other landmarks) into a parent. A location is contained only when its *defining*
    sentence links to another selected landmark card (e.g. "Mardenholde Keep is the fortress
    keep of [[Hearthglen]]"). Andorhal's lead links only to the zone, so it is kept.
    """
    if child.location_id == parent.location_id:
        return False
    if not parent.lore_significant:
        return False
    if child.significance_tag in {"active_quest_hub", "instance_anchor"}:
        return False
    return _candidate_path_key(parent) in _lead_link_path_keys(child)


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
    has_eligible = any(_is_electable(candidate) for candidate in ranked)
    if has_eligible:
        queue = [candidate for candidate in ranked if _is_electable(candidate)]
    else:
        queue = [candidate for candidate in ranked if _candidate_is_finalize_eligible(candidate)]
    return target_count, _suppress_contained_locations(queue)


def finalize_evidence_pools(candidate: LocationCandidate) -> list[list[dict[str, Any]]]:
    # The selected target page owns primary card evidence.  Zone-page mentions can
    # document a directed relation, but cannot become a fallback description.
    return [candidate.profile_items] if candidate.profile_items else []


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
