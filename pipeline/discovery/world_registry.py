"""Build and load the generated world geography registry from Warcraft Wiki."""

from __future__ import annotations

import json
import re
import time
import urllib.parse
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import httpx

from pipeline.common import http
from pipeline.common.io import write_json

_REGISTRY_VERSION = "3"
_WIKI_API = "https://warcraft.wiki.gg/api.php"
_USER_AGENT = "wow-lore-registry/1.0"
_SUBZONE_PARENT_RE = re.compile(r"^(?:Category:)?(.+?) subzones$", re.IGNORECASE)
_META_TITLE_RE = re.compile(
    r"(?:instances by|zones by|by level|by expansion|by continent|by faction|image requests|npcs|mobs|achievements|walkthrough|delves\b|\borganizations$)",
    re.IGNORECASE,
)
_JUNK_HEX_TITLE_RE = re.compile(r"^\(0x[0-9a-f]+\)$", re.IGNORECASE)
_CLASSIC_SUFFIX_RE = re.compile(
    r"\s+\((Classic|Burning Crusade|Wrath of the Lich King|Mists of Pandaria|Warlords of Draenor|Legion|Battle for Azeroth|Shadowlands|Dragonflight|The War Within)\)$",
    re.I,
)

EntryKind = Literal[
    "zone",
    "instance",
    "continent",
    "capital",
    "region",
    "person",
    "place",
    "meta",
    "subzone_parent",
    "organization",
]

# Categories whose article members are geography/meta hubs, not playable zones.
_META_ARTICLE_TITLES = frozenset(
    {
        "zone",
        "instance",
        "closed zone",
        "contested territory",
        "cross-realm zones",
        "classic zones",
        "zones by faction",
        "zones by level",
        "instances by continent",
        "instances by expansion",
        "instances by level",
        "instance difficulty",
        "call to arms (dungeon)",
        # Concept articles living inside the organization categories ("<X>
        # organizations" list articles are caught by _META_TITLE_RE instead).
        "faction",
        "subfaction",
        "organization",
        "icon",
    }
)

# Root categories scanned for article members (continents, capitals, etc.).
_ARTICLE_CATEGORY_SEEDS: tuple[tuple[str, str], ...] = (
    ("Category:Classic zones", "zone"),
    ("Category:World of Warcraft zones", "zone"),
    ("Category:Starting areas", "zone"),
    ("Category:Capital cities", "capital"),
    ("Category:Continents", "continent"),
    ("Category:Major cities", "capital"),
    ("Category:Raids", "instance"),
    ("Category:Dungeons", "instance"),
    ("Category:Battlegrounds", "zone"),
    ("Category:Lore characters", "person"),
    ("Category:NPCs", "person"),
    ("Category:Lore locations", "place"),
    ("Category:Locations", "place"),
)

# Organization category seeds (Slice 12). The wiki's own taxonomy differs from the
# names the plan sketched: there are no "Category:<X> organizations" member categories;
# organizations live under Category:Organizations (lore groups) and Category:Factions
# (gameplay/reputation factions), with the umbrella affiliation carried by
# Category:Alliance factions / Category:Horde factions membership. There is no neutral
# category — neutrality is the absence of an umbrella membership. Racial organization
# categories are enumerated live from Category:Organizations by race subcategories
# (see build_world_registry), never hand-listed here.
_ORGANIZATION_CATEGORY_SEEDS: tuple[tuple[str, str], ...] = (
    ("Category:Organizations", ""),
    ("Category:Factions", ""),
    ("Category:Alliance factions", "alliance"),
    ("Category:Horde factions", "horde"),
)

# The category whose subcategories are the wiki's racial organization categories.
_ORGANIZATIONS_BY_RACE_CATEGORY = "Category:Organizations by race"

# Known continent/region article titles (fallback when category seeds are sparse).
_CONTINENT_TITLES = (
    "Azeroth",
    "Eastern Kingdoms",
    "Kalimdor",
    "Northrend",
    "Pandaria",
    "Broken Isles",
    "Dragon Isles",
    "Khaz Modan",
    "Lordaeron",
    "Outland",
    "Draenor",
    "Zandalar",
    "Kul Tiras",
    "Shadowlands",
    "Dragon Isles",
    "K'aresh",
)

_CAPITAL_TITLES = (
    "Stormwind City",
    "Ironforge",
    "Darnassus",
    "Exodar",
    "Orgrimmar",
    "Thunder Bluff",
    "Undercity",
    "Silvermoon City",
    "Dalaran",
    "Shattrath City",
    "Boralus",
    "Dazar'alor",
    "Oribos",
    "Dornogal",
)


@dataclass(frozen=True)
class RegistryEntry:
    title: str
    normalized_title: str
    wiki_path: str
    kinds: tuple[str, ...]
    source_categories: tuple[str, ...]
    # Umbrella affiliations from organization-category memberships (Slice 12):
    # "alliance"/"horde" via Category:Alliance factions / Category:Horde factions.
    # Empty means neutral/unaffiliated (the wiki has no neutral category).
    affiliations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "normalized_title": self.normalized_title,
            "wiki_path": self.wiki_path,
            "kinds": list(self.kinds),
            "source_categories": list(self.source_categories),
            "affiliations": list(self.affiliations),
        }


def registry_path() -> Path:
    return Path(__file__).with_name("world_registry.json")


def category_cache_path() -> Path:
    return Path(__file__).with_name(".world_registry_category_cache.json")


def _normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", title.strip()).lower()


def _wiki_path(title: str) -> str:
    slug = title.replace(" ", "_")
    return f"/wiki/{slug}"


def _canonical_zone_title(title: str) -> str:
    cleaned = title.strip()
    if cleaned.startswith("Category:"):
        cleaned = cleaned.split(":", 1)[1].strip()
    cleaned = _CLASSIC_SUFFIX_RE.sub("", cleaned)
    return cleaned


def _should_skip_registry_title(title: str) -> bool:
    cleaned = _canonical_zone_title(title)
    normalized = _normalize_title(cleaned)
    if not normalized:
        return True
    if normalized.startswith("category:"):
        return True
    if normalized in _META_ARTICLE_TITLES:
        return True
    if normalized in {"lore character", "lore location"}:
        return True
    if _JUNK_HEX_TITLE_RE.match(cleaned.strip()):
        return True
    if _META_TITLE_RE.search(title):
        return True
    return False


def _parent_kind_from_entries(entries: dict[str, RegistryEntry], parent_title: str) -> str:
    """Classify a ``<X> subzones`` category parent from already-ingested entries.

    Instance-ness flows from the wiki's own category memberships (Category:Dungeons /
    Category:Raids / Category:Instances seeds, ingested before the Subzones sweep) —
    never from name markers. A parent the wiki does not class as an instance is a zone.
    """
    existing = entries.get(_normalize_title(parent_title))
    if existing is not None and "instance" in existing.kinds:
        return "instance"
    return "zone"


def _load_category_cache(path: Path | None = None) -> dict[str, list[dict[str, Any]]]:
    target = path or category_cache_path()
    if not target.exists():
        return {}
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {}
    cache: dict[str, list[dict[str, Any]]] = {}
    for key, value in payload.items():
        if isinstance(key, str) and isinstance(value, list):
            cache[key] = [row for row in value if isinstance(row, dict)]
    return cache


def _save_category_cache(cache: dict[str, list[dict[str, Any]]], path: Path | None = None) -> None:
    target = path or category_cache_path()
    write_json(target, cache)


def _cache_key(category: str, cmtype: str | None) -> str:
    return f"{category}|{cmtype or 'all'}"


def _fetch_category_members(
    category: str,
    *,
    cmtype: str | None = None,
    sleep_seconds: float = 0.35,
    cache: dict[str, list[dict[str, Any]]] | None = None,
    cache_path: Path | None = None,
) -> list[dict[str, Any]]:
    key = _cache_key(category, cmtype)
    if cache is not None and key in cache:
        return list(cache[key])

    members: list[dict[str, Any]] = []
    cmcontinue: str | None = None
    while True:
        params: dict[str, str] = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": category,
            "cmlimit": "500",
            "format": "json",
        }
        if cmtype:
            params["cmtype"] = cmtype
        if cmcontinue:
            params["cmcontinue"] = cmcontinue
        url = f"{_WIKI_API}?{urllib.parse.urlencode(params)}"
        payload: dict[str, Any] | None = None
        for attempt in range(12):
            try:
                response = http.send("GET", url, headers={"User-Agent": _USER_AGENT}, timeout=60)
                payload = response.json()
                break
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429 and attempt < 11:
                    time.sleep(min(60.0, 5.0 * (2 ** min(attempt, 4))))
                    continue
                raise RuntimeError(f"failed to fetch category {category!r}: {exc!r}") from exc
            except httpx.RequestError as exc:
                raise RuntimeError(f"failed to fetch category {category!r}: {exc!r}") from exc
        if payload is None:
            raise RuntimeError(f"failed to fetch category {category!r}: empty payload")
        batch = payload.get("query", {}).get("categorymembers", [])
        if isinstance(batch, list):
            members.extend(row for row in batch if isinstance(row, dict))
        cmcontinue = payload.get("continue", {}).get("cmcontinue")
        if not cmcontinue:
            break
        time.sleep(sleep_seconds)
    if cache is not None:
        cache[key] = members
        _save_category_cache(cache, cache_path)
    time.sleep(sleep_seconds)
    return members


def _merge_entry(
    entries: dict[str, RegistryEntry],
    *,
    title: str,
    kind: str,
    source_category: str,
    affiliation: str = "",
) -> None:
    cleaned = _canonical_zone_title(title)
    if not cleaned or _should_skip_registry_title(cleaned):
        return
    normalized = _normalize_title(cleaned)
    if normalized in _META_ARTICLE_TITLES:
        return
    new_affiliations = (affiliation,) if affiliation else ()
    existing = entries.get(normalized)
    if existing is None:
        entries[normalized] = RegistryEntry(
            title=cleaned,
            normalized_title=normalized,
            wiki_path=_wiki_path(cleaned),
            kinds=(kind,),
            source_categories=(source_category,),
            affiliations=new_affiliations,
        )
        return
    kinds = tuple(sorted(set(existing.kinds) | {kind}))
    sources = tuple(sorted(set(existing.source_categories) | {source_category}))
    affiliations = tuple(sorted(set(existing.affiliations) | set(new_affiliations)))
    entries[normalized] = RegistryEntry(
        title=existing.title,
        normalized_title=existing.normalized_title,
        wiki_path=existing.wiki_path,
        kinds=kinds,
        source_categories=sources,
        affiliations=affiliations,
    )


def _ingest_organization_categories(
    entries: dict[str, RegistryEntry],
    *,
    sleep_seconds: float,
    cache: dict[str, list[dict[str, Any]]],
    cache_path: Path | None,
) -> None:
    """Seed ``kind="organization"`` entries with umbrella affiliations (Slice 12).

    Fixed seeds carry the wiki's umbrella signal (Alliance/Horde factions); the
    racial organization categories are swept live from the wiki's own
    Category:Organizations by race subcategory list, mirroring the Subzones sweep,
    so no racial category is ever hand-enumerated.
    """
    for category, affiliation in _ORGANIZATION_CATEGORY_SEEDS:
        members = _fetch_category_members(
            category,
            cmtype="page",
            sleep_seconds=sleep_seconds,
            cache=cache,
            cache_path=cache_path,
        )
        for row in members:
            if int(row.get("ns", -1)) != 0:
                continue
            title = str(row.get("title", "")).strip()
            if not title:
                continue
            _merge_entry(
                entries,
                title=title,
                kind="organization",
                source_category=category,
                affiliation=affiliation,
            )

    race_subcats = _fetch_category_members(
        _ORGANIZATIONS_BY_RACE_CATEGORY,
        cmtype="subcat",
        sleep_seconds=sleep_seconds,
        cache=cache,
        cache_path=cache_path,
    )
    for row in race_subcats:
        subcat_title = str(row.get("title", "")).strip()
        if not subcat_title.startswith("Category:"):
            continue
        for page_row in _fetch_category_members(
            subcat_title,
            cmtype="page",
            sleep_seconds=sleep_seconds,
            cache=cache,
            cache_path=cache_path,
        ):
            if int(page_row.get("ns", -1)) != 0:
                continue
            page_title = str(page_row.get("title", "")).strip()
            if not page_title:
                continue
            _merge_entry(
                entries,
                title=page_title,
                kind="organization",
                source_category=subcat_title,
            )


def _ingest_category_pages(
    entries: dict[str, RegistryEntry],
    category: str,
    kind: str,
    *,
    sleep_seconds: float,
    cache: dict[str, list[dict[str, Any]]],
    cache_path: Path | None,
) -> None:
    members = _fetch_category_members(
        category,
        cmtype="page",
        sleep_seconds=sleep_seconds,
        cache=cache,
        cache_path=cache_path,
    )
    for row in members:
        if int(row.get("ns", -1)) != 0:
            continue
        title = str(row.get("title", "")).strip()
        if not title:
            continue
        _merge_entry(entries, title=title, kind=kind, source_category=category)


def build_world_registry(
    *,
    sleep_seconds: float = 0.35,
    cache_path: Path | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Scrape Warcraft Wiki categories and return a registry payload."""
    entries: dict[str, RegistryEntry] = {}
    cache = _load_category_cache(cache_path) if use_cache else {}

    # Category seeds first: they carry the wiki's own kind signal (Category:Dungeons /
    # Category:Raids / Category:Instances -> "instance"), which the Subzones sweep below
    # consults to classify subzone parents — no hardcoded name markers.
    for category, kind in _ARTICLE_CATEGORY_SEEDS:
        _ingest_category_pages(
            entries,
            category,
            kind,
            sleep_seconds=sleep_seconds,
            cache=cache,
            cache_path=cache_path,
        )

    for title in _CONTINENT_TITLES:
        _merge_entry(entries, title=title, kind="continent", source_category="seed:continents")
    for title in _CAPITAL_TITLES:
        _merge_entry(entries, title=title, kind="capital", source_category="seed:capitals")

    _ingest_category_pages(
        entries,
        "Category:Instances",
        "instance",
        sleep_seconds=sleep_seconds,
        cache=cache,
        cache_path=cache_path,
    )

    # Slice 12: organization entries (with umbrella affiliations) are always part
    # of the registry from version 3 on.
    _ingest_organization_categories(
        entries,
        sleep_seconds=sleep_seconds,
        cache=cache,
        cache_path=cache_path,
    )

    subcats = _fetch_category_members(
        "Category:Subzones",
        cmtype="subcat",
        sleep_seconds=sleep_seconds,
        cache=cache,
        cache_path=cache_path,
    )
    for row in subcats:
        subcat_title = str(row.get("title", "")).strip()
        match = _SUBZONE_PARENT_RE.match(subcat_title)
        if not match:
            continue
        parent = _canonical_zone_title(match.group(1))
        kind = _parent_kind_from_entries(entries, parent)
        _merge_entry(entries, title=parent, kind=kind, source_category="Category:Subzones")
        for page_row in _fetch_category_members(
            subcat_title,
            cmtype="page",
            sleep_seconds=sleep_seconds,
            cache=cache,
            cache_path=cache_path,
        ):
            if int(page_row.get("ns", -1)) != 0:
                continue
            page_title = str(page_row.get("title", "")).strip()
            if not page_title:
                continue
            _merge_entry(entries, title=page_title, kind="place", source_category=subcat_title)

    sorted_entries = [entries[key].to_dict() for key in sorted(entries)]
    return {
        "version": _REGISTRY_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "source": "warcraft.wiki.gg MediaWiki API",
        "entry_count": len(sorted_entries),
        "entries": sorted_entries,
    }


def write_world_registry(
    path: Path | None = None,
    *,
    sleep_seconds: float = 0.35,
    cache_path: Path | None = None,
    use_cache: bool = True,
) -> Path:
    target = path or registry_path()
    payload = build_world_registry(
        sleep_seconds=sleep_seconds,
        cache_path=cache_path,
        use_cache=use_cache,
    )
    write_json(target, payload)
    return target


def load_world_registry(path: Path | None = None) -> dict[str, Any]:
    target = path or registry_path()
    if not target.exists():
        return {"version": _REGISTRY_VERSION, "entries": []}
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {"version": _REGISTRY_VERSION, "entries": []}
    return payload


def registry_entries(path: Path | None = None) -> list[dict[str, Any]]:
    payload = load_world_registry(path)
    rows = payload.get("entries", [])
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


@lru_cache(maxsize=8)
def _registry_index_for(path_key: str) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("normalized_title", "")).strip(): row
        for row in registry_entries(Path(path_key))
        if str(row.get("normalized_title", "")).strip()
    }


def registry_index(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Normalized-title index over the registry, cached per path.

    The committed registry file is static for the life of a process, and Slice 13's
    link-based faction recognition looks entries up per inline link — an uncached
    read would re-parse the 11k-entry JSON on every call. A process that rewrites a
    registry file in place must use a fresh path (or ``_registry_index_for.cache_clear()``).
    """
    return _registry_index_for(str(path or registry_path()))


def entry_kinds(title: str, path: Path | None = None) -> frozenset[str]:
    row = registry_index(path).get(_normalize_title(title))
    if row is None:
        return frozenset()
    kinds = row.get("kinds", [])
    if not isinstance(kinds, list):
        return frozenset()
    return frozenset(str(kind) for kind in kinds if isinstance(kind, str))


def entry_affiliations(title: str, path: Path | None = None) -> frozenset[str]:
    """Umbrella affiliations recorded for a registry entry ("alliance"/"horde").

    Empty for unknown titles and for neutral/unaffiliated organizations.
    """
    row = registry_index(path).get(_normalize_title(title))
    if row is None:
        return frozenset()
    affiliations = row.get("affiliations", [])
    if not isinstance(affiliations, list):
        return frozenset()
    return frozenset(str(item) for item in affiliations if isinstance(item, str))


def title_from_wiki_href(href: str) -> str:
    """Article title for a wiki href or bare wiki path (``/wiki/Cult_of_the_Damned``,
    ``https://warcraft.wiki.gg/wiki/Forsaken#History``, ``Instructor_Razuvious``)."""
    value = str(href or "").strip()
    if not value or value.startswith("#"):
        return ""
    if "/wiki/" in value:
        value = value.split("/wiki/", 1)[1]
    elif "://" in value:
        return ""
    value = value.split("#", 1)[0].split("?", 1)[0].strip("/")
    return urllib.parse.unquote(value).replace("_", " ").strip()


def organization_entry(title: str, path: Path | None = None) -> dict[str, Any] | None:
    """The registry row for ``title`` when the wiki classes it as an organization."""
    row = registry_index(path).get(_normalize_title(title))
    if row is None:
        return None
    kinds = row.get("kinds", [])
    if not isinstance(kinds, list) or "organization" not in kinds:
        return None
    return row


def organization_entry_for_href(href: str, path: Path | None = None) -> dict[str, Any] | None:
    """Resolve an inline-link target to a registry organization (Slice 13)."""
    title = title_from_wiki_href(href)
    if not title:
        return None
    return organization_entry(title, path)


@lru_cache(maxsize=8)
def _umbrella_organizations_for(path_key: str) -> dict[str, str]:
    tags: set[str] = set()
    index = _registry_index_for(path_key)
    for row in index.values():
        affiliations = row.get("affiliations", [])
        if isinstance(affiliations, list):
            tags.update(str(tag) for tag in affiliations if isinstance(tag, str) and tag)
    umbrellas: dict[str, str] = {}
    for tag in sorted(tags):
        umbrella_row = index.get(_normalize_title(tag))
        if umbrella_row is None:
            continue
        kinds = umbrella_row.get("kinds", [])
        if isinstance(kinds, list) and "organization" in kinds:
            umbrellas[str(umbrella_row.get("title", tag))] = tag
    return umbrellas


def umbrella_organizations(path: Path | None = None) -> dict[str, str]:
    """Display title -> umbrella tag for the faction-capital organizations.

    Structurally derived (Slice 13): the umbrella tag vocabulary is the set of
    affiliation values the org-category seeds recorded (``Category:<X> factions``),
    and the umbrella organization for a tag is the registry org entry bearing that
    title — {"Alliance": "alliance", "Horde": "horde"} on the live wiki, with no
    hand-enumerated faction list.
    """
    return _umbrella_organizations_for(str(path or registry_path()))


def umbrella_faction_tags(path: Path | None = None) -> frozenset[str]:
    """The registry's umbrella affiliation tags (``alliance``/``horde`` on the live wiki)."""
    return frozenset(umbrella_organizations(path).values())


def is_registry_title(title: str, *kinds: str, path: Path | None = None) -> bool:
    found = entry_kinds(title, path)
    if not kinds:
        return bool(found)
    return bool(found & frozenset(kinds))


def summarize_registry(payload: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in payload.get("entries", []):
        if not isinstance(row, dict):
            continue
        for kind in row.get("kinds", []):
            if isinstance(kind, str):
                counts[kind] = counts.get(kind, 0) + 1
    return dict(sorted(counts.items()))
