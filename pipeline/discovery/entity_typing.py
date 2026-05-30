"""Deterministic entity typing guardrails for wiki link classification."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from pipeline.discovery.world_registry import entry_kinds, registry_index

TraverseRole = Literal[
    "storyline",
    "quest",
    "faction_profile",
    "location_profile",
    "instance_lore",
]

_DATING_CONVENTION_TITLE_RE = re.compile(
    r"\([^)]*\b(?:BCE|CE|ADP|BDP)\b[^)]*\)|\b\d+\s+(?:BCE|CE|AD)\b",
    re.IGNORECASE,
)

_GEOGRAPHY_SOURCE_ROLES = frozenset({"maps_subregions", "geography_edit", "geography", "subregion"})

_RACE_SPECIES_DENYLIST = frozenset(
    {
        "human",
        "gnoll",
        "undead",
        "night elf",
        "blood elf",
        "draenei",
        "dwarf",
        "gnome",
        "troll",
        "tauren",
        "orc",
        "goblin",
        "worgen",
        "pandaren",
        "vulpera",
        "mechagnome",
        "dracthyr",
    }
)

_META_PAGE_DENYLIST = frozenset(
    {
        "faction",
        "category",
        "world",
        "class",
        "race",
        "quest",
        "item",
        "spell",
        "ability",
    }
)

_LOCATION_META_TITLES = frozenset({"lore", "adp"})

_FACTION_AS_LOCATION_DENYLIST = frozenset(
    {
        "argent dawn",
        "scourge",
        "alliance",
        "horde",
        "forsaken",
        "cult of the damned",
        "crusade",
    }
)

_QUEST_GRAPH_REGISTRY_KINDS = frozenset(
    {"zone", "continent", "capital", "region", "instance", "person", "place"}
)
_TRAVERSE_BLOCK_BY_ROLE: dict[str, frozenset[str]] = {
    "quest": frozenset({"zone", "continent", "capital", "region", "instance", "person", "place"}),
    "faction_profile": frozenset({"zone", "continent", "instance"}),
    "location_profile": frozenset({"zone", "continent", "instance"}),
    "storyline": frozenset(),
    "instance_lore": frozenset({"zone", "continent", "capital", "region"}),
}


def _denylist_path() -> Path:
    return Path(__file__).with_name("entity_denylist.json")


def load_curated_denylist() -> dict[str, list[str]]:
    path = _denylist_path()
    if not path.exists():
        return {"location_titles": [], "faction_titles": [], "quest_graph_titles": []}
    blob = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(blob, dict):
        return {"location_titles": [], "faction_titles": [], "quest_graph_titles": []}
    return {
        "location_titles": [
            str(item).lower()
            for item in blob.get("location_titles", [])
            if isinstance(item, str)
        ],
        "faction_titles": [
            str(item).lower()
            for item in blob.get("faction_titles", [])
            if isinstance(item, str)
        ],
        "quest_graph_titles": [
            str(item).lower()
            for item in blob.get("quest_graph_titles", [])
            if isinstance(item, str)
        ],
    }


def _registry_titles_for_kinds(*kinds: str) -> frozenset[str]:
    wanted = frozenset(kinds)
    titles: set[str] = set()
    for row in registry_index().values():
        row_kinds = row.get("kinds", [])
        if not isinstance(row_kinds, list):
            continue
        if wanted.intersection(str(kind) for kind in row_kinds if isinstance(kind, str)):
            normalized = str(row.get("normalized_title", "")).strip()
            if normalized:
                titles.add(normalized)
    return frozenset(titles)


def _geography_hub_titles() -> frozenset[str]:
    curated = load_curated_denylist()
    registry_hubs = _registry_titles_for_kinds("zone", "continent", "capital", "region", "instance")
    return frozenset(curated["quest_graph_titles"] + curated["location_titles"]) | registry_hubs


def _wiki_title_from_link(link: str) -> str:
    if "://" in link:
        path = link.split("://", 1)[-1]
        path = path.split("/", 1)[-1] if "/" in path else path
    else:
        path = link
    title = path.split("/wiki/", 1)[-1].split("#", 1)[0]
    from urllib.parse import unquote

    return unquote(title).strip().replace("_", " ")


def normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", title.strip()).lower()


def is_valid_quest_graph_link(link: str, *, zone_name: str = "") -> tuple[bool, list[str]]:
    """Return (valid, reason_codes) for a quest graph node href."""
    if not link or "/wiki/" not in link:
        return False, ["missing_wiki_path"]
    if "#" in link.split("/wiki/", 1)[-1]:
        return False, ["fragment_link"]
    if "redlink=1" in link.lower() or "action=edit" in link.lower():
        return False, ["meta_url"]
    title = _wiki_title_from_link(link)
    lowered = normalize_title(title)
    if not lowered:
        return False, ["empty_title"]
    if lowered.startswith("file:") or lowered.startswith("category:"):
        return False, ["namespace"]
    if lowered in _META_PAGE_DENYLIST:
        return False, ["meta_page"]
    curated = load_curated_denylist()
    if lowered in curated["quest_graph_titles"]:
        return False, ["quest_graph_denylist"]
    registry_kind = entry_kinds(title)
    if registry_kind & _QUEST_GRAPH_REGISTRY_KINDS:
        return False, [f"registry_{sorted(registry_kind & _QUEST_GRAPH_REGISTRY_KINDS)[0]}"]
    zone_lower = normalize_title(zone_name)
    if zone_lower and lowered == zone_lower:
        return False, ["self_zone"]
    if lowered.endswith(" quests"):
        return False, ["achievement_hub"]
    if "storyline" in lowered or "questline" in lowered:
        return False, ["storyline_page"]
    return True, []


def should_reject_location_title(
    title: str,
    *,
    zone_name: str = "",
    source_section_role: str = "other",
    entity_type: str = "location",
) -> tuple[bool, list[str]]:
    """Return (reject, reason_codes) for a location candidate title."""
    if entity_type != "location":
        return True, [f"entity_type:{entity_type}"]
    lowered = normalize_title(title)
    if not lowered:
        return True, ["empty_title"]
    if lowered in _META_PAGE_DENYLIST:
        return True, ["meta_page"]
    if lowered in _LOCATION_META_TITLES:
        return True, ["meta_page"]
    if lowered in _FACTION_AS_LOCATION_DENYLIST:
        return True, ["faction_title"]
    if lowered in _RACE_SPECIES_DENYLIST:
        return True, ["race_or_species"]
    curated = load_curated_denylist()
    if lowered in curated["location_titles"]:
        return True, ["curated_denylist"]
    if lowered in curated["faction_titles"]:
        return True, ["faction_title"]
    zone_lower = normalize_title(zone_name)
    if zone_lower and lowered == zone_lower:
        return True, ["self_zone"]
    if lowered in _geography_hub_titles():
        return True, ["geography_hub"]
    if _DATING_CONVENTION_TITLE_RE.search(title):
        return True, ["dating_convention"]
    normalized_role = re.sub(r"\s+", " ", source_section_role.strip()).lower().replace(" ", "_")
    if (
        normalized_role not in _GEOGRAPHY_SOURCE_ROLES
        and source_section_role != "notable_characters"
        and _is_likely_npc_name(title)
    ):
        return True, ["likely_npc"]
    return False, []


def should_skip_registry_traversal(
    link: str,
    *,
    auxiliary_role: str,
    zone_name: str = "",
    allowed_instance_titles: frozenset[str] | None = None,
) -> tuple[bool, list[str]]:
    """Return (skip, reason_codes) for auxiliary wiki traversal."""
    role = auxiliary_role.strip().lower()
    if role == "storyline":
        return False, []
    if is_bogus_traversal_link(link):
        return True, ["bogus_link"]
    title = _wiki_title_from_link(link)
    lowered = normalize_title(title)
    if not lowered:
        return True, ["empty_title"]
    zone_lower = normalize_title(zone_name)
    if zone_lower and lowered == zone_lower and role in {"quest", "location_profile"}:
        return True, ["self_zone"]
    allowed_instances = {normalize_title(value) for value in (allowed_instance_titles or frozenset())}
    if lowered in allowed_instances and role in {"location_profile", "instance_lore"}:
        return False, []
    block_kinds = _TRAVERSE_BLOCK_BY_ROLE.get(role, frozenset({"zone", "continent", "instance"}))
    kinds = entry_kinds(title)
    blocked = kinds & block_kinds
    if blocked:
        return True, [f"registry_{sorted(blocked)[0]}_for_{role}"]
    curated = load_curated_denylist()
    if role == "quest" and lowered in curated["quest_graph_titles"]:
        return True, ["quest_graph_denylist"]
    if role in {"location_profile", "faction_profile"} and lowered in _geography_hub_titles():
        registry_kind = entry_kinds(title)
        if "capital" in registry_kind and role == "location_profile":
            return True, ["geography_hub_capital"]
        if lowered not in allowed_instances:
            return True, ["geography_hub"]
    return False, []


def _is_likely_npc_name(title: str) -> bool:
    parts = [part for part in re.split(r"\s+", title.strip()) if part]
    if len(parts) != 2:
        return False
    return all(part[:1].isupper() for part in parts if part)


def is_bogus_traversal_link(link: str) -> bool:
    """True when a wiki link should not be fetched during traversal."""
    if not link or "/wiki/" not in link:
        return True
    title = link.split("/wiki/", 1)[-1].split("#", 1)[0]
    title = title.replace("_", " ").strip().lower()
    if not title:
        return True
    if title.startswith("see "):
        return True
    if title in _META_PAGE_DENYLIST:
        return True
    if "redlink=1" in link.lower():
        return True
    return False
