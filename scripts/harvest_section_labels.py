#!/usr/bin/env python3
"""Harvest Warcraft Wiki section-heading labels game-wide to seed a section-label registry.

Motivation: ``pipeline/discovery/enrich.py`` classifies crawled sections with scattered
hardcoded literals + a substring ``era_section_role_tokens`` set. The substring approach is
brittle and *incorrect* (it false-matches ``crimson_legion``/``lights_wrath``). We want an
externalized exact-match registry (``section_label_registry.v1.json``) covering the whole game,
with the open tail handled by parent-inheritance. This script produces the frequency-ranked
evidence a human curates the registry head from.

It is a **manual developer tool**, not part of a pipeline run. Design:

- Whole-game, UNBIASED sampling via ``generator=random`` (namespace 0) — no hand-picked
  categories, so the label distribution reflects the real wiki, not a pilot slice.
- Headings + nesting are read from wikitext (``prop=revisions``): a ``== Heading ==`` line's
  ``=`` count is its level; a level-3+ subsection's parent is the enclosing level-2 heading.
  This mirrors the pipeline's ``section_role`` / ``parent_section_role`` (slug =
  ``slugify(heading,'_')``; the pipeline appends ``_edit`` from the HTML edit-link — a lookup
  strips a trailing ``_edit``). 50 pages per request keeps API load low (~120 req / 6k pages).
- API-polite: serial, ``maxlag=5``, sleep between calls, 429/lag backoff, resumable cache.

Usage:
    python -m scripts.harvest_section_labels                    # ~6k random pages (default)
    python -m scripts.harvest_section_labels --max-pages 15000  # broader
    python -m scripts.harvest_section_labels --summary-only     # recompute report from cache
    python -m scripts.harvest_section_labels --head 80
"""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.parse
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import httpx

from pipeline.common import http
from pipeline.common.text_ids import slugify

_WIKI_API = "https://warcraft.wiki.gg/api.php"
_USER_AGENT = "wow-lore-section-harvest/2.0 (registry seed; contact nymphipoo@gmail.com)"

_DEFAULT_OUTPUT = Path("pipeline/data/section_label_harvest.v1.json")
_DEFAULT_CACHE = Path("pipeline/data/.section_label_harvest_cache_v2.json")

_HEADING_RE = re.compile(r"^(={2,6})[ \t]*(.+?)[ \t]*\1[ \t]*$", re.M)
_TEMPLATE_RE = re.compile(r"\{\{[^{}]*\}\}")
_LINK_RE = re.compile(r"\[\[(?:[^\]|]*\|)?([^\]|]+)\]\]")
_BOLDITALIC_RE = re.compile(r"'{2,}")
_TAG_RE = re.compile(r"<[^>]+>")


def _api_get(params: dict[str, str], *, sleep_seconds: float) -> dict[str, Any]:
    url = f"{_WIKI_API}?{urllib.parse.urlencode(params)}"
    for attempt in range(12):
        try:
            resp = http.send("GET", url, headers={"User-Agent": _USER_AGENT}, timeout=60)
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429 and attempt < 11:
                time.sleep(min(60.0, 5.0 * (2 ** min(attempt, 4))))
                continue
            raise RuntimeError(f"api call failed: {exc!r}") from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"api call failed: {exc!r}") from exc
        # maxlag: the server asks us to back off
        if isinstance(data, dict) and data.get("error", {}).get("code") == "maxlag":
            time.sleep(min(30.0, 5.0 * (attempt + 1)))
            continue
        return data
    raise RuntimeError("api call exhausted retries")


def _clean_heading(raw: str) -> str:
    text = _TEMPLATE_RE.sub("", raw)
    text = _LINK_RE.sub(r"\1", text)
    text = _BOLDITALIC_RE.sub("", text)
    text = _TAG_RE.sub("", text)
    return text.strip()


def _headings_from_wikitext(text: str) -> list[tuple[int, str, str]]:
    """Return (level, slug, parent_slug) per heading; parent = enclosing level-2 heading."""
    out: list[tuple[int, str, str]] = []
    top = ""
    for m in _HEADING_RE.finditer(text):
        level = len(m.group(1))
        slug = slugify(_clean_heading(m.group(2)), separator="_")
        if not slug:
            continue
        if level <= 2:
            top = slug
        out.append((level, slug, top))
    return out


def _load_cache(path: Path) -> dict[str, list[list[Any]]]:
    if not path.exists():
        return {}
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return blob if isinstance(blob, dict) else {}


def _save_cache(cache: dict[str, list[list[Any]]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def _sample_random_pages(
    *, target_new: int, cache: dict[str, list[list[Any]]], cache_path: Path, sleep_seconds: float
) -> int:
    """Pull random ns-0 pages (50/req, with content), extract headings into the cache.

    Returns when ``target_new`` previously-unseen pages have been added this run. Random
    repeats are skipped via the cache. The saturation curve is printed as we go."""
    added = 0
    since_save = 0
    milestone = 0
    distinct_at_start = _recurring_label_count(cache)
    while added < target_new:
        data = _api_get(
            {
                "action": "query",
                "generator": "random",
                "grnnamespace": "0",
                "grnlimit": "50",
                "grnfilterredir": "nonredirects",
                "prop": "revisions",
                "rvprop": "content",
                "rvslots": "main",
                "format": "json",
                "formatversion": "2",
                "maxlag": "5",
            },
            sleep_seconds=sleep_seconds,
        )
        pages = data.get("query", {}).get("pages", [])
        for pg in pages:
            title = str(pg.get("title", "")).strip()
            if not title or title in cache:
                continue
            revs = pg.get("revisions") or [{}]
            content = revs[0].get("slots", {}).get("main", {}).get("content", "") or ""
            cache[title] = [[lvl, slug, par] for lvl, slug, par in _headings_from_wikitext(content)]
            added += 1
            since_save += 1
        if since_save >= 500:
            _save_cache(cache, cache_path)
            since_save = 0
        if added // 1000 > milestone:
            milestone = added // 1000
            rec = _recurring_label_count(cache)
            print(f"  ...{len(cache):6d} pages cached | recurring labels (>=3pg): {rec}")
        time.sleep(sleep_seconds)
    _save_cache(cache, cache_path)
    print(
        f"  recurring labels (>=3pg): {distinct_at_start} -> {_recurring_label_count(cache)} "
        f"after +{added} pages"
    )
    return added


def _recurring_label_count(cache: dict[str, list[list[Any]]], *, min_pages: int = 3) -> int:
    pages_per: Counter[str] = Counter()
    for headings in cache.values():
        for _lvl, slug, _par in {(0, h[1], "") for h in headings}:  # unique slugs per page
            pages_per[slug] += 1
    return sum(1 for n in pages_per.values() if n >= min_pages)


def _build_stats(cache: dict[str, list[list[Any]]]) -> dict[str, Any]:
    all_freq: Counter[str] = Counter()
    pages_per: dict[str, set[str]] = defaultdict(set)
    top_freq: Counter[str] = Counter()
    parent_counts: dict[str, Counter[str]] = defaultdict(Counter)
    pages_with_headings = 0
    for title, headings in cache.items():
        if headings:
            pages_with_headings += 1
        for lvl, slug, parent in headings:
            all_freq[slug] += 1
            pages_per[slug].add(title)
            if int(lvl) <= 2:
                top_freq[slug] += 1
            if parent and parent != slug:
                parent_counts[slug][parent] += 1
    labels = [
        {
            "slug": slug,
            "blocks": all_freq[slug],
            "pages": len(pages_per[slug]),
            "top_level_occurrences": top_freq.get(slug, 0),
            "top_parents": [p for p, _ in parent_counts[slug].most_common(3)],
        }
        for slug in sorted(all_freq, key=lambda s: (-len(pages_per[s]), -all_freq[s], s))
    ]
    return {
        "version": 1,
        "_doc": (
            "Whole-game harvest of Warcraft Wiki section-heading labels (random ns-0 sample, "
            "wikitext headings) to seed a curated section_label_registry. slug = slugify(heading,"
            "'_'); the pipeline's raw_section_role appends '_edit'. Unknown labels are not "
            "enumerated: they inherit their parent section's class (see top_parents), falling back "
            "to a conservative default only when the parent is also unknown."
        ),
        "pages_sampled": len(cache),
        "pages_with_headings": pages_with_headings,
        "distinct_labels": len(all_freq),
        "labels": labels,
    }


def _print_report(result: dict[str, Any], *, head: int) -> None:
    labels = result["labels"]
    total_blocks = sum(r["blocks"] for r in labels)
    print(f"pages sampled   : {result['pages_sampled']} ({result['pages_with_headings']} w/ headings)")
    print(f"distinct labels : {result['distinct_labels']}  (heading occurrences: {total_blocks})")
    for thr in (3, 5, 10):
        n = sum(1 for r in labels if r["pages"] >= thr)
        print(f"  labels on >= {thr:2d} pages: {n}")
    print(f"\n=== top {head} labels by page-universality (blocks | pages | topLvl | parents) ===")
    for r in labels[:head]:
        parents = ",".join(r["top_parents"]) or "-"
        print(
            f"  {r['blocks']:6d} {r['pages']:5d}pg {r['top_level_occurrences']:5d}TL  "
            f"{parents:34s}  {r['slug']}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Harvest wiki section labels game-wide.")
    parser.add_argument("--output", type=Path, default=_DEFAULT_OUTPUT)
    parser.add_argument("--cache", type=Path, default=_DEFAULT_CACHE)
    parser.add_argument(
        "--max-pages", type=int, default=6000, help="Target new pages to sample this run"
    )
    parser.add_argument("--sleep", type=float, default=0.25, help="Seconds between API calls")
    parser.add_argument("--summary-only", action="store_true", help="Recompute report from cache")
    parser.add_argument("--head", type=int, default=70)
    args = parser.parse_args()

    cache = _load_cache(args.cache)
    if not args.summary_only:
        print(f"sampling up to {args.max_pages} new random pages (cache has {len(cache)})...")
        _sample_random_pages(
            target_new=args.max_pages,
            cache=cache,
            cache_path=args.cache,
            sleep_seconds=args.sleep,
        )
    result = _build_stats(cache)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    _print_report(result, head=args.head)
    print(f"\nWrote {args.output} ({result['distinct_labels']} labels)")


if __name__ == "__main__":
    main()
