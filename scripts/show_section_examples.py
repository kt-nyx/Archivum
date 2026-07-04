#!/usr/bin/env python3
"""Show real example content under a wiki section heading, to support registry curation.

You cannot classify a section label (``battles``, ``letter``, ``culture``) without seeing the
prose that actually sits under it. Given a label slug, this finds pages that use that heading
(from the harvest cache), fetches their wikitext, extracts the text under the matching heading,
and prints a cleaned snippet — so a human can decide narrative vs roster vs gameplay vs meta.

Usage:
    python -m scripts.show_section_examples battles letter culture
    python -m scripts.show_section_examples types --examples 3 --chars 500
"""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.parse
from pathlib import Path
from typing import Any

import httpx

from pipeline.common import http
from pipeline.common.text_ids import slugify

_WIKI_API = "https://warcraft.wiki.gg/api.php"
_USER_AGENT = "wow-lore-section-examples/1.0 (registry curation; contact nymphipoo@gmail.com)"
_CACHE = Path("pipeline/data/.section_label_harvest_cache_v2.json")

_HEADING_RE = re.compile(r"^(={2,6})[ \t]*(.+?)[ \t]*\1[ \t]*$", re.M)
_REF_RE = re.compile(r"<ref[^>]*>.*?</ref>|<ref[^>]*/>", re.S)
_TEMPLATE_RE = re.compile(r"\{\{[^{}]*\}\}")
_LINK_RE = re.compile(r"\[\[(?:[^\]|]*\|)?([^\]|]+)\]\]")
_EXTLINK_RE = re.compile(r"\[https?://[^\s\]]+\s*([^\]]*)\]")
_TAG_RE = re.compile(r"<[^>]+>")
_BOLDITALIC_RE = re.compile(r"'{2,}")


def _get_wikitext(title: str) -> str:
    params = {
        "action": "query",
        "titles": title,
        "prop": "revisions",
        "rvprop": "content",
        "rvslots": "main",
        "format": "json",
        "formatversion": "2",
        "maxlag": "5",
    }
    url = f"{_WIKI_API}?{urllib.parse.urlencode(params)}"
    for attempt in range(6):
        try:
            data = http.send("GET", url, headers={"User-Agent": _USER_AGENT}, timeout=60).json()
        except (httpx.HTTPStatusError, httpx.RequestError):
            time.sleep(2.0 * (attempt + 1))
            continue
        if data.get("error", {}).get("code") == "maxlag":
            time.sleep(5.0)
            continue
        pages = data.get("query", {}).get("pages", [])
        if not pages:
            return ""
        revs = pages[0].get("revisions") or [{}]
        return revs[0].get("slots", {}).get("main", {}).get("content", "") or ""
    return ""


def _section_text(wikitext: str, slug: str) -> tuple[str, str]:
    """Return (heading_text, raw_body) for the first heading whose slug matches, else ('','')."""
    matches = list(_HEADING_RE.finditer(wikitext))
    for i, m in enumerate(matches):
        if slugify(m.group(2), separator="_") == slug:
            level = len(m.group(1))
            start = m.end()
            end = len(wikitext)
            for nxt in matches[i + 1 :]:
                if len(nxt.group(1)) <= level:
                    end = nxt.start()
                    break
            return m.group(2).strip(), wikitext[start:end].strip()
    return "", ""


def _clean(body: str) -> str:
    text = _REF_RE.sub("", body)
    for _ in range(3):  # nested templates
        text = _TEMPLATE_RE.sub("", text)
    text = _EXTLINK_RE.sub(r"\1", text)
    text = _LINK_RE.sub(r"\1", text)
    text = _BOLDITALIC_RE.sub("", text)
    text = _TAG_RE.sub("", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def _describe_structure(body: str) -> str:
    """Rough shape hint: is the section prose, a bullet list, or a table?"""
    stripped = body.lstrip()
    if stripped.startswith("{|") or "{|" in body[:80]:
        return "TABLE"
    list_lines = sum(1 for ln in body.splitlines() if ln.strip().startswith(("*", "#", ":")))
    prose_lines = sum(1 for ln in body.splitlines() if ln.strip() and not ln.strip().startswith(("*", "#", ":", "{", "|", "!")))
    if list_lines > prose_lines:
        return "LIST"
    if prose_lines:
        return "PROSE"
    return "OTHER"


def main() -> None:
    parser = argparse.ArgumentParser(description="Show example content under section headings.")
    parser.add_argument("slugs", nargs="+", help="Section label slugs to sample")
    parser.add_argument("--examples", type=int, default=2, help="Examples per label (default 2)")
    parser.add_argument("--chars", type=int, default=420, help="Snippet char cap (default 420)")
    parser.add_argument("--candidates", type=int, default=8, help="Max pages to try per label")
    parser.add_argument("--cache", type=Path, default=_CACHE)
    args = parser.parse_args()

    cache: dict[str, list[list[Any]]] = json.loads(args.cache.read_text(encoding="utf-8"))
    # index: slug -> [titles that carry it]
    pages_by_slug: dict[str, list[str]] = {}
    for title, headings in cache.items():
        for _lvl, slug, _par in headings:
            pages_by_slug.setdefault(slug, []).append(title)

    for slug in args.slugs:
        titles = pages_by_slug.get(slug, [])
        print("\n" + "=" * 78)
        print(f"LABEL: {slug}   (on {len(titles)} sampled pages)")
        print("=" * 78)
        if not titles:
            print("  (no sampled page carries this heading — try the harvest or a known page)")
            continue
        shown = 0
        for title in titles[: args.candidates]:
            if shown >= args.examples:
                break
            heading, body = _section_text(_get_wikitext(title), slug)
            if not body:
                continue
            snippet = _clean(body)
            if not snippet:
                continue
            shape = _describe_structure(body)
            print(f"\n  [{shape}] {title}  —  == {heading} ==")
            trimmed = snippet[: args.chars].replace("\n", "\n    ")
            print(f"    {trimmed}{'...' if len(snippet) > args.chars else ''}")
            shown += 1
        if shown == 0:
            print("  (matched pages had empty/transcluded bodies; try --candidates higher)")


if __name__ == "__main__":
    main()
