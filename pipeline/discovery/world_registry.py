"""Build and load the generated world geography registry from Warcraft Wiki."""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

_REGISTRY_VERSION = "2"
_WIKI_API = "https://warcraft.wiki.gg/api.php"
_USER_AGENT = "wow-lore-registry/1.0"
_SUBZONE_PARENT_RE = re.compile(r"^(?:Category:)?(.+?) subzones$", re.IGNORECASE)
_META_TITLE_RE = re.compile(
    r"(?:instances by|zones by|by level|by expansion|by continent|by faction|image requests|npcs|mobs|achievements|walkthrough|delves\b)",
    re.IGNORECASE,
)
_JUNK_HEX_TITLE_RE = re.compile(r"^\(0x[0-9a-f]+\)$", re.IGNORECASE)
_CLASSIC_SUFFIX_RE = re.compile(r"\s+\((Classic|Burning Crusade|Wrath of the Lich King|Mists of Pandaria|Warlords of Draenor|Legion|Battle for Azeroth|Shadowlands|Dragonflight|The War Within)\)$", re.I)

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

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "normalized_title": self.normalized_title,
            "wiki_path": self.wiki_path,
            "kinds": list(self.kinds),
            "source_categories": list(self.source_categories),
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


def _is_instance_parent(name: str, subcategory_title: str) -> bool:
    lowered = name.lower()
    sub_lower = subcategory_title.lower()
    instance_markers = (
        "scholomance",
        "stratholme",
        "deadmines",
        " citadel",
        " raid",
        " dungeon",
        " depths",
        " throne",
        " palace",
        " sanctum",
        " nexus",
        " vault",
        " hold",
        " lair",
        " mine",
        " foundry",
        " terrace",
        " crypts",
        " karazhan",
        " naxxramas",
        " ulduar",
        " molten core",
        " blackwing",
        " scholomance",
        " stratholme",
        " dire maul",
        " maraudon",
        " ragefire",
        " deadmines",
        " stockade",
        " gnomeregan",
        " scarlet ",
        " abyssal",
        " operation:",
        " liberation of",
        " assault on",
        " siege of",
        " battle of ",
        " warfront",
        " island expedition",
        " proving ground",
    )
    if any(marker in lowered for marker in instance_markers):
        return True
    if "subzones" in sub_lower and any(
        token in lowered
        for token in ("sanctum", "citadel", "raid", "dungeon", "depths", "spire", "vault")
    ):
        return True
    return False


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
    target.write_text(json.dumps(cache, indent=2) + "\n", encoding="utf-8")


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
        request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        payload: dict[str, Any] | None = None
        for attempt in range(12):
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt < 11:
                    time.sleep(min(60.0, 5.0 * (2 ** min(attempt, 4))))
                    continue
                raise RuntimeError(f"failed to fetch category {category!r}: {exc!r}") from exc
            except urllib.error.URLError as exc:
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
) -> None:
    cleaned = _canonical_zone_title(title)
    if not cleaned or _should_skip_registry_title(cleaned):
        return
    normalized = _normalize_title(cleaned)
    if normalized in _META_ARTICLE_TITLES:
        return
    existing = entries.get(normalized)
    if existing is None:
        entries[normalized] = RegistryEntry(
            title=cleaned,
            normalized_title=normalized,
            wiki_path=_wiki_path(cleaned),
            kinds=(kind,),
            source_categories=(source_category,),
        )
        return
    kinds = tuple(sorted(set(existing.kinds) | {kind}))
    sources = tuple(sorted(set(existing.source_categories) | {source_category}))
    entries[normalized] = RegistryEntry(
        title=existing.title,
        normalized_title=existing.normalized_title,
        wiki_path=existing.wiki_path,
        kinds=kinds,
        source_categories=sources,
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
        kind = "instance" if _is_instance_parent(parent, subcat_title) else "zone"
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
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
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


def registry_index(path: Path | None = None) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("normalized_title", "")).strip(): row
        for row in registry_entries(path)
        if str(row.get("normalized_title", "")).strip()
    }


def entry_kinds(title: str, path: Path | None = None) -> frozenset[str]:
    row = registry_index(path).get(_normalize_title(title))
    if row is None:
        return frozenset()
    kinds = row.get("kinds", [])
    if not isinstance(kinds, list):
        return frozenset()
    return frozenset(str(kind) for kind in kinds if isinstance(kind, str))


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
