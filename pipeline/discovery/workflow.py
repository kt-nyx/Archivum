"""Deterministic wiki-first discovery workflow and artifact builders."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from pipeline.common.text_normalize import clean_wiki_snippet
from pipeline.common.run_context import RunContext
from pipeline.contracts.models import DecisionArtifact
from pipeline.discovery.entity_typing import should_reject_location_title

_CLASSIC_ONLY_MARKERS = ("classic", "classic-only", "vanilla")
_NON_RETAIL_MARKERS = ("warcraft iii", "removed", "undisplayed", "lore location")
_HARD_REJECT_MARKERS = ("undisplayed", "lore", "removed", "warcraft iii", "other game")
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
_FACTION_KEYWORDS = (
    "crusade",
    "horde",
    "alliance",
    "dawn",
    "circle",
    "cult",
    "order",
    "covenant",
    "faction",
    "forsaken",
    "tribe",
)
_EVENT_KEYWORDS = (
    "war",
    "battle",
    "invasion",
    "scourging",
    "cataclysm",
    "event",
)
_CHARACTER_ROLE_HINTS = (
    "king",
    "queen",
    "lord",
    "lady",
    "highlord",
    "commander",
    "inquisitor",
    "master",
)
_NON_LOCATION_KEYWORDS = (
    "warcraft",
    "novel",
    "novella",
    "short stories",
    "story",
    "faction",
    "class",
    "mob",
    "flight path",
    "instance portal",
    "rpg",
)
_LOCATION_INCLUDE_SECTION_WEIGHTS = {
    "maps_subregions": 0.35,
    "instances_or_dungeons": 0.1,
    "quests_or_storyline": 0.1,
    "history": 0.05,
    "other": 0.0,
}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


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
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return f"{prefix}-{slug}" if slug else prefix


def _classify_retail_eligibility(text: str) -> str:
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
    for role, patterns in _SECTION_ROLE_PATTERNS.items():
        if any(pattern in lowered for pattern in patterns):
            return role
    return "other"


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
        for match in re.finditer(r"([A-Za-z0-9'’\-\s]+(?:storyline|questline))", text, re.IGNORECASE):
            title = re.sub(r"\s+", " ", match.group(1)).strip()
            if title.lower().startswith("see "):
                continue
            if title:
                inferred.add(f"/wiki/{title.replace(' ', '_')}")
    # Zone fallback: "<Zone Name> storyline"
    if not inferred and entity_name:
        inferred.add(f"/wiki/{entity_name.replace(' ', '_')}_storyline")
    return inferred


def _link_section_role_from_structured(
    link: str,
    structured_links: list[dict[str, Any]],
) -> str | None:
    normalized = link.split("#", 1)[0]
    for row in structured_links:
        if not isinstance(row, dict):
            continue
        href = str(row.get("href", "")).split("#", 1)[0]
        if href == normalized or href.endswith(normalized) or normalized.endswith(href):
            return _section_role(str(row.get("section_role", "other")))
    return None


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
    return any(
        part.lower() in _CHARACTER_ROLE_HINTS
        or (part[:1].isupper() and part[1:].islower() and len(part) >= 3)
        for part in parts
    )


def _infer_entity_type_for_link(title: str, inferred_section_role: str) -> str:
    lowered = title.lower()
    if "storyline" in lowered or "questline" in lowered or inferred_section_role == "quests_or_storyline":
        return "quest"
    if "(instance)" in lowered or " dungeon" in lowered or " raid" in lowered:
        return "instance"
    if any(keyword in lowered for keyword in _FACTION_KEYWORDS):
        return "faction"
    if any(keyword in lowered for keyword in _EVENT_KEYWORDS):
        return "event"
    if _is_likely_character_title(title):
        return "character"
    return "location"


def _should_reject_location_candidate(title: str, entity_type: str) -> bool:
    lowered = title.lower()
    if entity_type != "location":
        return True
    if any(keyword in lowered for keyword in _NON_LOCATION_KEYWORDS):
        return True
    return False


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
                "retail_eligibility": _classify_retail_eligibility(body_text),
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
            if (
                known_instance is not None
                or inferred_entity_type == "instance"
            ):
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
                        "fallback_reason": None if has_history else "history_missing_on_instance_page",
                        "source_link": link,
                    }
                )
                instance_zone_profiles.append(
                    {
                        "zone_id": str(snapshot.get("entity_id", "")),
                        "instance_id": instance_id,
                        "instance_name": known_instance["name"] if known_instance is not None else title,
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
                if reject_location or _should_reject_location_candidate(title, inferred_entity_type):
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

    for candidate in location_candidates:
        name_lowered = str(candidate.get("name", "")).lower()
        hard_reject_reasons = [m for m in _HARD_REJECT_MARKERS if m in name_lowered]
        if hard_reject_reasons:
            location_class = "reject"
        elif "city" in name_lowered:
            location_class = "city"
        elif "starter" in name_lowered:
            location_class = "starter_area"
        else:
            location_class = "major_location_candidate"
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
        source_section_role = str(candidate.get("source_section_role", "other"))
        base_score = 0.15
        if location_class in {"city", "starter_area"}:
            base_score += 0.6
        else:
            base_score += 0.25
        base_score += _LOCATION_INCLUDE_SECTION_WEIGHTS.get(source_section_role, 0.0)
        if any(marker in name_lowered for marker in ("classic", "warcraft rpg", "novel", "novella")):
            base_score -= 0.35
        if len(name_lowered.split()) <= 1:
            base_score -= 0.1
        score = max(0.0, min(1.0, base_score))
        borderline = 0.45 <= score <= 0.65
        location_decisions.append(
            {
                "subject_id": candidate["location_id"],
                "subject_type": "location",
                "run_id": context.run_id,
                "algorithm_version": "v1",
                "features": {
                    "keyword_density": 1 if score > 0.6 else 0,
                    "has_hard_reject": bool(hard_reject_reasons),
                    "source_section_role": source_section_role,
                },
                "hard_reject": bool(hard_reject_reasons),
                "hard_reject_reasons": hard_reject_reasons,
                "score": score,
                "thresholds": {"include_min": 0.7, "borderline_min": 0.45, "borderline_max": 0.65},
                "borderline_adjudication": (
                    {
                        "prompt_class": "location_significance_borderline",
                        "ruling": "include" if score >= 0.5 else "exclude",
                    }
                    if borderline
                    else None
                ),
                "final_decision": "exclude" if hard_reject_reasons else ("include" if score >= 0.7 else "defer"),
                "reason_codes": (
                    ["hard_reject"]
                    if hard_reject_reasons
                    else ["score_based", f"source_role:{source_section_role}"]
                ),
            }
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
        "instance_zone_profiles": discovery_dir / "instance_zone_profiles.json",
        "location_significance_decisions": decisions_dir / "location_significance_decisions.json",
        "questline_inclusion_decisions": decisions_dir / "questline_inclusion_decisions.json",
        "evidence_packs": evidence_dir / "evidence_packs.jsonl",
    }
    outputs["zone_coverage_registry"].write_text(json.dumps(zone_registry, indent=2), encoding="utf-8")
    outputs["canonical_entity_map"].write_text(
        "\n".join(json.dumps(row) for row in canonical_entities) + "\n", encoding="utf-8"
    )
    outputs["zone_location_candidates"].write_text(
        json.dumps(location_candidates, indent=2), encoding="utf-8"
    )
    outputs["zone_location_classification"].write_text(
        json.dumps(location_classification, indent=2), encoding="utf-8"
    )
    outputs["zone_instance_registry"].write_text(
        json.dumps(instance_registry, indent=2), encoding="utf-8"
    )
    outputs["instance_lore_source_map"].write_text(
        json.dumps(instance_lore_source_map, indent=2), encoding="utf-8"
    )
    outputs["zone_quest_graph"].write_text(json.dumps(quest_graph, indent=2), encoding="utf-8")
    outputs["zone_quest_graph_v3"].write_text(json.dumps([], indent=2), encoding="utf-8")
    outputs["faction_profile_targets"].write_text(
        json.dumps(faction_profile_targets, indent=2), encoding="utf-8"
    )
    outputs["location_profile_targets"].write_text(
        json.dumps(location_profile_targets, indent=2), encoding="utf-8"
    )
    outputs["storyline_traversal_targets"].write_text(
        json.dumps(storyline_traversal_targets, indent=2), encoding="utf-8"
    )
    outputs["instance_zone_profiles"].write_text(
        json.dumps(instance_zone_profiles, indent=2), encoding="utf-8"
    )
    outputs["location_significance_decisions"].write_text(
        json.dumps(location_decisions, indent=2), encoding="utf-8"
    )
    outputs["questline_inclusion_decisions"].write_text(
        json.dumps(questline_decisions, indent=2), encoding="utf-8"
    )
    outputs["evidence_packs"].write_text("", encoding="utf-8")

    # Fail fast on contract drift for primary decision artifacts.
    for row in location_decisions:
        DecisionArtifact.model_validate(row)
    return outputs
