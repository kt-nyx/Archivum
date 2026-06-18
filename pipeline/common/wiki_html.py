"""BeautifulSoup-based Warcraft Wiki HTML parsing helpers.

Single home for HTML-structure parsing, replacing the per-module regex scrapers.
Text is extracted decoded (HTML entities resolved) and whitespace-collapsed, which
is what downstream consumers want for names/titles/snippets.

Parser: the stdlib ``html.parser`` backend is used for fidelity to source fragment
order (it does not restructure stray table rows the way ``lxml`` can).
"""

from __future__ import annotations

from typing import Any

from bs4 import BeautifulSoup
from bs4.element import Tag

_PARSER = "html.parser"

# Document-order content elements. Headings update the current section; paragraphs,
# list items, and content-table cells become blocks.
_BLOCK_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "td", "th")

# Chrome tables (infoboxes, navboxes, ToCs, message boxes) carry navigation/metadata,
# not roster content; their cells are dropped before the block walk.
_EXCLUDED_TABLE_CLASS_TOKENS = (
    "infobox",
    "navbox",
    "toc",
    "metadata",
    "mbox",
    "noprint",
    "navigation",
)


def soup(html: str) -> BeautifulSoup:
    """Parse an HTML fragment into a BeautifulSoup tree."""
    return BeautifulSoup(html or "", _PARSER)


def _collapse(text: str) -> str:
    return " ".join(text.split())


def strip_tags(html: str) -> str:
    """Return the decoded, whitespace-collapsed text content of an HTML fragment."""
    return _collapse(soup(html).get_text(" "))


def _table_is_chrome(table: Tag) -> bool:
    classes = " ".join(table.get("class") or []).lower()
    return any(token in classes for token in _EXCLUDED_TABLE_CLASS_TOKENS)


def _drop_chrome_tables(root: BeautifulSoup) -> None:
    """Remove top-level chrome tables (and their nested content) in place.

    Only top-level tables are evaluated, matching the original ingest behavior where
    a chrome table nested inside a kept content table stays with its parent.
    """
    for table in root.find_all("table"):
        if table.find_parent("table") is None and _table_is_chrome(table):
            table.decompose()


def content_blocks(html: str, *, drop_chrome: bool = True) -> list[dict[str, str]]:
    """Return top-most content blocks in document order.

    Each block is ``{"tag": <element name>, "text": <decoded collapsed text>}`` for
    the outermost ``h1..h6 / p / li / td / th`` elements (nested blocks are folded
    into their ancestor's text, never emitted twice). Empty-text blocks are included
    so callers can apply their own section/skip logic.
    """
    root = soup(html)
    if drop_chrome:
        _drop_chrome_tables(root)
    blocks: list[dict[str, str]] = []
    for element in root.find_all(_BLOCK_TAGS):
        if element.find_parent(_BLOCK_TAGS) is not None:
            continue  # nested inside another block; folded into the ancestor's text
        blocks.append({"tag": element.name.lower(), "text": _collapse(element.get_text(" "))})
    return blocks


def paragraph_texts(html: str) -> list[str]:
    """Return decoded text for every ``<p>`` in document order (chrome included)."""
    texts = [_collapse(p.get_text(" ")) for p in soup(html).find_all("p")]
    return [text for text in texts if text]


def iter_tagged_text(html: str, tags: tuple[str, ...]) -> list[dict[str, str]]:
    """Return ``{tag, text}`` for every matching element in document order (chrome included)."""
    return [
        {"tag": el.name.lower(), "text": _collapse(el.get_text(" "))}
        for el in soup(html).find_all(tags)
    ]


def iter_headings(html: str, *, levels: tuple[int, ...] = (2, 3)) -> list[dict[str, Any]]:
    """Return headings of the given levels in document order: ``{level, text}``."""
    tags = tuple(f"h{level}" for level in levels)
    out: list[dict[str, Any]] = []
    for heading in soup(html).find_all(tags):
        text = _collapse(heading.get_text(" "))
        if text:
            out.append({"level": int(heading.name[1:]), "text": text})
    return out


def list_item_texts(html: str) -> list[str]:
    """Return decoded text for every ``<li>`` in document order."""
    texts = [_collapse(li.get_text(" ")) for li in soup(html).find_all("li")]
    return [text for text in texts if text]


def extract_links(html: str, *, max_links: int = 300) -> list[str]:
    """Return de-duplicated wiki link hrefs (``/wiki/...`` or ``warcraft.wiki.gg/wiki/...``)."""
    links: list[str] = []
    for anchor in soup(html).find_all("a", href=True):
        href = str(anchor["href"]).strip()
        if not href:
            continue
        if href.startswith("/wiki/") or "warcraft.wiki.gg/wiki/" in href:
            links.append(href)
        if len(links) >= max_links:
            break
    return list(dict.fromkeys(links))
