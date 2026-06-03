"""Signal-based lore source selection + attribution-disciplined fusion (Slice I4).

The draft stage is offline but has every fetched snapshot, so it scores the
instance's own lore against the cross-page (parent-complex / related) lore pulled
during traverse and fuses only what is genuinely about this instance:

- Rich instance: its own history/lore is sufficient; cross-page lore is ignored so
  the existing output never regresses.
- Sparse instance: cross-page snippets that *name* this instance are fused into the
  overview (deterministic, attribution-safe). When even that is empty, an optional
  LLM relevance gate may rescue parent-complex context, with a conservative
  deterministic fallback when offline.

Every fused snippet keeps its originating ``source_id`` so provenance pointers stay
traceable to the source page + revision.
"""

from __future__ import annotations

import re
from typing import Any

from pipeline.generate.draft.wiki_first_workers import classify_lore_relevance_llm

# Below this many instance-owned narrative words, treat the instance page as sparse
# and allow cross-page lore to augment the overview.
LORE_SPARSE_WORD_THRESHOLD = 60


def _normalize_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def _instance_name_variants(instance_name: str) -> list[str]:
    base = _normalize_text(instance_name)
    variants = {base}
    # Drop a leading article so "The Deadmines" matches prose that says "Deadmines".
    if base.startswith("the "):
        variants.add(base[4:].strip())
    return [variant for variant in variants if variant]


def mentions_instance(snippet: str, instance_name: str) -> bool:
    """True when the snippet explicitly names the instance (word-boundary aware)."""
    padded = f" {_normalize_text(snippet)} "
    return any(f" {variant} " in padded for variant in _instance_name_variants(instance_name))


def instance_lore_word_count(items: list[dict[str, Any]]) -> int:
    return sum(len(str(item.get("snippet", "")).split()) for item in items or [])


def is_instance_lore_sparse(items: list[dict[str, Any]]) -> bool:
    return instance_lore_word_count(items) < LORE_SPARSE_WORD_THRESHOLD


def filter_relevant_lore_items(
    items: list[dict[str, Any]],
    *,
    instance_name: str,
    extra_terms: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """Keep only cross-page snippets that name the instance (or an extra term).

    This is the attribution guard: lore about the parent complex or a related page
    is never fused unless it explicitly refers to this instance, so tangential lore
    cannot leak into the instance's narrative.
    """
    extra_norm = [term for term in (_normalize_text(t) for t in extra_terms) if len(term) >= 4]
    relevant: list[dict[str, Any]] = []
    for item in items or []:
        snippet = str(item.get("snippet", ""))
        if mentions_instance(snippet, instance_name):
            relevant.append(item)
            continue
        padded = f" {_normalize_text(snippet)} "
        if any(f" {term} " in padded for term in extra_norm):
            relevant.append(item)
    return relevant


def dedupe_lore_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop near-duplicate snippets (same normalized text) across fused pools."""
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in items or []:
        key = _normalize_text(item.get("snippet", ""))
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _group_by_source(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items or []:
        grouped.setdefault(str(item.get("source_id", "")), []).append(item)
    return grouped


def build_sparse_lore_rescue_pool(
    *,
    parent_lore_pool: list[dict[str, Any]],
    related_lore_pool: list[dict[str, Any]],
    instance_name: str,
) -> list[dict[str, Any]]:
    """Last-resort lore for a sparse instance whose own page (and mention-gated
    cross-page lore) yielded nothing.

    Deterministic and safe: the parent-complex page is the canonical lore home for a
    wing/sub-instance and was enumerated from this instance's own infobox-corroborated
    lead link, so its prose is admitted directly. Related pages are admitted only when
    the LLM relevance gate affirms they are about this instance; offline that gate
    returns ``"unrelated"`` so related pages are not pulled in (overreach control).
    """
    rescue: list[dict[str, Any]] = list(parent_lore_pool or [])
    for _source_id, items in _group_by_source(related_lore_pool).items():
        if not items:
            continue
        page_title = str(items[0].get("source_title", "")).strip()
        verdict = classify_lore_relevance_llm(
            items,
            page_title=page_title,
            instance_name=instance_name,
            fallback="unrelated",
        )
        if verdict == "relevant":
            rescue.extend(items)
    return dedupe_lore_items(rescue)
