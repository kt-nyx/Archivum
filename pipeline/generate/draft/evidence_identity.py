"""Paragraph-level evidence identity for prompts, coverage, and provenance (Slice 7).

Every paragraph of a crawled wiki page shares one ``source_id``, so source ids cannot tell
paragraphs apart — coverage collapsed to one unit per page and provenance pointers were
backfilled positionally. The working identity at draft time is the ``canonical_evidence_id``
minted per paragraph by the temporal enrichment pass; this module is the single home for
resolving an evidence item to that identity and for translating the ids a synthesis model
cites back to it.
"""

from __future__ import annotations

from typing import Any


def evidence_id_for_item(item: dict[str, Any]) -> str:
    """The paragraph-level identity of an evidence item.

    ``canonical_evidence_id`` when the item went through temporal enrichment (every real
    pipeline item does); the ``source_id`` otherwise (synthetic items such as quest-start
    descriptions, which are one-per-source by construction). Empty string when the item
    carries neither — such an item cannot be cited.
    """
    canonical = str(item.get("canonical_evidence_id", "")).strip()
    if canonical:
        return canonical
    return str(item.get("source_id", "")).strip()


def translate_used_evidence_ids(
    values: list[Any],
    alias_map: dict[str, str],
) -> list[str]:
    """Resolve model-cited evidence ids through an alias map to paragraph-level ids.

    ``alias_map`` comes from the evidence-block formatter (prompt alias ``p1..pN`` plus the
    items' own canonical/source ids mapped to their paragraph identity). Unknown tokens are
    dropped — a hallucinated citation must never become a provenance pointer. Order is
    preserved and duplicates removed.
    """
    translated: list[str] = []
    for value in values:
        token = str(value).strip()
        if not token:
            continue
        mapped = alias_map.get(token, "")
        if mapped and mapped not in translated:
            translated.append(mapped)
    return translated
