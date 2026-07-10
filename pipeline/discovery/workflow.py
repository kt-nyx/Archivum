"""Deterministic wiki-first discovery workflow and artifact builders."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from pipeline.common.draft_vocab import era_section_role_tokens
from pipeline.common.io import read_json, write_json
from pipeline.common.retail import is_classic_categorized
from pipeline.common.run_context import RunContext
from pipeline.common.section_registry import section_content_class
from pipeline.common.text_ids import slugify
from pipeline.contracts.models import DecisionArtifact, EntityKind, EntityKindDecision
from pipeline.discovery.entity_typing import (
    canonical_path_for_link,
    decide_entity_kind,
    normalize_title,
)
from pipeline.discovery.instance_bosses import is_high_confidence_boss_section
from pipeline.discovery.location_discovery import (
    build_location_decision_row,
    build_zone_seed_text,
    classify_location_candidate,
)
from pipeline.discovery.lore_sources import (
    build_instance_lore_candidates,
    compute_instance_lore_density,
)
from pipeline.discovery.world_registry import entry_kinds, organization_entry_for_href
from pipeline.ingest.snapshots import load_source_snapshots

_CLASSIC_ONLY_MARKERS = ("classic", "classic-only", "vanilla")
_NON_RETAIL_MARKERS = ("warcraft iii", "removed", "undisplayed", "lore location")
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


# Slice D: instance roster structured-link sections whose members are the instance's key characters
# (faculty / adventure-guide / boss / encounter / per-dungeon boss table). Denizen/inhabitant rosters
# are trash-heavy (random skeletons, props), so they are excluded; the cast is the curated roster.
# Generic trash-roster terms (never the key-character roster we crawl); not instance-specific.
_INSTANCE_ROSTER_DENIZEN_TOKENS = ("denizen", "inhabitant")
# entry_kinds that mark a roster link as a place / structure rather than a character.
_NON_CHARACTER_ENTRY_KINDS = frozenset(
    {"place", "zone", "continent", "capital", "region", "instance"}
)


def _is_instance_roster_section(section_role: str) -> bool:
    """True for an instance's key-character roster section (boss roster or a registry ``roster``
    section like "Notable characters"/"NPCs"), excluding the denizens/inhabitants trash list.

    Structural: the authoritative boss roster is :func:`is_high_confidence_boss_section` and the
    registry supplies the general roster class — no instance-specific theme words.
    """
    lowered = re.sub(r"\s+", "_", section_role.strip().lower())
    if any(token in lowered for token in _INSTANCE_ROSTER_DENIZEN_TOKENS):
        return False
    if is_high_confidence_boss_section(section_role):
        return True
    return section_content_class(section_role) == "roster"


def _collect_instance_character_targets(
    snapshots: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Emit character-profile crawl targets scoped to each instance's key-character roster.

    Instance key-character cards are the only consumer of character biography, so targets are scoped
    to the instance (not the parent zone) and sourced from its boss-roster structured links, with
    places, structures, and meta pages filtered out. The draft only merges biography for an *elected*
    cast member, so a stray non-character that slips through is crawled but never reaches a card.
    """
    targets: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            continue
        if str(snapshot.get("entity_type", "")) != "instance":
            continue
        if str(snapshot.get("auxiliary_role", "")).strip():
            continue
        instance_id = str(snapshot.get("entity_id", "")).strip()
        if not instance_id:
            continue
        structured_links = snapshot.get("structured_links", [])
        if not isinstance(structured_links, list):
            continue
        for link in structured_links:
            if not isinstance(link, dict):
                continue
            if not _is_instance_roster_section(str(link.get("section_role", ""))):
                continue
            label = str(link.get("label", "")).strip()
            href = str(link.get("href", "")).strip()
            if not label or not href:
                continue
            if entry_kinds(label) & _NON_CHARACTER_ENTRY_KINDS:
                continue
            character_id = _to_entity_id("character", label)
            key = (instance_id, character_id)
            if key in seen:
                continue
            seen.add(key)
            targets.append(
                {
                    "zone_id": instance_id,
                    "character_id": character_id,
                    "name": label,
                    "source_link": href,
                    "source_section_role": str(link.get("section_role", "")),
                }
            )
    return targets


# Slice 13 (Cause A): faction profile targets are the organizations the zone's own page links
# to, ranked by link frequency x section class. Weights favor the sections that carry the
# zone's narrative actors (history, quests/storyline — the latter is what "questline-bound"
# means at discovery time, before the quest graph exists) over gazetteer/roster chrome; RPG
# sections contribute nothing. The lead is weighted separately (it classifies to "other").
_FACTION_TARGET_SECTION_WEIGHTS: dict[str, float] = {
    "history": 3.0,
    "quests_or_storyline": 3.0,
    "notable_characters": 1.0,
    "maps_subregions": 0.5,
    "instances_or_dungeons": 0.5,
    "in_the_rpg": 0.0,
    "other": 1.0,
}
_LEAD_FACTION_TARGET_WEIGHT = 2.0
_MAX_FACTION_PROFILE_TARGETS = 10


def _collect_zone_faction_targets(
    zone_id: str,
    zone_name: str,
    section_blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Faction-profile crawl targets: registry organizations linked from the zone's seed page.

    A target is minted from an inline block link whose target resolves to an org-registry
    entry — never from a name-shape vocabulary — and ranked by summed section-class weight
    (link frequency x section class), so the zone's current actors (Argent Crusade, Cenarion
    Circle, Alliance in WPL) get profiles crawled. Capped to the top
    ``_MAX_FACTION_PROFILE_TARGETS``; traverse applies its own per-zone crawl cap on top,
    in this ranked order.
    """
    zone_low = zone_name.strip().lower()
    stats: dict[str, dict[str, Any]] = {}
    for block in section_blocks:
        if not isinstance(block, dict):
            continue
        raw_leaf = str(block.get("section_role", ""))
        raw_parent = str(block.get("parent_section_role", ""))
        effective_slug = _effective_section_slug(raw_leaf, raw_parent)
        role = _section_role(effective_slug)
        if effective_slug.strip().lower() in ("lead", "introduction"):
            weight = _LEAD_FACTION_TARGET_WEIGHT
        else:
            weight = _FACTION_TARGET_SECTION_WEIGHTS.get(role, 0.0)
        if weight <= 0.0:
            continue
        links = block.get("links")
        if not isinstance(links, list):
            continue
        for link in links:
            if not isinstance(link, dict):
                continue
            href = str(link.get("href", "")).strip()
            org = organization_entry_for_href(href) if href else None
            if org is None:
                continue
            title = str(org.get("title", "")).strip()
            if not title or title.lower() == zone_low:
                continue
            key = str(org.get("normalized_title", title.lower()))
            record = stats.setdefault(
                key,
                {
                    "title": title,
                    "source_link": str(org.get("wiki_path", "")) or href,
                    "score": 0.0,
                    "count": 0,
                    "best_role": role,
                    "best_weight": 0.0,
                },
            )
            record["score"] += weight
            record["count"] += 1
            if weight > record["best_weight"]:
                record["best_weight"] = weight
                record["best_role"] = role
    ranked = sorted(
        stats.values(),
        key=lambda record: (-record["score"], -record["count"], str(record["title"]).lower()),
    )
    return [
        {
            "zone_id": zone_id,
            "faction_id": _to_entity_id("faction", str(record["title"])),
            "name": str(record["title"]),
            "source_link": str(record["source_link"]),
            "source_section_role": str(record["best_role"]),
        }
        for record in ranked[:_MAX_FACTION_PROFILE_TARGETS]
    ]


# Lore/narrative sections that mark a place as story-significant (a card-worthy landmark) vs the
# gameplay gazetteer. A location named in the zone's history/lore prose is marquee; one appearing
# only in maps/getting-there/travel/loot/etc. chrome is a gameplay waypoint, not a landmark.
def _zone_lore_body_text(section_blocks: list[dict[str, Any]]) -> str:
    """Concatenated, lowercased body text of the zone's lore/history narrative sections.

    Includes only registry ``narrative`` sections (with parent inheritance, so event/era
    subsections — "The Scourging", "Cataclysm", "Aftermath" — count via their History parent) and
    excludes geography/gameplay/meta/media chrome, so a name's presence here means narrative
    significance.
    """
    parts: list[str] = []
    for block in section_blocks:
        if not isinstance(block, dict):
            continue
        role = str(block.get("section_role", ""))
        parent = str(block.get("parent_section_role", ""))
        if section_content_class(role, parent) == "narrative":
            parts.append(str(block.get("text", "")))
    return " ".join(parts).lower()


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


def _snapshots_by_canonical_title(snapshots: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index already-fetched target pages by their source-native canonical title."""
    indexed: dict[str, dict[str, Any]] = {}
    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            continue
        title = str(snapshot.get("page_title", "")).strip() or _normalized_wiki_title(
            str(snapshot.get("url", ""))
        )
        if title:
            indexed.setdefault(normalize_title(title), snapshot)
    return indexed


def run_discovery_workflow(context: RunContext, source_manifest_path: Path) -> dict[str, Path]:
    """Build deterministic discovery artifacts from ingest snapshots."""
    snapshots = load_source_snapshots(context.stage_dir("ingest") / "source_snapshots.json")
    manifest_rows = _load_json(source_manifest_path)
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
    entity_kind_decisions: list[dict[str, Any]] = []
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
    snapshots_by_title = _snapshots_by_canonical_title(snapshots)

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

        lore_body_text = _zone_lore_body_text(section_blocks)

        for link in processing_links:
            title = _normalized_wiki_title(link)
            lowered = title.lower()
            candidate_id = _to_entity_id("location", title)
            inferred_role = _infer_link_section_role(link, section_blocks, structured_links)
            entity_decision = decide_entity_kind(
                candidate_id=_to_entity_id("entity", title),
                canonical_title=title,
                canonical_path=canonical_path_for_link(link),
                source_snapshot=snapshots_by_title.get(normalize_title(title)),
                source_relation=inferred_role,
                source_ids=[source_id],
            )
            entity_kind_decisions.append(entity_decision.model_dump(mode="json"))
            known_instance = known_instance_by_title.get(_normalized_wiki_slug(title))
            registry_kinds = entry_kinds(title)
            if known_instance is not None or "instance" in registry_kinds:
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
            elif entity_decision.kind == EntityKind.ORGANIZATION:
                # Slice 13: faction profile targets are built from the seed page's block
                # links against the org registry (see _collect_zone_faction_targets below);
                # a faction-typed link only means "not a location candidate" here.
                continue
            elif entity_decision.kind == EntityKind.NAMED_ACTOR:
                # Zone-page characters are not crawled: zones emit no key-character cards, so a
                # character profile here has no consumer. Instance key characters are targeted
                # separately from the instance roster (see _collect_instance_character_targets).
                continue
            else:
                # A section role is useful discovery context, not type evidence.  Only a positive
                # target-page/registry decision may enter the location-card pipeline.
                if entity_decision.kind != EntityKind.PLACE:
                    continue
                if normalize_title(title) in notable_character_titles:
                    continue
                lore_significant = title.lower() in lore_body_text
                location_candidates.append(
                    {
                        "zone_id": str(snapshot.get("entity_id", "")),
                        "location_id": candidate_id,
                        "name": title,
                        "source_link": link,
                        "source_section_role": inferred_role,
                        "entity_kind": entity_decision.kind.value,
                        "entity_kind_decision_id": entity_decision.decision_id,
                        "lore_significant": lore_significant,
                    }
                )
                location_profile_targets.append(
                    {
                        "zone_id": str(snapshot.get("entity_id", "")),
                        "location_id": candidate_id,
                        "name": title,
                        "source_link": link,
                        "source_section_role": inferred_role,
                        "entity_kind": entity_decision.kind.value,
                        "entity_kind_decision_id": entity_decision.decision_id,
                        "lore_significant": lore_significant,
                    }
                )

        faction_profile_targets.extend(
            _collect_zone_faction_targets(
                str(snapshot.get("entity_id", "")), entity_name, section_blocks
            )
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

    # Slice D: character crawl targets come from each instance's key-character roster (the only
    # consumer of character biography), scoped to the instance — not from the zone link loop above,
    # whose character-typed links are noisy places/meta with no key-character consumer.
    character_profile_targets = _collect_instance_character_targets(snapshots)

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
        location_class = classify_location_candidate(
            str(candidate.get("name", "")), hard_reject_reasons=[]
        )
        location_classification.append(
            {
                "zone_id": candidate["zone_id"],
                "location_id": candidate["location_id"],
                "name": candidate["name"],
                "classification": location_class,
                "entity_kind": candidate["entity_kind"],
                "entity_kind_decision_id": candidate["entity_kind_decision_id"],
                "hard_reject_reasons": [],
                "typing_signals": {
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
        "entity_kind_decisions": decisions_dir / "entity_kind_decisions.json",
        "zone_instance_registry": discovery_dir / "zone_instance_registry.json",
        "instance_lore_source_map": discovery_dir / "instance_lore_source_map.json",
        "zone_quest_graph": discovery_dir / "zone_quest_graph.json",
        "zone_quest_graph_v3": discovery_dir / "zone_quest_graph_v3.json",
        "faction_profile_targets": discovery_dir / "faction_profile_targets.json",
        "location_profile_targets": discovery_dir / "location_profile_targets.json",
        "character_profile_targets": discovery_dir / "character_profile_targets.json",
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
    write_json(
        outputs["entity_kind_decisions"],
        {"schema_version": "entity_kind_decision.v1", "decisions": entity_kind_decisions},
    )
    write_json(outputs["zone_instance_registry"], instance_registry)
    write_json(outputs["instance_lore_source_map"], instance_lore_source_map)
    write_json(outputs["zone_quest_graph"], quest_graph)
    write_json(outputs["zone_quest_graph_v3"], [])
    write_json(outputs["faction_profile_targets"], faction_profile_targets)
    write_json(outputs["location_profile_targets"], location_profile_targets)
    write_json(outputs["character_profile_targets"], character_profile_targets)
    write_json(outputs["storyline_traversal_targets"], storyline_traversal_targets)
    write_json(outputs["lore_traversal_targets"], lore_traversal_targets)
    write_json(outputs["instance_zone_profiles"], instance_zone_profiles)
    write_json(outputs["location_significance_decisions"], location_decisions)
    write_json(outputs["questline_inclusion_decisions"], questline_decisions)
    outputs["evidence_packs"].write_text("", encoding="utf-8")

    # Fail fast on contract drift for primary decision artifacts.
    for row in location_decisions:
        DecisionArtifact.model_validate(row)
    for row in entity_kind_decisions:
        EntityKindDecision.model_validate(row)
    return outputs
