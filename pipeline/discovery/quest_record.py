"""Parse the wiki ``{{Questbox}}`` parse tree into a structured QuestRecord.

MediaWiki ``action=parse&prop=parsetree`` returns the page preprocessed into an
XML tree: template invocations become ``<template>`` nodes (with ``<part>`` /
``<name>`` / ``<value>`` children), while ordinary wikitext — including
``[[links]]`` — survives as literal text inside the value nodes. This module
reconstructs the wikitext of the relevant Questbox parameters and pulls out the
fields clustering / significance / anchor stages need:

* ``start``/``end`` NPC (+ coordinates / sub-region from ``{{Co|x|y|zone}}``)
* ``previous`` / ``next`` chain edges (the in-game prerequisite graph)
* ``category`` (zone / sub-region) and ``reputation`` org
* faction binding (Alliance / Horde / shared)
* faction-mirror variant links when the page is a ``{{Faction disambiguation}}``

A page whose parse tree contains no Questbox and is not a faction-disambiguation
page is not a quest, so :func:`build_quest_record` returns ``None`` (used as the
not-a-quest filter that drops achievements, hubs, and hatnote pages).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

from pipeline.common.discovery_vocab import (
    quest_alliance_binding_tokens,
    quest_horde_binding_tokens,
)
from pipeline.discovery.quest_lore import extract_quest_lore

_QUESTBOX_TITLES = frozenset({"questbox", "quest box"})
_FACTION_DISAMBIG_HINT = re.compile(r"faction\s*disambig", re.IGNORECASE)

# [[Target]] or [[Target|label]] (drop the section anchor and label).
_LINK_RE = re.compile(r"\[\[\s*([^\]\|#]+?)\s*(?:\||#|\]\])")
# {{Co|x|y|zone}} coordinate template (zone arg optional).
_CO_RE = re.compile(
    r"\{\{\s*[Cc]o\s*\|\s*([0-9.]+)\s*\|\s*([0-9.]+)\s*(?:\|\s*([^}|]+?)\s*)?(?:\||\}\})"
)
_NAMESPACE_LINK_RE = re.compile(r"^[A-Za-z][A-Za-z ]*:")

# WS-C: faction-binding tokens (matched against free Questbox wikitext) are
# externalized to pipeline/data/discovery_classification_vocab.v1.json (D-6).
_ALLIANCE_TOKENS = quest_alliance_binding_tokens()
_HORDE_TOKENS = quest_horde_binding_tokens()


def _local_text(elem: ET.Element | None) -> str:
    return "" if elem is None else (elem.text or "")


def _render_template(template: ET.Element) -> str:
    """Reconstruct ``{{title|arg|name=value}}`` wikitext from a template node."""
    title = _node_wikitext(template.find("title")).strip()
    parts: list[str] = []
    for part in template.findall("part"):
        name_el = part.find("name")
        value = _node_wikitext(part.find("value"))
        # Positional parts carry an ``index`` attribute and an empty <name>.
        name_text = _node_wikitext(name_el).strip() if name_el is not None else ""
        is_named = name_el is not None and name_el.get("index") is None and name_text
        if is_named:
            parts.append(f"{name_text}={value.strip()}")
        else:
            parts.append(value.strip())
    if parts:
        return "{{" + title + "|" + "|".join(parts) + "}}"
    return "{{" + title + "}}"


def _node_wikitext(elem: ET.Element | None) -> str:
    """Best-effort reconstruction of the wikitext contained in ``elem``.

    Literal text (which includes ``[[links]]``) is preserved; nested templates
    are re-rendered as ``{{...}}`` so coordinate/level helpers stay detectable.
    """
    if elem is None:
        return ""
    chunks: list[str] = [elem.text or ""]
    for child in elem:
        tag = child.tag.lower()
        if tag == "template":
            chunks.append(_render_template(child))
        elif tag in {"comment", "ignore"}:
            pass
        else:
            chunks.append(_node_wikitext(child))
        chunks.append(child.tail or "")
    return "".join(chunks)


def _all_links(wikitext: str) -> list[str]:
    links: list[str] = []
    for match in _LINK_RE.finditer(wikitext):
        title = match.group(1).strip()
        if title:
            links.append(title)
    return links


def _first_link(wikitext: str) -> str:
    links = _all_links(wikitext)
    return links[0] if links else ""


def _plain_text(wikitext: str) -> str:
    text = re.sub(r"\{\{[^{}]*\}\}", " ", wikitext)
    text = _LINK_RE.sub(lambda m: m.group(1), text)
    text = re.sub(r"\[\[|\]\]|'''|''", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _coords(wikitext: str) -> tuple[str, str]:
    """Return (``"x, y"`` coords, sub-region/zone) from a ``{{Co}}`` template."""
    match = _CO_RE.search(wikitext)
    if not match:
        return "", ""
    coords = f"{match.group(1)}, {match.group(2)}"
    subregion = (match.group(3) or "").strip()
    return coords, subregion


def _iter_templates(root: ET.Element) -> list[ET.Element]:
    return list(root.iter("template"))


def _template_title(template: ET.Element) -> str:
    return re.sub(r"\s+", " ", _node_wikitext(template.find("title"))).strip().lower()


def find_questbox(root: ET.Element) -> ET.Element | None:
    for template in _iter_templates(root):
        if _template_title(template) in _QUESTBOX_TITLES:
            return template
    return None


def _template_params(template: ET.Element) -> dict[str, str]:
    params: dict[str, str] = {}
    for part in template.findall("part"):
        name = _node_wikitext(part.find("name")).strip().lower()
        if not name:
            continue
        params[name] = _node_wikitext(part.find("value")).strip()
    return params


def _infer_faction(params: dict[str, str]) -> str:
    side = params.get("side", "").lower()
    if any(token in side for token in _ALLIANCE_TOKENS):
        return "alliance"
    if any(token in side for token in _HORDE_TOKENS):
        return "horde"
    faction = params.get("faction", "").lower()
    if any(token in faction for token in _ALLIANCE_TOKENS):
        return "alliance"
    if any(token in faction for token in _HORDE_TOKENS):
        return "horde"
    rep = _plain_text(params.get("reputation", "")).lower()
    if any(token in rep for token in _ALLIANCE_TOKENS):
        return "alliance"
    if any(token in rep for token in _HORDE_TOKENS):
        return "horde"
    return "shared"


def _is_faction_disambiguation(root: ET.Element) -> bool:
    for template in _iter_templates(root):
        if _FACTION_DISAMBIG_HINT.search(_template_title(template)):
            return True
    return False


def faction_disambiguation_variants(root: ET.Element) -> list[str]:
    """Return per-faction variant page titles linked from a disambiguation page."""
    if not _is_faction_disambiguation(root):
        return []
    variants: list[str] = []
    seen: set[str] = set()
    for link in _all_links(_node_wikitext(root)):
        if _NAMESPACE_LINK_RE.match(link):
            continue
        key = link.lower()
        if key in seen:
            continue
        seen.add(key)
        variants.append(link)
    return variants


def parse_parsetree(parse_tree: str) -> ET.Element | None:
    if not parse_tree or not parse_tree.strip():
        return None
    try:
        return ET.fromstring(parse_tree)
    except ET.ParseError:
        return None


def _description(section_blocks: list[dict[str, Any]] | None) -> str:
    if not section_blocks:
        return ""
    snippets = extract_quest_lore(section_blocks)
    return " ".join(str(row.get("text", "")).strip() for row in snippets if row.get("text")).strip()


def build_quest_record(
    *,
    zone_id: str,
    node_id: str,
    quest_title: str,
    source_link: str,
    parse_tree: str,
    section_blocks: list[dict[str, Any]] | None = None,
    faction_binding: str = "shared",
) -> dict[str, Any] | None:
    """Build a QuestRecord dict from a quest page parse tree.

    Returns ``None`` when the page is neither a quest (no ``{{Questbox}}``) nor a
    faction-disambiguation page. Disambiguation pages return a record with
    ``has_questbox=False`` and ``faction_mirror`` populated so the caller can
    fetch the per-faction variants.
    """
    root = parse_parsetree(parse_tree)
    if root is None:
        return None

    questbox = find_questbox(root)
    if questbox is None:
        variants = faction_disambiguation_variants(root)
        if not variants:
            return None
        valid_factions = {"alliance", "horde", "shared"}
        safe_faction = faction_binding if faction_binding in valid_factions else "shared"
        return {
            "zone_id": zone_id,
            "node_id": node_id,
            "quest_title": quest_title,
            "source_link": source_link,
            "has_questbox": False,
            "start_npc": "",
            "start_location": "",
            "start_coords": "",
            "end_npc": "",
            "category": "",
            "reputation_org": "",
            "faction": safe_faction,
            "previous": [],
            "next": [],
            "faction_mirror": variants,
            "description": "",
        }

    params = _template_params(questbox)
    start_value = params.get("start", "")
    start_coords, start_subregion = _coords(start_value)
    category_value = params.get("category", "")
    category = _plain_text(category_value) or _first_link(category_value)
    reputation_value = params.get("reputation", "")
    reputation_org = _first_link(reputation_value) or _plain_text(reputation_value)
    faction = _infer_faction(params)
    if faction == "shared" and faction_binding in {"alliance", "horde"}:
        faction = faction_binding

    return {
        "zone_id": zone_id,
        "node_id": node_id,
        "quest_title": quest_title or _plain_text(params.get("name", "")) or quest_title,
        "source_link": source_link,
        "has_questbox": True,
        "start_npc": _first_link(start_value) or _plain_text(start_value),
        "start_location": start_subregion,
        "start_coords": start_coords,
        "end_npc": _first_link(params.get("end", "")) or _plain_text(params.get("end", "")),
        "category": category,
        "reputation_org": reputation_org,
        "faction": faction,
        "previous": _all_links(params.get("previous", "")),
        "next": _all_links(params.get("next", "")),
        "faction_mirror": [],
        "description": _description(section_blocks),
    }
