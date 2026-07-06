"""Single home for the temporal exclusion policy on card synthesis pools (Slice 9, Cause C).

Every pool that feeds a *rendered* card's synthesis prompt (faction, location, and the shared
pool primitives) is filtered through this one policy, so "ambiguous means excluded, everywhere".
Discovery/scoring may keep looser admission; SYNTHESIS INPUT is uniformly filtered here.

The excluded set is the spoiler/temporal floor: post-active lore, this content's own active
storyline outcome (a spoiler resolution), non-canon material, and any paragraph the temporal
layer never resolved (``ambiguous_temporal``). ``active_storyline`` (the ongoing conflict a
belligerent is part of) is deliberately NOT excluded — an active combatant's current-conflict
evidence still justifies its card (Slice 6).
"""

from __future__ import annotations

from typing import Any

from pipeline.generate.draft.temporal import (
    ACTIVE_STORYLINE_OUTCOME,
    AMBIGUOUS_TEMPORAL,
    EXCLUDED_NONCANON,
    POST_ACTIVE_LORE,
)

# Temporal scopes never shown to a card synthesis prompt. One home; everything else imports this.
EXCLUDED_CARD_POOL_SCOPES = frozenset(
    {
        POST_ACTIVE_LORE,
        ACTIVE_STORYLINE_OUTCOME,
        EXCLUDED_NONCANON,
        AMBIGUOUS_TEMPORAL,
    }
)


def card_pool_scope(item: dict[str, Any], *, row: dict[str, Any] | None = None) -> str:
    """The item's temporal scope, falling back to the pack ``build_meta`` scope.

    Card-pool items (flattened by ``assembly._iter_evidence_items``) carry their own
    ``temporal_scope``; raw evidence items harvested straight off a row do not, so a ``row`` may
    be supplied to read the pack-level scope from its ``build_meta``.
    """
    build_meta = (row or {}).get("build_meta") if isinstance(row, dict) else {}
    if not isinstance(build_meta, dict):
        build_meta = {}
    return str(item.get("temporal_scope", build_meta.get("temporal_scope", ""))).strip()


def is_excluded_from_card_pool(item: dict[str, Any], *, row: dict[str, Any] | None = None) -> bool:
    """True when the item's temporal scope bars it from any card synthesis pool."""
    return card_pool_scope(item, row=row) in EXCLUDED_CARD_POOL_SCOPES


def filter_card_pool(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop temporally-excluded items from a card synthesis pool (unscoped items are kept)."""
    return [item for item in items if not is_excluded_from_card_pool(item)]


def row_has_admissible_item(row: dict[str, Any]) -> bool:
    """True when a row carries at least one item admissible to card synthesis (or no items)."""
    items = row.get("evidence_items")
    if not isinstance(items, list):
        return True
    saw_item = False
    for item in items:
        if not isinstance(item, dict):
            continue
        saw_item = True
        if not is_excluded_from_card_pool(item, row=row):
            return True
    return not saw_item
