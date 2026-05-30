"""Zone-agnostic geography helpers for draft metadata."""

from __future__ import annotations

import re
from typing import Any

# Continent article titles aligned with world_registry seed list.
CONTINENT_TITLES: tuple[str, ...] = (
    "Azeroth",
    "Eastern Kingdoms",
    "Kalimdor",
    "Northrend",
    "Pandaria",
    "Broken Isles",
    "Dragon Isles",
    "Khaz Modan",
    "Lordaeron",
    "Outland",
    "Draenor",
    "Zandalar",
    "Kul Tiras",
    "Shadowlands",
    "K'aresh",
)

_SEED_FIELD_NAMES = frozenset({"at_a_glance_input", "currently_input", "history_digest"})


def title_to_slug(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.strip().lower())
    return slug.strip("-")


def resolve_parent_continent(evidence_rows: list[dict[str, Any]]) -> str | None:
    """Infer parent continent slug from seed evidence snippets mentioning a continent title."""
    snippets: list[str] = []
    for row in evidence_rows:
        if str(row.get("field_name", "")) not in _SEED_FIELD_NAMES:
            continue
        build_meta = row.get("build_meta") or {}
        if str(build_meta.get("source_kind", "")).strip() and str(build_meta.get("source_kind", "")) != "seed":
            continue
        for item in row.get("evidence_items") or []:
            if not isinstance(item, dict):
                continue
            snippet = str(item.get("snippet", "")).strip()
            if snippet:
                snippets.append(snippet)
    if not snippets:
        return None
    for title in sorted(CONTINENT_TITLES, key=len, reverse=True):
        pattern = rf"\b{re.escape(title)}\b"
        for snippet in snippets:
            if re.search(pattern, snippet, re.IGNORECASE):
                return title_to_slug(title)
    return None
