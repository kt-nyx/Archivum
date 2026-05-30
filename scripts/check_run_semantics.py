#!/usr/bin/env python3
"""Semantic acceptance checks for a pipeline run (zone-agnostic).

Zone prose division (Compendium Voice):
- at_a_glance: past-tense historical identity caption (zone flavor).
- currently: present-tense active retail state; must not overlap at_a_glance.
- history_sections: past-tense reference-chronicle era blocks.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from pipeline.discovery.entity_typing import is_valid_quest_graph_link, normalize_title
from pipeline.discovery.storyline_html import parse_storyline_html
from pipeline.discovery.world_registry import entry_kinds

_GEOGRAPHY_KINDS = frozenset({"zone", "continent", "capital", "region", "instance"})
_FILLER_RE = re.compile(r"\blocated in\b|\bis a zone\b|\bis located\b", re.IGNORECASE)
_MAX_CLUSTER_CARDS = 8
_MAX_CHAIN_REFS = 12


class SemanticCheckError(Exception):
    """Raised when a semantic acceptance check fails."""


def _fail(message: str) -> None:
    raise SemanticCheckError(message)


def _load_json(path: Path) -> object:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_zone_target(run_root: Path, zone_id: str | None) -> tuple[Path, str, str]:
    draft_dir = run_root / "data" / "drafts" / "zone_page"
    if not draft_dir.exists():
        _fail(f"missing zone draft directory at {draft_dir}")

    if zone_id:
        draft_path = draft_dir / f"{zone_id}.json"
        if not draft_path.exists():
            _fail(f"missing zone draft at {draft_path}")
        draft = _load_json(draft_path)
        if not isinstance(draft, dict):
            _fail(f"zone draft is not a JSON object: {draft_path}")
        zone_name = str(draft.get("name", "")).strip() or zone_id
        return draft_path, zone_id, zone_name

    draft_paths = sorted(draft_dir.glob("zone-*.json"))
    if len(draft_paths) == 1:
        draft_path = draft_paths[0]
        resolved_id = draft_path.stem
        draft = _load_json(draft_path)
        if not isinstance(draft, dict):
            _fail(f"zone draft is not a JSON object: {draft_path}")
        zone_name = str(draft.get("name", "")).strip() or resolved_id
        return draft_path, resolved_id, zone_name

    manifest_path = run_root / "source_manifest.json"
    manifest = _load_json(manifest_path)
    zone_ids: list[str] = []
    if isinstance(manifest, list):
        for row in manifest:
            if not isinstance(row, dict):
                continue
            if str(row.get("entity_type", "")).strip() != "zone":
                continue
            entity_id = str(row.get("entity_id", "")).strip()
            if entity_id and entity_id not in zone_ids:
                zone_ids.append(entity_id)
    if len(zone_ids) == 1:
        resolved_id = zone_ids[0]
        draft_path = draft_dir / f"{resolved_id}.json"
        if not draft_path.exists():
            _fail(f"manifest zone {resolved_id!r} has no draft at {draft_path}")
        draft = _load_json(draft_path)
        if not isinstance(draft, dict):
            _fail(f"zone draft is not a JSON object: {draft_path}")
        zone_name = str(draft.get("name", "")).strip() or resolved_id
        return draft_path, resolved_id, zone_name

    _fail(
        "could not resolve zone target: pass --zone-id or ensure the run has exactly one zone draft "
        f"(found {len(draft_paths)} drafts, {len(zone_ids)} zone manifest rows)"
    )


def _cluster_ids_from_v3(v3_rows: list[dict[str, Any]], zone_id: str) -> set[str]:
    return {
        str(row.get("cluster_id", "")).strip()
        for row in v3_rows
        if isinstance(row, dict)
        and str(row.get("zone_id", "")) == zone_id
        and str(row.get("node_type", "")) == "quest"
        and str(row.get("cluster_id", "")).strip()
    }


def _cluster_id_from_card_id(card_id: str) -> str:
    normalized = str(card_id).replace("cluster-", "", 1)
    if normalized.endswith("-continued"):
        return normalized[: -len("-continued")]
    return normalized


def check_run(run_root: Path, *, zone_id: str | None = None) -> None:
    draft_path, resolved_zone_id, zone_name = _resolve_zone_target(run_root, zone_id)
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    if not draft.get("major_questlines"):
        _fail("major_questlines is empty")
    zone_lower = normalize_title(zone_name)
    for row in draft.get("major_questlines", []):
        if not isinstance(row, dict):
            continue
        title = str(row.get("title", "")).strip()
        if not title:
            _fail("major_questlines contains empty title")
        title_kinds = entry_kinds(title)
        if title_kinds & _GEOGRAPHY_KINDS:
            _fail(f"major_questlines cluster title is a geography hub: {title!r}")
        if title.lower().endswith(" quests"):
            _fail(f"major_questlines cluster title looks like an achievement hub: {title!r}")
        cta = str(row.get("cta_hook", "")).strip()
        if zone_lower and zone_lower in normalize_title(cta):
            _fail(f"major_questlines cta_hook reads like zone-description filler: {cta!r}")
        if _FILLER_RE.search(cta):
            _fail(f"major_questlines cta_hook reads like zone-description filler: {cta!r}")
        from pipeline.generate.draft.card_lint import lint_cta_hook

        for issue in lint_cta_hook(cta):
            _fail(f"major_questlines cta_hook quality check failed for {title!r}: {issue}")
        chain_refs = row.get("chain_refs", [])
        if isinstance(chain_refs, list) and len(chain_refs) > _MAX_CHAIN_REFS:
            _fail(
                f"major_questlines chain_refs exceeds cap for {title!r} "
                f"({len(chain_refs)} > {_MAX_CHAIN_REFS})"
            )
        wiki_refs = row.get("wiki_refs", [])
        if not isinstance(wiki_refs, list) or not wiki_refs:
            _fail(f"major_questlines card missing wiki_refs: {title!r}")
        for ref in wiki_refs:
            link = str(ref).strip()
            if not link.startswith("/wiki/"):
                link = f"/wiki/{link.replace(' ', '_')}"
            valid, reasons = is_valid_quest_graph_link(link, zone_name=zone_name)
            if not valid:
                _fail(f"major_questlines wiki_ref denied by quest graph classifier: {link!r} ({reasons})")
    cards = [row for row in draft.get("major_questlines", []) if isinstance(row, dict)]
    if len(cards) > _MAX_CLUSTER_CARDS:
        _fail(f"major_questlines exceeds cluster card cap ({len(cards)} > {_MAX_CLUSTER_CARDS})")
    card_titles = [str(row.get("title", "")).strip() for row in cards]
    if len(cards) >= 2 and all(title.lower() == "main storylines" for title in card_titles if title):
        _fail("major_questlines cards all use generic Main storylines title")

    from pipeline.generate.draft.prose_lint import (
        MAX_HISTORY_SECTIONS,
        MIN_HISTORY_SECTIONS,
        lint_at_a_glance,
        lint_currently,
        lint_history_sections,
    )

    at_a_glance = str(draft.get("at_a_glance", "")).strip()
    if not at_a_glance:
        _fail("at_a_glance is empty")
    for issue in lint_at_a_glance(at_a_glance, zone_name=zone_name):
        _fail(f"at_a_glance quality check failed: {issue}")

    currently = str(draft.get("currently", "")).strip()
    if not currently:
        _fail("currently is empty")
    for issue in lint_currently(currently, zone_name=zone_name, at_a_glance=at_a_glance):
        _fail(f"currently quality check failed: {issue}")

    history = draft.get("history_sections") or []
    if not history:
        _fail("history_sections is empty")
    history_issues = lint_history_sections(history, max_sections=MAX_HISTORY_SECTIONS)
    for issue in history_issues:
        _fail(f"history_sections quality check failed: {issue}")
    if len(history) > MAX_HISTORY_SECTIONS:
        _fail(f"history_sections exceeds cap ({len(history)} > {MAX_HISTORY_SECTIONS})")

    blob = json.dumps(history)
    if "&#91;" in blob or "History 1" in blob:
        _fail("history_sections contain raw passthrough markers")

    from pipeline.generate.draft.faction_lint import lint_faction_summary, summary_has_zone_anchor
    from pipeline.generate.draft.faction_scoring import (
        MAX_FACTION_CARDS,
        MIN_FACTION_CARDS,
        alliance_horde_conflict_met,
    )
    from pipeline.generate.draft.location_scoring import extract_subregion_tokens

    subregion_tokens: list[str] = []
    evidence_path_early = run_root / "data" / "evidence" / "evidence_packs.jsonl"
    if evidence_path_early.exists():
        seed_pool: list[dict[str, Any]] = []
        for line in evidence_path_early.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                continue
            if str(row.get("field_name", "")) not in {"geography_input", "history_digest", "currently_input"}:
                continue
            build_meta = row.get("build_meta") or {}
            if str(build_meta.get("subject_zone_id", row.get("subject_id", ""))).strip() not in {
                "",
                resolved_zone_id,
            }:
                continue
            for item in row.get("evidence_items") or []:
                if isinstance(item, dict):
                    seed_pool.append(
                        {
                            "snippet": str(item.get("snippet", "")),
                            "section_role": str(item.get("section_role", "")),
                        }
                    )
        subregion_tokens = extract_subregion_tokens(seed_pool, zone_name=zone_name)

    major_factions = draft.get("major_factions") or []
    faction_cards = [row for row in major_factions if isinstance(row, dict)]
    for card in faction_cards:
        card_id = str(card.get("id", "")).strip()
        if not card_id.startswith("faction-"):
            _fail(f"major_factions card id is not faction-scoped: {card_id!r}")
        summary = str(card.get("summary", "")).strip()
        if not summary:
            _fail(f"major_factions card missing summary: {card_id!r}")
        for issue in lint_faction_summary(
            summary,
            zone_name=zone_name,
            subregion_tokens=subregion_tokens,
        ):
            _fail(f"major_factions quality check failed for {card_id!r}: {issue}")
        if card_id in {"faction-alliance", "faction-horde"} and not summary_has_zone_anchor(
            summary,
            zone_name=zone_name,
            subregion_tokens=subregion_tokens,
        ):
            _fail(f"major_factions Alliance/Horde summary lacks zone anchor for {card_id!r}")
    if len(faction_cards) > MAX_FACTION_CARDS:
        _fail(f"major_factions exceeds cap ({len(faction_cards)} > {MAX_FACTION_CARDS})")

    from pipeline.generate.draft.location_scoring import (
        MAX_LOCATION_CARDS,
        MIN_LOCATION_CARDS,
    )

    location_cards = [row for row in draft.get("location_cards") or [] if isinstance(row, dict)]
    if not location_cards:
        _fail("location_cards is empty")

    from pipeline.discovery.entity_typing import should_reject_location_title
    from pipeline.generate.draft.location_lint import lint_location_summary
    for card in location_cards:
        card_id = str(card.get("id", "")).strip()
        if not (card_id.startswith("location-") or card_id.startswith("loc-")):
            _fail(f"location_cards card id is not location-scoped: {card_id!r}")
        summary = str(card.get("summary", "")).strip()
        if not summary:
            _fail(f"location_cards card missing summary: {card_id!r}")
        for issue in lint_location_summary(
            summary,
            zone_name=zone_name,
            location_name=str(card.get("name", "")).strip(),
        ):
            _fail(f"location_cards quality check failed for {card_id!r}: {issue}")
        reason_codes = [str(code) for code in (card.get("decision_reason_codes") or [])]
        if reason_codes == ["defer"] or (
            "defer" in reason_codes and "include" not in reason_codes and "score_based" not in reason_codes
        ):
            _fail(f"location_cards card appears defer-only selected: {card_id!r}")
        reject, reject_reasons = should_reject_location_title(str(card.get("name", "")).strip(), zone_name=zone_name)
        hard_reasons = [reason for reason in reject_reasons if reason != "likely_npc"]
        if hard_reasons:
            _fail(f"location_cards card name denied by location guards: {card_id!r} ({hard_reasons})")
    if len(location_cards) > MAX_LOCATION_CARDS:
        _fail(f"location_cards exceeds cap ({len(location_cards)} > {MAX_LOCATION_CARDS})")

    if len(draft.get("sources", [])) < 2:
        _fail("expected multiple sources on zone draft")

    parent_continent = str(draft.get("parent_continent", "")).strip().lower()
    if not parent_continent or parent_continent == "unknown":
        _fail(f"parent_continent unresolved for zone {resolved_zone_id!r}")

    from pipeline.generate.draft.instance_link_lint import (
        is_generic_instance_link_summary,
        lint_instance_link_summary,
    )

    instance_links = [row for row in draft.get("instance_links") or [] if isinstance(row, dict)]
    instance_registry_path = run_root / "data" / "discovery" / "zone_instance_registry.json"
    expected_instance_ids: set[str] = set()
    if instance_registry_path.exists():
        registry_blob = _load_json(instance_registry_path)
        if isinstance(registry_blob, list):
            expected_instance_ids = {
                str(row.get("instance_id", "")).strip()
                for row in registry_blob
                if isinstance(row, dict) and str(row.get("source_zone_id", "")).strip() == resolved_zone_id
            }
            expected_instance_ids = {instance_id for instance_id in expected_instance_ids if instance_id}
    instance_provenance = (draft.get("provenance") or {}).get("instances") or {}
    for card in instance_links:
        card_id = str(card.get("id", "")).strip()
        instance_name = str(card.get("name", "")).strip()
        summary = str(card.get("summary", "")).strip()
        if not summary:
            _fail(f"instance_links card missing summary: {card_id!r}")
        if is_generic_instance_link_summary(summary):
            _fail(f"instance_links summary reads like generic stub: {card_id!r}")
        for issue in lint_instance_link_summary(
            summary,
            instance_name=instance_name,
            zone_name=zone_name,
        ):
            _fail(f"instance_links quality check failed for {card_id!r}: {issue}")
        if card_id and card_id not in instance_provenance:
            _fail(f"instance_links card missing provenance: {card_id!r}")
    if expected_instance_ids and not instance_links:
        _fail(
            f"instance_links empty despite {len(expected_instance_ids)} registered instances "
            f"for zone {resolved_zone_id!r}"
        )

    v3_path = run_root / "data" / "discovery" / "zone_quest_graph_v3.json"
    snapshots_path = run_root / "data" / "ingest" / "source_snapshots.json"
    v3_rows: list[dict[str, Any]] = []
    if v3_path.exists():
        blob = _load_json(v3_path)
        if isinstance(blob, list):
            v3_rows = [row for row in blob if isinstance(row, dict)]

    if (
        len(cards) == 1
        and card_titles
        and card_titles[0].lower() == "main storylines"
        and v3_rows
    ):
        distinct_titles = {
            str(row.get("cluster_title", "")).strip()
            for row in v3_rows
            if str(row.get("zone_id", "")) == resolved_zone_id
            and str(row.get("node_type", "")) == "quest"
            and str(row.get("cluster_title", "")).strip()
            and str(row.get("cluster_title", "")).strip().lower() != "main storylines"
        }
        if len(distinct_titles) >= 2:
            _fail("major_questlines single card uses Main storylines despite distinct v3 cluster titles")

    if v3_rows and snapshots_path.exists():
        v3_titles = {
            str(row.get("title", "")).lower()
            for row in v3_rows
            if row.get("node_type") == "quest" and str(row.get("zone_id", "")) == resolved_zone_id
        }
        snapshots = json.loads(snapshots_path.read_text(encoding="utf-8"))
        storyline = next(
            (
                row
                for row in snapshots
                if isinstance(row, dict)
                and str(row.get("entity_id", "")) == resolved_zone_id
                and str(row.get("auxiliary_role", "")) == "storyline"
            ),
            None,
        )
        if storyline is not None:
            parse_html = str(storyline.get("parse_html", "")).strip()
            if parse_html:
                expected_titles = {
                    str(row.get("title", "")).lower()
                    for row in parse_storyline_html(
                        parse_html,
                        zone_id=resolved_zone_id,
                        zone_name=zone_name,
                    )
                }
                extra = v3_titles - expected_titles
                if extra:
                    _fail(
                        "v3 quest graph includes quests not parsed from storyline list items: "
                        f"{sorted(extra)}"
                    )

    if v3_rows:
        expected_clusters = _cluster_ids_from_v3(v3_rows, resolved_zone_id)
        card_ids = {
            _cluster_id_from_card_id(str(row.get("id", "")))
            for row in cards
        }
        if expected_clusters:
            if not card_ids:
                _fail("major_questlines has no cluster cards despite v3 quest clusters")
            if len(expected_clusters) >= 2 and len(card_ids) < 2:
                _fail(
                    f"major_questlines has fewer than 2 cluster cards "
                    f"({len(card_ids)}) despite {len(expected_clusters)} v3 clusters"
                )
            if not card_ids.issubset(expected_clusters):
                _fail(
                    "major_questlines cards reference unknown cluster ids "
                    f"(got {sorted(card_ids)}, expected subset of {sorted(expected_clusters)})"
                )
            if not card_ids.intersection(expected_clusters):
                _fail(
                    "major_questlines cards do not align with v3 cluster ids "
                    f"(expected one of {sorted(expected_clusters)}, got {sorted(card_ids)})"
                )

    evidence_path = run_root / "data" / "evidence" / "evidence_packs.jsonl"
    if evidence_path.exists():
        zone_evidence_rows: list[dict[str, Any]] = []
        for line in evidence_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            build_meta = row.get("build_meta") or {}
            subject_zone = str(build_meta.get("subject_zone_id", row.get("subject_id", "")))
            if subject_zone not in {"", resolved_zone_id}:
                continue
            zone_evidence_rows.append(row)

        location_decisions_path = run_root / "data" / "decisions" / "location_significance_decisions.json"
        include_location_ids: set[str] | None = None
        if location_decisions_path.exists():
            decisions_blob = _load_json(location_decisions_path)
            if isinstance(decisions_blob, list):
                include_location_ids = {
                    str(row.get("subject_id", "")).strip()
                    for row in decisions_blob
                    if isinstance(row, dict)
                    and str(row.get("final_decision", "")).strip() == "include"
                }
                include_location_ids = {location_id for location_id in include_location_ids if location_id}

        def _location_is_include(location_id: str) -> bool:
            if include_location_ids is None:
                return True
            return location_id in include_location_ids

        eligible_history_blocks = 0
        covered_clusters: set[str] = set()
        glance_items = 0
        eligible_faction_candidates: set[str] = set()
        faction_ids_with_profile: set[str] = set()
        faction_names_by_id: dict[str, str] = {}
        eligible_location_candidates: set[str] = set()
        location_ids_with_profile: set[str] = set()
        location_names_by_id: dict[str, str] = {}
        location_seed_pool_items: list[dict[str, Any]] = []
        for row in zone_evidence_rows:
            field_name = str(row.get("field_name", ""))
            build_meta = row.get("build_meta") or {}
            if field_name == "history_digest":
                eligible_history_blocks += len(row.get("evidence_items", []))
            elif field_name == "quest_cluster_lore":
                cluster_id = str(build_meta.get("cluster_id", "")).strip()
                if cluster_id:
                    covered_clusters.add(cluster_id)
            elif field_name == "at_a_glance_input":
                glance_items += len(row.get("evidence_items", []))
            elif field_name == "faction_pool":
                faction_id = str(build_meta.get("faction_id", "")).strip()
                if faction_id:
                    eligible_faction_candidates.add(faction_id)
                    faction_ids_with_profile.add(faction_id)
                    faction_name = str(build_meta.get("faction_name", "")).strip()
                    if faction_name:
                        faction_names_by_id[faction_id] = faction_name
            elif field_name == "location_pool":
                location_id = str(build_meta.get("location_id", "")).strip()
                if location_id and _location_is_include(location_id):
                    eligible_location_candidates.add(location_id)
                    location_ids_with_profile.add(location_id)
                    location_name = str(build_meta.get("location_name", "")).strip()
                    if location_name:
                        location_names_by_id[location_id] = location_name
            elif field_name in {"history_digest", "at_a_glance_input"}:
                for item in row.get("evidence_items", []):
                    if not isinstance(item, dict):
                        continue
                    role = str(item.get("section_role", build_meta.get("section_role", ""))).lower()
                    if any(hint in role for hint in ("maps", "subregion", "geography")):
                        location_seed_pool_items.append(
                            {
                                "snippet": str(item.get("snippet", "")),
                                "section_role": role,
                            }
                        )
        targets_path = run_root / "data" / "discovery" / "faction_profile_targets.json"
        if targets_path.exists():
            targets_blob = _load_json(targets_path)
            if isinstance(targets_blob, list):
                for row in targets_blob:
                    if not isinstance(row, dict):
                        continue
                    if str(row.get("zone_id", "")).strip() != resolved_zone_id:
                        continue
                    faction_id = str(row.get("faction_id", "")).strip()
                    faction_name = str(row.get("name", "")).strip()
                    if faction_id:
                        eligible_faction_candidates.add(faction_id)
                        if faction_name:
                            faction_names_by_id.setdefault(faction_id, faction_name)
        location_targets_path = run_root / "data" / "discovery" / "location_profile_targets.json"
        if location_targets_path.exists():
            targets_blob = _load_json(location_targets_path)
            if isinstance(targets_blob, list):
                for row in targets_blob:
                    if not isinstance(row, dict):
                        continue
                    if str(row.get("zone_id", "")).strip() != resolved_zone_id:
                        continue
                    location_id = str(row.get("location_id", "")).strip()
                    location_name = str(row.get("name", "")).strip()
                    if location_id and _location_is_include(location_id):
                        eligible_location_candidates.add(location_id)
                        if location_name:
                            location_names_by_id.setdefault(location_id, location_name)
        for card in location_cards:
            card_id = str(card.get("id", "")).strip()
            card_name = str(card.get("name", "")).strip()
            if card_id and card_name:
                location_names_by_id.setdefault(card_id, card_name)
        if len(eligible_location_candidates) >= MIN_LOCATION_CARDS and len(location_cards) < MIN_LOCATION_CARDS:
            _fail(
                f"location_cards count {len(location_cards)} below minimum {MIN_LOCATION_CARDS} "
                f"for {len(eligible_location_candidates)} location candidates"
            )
        draft_location_ids = {str(card.get("id", "")).strip() for card in location_cards}
        unknown_location_ids = sorted(draft_location_ids - eligible_location_candidates)
        if unknown_location_ids and eligible_location_candidates:
            _fail(
                "location_cards reference unknown location ids "
                f"(got {unknown_location_ids}, expected subset of {sorted(eligible_location_candidates)})"
            )
        location_provenance = (draft.get("provenance") or {}).get("major_landmarks") or {}
        for card in location_cards:
            card_id = str(card.get("id", "")).strip()
            if card_id in location_ids_with_profile and card_id not in location_provenance:
                _fail(f"location_cards card missing provenance despite profile evidence: {card_id!r}")
        subregion_tokens = extract_subregion_tokens(location_seed_pool_items, zone_name=zone_name)
        for card in location_cards:
            card_id = str(card.get("id", "")).strip()
            if card_id not in location_ids_with_profile:
                continue
            summary = str(card.get("summary", "")).strip()
            from pipeline.generate.draft.location_scoring import location_zone_relevant

            if summary and not location_zone_relevant(
                summary,
                zone_name=zone_name,
                subregion_tokens=subregion_tokens,
            ):
                print(
                    f"WARN: {card_id!r} summary lacks zone/subregion anchor despite profile evidence"
                )
        for card in faction_cards:
            card_id = str(card.get("id", "")).strip()
            card_name = str(card.get("name", "")).strip()
            if card_id and card_name:
                faction_names_by_id.setdefault(card_id, card_name)

        def _seed_mentions_for_faction(faction_id: str) -> list[dict[str, Any]]:
            faction_name = faction_names_by_id.get(faction_id, "").strip()
            if not faction_name:
                return []
            mentions: list[dict[str, Any]] = []
            for row in zone_evidence_rows:
                field_name = str(row.get("field_name", ""))
                if field_name not in {"history_digest", "currently_input", "questline_pool", "at_a_glance_input"}:
                    continue
                build_meta = row.get("build_meta") or {}
                for item in row.get("evidence_items", []):
                    if not isinstance(item, dict):
                        continue
                    snippet = str(item.get("snippet", "")).strip()
                    if not snippet:
                        continue
                    if re.search(rf"\b{re.escape(faction_name)}\b", snippet, re.IGNORECASE):
                        mentions.append(
                            {
                                "snippet": snippet,
                                "section_role": str(item.get("section_role", build_meta.get("section_role", ""))),
                                "field_name": field_name,
                            }
                        )
            return mentions
        if len(eligible_faction_candidates) >= MIN_FACTION_CARDS and len(faction_cards) < MIN_FACTION_CARDS:
            _fail(
                f"major_factions count {len(faction_cards)} below minimum {MIN_FACTION_CARDS} "
                f"for {len(eligible_faction_candidates)} faction candidates"
            )
        draft_faction_ids = {str(card.get("id", "")).strip() for card in faction_cards}
        unknown_ids = sorted(draft_faction_ids - eligible_faction_candidates)
        if unknown_ids and eligible_faction_candidates:
            _fail(
                "major_factions cards reference unknown faction ids "
                f"(got {unknown_ids}, expected subset of {sorted(eligible_faction_candidates)})"
            )
        provenance = draft.get("provenance") or {}
        faction_provenance = provenance.get("major_factions") or {}
        for card in faction_cards:
            card_id = str(card.get("id", "")).strip()
            if card_id in faction_ids_with_profile and card_id not in faction_provenance:
                _fail(f"major_factions card missing provenance despite profile evidence: {card_id!r}")
        for card in faction_cards:
            card_id = str(card.get("id", "")).strip()
            if card_id not in {"faction-alliance", "faction-horde"}:
                continue
            binding_count = 0
            if v3_rows:
                binding = "alliance" if card_id == "faction-alliance" else "horde"
                binding_count = sum(
                    1
                    for row in v3_rows
                    if isinstance(row, dict)
                    and str(row.get("zone_id", "")) == resolved_zone_id
                    and str(row.get("node_type", "")) == "quest"
                    and str(row.get("faction_binding", "")).strip().lower() == binding
                )
            seed_mentions = _seed_mentions_for_faction(card_id)
            if not alliance_horde_conflict_met(
                faction_id=card_id,
                quest_binding_count=binding_count,
                seed_mentions=seed_mentions,
            ):
                print(
                    f"WARN: {card_id!r} present in major_factions without strong conflict signal "
                    "(quest bindings or high-weight seed mention)"
                )
        if eligible_history_blocks >= MIN_HISTORY_SECTIONS and len(history) < MIN_HISTORY_SECTIONS:
            _fail(
                f"history_sections count {len(history)} below minimum {MIN_HISTORY_SECTIONS} "
                f"for {eligible_history_blocks} seed history blocks"
            )
        if v3_rows:
            expected_clusters = _cluster_ids_from_v3(v3_rows, resolved_zone_id)
            missing = sorted(expected_clusters - covered_clusters)
            if expected_clusters and missing:
                _fail(f"clusters missing quest_cluster_lore evidence: {missing}")
        if glance_items > 50:
            _fail(f"at_a_glance_input pool exceeds cap: {glance_items}")

        source_kind_by_id: dict[str, str] = {}
        for row in zone_evidence_rows:
            build_meta = row.get("build_meta") or {}
            source_id = str(build_meta.get("source_id", "")).strip()
            source_kind = str(build_meta.get("source_kind", "")).strip()
            if source_id and source_kind:
                source_kind_by_id[source_id] = source_kind
        provenance = draft.get("provenance") or {}
        for field_name in ("at_a_glance", "currently", "history"):
            for pointer in provenance.get(field_name, []):
                if not isinstance(pointer, dict):
                    continue
                source_id = str(pointer.get("source_id", "")).strip()
                source_kind = source_kind_by_id.get(source_id, "")
                if source_kind and source_kind != "seed":
                    print(
                        f"WARN: {field_name} provenance references non-seed source "
                        f"{source_id!r} (source_kind={source_kind!r})"
                    )

    traversal_path = run_root / "data" / "ingest" / "traversal_report.json"
    if traversal_path.exists():
        traversal_blob = _load_json(traversal_path)
        if isinstance(traversal_blob, dict):
            for entry in traversal_blob.get("entries", []):
                if not isinstance(entry, dict):
                    continue
                if entry.get("role") != "quest" or entry.get("status") != "fetched":
                    continue
                link = str(entry.get("link", "")).strip()
                if not link:
                    continue
                if str(entry.get("traversal_origin", "")).strip() == "hub_resolved":
                    if not str(entry.get("hub_resolved_from", "")).strip():
                        _fail(f"hub_resolved quest fetch missing hub_resolved_from: {link!r}")
                valid, reasons = is_valid_quest_graph_link(link, zone_name=zone_name)
                if not valid:
                    _fail(f"traversal report fetched denylisted quest href: {link!r} ({reasons})")

    print(f"PASS: semantic checks ok for {run_root.name} ({resolved_zone_id})")
    _check_instance_drafts(run_root)
    _check_glossary(run_root)


def _glossary_min_terms() -> int:
    import os

    raw = os.environ.get("LORE_GLOSSARY_MIN_TERMS", "7").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 7


def _linked_glossary_refs(run_root: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    draft_root = run_root / "data" / "drafts"
    refs: list[dict[str, Any]] = []
    for draft_dir_name in ("zone_page", "instance_page"):
        draft_dir = draft_root / draft_dir_name
        if not draft_dir.exists():
            continue
        for draft_path in sorted(draft_dir.glob("*.json")):
            draft = _load_json(draft_path)
            if not isinstance(draft, dict):
                continue
            for ref in draft.get("glossary_refs") or []:
                if isinstance(ref, dict):
                    refs.append(ref)
    run_terms_path = run_root / "data" / "glossary" / "run_terms.jsonl"
    run_terms_by_id: dict[str, dict[str, Any]] = {}
    if run_terms_path.exists():
        for line in run_terms_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if isinstance(row, dict):
                term_id = str(row.get("term_id", "")).strip()
                if term_id:
                    run_terms_by_id[term_id] = row
    return refs, run_terms_by_id


def _has_wiki_first_drafts(run_root: Path) -> bool:
    draft_root = run_root / "data" / "drafts"
    for draft_dir_name in ("zone_page", "instance_page"):
        draft_dir = draft_root / draft_dir_name
        if draft_dir.exists() and any(draft_dir.glob("*.json")):
            return True
    return False


def _check_glossary(run_root: Path) -> None:
    if not _has_wiki_first_drafts(run_root):
        return

    run_terms_path = run_root / "data" / "glossary" / "run_terms.jsonl"
    if not run_terms_path.exists():
        _fail(f"missing run-scoped glossary terms file: {run_terms_path}")
    if not run_terms_path.read_text(encoding="utf-8").strip():
        _fail(f"run-scoped glossary terms file is empty: {run_terms_path}")

    zone_dir = run_root / "data" / "drafts" / "zone_page"
    refs, run_terms_by_id = _linked_glossary_refs(run_root)
    unique_term_ids = {str(ref.get("term_id", "")).strip() for ref in refs if str(ref.get("term_id", "")).strip()}
    if not unique_term_ids:
        print(f"PASS: glossary semantic checks ok for {run_root.name} (no linked refs yet)")
        return

    min_terms = _glossary_min_terms()
    if min_terms > 0 and len(unique_term_ids) < min_terms:
        _fail(
            f"glossary link count {len(unique_term_ids)} below minimum {min_terms} "
            f"for run {run_root.name!r}"
        )

    for index, ref in enumerate(refs):
        term_id = str(ref.get("term_id", "")).strip()
        label = str(ref.get("label", "")).strip()
        wiki_url = str(ref.get("wiki_url", "")).strip()
        if not term_id:
            _fail(f"glossary ref missing term_id at index {index}")
        if not label:
            _fail(f"glossary ref missing label for term_id {term_id!r}")
        if not wiki_url.startswith("http"):
            _fail(f"glossary ref missing wiki_url for term_id {term_id!r}")
        if run_terms_by_id and term_id not in run_terms_by_id:
            _fail(f"linked glossary term {term_id!r} not present in run_terms.jsonl")

    linked_categories: set[str] = set()
    zone_name_terms: set[str] = set()
    linked_labels: set[str] = set()
    if zone_dir.exists():
        for draft_path in sorted(zone_dir.glob("*.json")):
            draft = _load_json(draft_path)
            if not isinstance(draft, dict):
                continue
            zone_name = str(draft.get("name", "")).strip().lower()
            if zone_name:
                zone_name_terms.add(zone_name)
    for term_id in unique_term_ids:
        row = run_terms_by_id.get(term_id, {})
        category = str(row.get("category", "")).strip().lower()
        if category:
            linked_categories.add(category)
        label = str(row.get("label", "")).strip().lower()
        if label:
            linked_labels.add(label)

    if "faction" not in linked_categories:
        _fail("glossary links missing at least one faction category term")
    if "place" not in linked_categories:
        _fail("glossary links missing at least one place category term")
    if zone_name_terms and not zone_name_terms.intersection(linked_labels):
        _fail("glossary links missing zone name term coverage")

    draft_root = run_root / "data" / "drafts"
    for draft_dir_name in ("zone_page", "instance_page"):
        draft_dir = draft_root / draft_dir_name
        if not draft_dir.exists():
            continue
        for draft_path in sorted(draft_dir.glob("*.json")):
            draft = _load_json(draft_path)
            if not isinstance(draft, dict):
                continue
            glossary_map = (draft.get("provenance") or {}).get("glossary") or {}
            for ref in draft.get("glossary_refs") or []:
                if not isinstance(ref, dict):
                    continue
                term_id = str(ref.get("term_id", "")).strip()
                if term_id and term_id not in glossary_map:
                    _fail(
                        f"glossary ref {term_id!r} missing provenance.glossary entry "
                        f"in {draft_path.name}"
                    )

    print(f"PASS: glossary semantic checks ok for {run_root.name}")


def _instance_seed_section_blocks(run_root: Path, instance_id: str) -> list[dict[str, Any]]:
    snapshots_path = run_root / "data" / "ingest" / "source_snapshots.json"
    if not snapshots_path.exists():
        return []
    blob = _load_json(snapshots_path)
    if not isinstance(blob, list):
        return []
    for snapshot in blob:
        if not isinstance(snapshot, dict):
            continue
        if (
            str(snapshot.get("entity_id", "")).strip() == instance_id
            and str(snapshot.get("entity_type", "")).strip() == "instance"
            and not str(snapshot.get("auxiliary_role", "")).strip()
        ):
            blocks = snapshot.get("section_blocks", [])
            if isinstance(blocks, list):
                return [row for row in blocks if isinstance(row, dict)]
    return []


def _check_instance_drafts(run_root: Path) -> None:
    draft_dir = run_root / "data" / "drafts" / "instance_page"
    if not draft_dir.exists():
        return

    from pipeline.contracts.models import INSTANCE_MAX_KEY_CHARACTERS, INSTANCE_MIN_KEY_CHARACTERS
    from pipeline.discovery.instance_bosses import collect_boss_candidates
    from pipeline.generate.draft.faction_lint import lint_faction_summary
    from pipeline.generate.draft.instance_lint import (
        is_generic_at_a_glance,
        is_generic_key_enemy_summary,
        is_generic_overview,
        lint_at_a_glance as lint_instance_at_a_glance,
        lint_key_enemy_summary,
        lint_overview,
    )
    from pipeline.generate.draft.prose_lint import (
        lint_history_sections,
        MAX_HISTORY_SECTIONS,
        MIN_HISTORY_SECTIONS,
    )

    evidence_rows: list[dict[str, Any]] = []
    evidence_path = run_root / "data" / "evidence" / "evidence_packs.jsonl"
    if evidence_path.exists():
        for line in evidence_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if isinstance(row, dict):
                evidence_rows.append(row)

    for draft_path in sorted(draft_dir.glob("instance-*.json")):
        draft = _load_json(draft_path)
        if not isinstance(draft, dict):
            _fail(f"instance draft is not a JSON object: {draft_path}")
        instance_id = draft_path.stem
        instance_name = str(draft.get("name", instance_id)).strip() or instance_id
        parent_zone_id = str(draft.get("parent_zone_id", "")).strip()
        parent_zone_name = instance_name
        if parent_zone_id:
            parent_draft_path = run_root / "data" / "drafts" / "zone_page" / f"{parent_zone_id}.json"
            if parent_draft_path.exists():
                parent_draft = _load_json(parent_draft_path)
                if isinstance(parent_draft, dict):
                    parent_zone_name = str(parent_draft.get("name", parent_zone_id)).strip() or parent_zone_id
        instance_evidence = [
            row for row in evidence_rows if str(row.get("subject_id", "")).strip() == instance_id
        ]
        faction_ids_with_profile: set[str] = set()
        for row in instance_evidence:
            if str(row.get("field_name", "")) != "faction_pool":
                continue
            build_meta = row.get("build_meta") or {}
            faction_id = str(build_meta.get("faction_id", "")).strip()
            if faction_id:
                faction_ids_with_profile.add(faction_id)
        if parent_zone_id:
            targets_path = run_root / "data" / "discovery" / "faction_profile_targets.json"
            if targets_path.exists():
                targets_blob = _load_json(targets_path)
                if isinstance(targets_blob, list):
                    for row in targets_blob:
                        if not isinstance(row, dict):
                            continue
                        if str(row.get("zone_id", "")).strip() != parent_zone_id:
                            continue
                        faction_id = str(row.get("faction_id", "")).strip()
                        if faction_id:
                            faction_ids_with_profile.add(faction_id)

        at_a_glance = str(draft.get("at_a_glance", "")).strip()
        if not at_a_glance:
            _fail(f"instance at_a_glance is empty: {instance_id!r}")
        if is_generic_at_a_glance(at_a_glance):
            _fail(f"instance at_a_glance reads like generic stub: {instance_id!r}")
        for issue in lint_instance_at_a_glance(at_a_glance, instance_name=instance_name):
            _fail(f"instance at_a_glance quality check failed for {instance_id!r}: {issue}")

        overview = str(draft.get("overview", "")).strip()
        if not overview:
            _fail(f"instance overview is empty: {instance_id!r}")
        if is_generic_overview(overview):
            _fail(f"instance overview reads like generic stub: {instance_id!r}")
        for issue in lint_overview(overview, instance_name=instance_name):
            _fail(f"instance overview quality check failed for {instance_id!r}: {issue}")

        history = draft.get("history_sections") or []
        for issue in lint_history_sections(history, max_sections=MAX_HISTORY_SECTIONS):
            _fail(f"instance history_sections quality check failed for {instance_id!r}: {issue}")

        eligible_history_blocks = sum(
            len(row.get("evidence_items", []))
            for row in instance_evidence
            if str(row.get("field_name", "")) == "history_digest"
            and str((row.get("build_meta") or {}).get("source_kind", "")) == "seed"
        )
        if eligible_history_blocks >= MIN_HISTORY_SECTIONS and len(history) < MIN_HISTORY_SECTIONS:
            _fail(
                f"instance history_sections count {len(history)} below minimum {MIN_HISTORY_SECTIONS} "
                f"for {eligible_history_blocks} seed history blocks ({instance_id!r})"
            )

        boss_pool_items = []
        for row in instance_evidence:
            if str(row.get("field_name", "")) != "boss_pool":
                continue
            build_meta = row.get("build_meta") or {}
            for item in row.get("evidence_items", []):
                if not isinstance(item, dict):
                    continue
                boss_pool_items.append(
                    {
                        "snippet": str(item.get("snippet", "")),
                        "section_role": str(item.get("section_role", "boss_pool")),
                        "source_id": str(build_meta.get("source_id", "")),
                    }
                )
        boss_candidates = collect_boss_candidates(
            section_blocks=_instance_seed_section_blocks(run_root, instance_id),
            instance_name=instance_name,
            boss_pool_items=boss_pool_items,
        )

        key_enemies = [row for row in draft.get("key_enemies") or [] if isinstance(row, dict)]
        if len(key_enemies) > INSTANCE_MAX_KEY_CHARACTERS:
            _fail(
                f"instance key_enemies exceeds cap for {instance_id!r} "
                f"({len(key_enemies)} > {INSTANCE_MAX_KEY_CHARACTERS})"
            )
        if len(boss_candidates) >= INSTANCE_MIN_KEY_CHARACTERS and len(key_enemies) < INSTANCE_MIN_KEY_CHARACTERS:
            _fail(
                f"instance key_enemies count {len(key_enemies)} below minimum {INSTANCE_MIN_KEY_CHARACTERS} "
                f"despite {len(boss_candidates)} boss candidates for {instance_id!r}"
            )
        for card in key_enemies:
            summary = str(card.get("summary", "")).strip()
            boss_name = str(card.get("name", "")).strip()
            if is_generic_key_enemy_summary(summary):
                _fail(f"instance key_enemy summary reads like generic stub: {boss_name!r}")
            for issue in lint_key_enemy_summary(
                summary,
                boss_name=boss_name,
                instance_name=instance_name,
            ):
                _fail(f"instance key_enemy quality check failed for {boss_name!r}: {issue}")

        provenance = draft.get("provenance") or {}
        if at_a_glance and not provenance.get("identity_header"):
            _fail(f"instance at_a_glance missing identity_header provenance: {instance_id!r}")
        if overview and not provenance.get("story_context"):
            _fail(f"instance overview missing story_context provenance: {instance_id!r}")
        key_char_provenance = provenance.get("key_characters") or {}
        for card in key_enemies:
            card_id = str(card.get("id", "")).strip()
            if card_id and card_id not in key_char_provenance:
                _fail(f"instance key_enemy missing provenance: {card_id!r}")

        faction_cards = [row for row in draft.get("major_factions") or [] if isinstance(row, dict)]
        faction_provenance = provenance.get("major_factions") or {}
        for card in faction_cards:
            card_id = str(card.get("id", "")).strip()
            summary = str(card.get("summary", "")).strip()
            for issue in lint_faction_summary(summary, zone_name=parent_zone_name):
                _fail(f"instance major_factions quality check failed for {instance_id!r}: {issue}")
            if card_id in faction_ids_with_profile and card_id not in faction_provenance:
                _fail(
                    f"instance major_factions card missing provenance despite profile evidence: {card_id!r}"
                )

        print(f"PASS: instance semantic checks ok for {instance_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Semantic acceptance checks for a pipeline run.")
    parser.add_argument("run_root", type=Path, help="Path to artifacts/runs/<run-id>")
    parser.add_argument(
        "--zone-id",
        default=None,
        help="Zone entity id (e.g. zone-western-plaguelands). Auto-detected when omitted.",
    )
    args = parser.parse_args()
    try:
        check_run(args.run_root, zone_id=args.zone_id)
    except SemanticCheckError as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
