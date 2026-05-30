"""Structural boss/encounter parsing from instance wiki section blocks."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from pipeline.discovery.entity_typing import _DATING_CONVENTION_TITLE_RE, normalize_title
from pipeline.discovery.world_registry import entry_kinds

_WIKI_LINK_RE = re.compile(r"/wiki/([^|\s\]#<>]+)")
_BOSS_SECTION_TOKENS = ("adventurer", "encounter", "boss", "dungeon", "adventure_guide", "walkthrough")
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
    lowered = _normalize_role(section_role)
    return any(token in lowered for token in _BOSS_SECTION_TOKENS)


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


def _extract_wiki_links(text: str) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    seen: set[str] = set()
    for match in _WIKI_LINK_RE.finditer(text):
        path = match.group(1).split("#", 1)[0]
        title = _title_from_wiki_path(path)
        key = normalize_title(title)
        if not key or key in seen:
            continue
        seen.add(key)
        url = f"https://warcraft.wiki.gg/wiki/{path}"
        results.append((title, url))
    return results


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
        snippet = str(item.get("snippet", ""))
        if pattern.search(snippet) or slug_pattern.search(snippet):
            pool.append(item)
    for block in section_blocks:
        if not isinstance(block, dict):
            continue
        text = str(block.get("text", ""))
        if not (pattern.search(text) or slug_pattern.search(text)):
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
) -> list[BossCandidate]:
    """Parse boss names from encounter sections and boss_pool evidence."""
    boss_pool_items = boss_pool_items or []
    candidates: dict[str, BossCandidate] = {}

    for block in section_blocks:
        if not isinstance(block, dict):
            continue
        role = str(block.get("section_role", "other"))
        if not is_boss_section_role(role):
            continue
        text = str(block.get("text", ""))
        for title, url in _extract_wiki_links(text):
            if should_reject_boss_title(title, instance_name=instance_name):
                continue
            boss_id = _slug_id(title)
            if not boss_id:
                continue
            key = normalize_title(title)
            if key in candidates:
                continue
            candidates[key] = BossCandidate(
                boss_id=boss_id,
                name=title,
                wiki_url=url,
                source_section_role=role,
            )

    for item in boss_pool_items:
        for title, url in _extract_wiki_links(str(item.get("snippet", ""))):
            if should_reject_boss_title(title, instance_name=instance_name):
                continue
            boss_id = _slug_id(title)
            if not boss_id:
                continue
            key = normalize_title(title)
            if key in candidates:
                continue
            candidates[key] = BossCandidate(
                boss_id=boss_id,
                name=title,
                wiki_url=url,
                source_section_role=str(item.get("section_role", "boss_pool")),
            )

    ordered = sorted(candidates.values(), key=lambda row: row.name.lower())
    for candidate in ordered:
        candidate.profile_pool = _profile_pool_for_boss(
            candidate.name,
            boss_pool_items=boss_pool_items,
            section_blocks=section_blocks,
        )
    return ordered
