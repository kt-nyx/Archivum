"""Shared retail-vs-Classic/legacy filtering (S3).

Single home for the "is this content retail?" signals so the crawl filter, the
discovery/draft roster paths, and the gold-fixture audit can never drift:

- ``is_classic_categorized`` — authoritative wiki-category signal (use the INGEST-CAT
  ``categories`` captured per page; the most reliable retail-eligibility check).
- ``is_non_retail_title`` — structural title parenthetical (``Foo (Classic)``, expansion
  variants); deterministic and offline.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from pipeline.common.section_registry import expansion_era_display_names

# Category-name substrings that mark a page as non-retail (case-insensitive substring).
CLASSIC_CATEGORY_MARKERS: tuple[str, ...] = ("classic", "removed", "legacy", "warcraft iii")


def _build_non_retail_parenthetical_re() -> re.Pattern[str]:
    """Parenthetical version suffixes that mark a non-retail page variant, anywhere in a title or
    href (e.g. "Scholomance (Classic)"). Expansion display names are single-homed on the section
    registry's ``expansion_era`` labels (Slice 14); a leading article is optional so "(Burning
    Crusade)" and "(The Burning Crusade)" both match. "World of Warcraft" is excluded — it names the
    game, not a legacy version variant.
    """
    names: set[str] = {"vanilla"}
    for display in expansion_era_display_names():
        if display == "world of warcraft":
            continue
        names.add(display[4:] if display.startswith("the ") else display)
    alternation = "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True))
    return re.compile(rf"\((?:the\s+)?(?:{alternation})\b[^)]*\)", re.IGNORECASE)


_NON_RETAIL_PARENTHETICAL_RE = _build_non_retail_parenthetical_re()


def is_classic_categorized(categories: Iterable[str] | None) -> bool:
    """True when any wiki category name matches a Classic/legacy/removed marker."""
    for category in categories or ():
        lowered = str(category).casefold()
        if any(marker in lowered for marker in CLASSIC_CATEGORY_MARKERS):
            return True
    return False


def is_non_retail_title(title: str) -> bool:
    """True for explicitly version-suffixed titles/hrefs (e.g. ``Foo (Classic)``)."""
    return bool(_NON_RETAIL_PARENTHETICAL_RE.search(str(title or "")))
