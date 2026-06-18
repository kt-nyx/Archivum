"""Shared retail-vs-Classic/legacy filtering (S3).

Single home for the "is this content retail?" signals so the crawl filter, the
discovery/draft roster paths, and the gold-fixture audit can never drift:

- ``is_classic_categorized`` — authoritative wiki-category signal (use the INGEST-CAT
  ``categories`` captured per page; the most reliable retail-eligibility check).
- ``is_non_retail_title`` — structural title parenthetical (``Foo (Classic)``, expansion
  variants); deterministic and offline.
- ``KNOWN_CLASSIC_ENTITIES`` / ``is_known_classic_entity`` — a small, documented offline
  backstop for Classic-only entities whose clean wiki links carry no parenthetical
  (e.g. original-Scholomance bosses). Authoritative filtering is the category check; this
  list only guarantees deterministic offline exclusion of named, justified contaminants.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

# Category-name substrings that mark a page as non-retail (case-insensitive substring).
CLASSIC_CATEGORY_MARKERS: tuple[str, ...] = ("classic", "removed", "legacy", "warcraft iii")

# Parenthetical version suffixes that mark a non-retail page variant, anywhere in a title
# or href (e.g. "Scholomance (Classic)"). Mirrors world_registry's classic-suffix set but
# matches inline (not anchored to end) so it also catches hrefs and labels.
_NON_RETAIL_PARENTHETICAL_RE = re.compile(
    r"\((?:classic|vanilla|burning crusade|wrath of the lich king|"
    r"mists of pandaria|warlords of draenor|legion|battle for azeroth|"
    r"shadowlands|dragonflight|the war within)\b[^)]*\)",
    re.IGNORECASE,
)

# Classic-only entities that lack a "(Classic)" marker on their wiki link. Keep this small,
# justified, and retail-universal (no retail instance legitimately features these). The
# original-Scholomance roster + a couple of removed Scholomance NPCs.
KNOWN_CLASSIC_ENTITIES: frozenset[str] = frozenset(
    {
        "ravenian",
        "doctor theolen krastinov",
        "professor slate",
        "weldon barov",
        "lord alexei barov",
        "kirtonos the herald",
        "ras frostwhisper",
    }
)


def _norm(text: str) -> str:
    return " ".join(str(text or "").strip().casefold().split())


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


def is_known_classic_entity(name: str) -> bool:
    """True when ``name`` is on the documented Classic-only backstop denylist."""
    return _norm(name) in KNOWN_CLASSIC_ENTITIES
