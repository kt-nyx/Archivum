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

# Chrome containers that wiki templates render as <div>/<nav>, not <table> — navboxes,
# category footers, ToCs, hatnotes. These survive table-only chrome dropping and otherwise
# leak place-name/link lists into evidence pools (e.g. the Argent Crusade navbox summary, #2).
_EXCLUDED_DIV_CLASS_TOKENS = (
    "navbox",
    "navigation",
    "noprint",
    "toc",
    "catlinks",
    "footer",
    "hatnote",
    "metadata",
    "mbox",
)
_CHROME_CONTAINER_TAGS = ("div", "nav")


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


def _div_is_chrome(element: Tag) -> bool:
    classes = " ".join(element.get("class") or []).lower()
    role = str(element.get("role") or "").lower()
    if role == "navigation":
        return True
    return any(token in classes for token in _EXCLUDED_DIV_CLASS_TOKENS)


def _drop_chrome_tables(root: BeautifulSoup) -> None:
    """Remove top-level chrome tables/containers (and nested content) in place.

    Only top-level tables are evaluated, matching the original ingest behavior where
    a chrome table nested inside a kept content table stays with its parent. The chrome
    elements are collected before any removal, because decomposing one detaches any
    nested chrome still pending in the iteration. Beyond ``<table>`` chrome we also drop
    template-rendered ``<div>``/``<nav>`` chrome (navboxes, category footers, ToCs) that
    would otherwise leak place-name/link lists into evidence pools (#2).
    """
    chrome = [
        table
        for table in root.find_all("table")
        if table.find_parent("table") is None and _table_is_chrome(table)
    ]
    chrome.extend(
        element for element in root.find_all(_CHROME_CONTAINER_TAGS) if _div_is_chrome(element)
    )
    for element in chrome:
        # A nested chrome container may already have been destroyed when its chrome
        # ancestor was decomposed; skip those rather than decompose twice.
        if getattr(element, "decomposed", False):
            continue
        element.decompose()


def wiki_article_href(href: str) -> str:
    """Normalize an anchor href to a site-relative ``/wiki/...`` path.

    Absolute ``warcraft.wiki.gg/wiki/...`` links lose their origin and every link
    loses its fragment, so the same article resolves to one comparable path.
    Returns ``""`` for non-article links (external, ``#frag``, edit/redlinks).
    """
    value = str(href or "").strip()
    if value.startswith("/wiki/"):
        path = value
    elif "warcraft.wiki.gg/wiki/" in value:
        path = "/wiki/" + value.split("warcraft.wiki.gg/wiki/", 1)[1]
    else:
        return ""
    path = path.split("#", 1)[0]
    return path if len(path) > len("/wiki/") else ""


def _block_inline_links(element: Tag) -> list[dict[str, str]]:
    """Return the block's inline article links: ``[{anchor_text, href}]``.

    Document order, deduped per block by resolved href (first anchor wins).
    Text-less anchors (icon/image wrappers) are skipped — they are not inline
    prose links even when they target an article.
    """
    links: list[dict[str, str]] = []
    seen: set[str] = set()
    for anchor in element.find_all("a", href=True):
        anchor_text = _collapse(anchor.get_text(" "))
        if not anchor_text:
            continue
        href = wiki_article_href(str(anchor["href"]))
        if not href or href in seen:
            continue
        seen.add(href)
        links.append({"anchor_text": anchor_text, "href": href})
    return links


def content_blocks(html: str, *, drop_chrome: bool = True) -> list[dict[str, Any]]:
    """Return top-most content blocks in document order.

    Each block is ``{"tag": <element name>, "text": <decoded collapsed text>,
    "links": [{anchor_text, href}]}`` for the outermost ``h1..h6 / p / li / td / th``
    elements (nested blocks are folded into their ancestor's text and links, never
    emitted twice). ``links`` holds the block's inline article links in order,
    deduped per block (empty list when the block has none). Empty-text blocks are
    included so callers can apply their own section/skip logic.
    """
    root = soup(html)
    if drop_chrome:
        _drop_chrome_tables(root)
    blocks: list[dict[str, Any]] = []
    for element in root.find_all(_BLOCK_TAGS):
        if element.find_parent(_BLOCK_TAGS) is not None:
            continue  # nested inside another block; folded into the ancestor's text
        blocks.append(
            {
                "tag": element.name.lower(),
                "text": _collapse(element.get_text(" ")),
                "links": _block_inline_links(element),
            }
        )
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


def parse_infobox(html: str) -> dict[str, str]:
    """Return label→value pairs from the first ``infobox`` table, decoded and collapsed.

    Only rows carrying both a header cell and a value cell are kept; the first value
    wins on duplicate labels. The infobox's own title — a leading header-only row
    (``<th>`` without a ``<td>``, how the wiki renders the subject name banner) — is
    stored under the reserved ``"_title"`` key, which cannot collide with wiki labels
    (a character infobox's real ``Title`` row keeps its own key). Header-only rows
    after the first field are in-box section headers ("Bosses"), not the title, and
    are skipped. Returns ``{}`` when no infobox is present.
    """
    root = soup(html)
    table = next(
        (t for t in root.find_all("table") if "infobox" in " ".join(t.get("class") or []).lower()),
        None,
    )
    if table is None:
        return {}
    fields: dict[str, str] = {}
    for row in table.find_all("tr"):
        header = row.find("th")
        value = row.find("td")
        if header is None:
            continue
        if value is None:
            title = _collapse(header.get_text(" "))
            if title and not fields:
                fields["_title"] = title
            continue
        key = _collapse(header.get_text(" "))
        if key and key not in fields:
            fields[key] = _collapse(value.get_text(" "))
    return fields


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
