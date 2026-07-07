"""Deterministic enumeration of cross-page lore candidates for instances (Slice I4).

Instance pages frequently carry little or no narrative lore: the story lives on a
parent-complex page (e.g. Mana-Tombs -> Auchindoun) or on a related page named in
the instance's own lead/history prose. This module enumerates a small, filtered,
deterministic candidate set so the network-capable traverse stage can fetch those
pages and the offline draft stage can score + fuse them with strict attribution.

It is intentionally dependency-light (stdlib + the shared Classic-version regex) so
it can be imported by both discovery and ingest without creating import cycles.
"""

from __future__ import annotations

import re
from typing import Any

from pipeline.common.discovery_vocab import lore_character_role_hints
from pipeline.discovery.world_registry import _CLASSIC_SUFFIX_RE, entry_kinds

# Raw ingest section roles (not the discovery canonical buckets) that signal narrative
# prose. Parent complexes are named in the lead; related lore is named in history/lore.
_LEAD_ROLE_TOKENS = ("lead", "introduction")
_HISTORY_ROLE_TOKENS = ("history", "lore", "background", "story")

_NOISE_PREFIXES = (
    "file:",
    "template:",
    "category:",
    "help:",
    "special:",
    "module:",
    "talk:",
    "user:",
    "portal:",
    "media:",
)

# Conservative character markers: these belong to the I3 key_characters path, not the
# cross-page lore set. WS-C: externalized to
# pipeline/data/discovery_classification_vocab.v1.json (D-6) — judged on the link title
# pre-fetch, so no category/section signal exists at the decision point. Faction-ness is
# settled by the org registry (Slice 13), not a keyword list.
_CHARACTER_ROLE_HINTS = lore_character_role_hints()

# Body-text markers used to drop Classic-only / non-retail pages after they are fetched.
# Deliberately narrower than discovery's _classify_retail_eligibility (which treats a bare
# "classic"/"removed" substring as ineligible) so a parent-complex page that merely mentions
# Classic in passing is not wrongly dropped; explicit Classic-version pages are already
# filtered by title at enumeration.
_CLASSIC_ONLY_BODY_MARKERS = ("classic-only", "vanilla wow")
_NON_RETAIL_BODY_MARKERS = ("warcraft iii", "removed from the game", "lore location")

_MAX_RELATED_CANDIDATES = 3
_SPARSE_HISTORY_WORD_THRESHOLD = 60


def _title_from_href(href: str) -> str:
    value = str(href or "").strip()
    if not value:
        return ""
    path = value.split("/wiki/", 1)[-1] if "/wiki/" in value else value
    path = path.split("#", 1)[0].split("?", 1)[0]
    return path.replace("_", " ").strip()


def _slug(title: str) -> str:
    return re.sub(r"\s+", " ", str(title or "")).strip().lower()


def variant_cluster_key(title: str) -> str:
    """Collapse parenthetical version suffixes so retail/Classic variants share a key."""
    return re.sub(r"\s*\(.*?\)\s*", " ", str(title or "").lower()).strip()


def is_classic_variant_title(title: str) -> bool:
    """True for explicitly version-suffixed pages, e.g. ``Scholomance (Classic)``."""
    return bool(_CLASSIC_SUFFIX_RE.search(str(title or "")))


def classify_lore_retail_eligibility(text: str) -> str:
    """Coarse retail eligibility from page body text (best-effort, post-fetch guard)."""
    lowered = str(text or "").lower()
    if any(marker in lowered for marker in _CLASSIC_ONLY_BODY_MARKERS):
        return "ineligible_classic_only"
    if any(marker in lowered for marker in _NON_RETAIL_BODY_MARKERS):
        return "ineligible_other_game"
    return "eligible"


def _is_noise_href(href: str) -> bool:
    value = str(href or "").strip()
    if "/wiki/" not in value:
        return True
    title = _title_from_href(value)
    lowered = title.lower()
    if not lowered or lowered.startswith("#"):
        return True
    if "action=edit" in lowered or "redlink=1" in value.lower():
        return True
    return lowered.startswith(_NOISE_PREFIXES)


def _looks_like_character_or_faction(title: str) -> bool:
    # Slice 13: faction-ness comes from the wiki's own category taxonomy (org registry),
    # never a faction-word vocabulary.
    if "organization" in entry_kinds(title):
        return True
    parts = [part for part in re.split(r"\s+", title.strip()) if part]
    if any(part.lower() in _CHARACTER_ROLE_HINTS for part in parts):
        return True
    return False


def _role_kind(section_role: str, parent_section_role: str) -> str | None:
    """Map raw ingest roles to a narrative candidate kind, or None when non-narrative."""
    leaf = str(section_role or "").lower()
    parent = str(parent_section_role or "").lower()
    if any(token in leaf or token in parent for token in _HISTORY_ROLE_TOKENS):
        return "related"
    if leaf in _LEAD_ROLE_TOKENS or parent in _LEAD_ROLE_TOKENS:
        return "lead"
    return None


def compute_instance_lore_density(section_blocks: list[dict[str, Any]]) -> dict[str, Any]:
    """Measure the instance page's own narrative lore volume from its section blocks."""
    history_words = 0
    history_blocks = 0
    lead_words = 0
    for block in section_blocks or []:
        if not isinstance(block, dict):
            continue
        if str(block.get("block_type", "paragraph")) != "paragraph":
            continue
        role = str(block.get("section_role", "")).lower()
        text = str(block.get("text", ""))
        word_count = len(text.split())
        if any(token in role for token in _HISTORY_ROLE_TOKENS):
            history_blocks += 1
            history_words += word_count
        elif role in _LEAD_ROLE_TOKENS:
            lead_words += word_count
    return {
        "history_block_count": history_blocks,
        "history_word_count": history_words,
        "lead_word_count": lead_words,
        "lore_word_count": history_words + lead_words,
        "is_sparse": history_words < _SPARSE_HISTORY_WORD_THRESHOLD,
    }


def build_instance_lore_candidates(
    *,
    instance_id: str,
    instance_name: str,
    section_blocks: list[dict[str, Any]],
    wiki_links: list[str],
    structured_links: list[dict[str, Any]],
    max_related: int = _MAX_RELATED_CANDIDATES,
) -> list[dict[str, Any]]:
    """Return deterministic parent/related lore-candidate rows for one instance.

    Parent candidate: a lead-section link corroborated in ``wiki_links`` (the infobox
    "part of" link survives ingest there); capped to one. Related candidates: links
    named in the instance's history/lore prose; capped. Classic/version variants,
    self-references, noise, and obvious character/faction links are excluded.
    """
    instance_slug = _slug(instance_name)
    instance_variant = variant_cluster_key(instance_name)
    wiki_link_slugs = {
        _slug(_title_from_href(link)) for link in wiki_links or [] if not _is_noise_href(link)
    }

    # Collect every narrative occurrence per page slug. A link can appear in both the
    # lead and history; tracking both (rather than locking the kind to the first hit)
    # means an infobox-corroborated lead link is still recognized as the parent even if
    # a history mention happens to come first in document order.
    records: dict[str, dict[str, Any]] = {}
    for row in structured_links or []:
        if not isinstance(row, dict):
            continue
        href = str(row.get("href", "")).strip()
        if _is_noise_href(href):
            continue
        kind = _role_kind(str(row.get("section_role", "")), str(row.get("parent_section_role", "")))
        if kind is None:
            continue
        title = _title_from_href(href)
        slug = _slug(title)
        if not slug or slug == instance_slug:
            continue
        if variant_cluster_key(title) == instance_variant:
            continue
        if is_classic_variant_title(title):
            continue
        if _looks_like_character_or_faction(title):
            continue
        record = records.get(slug)
        if record is None:
            record = {
                "title": title,
                "source_link": href.split("#", 1)[0],
                "lead_role": "",
                "history_role": "",
                "in_wiki_links": slug in wiki_link_slugs,
            }
            records[slug] = record
        role = str(row.get("section_role", "other"))
        if kind == "lead" and not record["lead_role"]:
            record["lead_role"] = role
        elif kind == "related" and not record["history_role"]:
            record["history_role"] = role

    candidates: list[dict[str, Any]] = []
    # Parent: a lead link corroborated by the infobox; capped to one, deterministic by slug.
    parent_slug = ""
    corroborated = sorted(
        slug for slug, rec in records.items() if rec["lead_role"] and rec["in_wiki_links"]
    )
    if corroborated:
        parent_slug = corroborated[0]
        rec = records[parent_slug]
        candidates.append(
            {
                "instance_id": instance_id,
                "candidate_kind": "parent",
                "title": rec["title"],
                "source_link": rec["source_link"],
                "source_section_role": rec["lead_role"] or rec["history_role"] or "other",
            }
        )

    # Related: links named in history/lore prose (excluding the chosen parent), capped.
    related_slugs = sorted(
        slug for slug, rec in records.items() if rec["history_role"] and slug != parent_slug
    )
    for slug in related_slugs[:max_related]:
        rec = records[slug]
        candidates.append(
            {
                "instance_id": instance_id,
                "candidate_kind": "related",
                "title": rec["title"],
                "source_link": rec["source_link"],
                "source_section_role": rec["history_role"] or "other",
            }
        )

    return candidates
