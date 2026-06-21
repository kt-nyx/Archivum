"""Structure-based detection and resolution of quest hub/disambiguation pages."""

from __future__ import annotations

import re
from typing import Any

from pipeline.common import wiki_html
from pipeline.discovery.entity_typing import is_valid_quest_graph_link
from pipeline.discovery.quest_lore import extract_quest_lore, lore_word_count

# Text-level href scan for block text (already tag-stripped); not HTML-structure parsing.
_HREF_RE = re.compile(r'href="(/wiki/[^"#]+)"', re.IGNORECASE)
_HUB_LORE_WORD_THRESHOLD = 80
_MAX_HUB_CHILDREN = 2


def _normalized_wiki_link(href: str) -> str:
    value = str(href).strip()
    return value.split("#", 1)[0] if value.startswith("/wiki/") else ""


def _normalize_wiki_href(link: str) -> str:
    value = str(link).strip()
    if not value:
        return ""
    if value.startswith("/wiki/"):
        return value.split("#", 1)[0]
    if "/wiki/" in value:
        idx = value.index("/wiki/")
        return value[idx:].split("#", 1)[0]
    return ""


def _quest_links_from_html(html: str) -> list[str]:
    root = wiki_html.soup(html)
    links: list[str] = []
    seen: set[str] = set()
    # Prefer questlink anchors inside list items.
    for list_item in root.find_all("li"):
        for anchor in list_item.find_all("a", href=True):
            if not any("questlink" in cls for cls in (anchor.get("class") or [])):
                continue
            href = _normalized_wiki_link(str(anchor["href"]))
            if href and href not in seen:
                seen.add(href)
                links.append(href)
    if len(links) >= 2:
        return links
    # Fallback: every wiki anchor in document order.
    for anchor in root.find_all("a", href=True):
        href = _normalized_wiki_link(str(anchor["href"]))
        if href and href not in seen:
            seen.add(href)
            links.append(href)
    return links


def _quest_links_from_blocks(section_blocks: list[dict[str, Any]]) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    for block in section_blocks:
        if not isinstance(block, dict):
            continue
        text = str(block.get("text", ""))
        for match in _HREF_RE.finditer(text):
            href = str(match.group(1)).strip()
            if href and href not in seen:
                seen.add(href)
                links.append(href)
    return links


def _quest_links_from_structured(structured_links: list[dict[str, Any]]) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    for row in structured_links:
        if not isinstance(row, dict):
            continue
        href = _normalize_wiki_href(str(row.get("href", "")))
        if href and href not in seen:
            seen.add(href)
            links.append(href)
    return links


def _quest_links_from_wiki_links(wiki_links: list[str]) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    for raw in wiki_links:
        href = _normalize_wiki_href(raw)
        if href and href not in seen:
            seen.add(href)
            links.append(href)
    return links


def collect_quest_link_candidates(
    *,
    section_blocks: list[dict[str, Any]],
    parse_html: str = "",
    wiki_links: list[str] | None = None,
    structured_links: list[dict[str, Any]] | None = None,
) -> list[str]:
    if parse_html.strip():
        html_links = _quest_links_from_html(parse_html)
        if len(html_links) >= 2:
            return html_links
    structured = _quest_links_from_structured(structured_links or [])
    if len(structured) >= 2:
        return structured
    plain_links = _quest_links_from_wiki_links(wiki_links or [])
    if len(plain_links) >= 2:
        return plain_links
    return _quest_links_from_blocks(section_blocks)


def is_quest_hub_page(
    section_blocks: list[dict[str, Any]],
    *,
    parse_html: str = "",
    wiki_links: list[str] | None = None,
    structured_links: list[dict[str, Any]] | None = None,
    zone_name: str = "",
) -> bool:
    candidates = collect_quest_link_candidates(
        section_blocks=section_blocks,
        parse_html=parse_html,
        wiki_links=wiki_links,
        structured_links=structured_links,
    )
    valid = [link for link in candidates if is_valid_quest_graph_link(link, zone_name=zone_name)[0]]
    if len(valid) < 2:
        return False
    lore_words = lore_word_count(extract_quest_lore(section_blocks))
    if parse_html.strip() and lore_words == 0:
        stripped = wiki_html.strip_tags(parse_html)
        if len(stripped.split()) < _HUB_LORE_WORD_THRESHOLD:
            return True
    return lore_words < _HUB_LORE_WORD_THRESHOLD


def resolve_hub_child_links(
    section_blocks: list[dict[str, Any]],
    *,
    parse_html: str = "",
    wiki_links: list[str] | None = None,
    structured_links: list[dict[str, Any]] | None = None,
    zone_name: str = "",
    max_children: int = _MAX_HUB_CHILDREN,
) -> list[str]:
    if not is_quest_hub_page(
        section_blocks,
        parse_html=parse_html,
        wiki_links=wiki_links,
        structured_links=structured_links,
        zone_name=zone_name,
    ):
        return []
    candidates = collect_quest_link_candidates(
        section_blocks=section_blocks,
        parse_html=parse_html,
        wiki_links=wiki_links,
        structured_links=structured_links,
    )
    resolved: list[str] = []
    for link in candidates:
        valid, _ = is_valid_quest_graph_link(link, zone_name=zone_name)
        if not valid:
            continue
        if link not in resolved:
            resolved.append(link)
        if len(resolved) >= max_children:
            break
    return resolved
