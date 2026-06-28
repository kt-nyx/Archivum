"""Claim-level drafting views for section evidence pools.

Slice 6 keeps paragraph evidence as the compatibility fallback, but when claim temporal sidecars
exist each routed field consumes the safe claim text instead of the whole source paragraph.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable
from typing import Any

from pipeline.common.text_normalize import clean_wiki_snippet
from pipeline.generate.draft.temporal import (
    ACTIVE_STORYLINE,
    ACTIVE_STORYLINE_OUTCOME,
    ENTRY_STATE,
    EXCLUDED_NONCANON,
    HISTORY_BACKGROUND,
    HISTORY_SETUP_BRIDGE,
    POST_ACTIVE_LORE,
    PRE_ENTRY_HISTORY,
)

CLAIM_VIEW_KEY = "_claim_views"

SAFE_BACKGROUND = "safe_background"
SAFE_ENTRY_CONTEXT = "safe_entry_context"
SAFE_SETUP_HOOK = "safe_setup_hook"
ENCOUNTER_SETUP = "encounter_setup"
ACTIVE_MECHANICS_STATE = "active_mechanics_state"
ACTIVE_OUTCOME = "active_outcome"
POST_ACTIVE_REFERENCE = "post_active_reference"
UNSAFE_COMPLETION_DETAIL = "unsafe_completion_detail"
UNKNOWN_SPOILER_SAFETY = "unknown_spoiler_safety"

HISTORY_ROUTE = "history"
CURRENTLY_ROUTE = "currently"
AT_A_GLANCE_ROUTE = "at_a_glance"
FACTION_CONTEXT_ROUTE = "faction_context"
LOCATION_CONTEXT_ROUTE = "location_context"
INSTANCE_OVERVIEW_ROUTE = "instance_overview"
KEY_CHARACTER_ROUTE = "key_character"

CLAIM_ROUTES = frozenset(
    {
        HISTORY_ROUTE,
        CURRENTLY_ROUTE,
        AT_A_GLANCE_ROUTE,
        FACTION_CONTEXT_ROUTE,
        LOCATION_CONTEXT_ROUTE,
        INSTANCE_OVERVIEW_ROUTE,
        KEY_CHARACTER_ROUTE,
    }
)

_KEY_CHARACTER_UNSAFE_SPOILER = frozenset(
    {ACTIVE_MECHANICS_STATE, ACTIVE_OUTCOME, UNSAFE_COMPLETION_DETAIL}
)

_HISTORY_ELIGIBLE = frozenset({HISTORY_BACKGROUND, HISTORY_SETUP_BRIDGE})
_SAFE_CONTEXT = frozenset({SAFE_BACKGROUND, SAFE_ENTRY_CONTEXT, SAFE_SETUP_HOOK, ENCOUNTER_SETUP})
_UNSAFE_CONTEXT = frozenset(
    {
        ACTIVE_MECHANICS_STATE,
        ACTIVE_OUTCOME,
        POST_ACTIVE_REFERENCE,
        UNSAFE_COMPLETION_DETAIL,
        UNKNOWN_SPOILER_SAFETY,
    }
)


def apply_claim_views_to_evidence_rows(
    evidence_rows: list[dict[str, Any]],
    claim_temporal_decisions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach routeable claim views to matching evidence items.

    The returned rows are deep-copied so callers do not mutate the temporal decision artifacts.
    Public draft JSON never serializes these internal ``_claim_views``.
    """
    claims_by_canonical = _claims_by_canonical_id(claim_temporal_decisions)
    if not claims_by_canonical:
        return evidence_rows
    rows = copy.deepcopy(evidence_rows)
    for row in rows:
        if not isinstance(row, dict):
            continue
        build_meta = row.get("build_meta") or {}
        if not isinstance(build_meta, dict):
            build_meta = {}
        items = row.get("evidence_items")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            canonical_id = str(item.get("canonical_evidence_id", "")).strip()
            if not canonical_id:
                continue
            claims = claims_by_canonical.get(canonical_id, [])
            if not claims:
                continue
            item[CLAIM_VIEW_KEY] = [
                _claim_view_for_item(
                    claim,
                    row=row,
                    item=item,
                    build_meta=build_meta,
                )
                for claim in claims
            ]
    return rows


def route_claim_views_for_pool(
    items: list[dict[str, Any]],
    route: str,
) -> list[dict[str, Any]]:
    """Return route-safe claim views for a flattened evidence pool.

    If no item in the pool has claim views, paragraph items are returned unchanged for rollout
    compatibility. If claim views exist but none are safe for this route, the result is empty.
    """
    routed: list[dict[str, Any]] = []
    saw_claim_views = False
    for item in items:
        views = item.get(CLAIM_VIEW_KEY)
        if not isinstance(views, list) or not views:
            continue
        saw_claim_views = True
        routed.extend(view for view in views if _claim_allowed_for_route(view, route))
    if saw_claim_views:
        return _dedupe_claim_views(routed)
    return items


def build_claim_view_routing_decisions(
    evidence_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Non-public sidecar rows showing which claim views are routeable by field."""
    rows: list[dict[str, Any]] = []
    for row in evidence_rows:
        if not isinstance(row, dict):
            continue
        field_name = str(row.get("field_name", "")).strip()
        items = row.get("evidence_items")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            views = item.get(CLAIM_VIEW_KEY)
            if not isinstance(views, list):
                continue
            route_counts = {
                route: sum(1 for view in views if _claim_allowed_for_route(view, route))
                for route in sorted(CLAIM_ROUTES)
            }
            rows.append(
                {
                    "field_name": field_name,
                    "canonical_evidence_id": str(item.get("canonical_evidence_id", "")).strip(),
                    "source_id": str(
                        item.get("source_id") or (row.get("build_meta") or {}).get("source_id", "")
                    ).strip(),
                    "claim_count": len(views),
                    "route_counts": route_counts,
                    "routeable_claim_ids": {
                        route: [
                            str(view.get("claim_id", "")).strip()
                            for view in views
                            if _claim_allowed_for_route(view, route)
                        ]
                        for route in sorted(CLAIM_ROUTES)
                    },
                }
            )
    return rows


def item_has_claim_views(item: dict[str, Any]) -> bool:
    views = item.get(CLAIM_VIEW_KEY)
    return isinstance(views, list) and bool(views)


# Current/at-a-glance prefer entry-state identity over older background within the safe pool
# (Slice 8 tasks 1-2). Lower rank sorts first.
_CURRENT_SCOPE_PREFERENCE = {
    ENTRY_STATE: 0,
    ACTIVE_STORYLINE: 1,
    PRE_ENTRY_HISTORY: 2,
}


def prefer_entry_state_first(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stable-sort a claim-routed pool so entry-state / active claims precede older background.

    Returns the input unchanged (same object) when the pool contains no claim views, so offline
    paragraph-fallback pools stay byte-identical and their gold output is unchanged. The sort is
    stable: items of equal preference keep their incoming order, and ``safe_entry_context`` is
    preferred over other safe labels at the same scope (Slice 8 task 1).

    A live routed pool is a *mix* of claim views (paragraphs that produced claims) and paragraph
    items (those that did not). Only claim views are ranked by their temporal scope; paragraph items
    get a neutral mid rank and are deliberately **not** ordered by their coarse paragraph-level
    ``temporal_scope``. The refactor's premise is that the claim label is the trustworthy fine
    signal and the paragraph label is compatibility-grade, so this promotes the high-confidence
    entry-state claims without re-litigating order from the weaker paragraph labels. (The early
    return already guarantees the offline no-op regardless, since offline pools carry no claim
    views.)
    """
    if not any(isinstance(item, dict) and item.get("is_claim_view") for item in items):
        return items

    def _rank(item: dict[str, Any]) -> tuple[int, int]:
        if not (isinstance(item, dict) and item.get("is_claim_view")):
            return (1, 1)
        scope = str(item.get("temporal_scope", "")).strip()
        scope_rank = _CURRENT_SCOPE_PREFERENCE.get(scope, 1)
        spoiler_rank = 0 if str(item.get("spoiler_safety", "")).strip() == SAFE_ENTRY_CONTEXT else 1
        return (scope_rank, spoiler_rank)

    return sorted(items, key=_rank)


def key_character_unsafe_claim_views(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Claim views barred from key-character prose by spoiler safety (clarification question 1).

    These are encounter-mechanics / outcome / completion claims (e.g. ``Lilian Voss defeated``,
    ``Course: Reeducation``). They are returned only so the synthesizer can be told what NOT to say;
    they are never usable summary content. A pool with no claim views yields an empty list, so the
    paragraph-fallback path is unaffected.
    """
    unsafe: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        views = item.get(CLAIM_VIEW_KEY)
        if not isinstance(views, list):
            continue
        for view in views:
            if not isinstance(view, dict):
                continue
            if str(view.get("spoiler_safety", "")).strip() in _KEY_CHARACTER_UNSAFE_SPOILER:
                key = (
                    str(view.get("claim_id", "")).strip(),
                    str(view.get("claim_text", "")).strip(),
                )
                if key in seen:
                    continue
                seen.add(key)
                unsafe.append(view)
    return unsafe


def route_claim_views_for_item(item: dict[str, Any], route: str) -> list[dict[str, Any]]:
    views = item.get(CLAIM_VIEW_KEY)
    if not isinstance(views, list):
        return []
    return [view for view in views if _claim_allowed_for_route(view, route)]


def _claims_by_canonical_id(
    claim_temporal_decisions: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for decision in claim_temporal_decisions:
        if not isinstance(decision, dict):
            continue
        canonical_id = str(decision.get("canonical_evidence_id", "")).strip()
        claims = decision.get("claims")
        if not canonical_id or not isinstance(claims, list):
            continue
        for claim in claims:
            if isinstance(claim, dict):
                grouped.setdefault(canonical_id, []).append(claim)
    return grouped


def _claim_view_for_item(
    claim: dict[str, Any],
    *,
    row: dict[str, Any],
    item: dict[str, Any],
    build_meta: dict[str, Any],
) -> dict[str, Any]:
    claim_text = clean_wiki_snippet(str(claim.get("claim_text", "")))
    source_excerpt = clean_wiki_snippet(
        str(claim.get("source_excerpt") or item.get("snippet", ""))
    )
    source_id = str(
        claim.get("source_id") or item.get("source_id") or build_meta.get("source_id", "")
    ).strip()
    source_url = str(item.get("source_url", "")).strip()
    source_title = str(
        claim.get("source_title") or item.get("source_title") or row.get("source_title", "")
    ).strip()
    return {
        "snippet": claim_text,
        "claim_text": claim_text,
        "source_excerpt": source_excerpt,
        "source_url": source_url,
        "source_title": source_title,
        "source_id": source_id,
        "field_name": str(row.get("field_name", "")).strip(),
        "section_role": str(item.get("section_role", build_meta.get("section_role", ""))).strip(),
        "raw_section_role": str(
            item.get("raw_section_role", build_meta.get("raw_section_role", ""))
        ).strip(),
        "content_role": str(item.get("content_role", build_meta.get("content_role", ""))).strip(),
        "block_index": item.get("block_index", build_meta.get("block_index", 0)),
        "cluster_id": str(build_meta.get("cluster_id", "")).strip(),
        "quest_node_id": str(build_meta.get("quest_node_id", "")).strip(),
        "faction_id": str(build_meta.get("faction_id", "")).strip(),
        "faction_name": str(build_meta.get("faction_name", "")).strip(),
        "location_id": str(build_meta.get("location_id", "")).strip(),
        "location_name": str(build_meta.get("location_name", "")).strip(),
        "lore_scope": str(build_meta.get("lore_scope", "")).strip(),
        "lore_source_title": str(build_meta.get("lore_source_title", "")).strip(),
        "canonical_evidence_id": str(claim.get("canonical_evidence_id", "")).strip(),
        "claim_id": str(claim.get("claim_id", "")).strip(),
        "claim_type": str(claim.get("claim_type", "")).strip(),
        "temporal_scope": str(claim.get("temporal_scope", "")).strip(),
        "history_eligibility": str(claim.get("history_eligibility", "")).strip(),
        "spoiler_safety": str(claim.get("spoiler_safety", "")).strip(),
        "temporal_confidence": claim.get("confidence"),
        "temporal_reason": str(claim.get("rationale", "")).strip(),
        "history_reason": str(claim.get("history_rationale", "")).strip(),
        "temporal_event_label": str(claim.get("event_label", "")).strip(),
        "source_sentence_indexes": claim.get("source_sentence_indexes", []),
        "entities": claim.get("entities", []),
        "source_refs": [
            {
                "source_id": source_id,
                "source_url": source_url,
                "source_title": source_title,
                "canonical_evidence_id": str(claim.get("canonical_evidence_id", "")).strip(),
                "claim_id": str(claim.get("claim_id", "")).strip(),
            }
        ],
        "is_claim_view": True,
    }


def _claim_allowed_for_route(claim: dict[str, Any], route: str) -> bool:
    scope = str(claim.get("temporal_scope", "")).strip()
    history_eligibility = str(claim.get("history_eligibility", "")).strip()
    spoiler_safety = str(claim.get("spoiler_safety", "")).strip()
    if scope in {ACTIVE_STORYLINE_OUTCOME, POST_ACTIVE_LORE, EXCLUDED_NONCANON}:
        return False
    if spoiler_safety in _UNSAFE_CONTEXT:
        return False
    if route == HISTORY_ROUTE:
        return history_eligibility in _HISTORY_ELIGIBLE
    if route == CURRENTLY_ROUTE:
        return scope in {PRE_ENTRY_HISTORY, ENTRY_STATE, ACTIVE_STORYLINE} and (
            not spoiler_safety or spoiler_safety in _SAFE_CONTEXT
        )
    if route == AT_A_GLANCE_ROUTE:
        return scope in {PRE_ENTRY_HISTORY, ENTRY_STATE} and spoiler_safety in {
            SAFE_BACKGROUND,
            SAFE_ENTRY_CONTEXT,
        }
    if route == FACTION_CONTEXT_ROUTE:
        return scope in {PRE_ENTRY_HISTORY, ENTRY_STATE} and (
            not spoiler_safety or spoiler_safety in _SAFE_CONTEXT
        )
    if route == LOCATION_CONTEXT_ROUTE:
        return scope in {PRE_ENTRY_HISTORY, ENTRY_STATE, ACTIVE_STORYLINE} and (
            not spoiler_safety or spoiler_safety in _SAFE_CONTEXT
        )
    if route == INSTANCE_OVERVIEW_ROUTE:
        return scope in {PRE_ENTRY_HISTORY, ENTRY_STATE} and (
            not spoiler_safety or spoiler_safety in _SAFE_CONTEXT
        )
    if route == KEY_CHARACTER_ROUTE:
        return scope in {PRE_ENTRY_HISTORY, ENTRY_STATE} and spoiler_safety in {
            SAFE_BACKGROUND,
            SAFE_ENTRY_CONTEXT,
            ENCOUNTER_SETUP,
        }
    return False


def _dedupe_claim_views(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in items:
        key = (
            str(item.get("claim_id", "")).strip(),
            str(item.get("canonical_evidence_id", "")).strip(),
            str(item.get("field_name", "")).strip(),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped
