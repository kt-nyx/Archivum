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
)
_BOSS_SECTION_EXACT = frozenset(
    {
        "bosses",
        "denizens",
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
        role = str(block.get("section_role", "other"))
        if not is_boss_section_role(role):
            continue
        text = str(block.get("text", ""))
        for title, url in _extract_wiki_links(text):
            _register(title, url, role)

    for row in structured_links or []:
        if not isinstance(row, dict):
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
