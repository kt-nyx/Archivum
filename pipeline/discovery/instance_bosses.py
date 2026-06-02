"""Structural boss/encounter parsing from instance wiki section blocks."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from pipeline.discovery.entity_typing import _DATING_CONVENTION_TITLE_RE, normalize_title
from pipeline.discovery.world_registry import entry_kinds
from pipeline.common.text_normalize import clean_wiki_snippet

_WIKI_LINK_RE = re.compile(r"/wiki/([^|\s\]#<>\"']+)")
_WIKITEXT_LINK_RE = re.compile(r"\[\[([^|\]#]+)(?:\|[^\]]+)?\]\]")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_BOSS_SECTION_TOKENS = (
    "adventurer",
    "encounter",
    "boss",
    "dungeon",
    "adventure_guide",
    "walkthrough",
    "faculty",
    "denizen",
    "dungeon_journal",
    "adventurers_guide",
    "layout",
    "notable",
    "character",
    "npc",
    "monster",
    "inhabit",
)
_BOSS_SECTION_EXACT = frozenset(
    {
        "bosses",
        "denizens",
        "inhabitants",
        "scholomance_faculty",
    }
)
_GEOGRAPHY_KINDS = frozenset({"zone", "continent", "capital", "region", "instance"})
_REJECT_TITLES = frozenset(
    {
        "adventurers",
        "encounters",
        "bosses",
        "loot",
        "achievements",
        "strategy",
        "tactics",
        "abilities",
        "quotes",
        "gallery",
        "notes",
        "trivia",
    }
)


@dataclass
class BossCandidate:
    boss_id: str
    name: str
    wiki_url: str
    source_section_role: str
    profile_pool: list[dict[str, Any]] = field(default_factory=list)


def _normalize_role(section_role: str) -> str:
    return re.sub(r"\s+", " ", section_role.strip()).lower().replace(" ", "_")


def is_boss_section_role(section_role: str) -> bool:
    """Return True when a wiki section role should contribute boss_pool / encounter evidence."""
    lowered = _normalize_role(section_role)
    if lowered in _BOSS_SECTION_EXACT:
        return True
    if lowered.startswith("dungeon_"):
        return True
    return any(token in lowered for token in _BOSS_SECTION_TOKENS)


def boss_section_role_matches(section_role: str) -> bool:
    """Alias for is_boss_section_role (shared enrich + draft entry point)."""
    return is_boss_section_role(section_role)


def row_has_roster_role(row: dict[str, Any]) -> bool:
    """True when a block/structured link is roster-bearing by its leaf or parent section role."""
    if is_boss_section_role(str(row.get("section_role", "other"))):
        return True
    parent = str(row.get("parent_section_role", "")).strip()
    return bool(parent) and is_boss_section_role(parent)


def _title_from_wiki_path(path: str) -> str:
    return path.replace("_", " ").strip()


def _slug_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"character-{slug}" if slug else ""


def should_reject_boss_title(title: str, *, instance_name: str = "") -> bool:
    lowered = normalize_title(title)
    if not lowered or len(lowered) < 3:
        return True
    if instance_name and lowered == normalize_title(instance_name):
        return True
    if lowered in _REJECT_TITLES:
        return True
    if _DATING_CONVENTION_TITLE_RE.search(title):
        return True
    kinds = entry_kinds(title)
    if kinds & _GEOGRAPHY_KINDS:
        return True
    return False


def _append_wiki_link(
    results: list[tuple[str, str]],
    seen: set[str],
    *,
    path: str,
) -> None:
    path = path.split("#", 1)[0].strip()
    if not path:
        return
    title = _title_from_wiki_path(path)
    key = normalize_title(title)
    if not key or key in seen:
        return
    seen.add(key)
    url = f"https://warcraft.wiki.gg/wiki/{path}"
    results.append((title, url))


def _extract_wiki_links(text: str) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    seen: set[str] = set()
    for match in _WIKI_LINK_RE.finditer(text):
        _append_wiki_link(results, seen, path=match.group(1))
    for match in _WIKITEXT_LINK_RE.finditer(text):
        raw = match.group(1).strip()
        if raw.startswith("/wiki/"):
            _append_wiki_link(results, seen, path=raw.removeprefix("/wiki/"))
            continue
        if raw.startswith("http") or "://" in raw:
            continue
        _append_wiki_link(results, seen, path=raw.replace(" ", "_"))
    return results


def valid_boss_names_from_pool_items(
    boss_pool_items: list[dict[str, Any]],
    *,
    instance_name: str = "",
) -> set[str]:
    """Derive normalized boss names from boss_pool evidence snippets."""
    names: set[str] = set()
    for item in boss_pool_items:
        for title, _url in _extract_wiki_links(str(item.get("snippet", ""))):
            if should_reject_boss_title(title, instance_name=instance_name):
                continue
            names.add(normalize_title(title))
    return names


def _plain_snippet(text: str) -> str:
    return clean_wiki_snippet(_HTML_TAG_RE.sub(" ", text))


def _profile_pool_for_boss(
    boss_name: str,
    *,
    boss_pool_items: list[dict[str, Any]],
    section_blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    pattern = re.compile(rf"\b{re.escape(boss_name)}\b", re.IGNORECASE)
    slug_pattern = re.compile(
        rf"/wiki/{re.escape(boss_name.replace(' ', '_'))}\b",
        re.IGNORECASE,
    )
    default_source_id = str(boss_pool_items[0].get("source_id", "")).strip() if boss_pool_items else ""
    pool: list[dict[str, Any]] = []
    for item in boss_pool_items:
        raw_snippet = str(item.get("snippet", ""))
        snippet = _plain_snippet(raw_snippet)
        if pattern.search(snippet) or slug_pattern.search(snippet) or slug_pattern.search(raw_snippet):
            pool.append({**item, "snippet": snippet})
    for block in section_blocks:
        if not isinstance(block, dict):
            continue
        raw_text = str(block.get("text", ""))
        text = _plain_snippet(raw_text)
        if not (
            pattern.search(text)
            or slug_pattern.search(text)
            or slug_pattern.search(raw_text)
        ):
            continue
        role = str(block.get("section_role", "other"))
        pool.append(
            {
                "snippet": text,
                "section_role": role,
                "source_id": default_source_id,
                "field_name": "boss_pool",
            }
        )
    return pool


def collect_boss_candidates(
    *,
    section_blocks: list[dict[str, Any]],
    instance_name: str,
    boss_pool_items: list[dict[str, Any]] | None = None,
    structured_links: list[dict[str, Any]] | None = None,
) -> list[BossCandidate]:
    """Parse boss names from encounter sections, structured links, and boss_pool evidence."""
    boss_pool_items = boss_pool_items or []
    candidates: dict[str, BossCandidate] = {}

    def _register(title: str, url: str, role: str) -> None:
        if should_reject_boss_title(title, instance_name=instance_name):
            return
        boss_id = _slug_id(title)
        if not boss_id:
            return
        key = normalize_title(title)
        if key in candidates:
            return
        candidates[key] = BossCandidate(
            boss_id=boss_id,
            name=title,
            wiki_url=url,
            source_section_role=role,
        )

    for block in section_blocks:
        if not isinstance(block, dict):
            continue
        if not row_has_roster_role(block):
            continue
        leaf_role = str(block.get("section_role", "other"))
        role = leaf_role if is_boss_section_role(leaf_role) else str(block.get("parent_section_role", leaf_role))
        text = str(block.get("text", ""))
        for title, url in _extract_wiki_links(text):
            _register(title, url, role)

    for row in structured_links or []:
        if not isinstance(row, dict):
            continue
        if not row_has_roster_role(row):
            continue
        href = str(row.get("href", "")).strip()
        if not href.startswith("/wiki/"):
            continue
        path = href.removeprefix("/wiki/").split("#", 1)[0].strip()
        if not path:
            continue
        title = str(row.get("label", "")).strip() or _title_from_wiki_path(path)
        role = str(row.get("section_role", "structured_link"))
        url = href if href.startswith("http") else f"https://warcraft.wiki.gg/wiki/{path}"
        _register(title, url, role)

    for item in boss_pool_items:
        for title, url in _extract_wiki_links(str(item.get("snippet", ""))):
            _register(title, url, str(item.get("section_role", "boss_pool")))

    ordered = sorted(candidates.values(), key=lambda row: row.name.lower())
    for candidate in ordered:
        candidate.profile_pool = _profile_pool_for_boss(
            candidate.name,
            boss_pool_items=boss_pool_items,
            section_blocks=section_blocks,
        )
    return ordered


_NARRATIVE_SECTION_TOKENS = (
    "lead",
    "overview",
    "official",
    "history",
    "story",
    "description",
    "lore",
    "introduction",
    "background",
)

_PERSON_HONORIFICS = frozenset(
    {
        "highlord",
        "high",
        "lord",
        "lady",
        "professor",
        "archmage",
        "king",
        "queen",
        "prince",
        "princess",
        "sir",
        "dame",
        "captain",
        "commander",
        "general",
        "warchief",
        "warlord",
        "grand",
        "master",
        "baron",
        "baroness",
        "bishop",
        "sergeant",
        "marshal",
        "admiral",
        "chief",
        "elder",
        "prophet",
        "overlord",
        "lich",
        "emperor",
        "empress",
        "champion",
        "keeper",
        "prime",
    }
)

# Registry kinds that mark a link as a location, never an individual character.
_LOCATION_KINDS = frozenset({"place", "zone", "instance", "continent", "capital", "region"})

# Multi-word capitalized titles that are factions/forces/concepts, not individual characters.
_NON_PERSON_NARRATIVE_TITLES = frozenset(
    {
        "burning legion",
        "the burning legion",
        "scourge",
        "the scourge",
        "alliance",
        "the alliance",
        "horde",
        "the horde",
        "old god",
        "old gods",
        "scarlet crusade",
        "argent crusade",
        "argent dawn",
        "argent tournament",
        "sons of hodir",
        "kirin tor",
        "ashen verdict",
        "knights of the ebon blade",
        "bronze dragonflight",
        "black dragonflight",
        "green dragonflight",
        "red dragonflight",
        "blue dragonflight",
        "dragonflight",
        "twilight's hammer",
        "cult of the damned",
        "forsaken",
        "valarjar",
        "burning crusade",
        "boneguard",
        "warsong offensive",
        "valiance expedition",
        "gnomeregan army",
        "saronite",
        "adventurer",
        "event",
        "faction",
        "novels",
        "novellas",
        "short stories",
        "technology",
    }
)

# Generic common-noun / race / creature-type words that are not named characters.
_GENERIC_NON_PERSON_WORDS = frozenset(
    {
        "class",
        "race",
        "quest",
        "item",
        "mob",
        "boss",
        "comic",
        "comics",
        "novel",
        "engineer",
        "robot",
        "ram",
        "rat",
        "plane",
        "giant",
        "demon",
        "demigod",
        "undead",
        "elemental",
        "human",
        "orc",
        "dwarf",
        "gnome",
        "troll",
        "tauren",
        "goblin",
        "vrykul",
        "earthen",
        "mechagnome",
        "broken",
        "aqir",
        "nathrezim",
        "golem",
        "bloodhound",
        "survivor",
        "dungeon",
    }
)


def _is_narrative_role(section_role: str) -> bool:
    lowered = _normalize_role(section_role)
    return any(token in lowered for token in _NARRATIVE_SECTION_TOKENS)


def _looks_like_person(title: str) -> bool:
    """Heuristic person/NPC detector for narrative-fallback link mining."""
    norm = normalize_title(title)
    if norm in _NON_PERSON_NARRATIVE_TITLES or norm in _GENERIC_NON_PERSON_WORDS:
        return False
    kinds = entry_kinds(title)
    if kinds & _LOCATION_KINDS:
        return False
    words = title.split()
    if not words:
        return False
    first_word = re.sub(r"[^a-z]", "", words[0].lower())
    if first_word in _PERSON_HONORIFICS:
        return True
    if "person" in kinds:
        return True
    if len(words) > 4:
        return False
    significant = [word for word in words if re.search(r"[A-Za-z]", word)]
    if not significant or not all(word[0].isupper() for word in significant):
        return False
    if len(significant) == 1:
        token = re.sub(r"[^A-Za-z'\-]", "", significant[0])
        return len(token) >= 4
    return True


def mine_narrative_character_candidates(
    section_blocks: list[dict[str, Any]],
    *,
    instance_name: str,
    structured_links: list[dict[str, Any]] | None = None,
    narrative_pool: list[dict[str, Any]] | None = None,
    max_count: int = 10,
) -> list[BossCandidate]:
    """Deterministic grounding: mine person-like /wiki/ links from narrative content.

    Used as the narrative fallback when roster extraction yields nothing. Sources
    are narrative section blocks and narrative-scoped structured links (the latter
    survive ingest tag-stripping in real runs). Every returned candidate is backed
    by a real /wiki/ link, ranked by mention frequency then name, and capped. No LLM.
    """
    first_seen: dict[str, tuple[str, str]] = {}
    order: list[str] = []

    # Many wiki pages place their roster/lore in an eponymous lead bucket: the
    # MediaWiki <h1> article title is slugified into a section role equal to the
    # instance name (e.g. "razorfen_kraul"), which is neither a roster nor a
    # narrative role. Treat that bucket as narrative for the fallback so those
    # pages are not invisible. Compare on the same slug scheme used for section
    # roles, article-insensitive, so apostrophes/commas/"The " don't break it.
    def _slug_core(value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
        return slug[4:] if slug.startswith("the_") else slug

    instance_core = _slug_core(instance_name)

    def _is_narrative_for_instance(role: str) -> bool:
        return _is_narrative_role(role) or (bool(instance_core) and _slug_core(role) == instance_core)

    def _row_is_narr(row: dict[str, Any]) -> bool:
        if _is_narrative_for_instance(str(row.get("section_role", "other"))):
            return True
        parent = str(row.get("parent_section_role", "")).strip()
        return bool(parent) and _is_narrative_for_instance(parent)

    narrative_text = " ".join(
        _plain_snippet(str(block.get("text", "")))
        for block in section_blocks
        if isinstance(block, dict) and _row_is_narr(block)
    ).lower()

    def _accept(title: str, url: str) -> None:
        if should_reject_boss_title(title, instance_name=instance_name):
            return
        if not _looks_like_person(title):
            return
        key = normalize_title(title)
        if key not in first_seen:
            first_seen[key] = (title, url)
            order.append(key)

    for block in section_blocks:
        if not isinstance(block, dict):
            continue
        if not _row_is_narr(block):
            continue
        for title, url in _extract_wiki_links(str(block.get("text", ""))):
            _accept(title, url)

    for row in structured_links or []:
        if not isinstance(row, dict) or not _row_is_narr(row):
            continue
        href = str(row.get("href", "")).strip()
        if not href.startswith("/wiki/"):
            continue
        path = href.removeprefix("/wiki/").split("#", 1)[0].strip()
        if not path:
            continue
        title = str(row.get("label", "")).strip() or _title_from_wiki_path(path)
        url = href if href.startswith("http") else f"https://warcraft.wiki.gg/wiki/{path}"
        _accept(title, url)

    def _mention_frequency(title: str) -> int:
        if not narrative_text:
            return 0
        count = len(re.findall(rf"\b{re.escape(title.lower())}\b", narrative_text))
        if count == 0:
            last_token = title.split()[-1].lower() if title.split() else ""
            if len(last_token) >= 4:
                count = len(re.findall(rf"\b{re.escape(last_token)}\b", narrative_text))
        return count

    ranked = sorted(order, key=lambda key: (-_mention_frequency(first_seen[key][0]), key))
    results: list[BossCandidate] = []
    for key in ranked[:max_count]:
        title, url = first_seen[key]
        boss_id = _slug_id(title)
        if not boss_id:
            continue
        candidate = BossCandidate(
            boss_id=boss_id,
            name=title,
            wiki_url=url,
            source_section_role="narrative_fallback",
        )
        candidate.profile_pool = _profile_pool_for_boss(
            candidate.name,
            boss_pool_items=narrative_pool or [],
            section_blocks=section_blocks,
        )
        results.append(candidate)
    return results
