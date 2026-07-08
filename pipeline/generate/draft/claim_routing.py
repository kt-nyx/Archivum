"""Claim-level drafting views for section evidence pools.

Slice 6 keeps paragraph evidence as the compatibility fallback, but when claim temporal sidecars
exist each routed field consumes the safe claim text instead of the whole source paragraph.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable
from typing import Any

from pipeline.common.linguistics import clause_before_adversative
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


def key_character_setup_hook_claim_views(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Claim views labeled ``safe_setup_hook`` — the character's active-storyline motivation beats.

    These are barred from the key-character route (they share their labels with in-encounter
    mechanics), so they are surfaced here for the caller's grammar/cast-aware recovery of the
    spoiler-safe "why they're here" lead-in. A pool with no claim views yields an empty list.
    """
    hooks: list[dict[str, Any]] = []
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
            if str(view.get("spoiler_safety", "")).strip() != SAFE_SETUP_HOOK:
                continue
            key = (
                str(view.get("claim_id", "")).strip(),
                str(view.get("claim_text", "")).strip(),
            )
            if key in seen:
                continue
            seen.add(key)
            hooks.append(view)
    return hooks


def route_claim_views_for_item(item: dict[str, Any], route: str) -> list[dict[str, Any]]:
    views = item.get(CLAIM_VIEW_KEY)
    if not isinstance(views, list):
        return []
    return [view for view in views if _claim_allowed_for_route(view, route)]


def _char_spans(view: dict[str, Any]) -> list[tuple[int, int]]:
    """The view's sentence character spans (offsets into the cleaned paragraph text)."""
    raw = view.get("source_char_spans")
    if not isinstance(raw, list):
        return []
    out: list[tuple[int, int]] = []
    for value in raw:
        if (
            isinstance(value, (list, tuple))
            and len(value) == 2
            and all(isinstance(bound, int) and not isinstance(bound, bool) for bound in value)
        ):
            out.append((value[0], value[1]))
    return out


def safe_paragraph_excerpt(
    claim_views: list[dict[str, Any]], route: str, *, paragraph_text: str
) -> str:
    """Rebuild a source paragraph from only its route-safe sentences.

    Claims are atomized for fine-grained temporal/spoiler classification, but that shreds the
    synthesizer's input into fragments. This reconstructs contiguous prose by slicing
    ``clean_wiki_snippet(paragraph_text)`` at the claims' stored character offsets (Slice 8 —
    no re-splitting and substring re-finding), keeping a sentence only when it is covered by a
    route-safe claim AND by no filtered claim — so a sentence that produced any future/spoiler
    claim is dropped whole and no unsafe content leaks back in. Returns ``""`` when the
    paragraph text is unavailable or any view lacks in-bounds offsets (the contaminated set
    would be unknowable), so callers fall back to claim-text fragments.
    """
    cleaned = clean_wiki_snippet(paragraph_text)
    if not cleaned:
        return ""
    safe_spans: set[tuple[int, int]] = set()
    filtered_spans: set[tuple[int, int]] = set()
    for view in claim_views:
        spans = _char_spans(view)
        if not spans or any(
            not (0 <= start < end <= len(cleaned)) for start, end in spans
        ):
            return ""
        if _claim_allowed_for_route(view, route):
            safe_spans.update(spans)
        else:
            filtered_spans.update(spans)
    include = sorted(span for span in safe_spans if span not in filtered_spans)
    return " ".join(cleaned[start:end].strip() for start, end in include).strip()


def safe_intent_excerpt(view: dict[str, Any]) -> str:
    """The spoiler-safe *intent* clause of an otherwise-unsafe claim view (Cause 3).

    A character's connective 'why they're here' beat is often a single sentence that pairs the
    aim with its outcome ("intended to kill Gandling, though it failed"). The whole sentence is
    filtered by spoiler safety, discarding the intent with the outcome. This keeps the leading
    clause up to the first adversative connective — the aim/motivation — and drops the reversal
    tail. Returns ``""`` when no adversative connective marks an outcome tail (the sentence is a
    single realis assertion and stays filtered), so no outcome ever leaks back in.
    """
    text = clean_wiki_snippet(str(view.get("claim_text") or view.get("source_excerpt", "")))
    if not text:
        return ""
    trimmed = clause_before_adversative(text).strip()
    if trimmed and trimmed != text.strip():
        return trimmed
    return ""


def reconstruct_safe_paragraph_excerpts(
    source_pool: list[dict[str, Any]], route: str
) -> dict[str, str]:
    """Map each source paragraph (canonical_evidence_id) to its route-safe reconstructed excerpt.

    Operates on the full evidence items (which carry every claim view for the paragraph, safe and
    unsafe), so the safe/filtered sentence split is computed against the complete claim set. The
    item's ``snippet`` is the paragraph text the claim offsets index into.
    """
    views_by_paragraph: dict[str, list[dict[str, Any]]] = {}
    text_by_paragraph: dict[str, str] = {}
    for item in source_pool:
        views = item.get(CLAIM_VIEW_KEY)
        if not isinstance(views, list):
            continue
        for view in views:
            if not isinstance(view, dict):
                continue
            canonical_id = str(view.get("canonical_evidence_id", "")).strip()
            if not canonical_id:
                continue
            views_by_paragraph.setdefault(canonical_id, []).append(view)
            text_by_paragraph.setdefault(canonical_id, str(item.get("snippet", "")))
    excerpts: dict[str, str] = {}
    for canonical_id, claim_views in views_by_paragraph.items():
        excerpt = safe_paragraph_excerpt(
            claim_views, route, paragraph_text=text_by_paragraph.get(canonical_id, "")
        )
        if excerpt:
            excerpts[canonical_id] = excerpt
    return excerpts


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
    raw_links = item.get("links")
    return {
        "snippet": claim_text,
        # Slice 12/13: the source paragraph's inline article links ride onto each claim view so
        # link-based faction recognition sees them in routed pools.
        "links": [link for link in raw_links if isinstance(link, dict)]
        if isinstance(raw_links, list)
        else [],
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
        "character_id": str(build_meta.get("character_id", "")).strip(),
        "character_name": str(build_meta.get("character_name", "")).strip(),
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
        "source_char_spans": claim.get("source_char_spans", []),
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
        # safe_setup_hook is deliberately NOT admitted here: the classifier gives a genuine
        # motivation beat ("turned her wrath on the necromancers of this place") and an in-encounter
        # mechanic ("Gandling forced her to fight the adventurers") the same active_storyline /
        # safe_setup_hook labels, so a label-only rule cannot separate them — and this route also
        # feeds paragraph reconstruction. The motivation hook is recovered instead in
        # key_characters._recover_instance_setup_hooks, where the card's own cast identity and beat
        # grammar (the character must be the agent, no other cast member present) tell them apart.
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
