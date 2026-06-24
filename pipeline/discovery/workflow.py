"""Deterministic wiki-first discovery workflow and artifact builders."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from pipeline.common.discovery_vocab import (
    character_role_hints,
    event_title_tokens,
    faction_title_tokens,
    location_type_title_rules,
    non_location_title_tokens,
)
from pipeline.common.draft_vocab import era_section_role_tokens
from pipeline.common.io import read_json, write_json
from pipeline.common.retail import is_classic_categorized
from pipeline.common.run_context import RunContext
from pipeline.common.text_ids import slugify
from pipeline.contracts.models import DecisionArtifact
from pipeline.discovery.entity_typing import normalize_title, should_reject_location_title
from pipeline.discovery.location_discovery import (
    HARD_REJECT_MARKERS,
    build_location_decision_row,
    build_zone_seed_text,
    classify_location_candidate,
    hard_reject_markers,
)
from pipeline.discovery.lore_sources import (
    build_instance_lore_candidates,
    compute_instance_lore_density,
)

_CLASSIC_ONLY_MARKERS = ("classic", "classic-only", "vanilla")
_NON_RETAIL_MARKERS = ("warcraft iii", "removed", "undisplayed", "lore location")
_HARD_REJECT_MARKERS = HARD_REJECT_MARKERS
_SECTION_ROLE_PATTERNS: dict[str, tuple[str, ...]] = {
    "maps_subregions": ("subregion", "sub-region", "maps", "geography"),
    "instances_or_dungeons": ("instance", "dungeon", "raid"),
    "quests_or_storyline": ("quest", "storyline"),
    "notable_characters": ("notable", "character", "npc"),
    "history": ("history", "lore"),
}
_NOISE_LINK_PREFIXES = (
    "file:",
    "template:",
    "category:",
    "help:",
    "special:",
    "module:",
    "talk:",
    "user:",
    "game guide/",
)
# WS-C: title-token classification vocab is externalized to
# pipeline/data/discovery_classification_vocab.v1.json (D-6). These are the
# pre-fetch fallback signals; the link's section role is the primary classifier
# (see _infer_entity_type_for_link).
_LOCATION_INCLUDE_SECTION_WEIGHTS = {
    "maps_subregions": 0.35,
    "instances_or_dungeons": 0.1,
    "quests_or_storyline": 0.1,
    "history": 0.05,
    "other": 0.0,
}


def _load_json(path: Path) -> Any:
    return read_json(path)


def _normalized_wiki_title(link: str) -> str:
    if "://" in link:
        parsed = urlparse(link)
        path = parsed.path
    else:
        path = link
    title = path.split("/wiki/", 1)[-1]
    return unquote(title).strip().replace("_", " ")


def _normalized_wiki_slug(link: str) -> str:
    title = _normalized_wiki_title(link)
    return re.sub(r"\s+", " ", title).strip().lower()


def _to_entity_id(prefix: str, title: str) -> str:
    slug = slugify(title)
    return f"{prefix}-{slug}" if slug else prefix


def _classify_retail_eligibility(text: str, categories: list[str] | None = None) -> str:
    # Wiki categories are the authoritative retail-eligibility signal (INGEST-CAT); the
    # body-text keyword markers remain as a fallback when categories are absent.
    if categories and is_classic_categorized(categories):
        return "ineligible_classic_only"
    lowered = text.lower()
    if any(marker in lowered for marker in _CLASSIC_ONLY_MARKERS):
        return "ineligible_classic_only"
    if any(marker in lowered for marker in _NON_RETAIL_MARKERS):
        return "ineligible_other_game"
    return "eligible"


def _is_storyline_traversal_url(link: str) -> bool:
    lowered = link.lower().split("#", 1)[0]
    return "_storyline" in lowered


def _section_role(raw_role: str) -> str:
    lowered = raw_role.lower()
    if lowered.startswith("in_the_rpg"):
        return "in_the_rpg"
    for role, patterns in _SECTION_ROLE_PATTERNS.items():
        if any(pattern in lowered for pattern in patterns):
            return role
    # Expansion-/era-named timeline sections ("Cataclysm", "Battle for Azeroth",
    # "Legion", "Mists of Pandaria") are in-universe history even though their
    # heading carries no "history"/"lore" token. Reuse the externalized era vocab
    # (WS-C D-6) rather than a new inline keyword list so the timeline prose keeps
    # its real history role instead of collapsing to "other".
    if any(token in lowered for token in era_section_role_tokens()):
        return "history"
    return "other"


def _effective_section_slug(raw_leaf: str, raw_parent: str = "") -> str:
    """Return the slug a block should be classified by, inheriting its parent section.

    Wiki storyline subsections ("The Scourging", "Cataclysm", "Creation") classify to
    ``"other"`` on their own, which strips their paragraphs of the enclosing
    History/Lore role and collapses them downstream (Fix B). The ingest section walk
    already records ``parent_section_role`` but consumers never fell back to it. When a
    leaf subsection is unrecognized but the enclosing top-level section is recognized,
    classify by the parent slug so the content keeps its real narrative role. RPG
    parents stay RPG (``_section_role`` returns ``"in_the_rpg"``), so canon history is
    never polluted with RPG content.
    """
    if _section_role(raw_leaf) != "other":
        return raw_leaf
    if raw_parent and _section_role(raw_parent) != "other":
        return raw_parent
    return raw_leaf


def _is_noise_wiki_link(link: str) -> bool:
    if not isinstance(link, str):
        return True
    if "/wiki/" not in link:
        return True
    title = _normalized_wiki_title(link)
    title_lower = title.lower()
    if not title or title.startswith("#"):
        return True
    if "action=edit" in title_lower or "&redlink=1" in title_lower:
        return True
    if "#" in title:
        return True
    return title_lower.startswith(_NOISE_LINK_PREFIXES)


def _infer_storyline_links(
    entity_name: str,
    section_blocks: list[dict[str, Any]],
    wiki_links: list[str],
) -> set[str]:
    inferred: set[str] = set()
    # First, trust explicit links when present and clean.
    for link in wiki_links:
        if _is_noise_wiki_link(link):
            continue
        title_lower = _normalized_wiki_title(link).lower()
        if "storyline" in title_lower or "questline" in title_lower:
            inferred.add(link)
    # If no explicit link exists, infer from quest/storyline section text.
    for block in section_blocks:
        if not isinstance(block, dict):
            continue
        role = _section_role(str(block.get("section_role", "")))
        if role != "quests_or_storyline":
            continue
        text = str(block.get("text", "")).strip()
        if not text:
            continue
        # Example: "See {Zone Name} storyline"
        see_match = re.search(
            r"(?i)see\s+([A-Za-z0-9'’\-\s]+?)\s+(?:storyline|questline)",
            text,
        )
        if see_match:
            title = re.sub(r"\s+", " ", see_match.group(1)).strip()
            if title:
                inferred.add(f"/wiki/{title.replace(' ', '_')}_storyline")
                continue
        for match in re.finditer(
            r"([A-Za-z0-9'’\-\s]+(?:storyline|questline))", text, re.IGNORECASE
        ):
            title = re.sub(r"\s+", " ", match.group(1)).strip()
            if title.lower().startswith("see "):
                continue
            if title:
                inferred.add(f"/wiki/{title.replace(' ', '_')}")
    # Zone fallback: "<Zone Name> storyline"
    if not inferred and entity_name:
        inferred.add(f"/wiki/{entity_name.replace(' ', '_')}_storyline")
    return inferred


# When a link appears under several sections, prefer the most authoritative role for typing:
# the cast roster settles characters; a maps/subregions entry settles a location. Generic chrome
# ("lead", "getting there", "patch changes") must not win over these.
_STRUCTURED_ROLE_PRECEDENCE = (
    "notable_characters",
    "maps_subregions",
    "instances_or_dungeons",
    "quests_or_storyline",
    "history",
)


def _best_section_role(roles: list[str]) -> str:
    ranked = sorted(
        roles,
        key=lambda role: _STRUCTURED_ROLE_PRECEDENCE.index(role)
        if role in _STRUCTURED_ROLE_PRECEDENCE
        else len(_STRUCTURED_ROLE_PRECEDENCE),
    )
    return ranked[0] if ranked else "other"


def _link_section_role_from_structured(
    link: str,
    structured_links: list[dict[str, Any]],
) -> str | None:
    normalized = link.split("#", 1)[0]
    matched_roles: list[str] = []
    for row in structured_links:
        if not isinstance(row, dict):
            continue
        href = str(row.get("href", "")).split("#", 1)[0]
        if href == normalized or href.endswith(normalized) or normalized.endswith(href):
            matched_roles.append(_section_role(str(row.get("section_role", "other"))))
    if not matched_roles:
        return None
    return _best_section_role(matched_roles)


def _infer_link_section_role(
    link: str,
    section_blocks: list[dict[str, Any]],
    structured_links: list[dict[str, Any]] | None = None,
) -> str:
    if structured_links:
        from_structured = _link_section_role_from_structured(link, structured_links)
        if from_structured and from_structured != "other":
            return from_structured
    title = _normalized_wiki_title(link)
    if not title:
        return "other"
    title_lower = title.lower()
    normalized_title = re.sub(r"[^a-z0-9]+", " ", title_lower).strip()
    if not normalized_title:
        return "other"
    for block in section_blocks:
        if not isinstance(block, dict):
            continue
        text = str(block.get("text", "")).lower()
        if not text:
            continue
        if title_lower in text or normalized_title in re.sub(r"[^a-z0-9]+", " ", text):
            return _section_role(str(block.get("section_role", "")))
    return "other"


def _is_likely_character_title(title: str) -> bool:
    parts = [part for part in re.split(r"\s+", title.strip()) if part]
    if len(parts) < 2:
        return False
    role_hints = character_role_hints()
    return any(
        part.lower() in role_hints or (part[:1].isupper() and part[1:].islower() and len(part) >= 3)
        for part in parts
    )


def _title_has_location_type_token(title: str) -> bool:
    tokens = set(re.findall(r"[a-z]+", title.lower()))
    if not tokens:
        return False
    return any(tokens & type_tokens for _type, type_tokens in location_type_title_rules())


def _infer_entity_type_for_link(title: str, inferred_section_role: str) -> str:
    # WS-C: the link's section role (WS-A structural signal) is the primary
    # classifier. The title-token fallbacks below only run when the section role
    # is uninformative ("other"/"history") — that is the only point at which no
    # category/section signal exists for the (not-yet-fetched) target page.
    lowered = title.lower()
    if (
        "storyline" in lowered
        or "questline" in lowered
        or inferred_section_role == "quests_or_storyline"
    ):
        return "quest"
    if inferred_section_role == "instances_or_dungeons":
        return "instance"
    if inferred_section_role == "notable_characters":
        return "character"
    if inferred_section_role == "maps_subregions":
        return "location"
    if "(instance)" in lowered or " dungeon" in lowered or " raid" in lowered:
        return "instance"
    if any(keyword in lowered for keyword in faction_title_tokens()):
        return "faction"
    if any(keyword in lowered for keyword in event_title_tokens()):
        return "event"
    # A descriptive place token (tomb, crypt, keep, mill, ...) marks a landmark/structure even in an
    # ambiguous section, so a possessive name like "Uther's Tomb" is not mistaken for a character.
    if _title_has_location_type_token(title):
        return "location"
    if _is_likely_character_title(title):
        return "character"
    return "location"


def _should_reject_location_candidate(title: str, entity_type: str) -> bool:
    lowered = title.lower()
    if entity_type != "location":
        return True
    if any(keyword in lowered for keyword in non_location_title_tokens()):
        return True
    return False


# Section-role precedence used when collapsing location variants: a place's strongest role
# (a maps/subregions or history mention) survives over a bare "other".
_LOCATION_ROLE_PRECEDENCE = (
    "maps_subregions",
    "history",
    "quests_or_storyline",
    "instances_or_dungeons",
    "other",
)


def _location_role_rank(role: str) -> int:
    normalized = re.sub(r"\s+", " ", role.strip()).lower().replace(" ", "_")
    try:
        return _LOCATION_ROLE_PRECEDENCE.index(normalized)
    except ValueError:
        return len(_LOCATION_ROLE_PRECEDENCE)


def _location_name_tokens(name: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", name.lower())


def _is_contiguous_sublist(needle: list[str], haystack: list[str]) -> bool:
    if not needle or len(needle) >= len(haystack):
        return False
    for start in range(len(haystack) - len(needle) + 1):
        if haystack[start : start + len(needle)] == needle:
            return True
    return False


def _collapse_location_variants(
    candidates: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Collapse same-place variants into their canonical base candidate.

    A candidate whose name is another candidate's name plus a descriptor — "Ruins of Andorhal"
    over "Andorhal", "Hearthglen Hills/Pass/Woods" over "Hearthglen", "Sorrow Hill Crypt" over
    "Sorrow Hill" — is a sub-feature/state of the base, not a distinct location. The base survives
    and inherits the strongest section role across the group (so the marquee place isn't stranded
    at ``other`` while its map-listed sub-features carried ``maps_subregions``). Returns the kept
    candidates and a ``location_id -> best_role`` map for parallel target lists.

    The base must be a *shorter* contiguous token-subsequence of the variant, so distinct
    same-owner places ("Dalson's Tears" vs "Dalson's Farm", neither a subsequence of the other)
    are left untouched.
    """
    by_zone: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        by_zone.setdefault(str(candidate.get("zone_id", "")), []).append(candidate)

    kept: list[dict[str, Any]] = []
    best_role: dict[str, str] = {}
    for _zone_id, group in by_zone.items():
        # Bases first (fewest tokens) so a variant always meets its base already kept.
        ordered = sorted(group, key=lambda row: len(_location_name_tokens(str(row.get("name", "")))))
        kept_in_zone: list[dict[str, Any]] = []
        for candidate in ordered:
            tokens = _location_name_tokens(str(candidate.get("name", "")))
            role = str(candidate.get("source_section_role", "other"))
            base = next(
                (
                    existing
                    for existing in kept_in_zone
                    if _is_contiguous_sublist(
                        _location_name_tokens(str(existing.get("name", ""))), tokens
                    )
                ),
                None,
            )
            if base is not None:
                base_id = str(base.get("location_id", ""))
                if _location_role_rank(role) < _location_role_rank(
                    str(base.get("source_section_role", "other"))
                ):
                    base["source_section_role"] = role
                best_role[base_id] = str(base.get("source_section_role", "other"))
                continue
            kept_in_zone.append(candidate)
            best_role[str(candidate.get("location_id", ""))] = role
        kept.extend(kept_in_zone)
    return kept, best_role


def run_discovery_workflow(context: RunContext, source_manifest_path: Path) -> dict[str, Path]:
    """Build deterministic discovery artifacts from ingest snapshots."""
    snapshots = _load_json(context.stage_dir("ingest") / "source_snapshots.json")
    manifest_rows = _load_json(source_manifest_path)
    if not isinstance(snapshots, list):
        raise RuntimeError("source_snapshots.json must be a JSON array")
    if not isinstance(manifest_rows, list):
        raise RuntimeError("source_manifest.json must be a JSON array")

    discovery_dir = context.data_dir / "discovery"
    discovery_dir.mkdir(parents=True, exist_ok=True)
    decisions_dir = context.data_dir / "decisions"
    decisions_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir = context.data_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    zone_registry: list[dict[str, Any]] = []
    canonical_entities: list[dict[str, Any]] = []
    location_candidates: list[dict[str, Any]] = []
    location_classification: list[dict[str, Any]] = []
    instance_registry: list[dict[str, Any]] = []
    instance_lore_source_map: list[dict[str, Any]] = []
    quest_graph: list[dict[str, Any]] = []
    location_decisions: list[dict[str, Any]] = []
    questline_decisions: list[dict[str, Any]] = []
    faction_profile_targets: list[dict[str, Any]] = []
    location_profile_targets: list[dict[str, Any]] = []
    storyline_traversal_targets: list[dict[str, Any]] = []
    instance_zone_profiles: list[dict[str, Any]] = []

    manifest_by_source = {
        str(row.get("source_id", "")).strip(): row for row in manifest_rows if isinstance(row, dict)
    }
    known_instance_by_title: dict[str, dict[str, str]] = {}
    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            continue
        if str(snapshot.get("entity_type", "")).strip() != "instance":
            continue
        instance_name = str(snapshot.get("name", "")).strip()
        instance_id = str(snapshot.get("entity_id", "")).strip()
        if not instance_name or not instance_id:
            continue
        known_instance_by_title[_normalized_wiki_slug(instance_name)] = {
            "instance_id": instance_id,
            "name": instance_name,
        }

    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            continue
        source_id = str(snapshot.get("source_id", "")).strip()
        entity_type = str(snapshot.get("entity_type", "")).strip()
        entity_name = str(snapshot.get("name", "")).strip()
        source_row = manifest_by_source.get(source_id, {})
        body_text = str(snapshot.get("body", ""))
        snapshot_categories = snapshot.get("categories", [])
        if not isinstance(snapshot_categories, list):
            snapshot_categories = []
        wiki_url = str(snapshot.get("url", ""))
        section_blocks = snapshot.get("section_blocks", [])
        if not isinstance(section_blocks, list):
            section_blocks = []
        wiki_links = snapshot.get("wiki_links", [])
        if not isinstance(wiki_links, list):
            wiki_links = []
        structured_links = snapshot.get("structured_links", [])
        if not isinstance(structured_links, list):
            structured_links = []

        is_seed_snapshot = not str(snapshot.get("auxiliary_role", "")).strip()

        if entity_type == "zone":
            zone_registry.append(
                {
                    "zone_id": str(snapshot.get("entity_id", "")),
                    "name": entity_name,
                    "wiki_url": wiki_url,
                    "source_id": source_id,
                    "page_id": None,
                }
            )

        canonical_entities.append(
            {
                "entity_id": str(snapshot.get("entity_id", "")),
                "entity_type": entity_type,
                "wiki_title": entity_name,
                "wiki_url": wiki_url,
                "page_id": None,
                "redirect_chain": [],
                "disambiguation_state": "none",
                "retail_eligibility": _classify_retail_eligibility(body_text, snapshot_categories),
            }
        )

        role_counts: dict[str, int] = {}
        for block in section_blocks:
            if not isinstance(block, dict):
                continue
            role = _section_role(str(block.get("section_role", "")))
            role_counts[role] = role_counts.get(role, 0) + 1

        if entity_type != "zone" or not is_seed_snapshot:
            _ = source_row
            continue

        clean_links: list[str] = [link for link in wiki_links if not _is_noise_wiki_link(link)]
        storyline_links = _infer_storyline_links(entity_name, section_blocks, clean_links)

        seen_storyline_target_urls: set[str] = set()
        for link in sorted(storyline_links):
            if not _is_storyline_traversal_url(link):
                continue
            normalized = link.lower().split("#", 1)[0]
            if normalized in seen_storyline_target_urls:
                continue
            seen_storyline_target_urls.add(normalized)
            title = _normalized_wiki_title(link)
            storyline_traversal_targets.append(
                {
                    "zone_id": str(snapshot.get("entity_id", "")),
                    "storyline_id": _to_entity_id("storyline", title),
                    "title": title,
                    "source_link": link,
                    "source_section_role": "quests_or_storyline",
                }
            )

        processing_links = sorted(set(clean_links))

        # The zone page's "notable characters" links are the cast roster; a sub-location candidate
        # whose title matches one is a misfiled NPC (e.g. Thassarian), not a place. Reject those.
        notable_character_titles = {
            normalize_title(str(link_row.get("label", "")))
            for link_row in structured_links
            if isinstance(link_row, dict)
            and "character" in str(link_row.get("section_role", "")).lower()
            and str(link_row.get("label", "")).strip()
        }

        for link in processing_links:
            title = _normalized_wiki_title(link)
            lowered = title.lower()
            candidate_id = _to_entity_id("location", title)
            inferred_role = _infer_link_section_role(link, section_blocks, structured_links)
            inferred_entity_type = _infer_entity_type_for_link(title, inferred_role)
            reject_location, reject_reasons = should_reject_location_title(
                title,
                zone_name=entity_name,
                source_section_role=inferred_role,
                entity_type=inferred_entity_type,
            )
            known_instance = known_instance_by_title.get(_normalized_wiki_slug(title))
            if known_instance is not None or inferred_entity_type == "instance":
                instance_id = (
                    known_instance["instance_id"]
                    if known_instance is not None
                    else _to_entity_id("instance", title)
                )
                instance_registry.append(
                    {
                        "instance_id": instance_id,
                        "name": known_instance["name"] if known_instance is not None else title,
                        "source_zone_id": str(snapshot.get("entity_id", "")),
                        "source_link": link,
                        "instance_type": "raid" if "raid" in lowered else "dungeon",
                        "variant_cluster_key": re.sub(r"\s*\(.*?\)\s*", " ", lowered).strip(),
                        "source_section_role": inferred_role,
                    }
                )
                has_history = role_counts.get("history", 0) > 0
                instance_lore_source_map.append(
                    {
                        "instance_id": instance_id,
                        "lore_source": "instance_page" if has_history else "linked_lore_page",
                        "fallback_reason": None
                        if has_history
                        else "history_missing_on_instance_page",
                        "source_link": link,
                    }
                )
                instance_zone_profiles.append(
                    {
                        "zone_id": str(snapshot.get("entity_id", "")),
                        "instance_id": instance_id,
                        "instance_name": known_instance["name"]
                        if known_instance is not None
                        else title,
                        "source_link": link,
                        "source_section_role": inferred_role,
                    }
                )
            elif inferred_entity_type == "faction":
                faction_profile_targets.append(
                    {
                        "zone_id": str(snapshot.get("entity_id", "")),
                        "faction_id": _to_entity_id("faction", title),
                        "name": title,
                        "source_link": link,
                        "source_section_role": inferred_role,
                    }
                )
            else:
                if reject_location or _should_reject_location_candidate(
                    title, inferred_entity_type
                ):
                    continue
                if normalize_title(title) in notable_character_titles:
                    continue
                # WS-C: section-role-first typing now admits whole maps/subregions sections,
                # which can include meta-placeholder pages ("Lore location", "Undisplayed
                # location"). The downstream classification already hard-rejects these by name;
                # apply the same gate here so they never become traversal targets/candidates.
                if hard_reject_markers(title):
                    continue
                location_candidates.append(
                    {
                        "zone_id": str(snapshot.get("entity_id", "")),
                        "location_id": candidate_id,
                        "name": title,
                        "source_link": link,
                        "source_section_role": inferred_role,
                        "entity_type": inferred_entity_type,
                        "reject_reasons": reject_reasons,
                    }
                )
                location_profile_targets.append(
                    {
                        "zone_id": str(snapshot.get("entity_id", "")),
                        "location_id": candidate_id,
                        "name": title,
                        "source_link": link,
                        "source_section_role": inferred_role,
                    }
                )

        _ = source_row

    deduped_candidates: list[dict[str, Any]] = []
    seen_candidates: set[tuple[str, str]] = set()
    for candidate in location_candidates:
        key = (str(candidate.get("zone_id", "")), str(candidate.get("location_id", "")))
        if key in seen_candidates:
            continue
        seen_candidates.add(key)
        deduped_candidates.append(candidate)
    location_candidates = deduped_candidates

    # Collapse same-place variants (Ruins of Andorhal -> Andorhal; Hearthglen Hills -> Hearthglen)
    # and drop the matching profile targets so traversal/enrich don't re-introduce them.
    location_candidates, _variant_best_role = _collapse_location_variants(location_candidates)
    kept_location_ids = {str(row.get("location_id", "")) for row in location_candidates}
    collapsed_profile_targets: list[dict[str, Any]] = []
    for target in location_profile_targets:
        target_id = str(target.get("location_id", ""))
        if target_id not in kept_location_ids:
            continue
        upgraded_role = _variant_best_role.get(target_id)
        if upgraded_role:
            target["source_section_role"] = upgraded_role
        collapsed_profile_targets.append(target)
    location_profile_targets = collapsed_profile_targets

    zone_seed_text_by_id = {
        str(snapshot.get("entity_id", "")).strip(): build_zone_seed_text(
            snapshots, str(snapshot.get("entity_id", "")).strip()
        )
        for snapshot in snapshots
        if isinstance(snapshot, dict)
        and str(snapshot.get("entity_type", "")).strip() == "zone"
        and not str(snapshot.get("auxiliary_role", "")).strip()
    }

    for candidate in location_candidates:
        name_lowered = str(candidate.get("name", "")).lower()
        hard_reject_reasons = hard_reject_markers(str(candidate.get("name", "")))
        location_class = classify_location_candidate(
            str(candidate.get("name", "")), hard_reject_reasons=hard_reject_reasons
        )
        location_classification.append(
            {
                "zone_id": candidate["zone_id"],
                "location_id": candidate["location_id"],
                "name": candidate["name"],
                "classification": location_class,
                "hard_reject_reasons": hard_reject_reasons,
                "typing_signals": {
                    "contains_city_keyword": "city" in name_lowered,
                    "contains_starter_keyword": "starter" in name_lowered,
                    "source_section_role": str(candidate.get("source_section_role", "other")),
                },
            }
        )
        zone_id = str(candidate.get("zone_id", "")).strip()
        location_decisions.append(
            build_location_decision_row(
                candidate,
                run_id=context.run_id,
                algorithm_version="v1",
                seed_text=zone_seed_text_by_id.get(zone_id, ""),
            )
        )

    deduped_instances: list[dict[str, Any]] = []
    seen_instances: set[str] = set()
    for row in instance_registry:
        instance_id = str(row.get("instance_id", ""))
        if not instance_id or instance_id in seen_instances:
            continue
        seen_instances.add(instance_id)
        deduped_instances.append(row)
    instance_registry = deduped_instances

    # Slice I4: enumerate cross-page lore candidates from each instance's OWN page
    # (parent-complex + related narrative links), and record the instance page's own
    # lore density so the linked-lore decision stops relying on the zone-seed proxy.
    lore_traversal_targets: list[dict[str, Any]] = []
    instance_density_by_id: dict[str, dict[str, Any]] = {}
    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            continue
        if str(snapshot.get("entity_type", "")).strip() != "instance":
            continue
        if str(snapshot.get("auxiliary_role", "")).strip():
            continue
        instance_id = str(snapshot.get("entity_id", "")).strip()
        instance_name = str(snapshot.get("name", "")).strip()
        if not instance_id or not instance_name:
            continue
        section_blocks = snapshot.get("section_blocks", [])
        if not isinstance(section_blocks, list):
            section_blocks = []
        wiki_links = snapshot.get("wiki_links", [])
        if not isinstance(wiki_links, list):
            wiki_links = []
        structured_links = snapshot.get("structured_links", [])
        if not isinstance(structured_links, list):
            structured_links = []
        instance_density_by_id[instance_id] = compute_instance_lore_density(section_blocks)
        lore_traversal_targets.extend(
            build_instance_lore_candidates(
                instance_id=instance_id,
                instance_name=instance_name,
                section_blocks=section_blocks,
                wiki_links=wiki_links,
                structured_links=structured_links,
            )
        )

    for row in instance_lore_source_map:
        density = instance_density_by_id.get(str(row.get("instance_id", "")).strip())
        if density is not None:
            row["instance_page_density"] = density

    outputs = {
        "zone_coverage_registry": discovery_dir / "zone_coverage_registry.json",
        "canonical_entity_map": discovery_dir / "canonical_entity_map.jsonl",
        "zone_location_candidates": discovery_dir / "zone_location_candidates.json",
        "zone_location_classification": discovery_dir / "zone_location_classification.json",
        "zone_instance_registry": discovery_dir / "zone_instance_registry.json",
        "instance_lore_source_map": discovery_dir / "instance_lore_source_map.json",
        "zone_quest_graph": discovery_dir / "zone_quest_graph.json",
        "zone_quest_graph_v3": discovery_dir / "zone_quest_graph_v3.json",
        "faction_profile_targets": discovery_dir / "faction_profile_targets.json",
        "location_profile_targets": discovery_dir / "location_profile_targets.json",
        "storyline_traversal_targets": discovery_dir / "storyline_traversal_targets.json",
        "lore_traversal_targets": discovery_dir / "lore_traversal_targets.json",
        "instance_zone_profiles": discovery_dir / "instance_zone_profiles.json",
        "location_significance_decisions": decisions_dir / "location_significance_decisions.json",
        "questline_inclusion_decisions": decisions_dir / "questline_inclusion_decisions.json",
        "evidence_packs": evidence_dir / "evidence_packs.jsonl",
    }
    write_json(outputs["zone_coverage_registry"], zone_registry)
    outputs["canonical_entity_map"].write_text(
        "\n".join(json.dumps(row) for row in canonical_entities) + "\n", encoding="utf-8"
    )
    write_json(outputs["zone_location_candidates"], location_candidates)
    write_json(outputs["zone_location_classification"], location_classification)
    write_json(outputs["zone_instance_registry"], instance_registry)
    write_json(outputs["instance_lore_source_map"], instance_lore_source_map)
    write_json(outputs["zone_quest_graph"], quest_graph)
    write_json(outputs["zone_quest_graph_v3"], [])
    write_json(outputs["faction_profile_targets"], faction_profile_targets)
    write_json(outputs["location_profile_targets"], location_profile_targets)
    write_json(outputs["storyline_traversal_targets"], storyline_traversal_targets)
    write_json(outputs["lore_traversal_targets"], lore_traversal_targets)
    write_json(outputs["instance_zone_profiles"], instance_zone_profiles)
    write_json(outputs["location_significance_decisions"], location_decisions)
    write_json(outputs["questline_inclusion_decisions"], questline_decisions)
    outputs["evidence_packs"].write_text("", encoding="utf-8")

    # Fail fast on contract drift for primary decision artifacts.
    for row in location_decisions:
        DecisionArtifact.model_validate(row)
    return outputs
