"""Fetch auxiliary wiki pages discovered during the seed pass."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pipeline.common.run_context import RunContext
from pipeline.common.text_normalize import clean_wiki_snippet
from pipeline.discovery.entity_typing import (
    is_bogus_traversal_link,
    is_valid_quest_graph_link,
    should_reject_location_title,
    should_skip_registry_traversal,
)
from pipeline.discovery.quest_hub import resolve_hub_child_links
from pipeline.discovery.quest_lore import build_quest_lore_record
from pipeline.discovery.storyline_parser import _to_entity_id, _wiki_title
from pipeline.ingest.fetch_wiki import (
    _fetch_url_text,
    _validate_manifest_schema,
    build_structured_links_from_sections,
)
from pipeline.ingest.normalize_source import run_normalize_source

_WARCRAFT_WIKI_ORIGIN = "https://warcraft.wiki.gg"
_MAX_STORYLINE = 1
_MAX_QUEST = 25
_MAX_FACTION = 6
_MAX_LOCATION = 8


def _load_json(path: Path) -> Any:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _absolute_wiki_url(link: str) -> str:
    if link.startswith("http://") or link.startswith("https://"):
        return link.split("#", 1)[0]
    if link.startswith("/wiki/"):
        return f"{_WARCRAFT_WIKI_ORIGIN}{link.split('#', 1)[0]}"
    return link


def _source_id_for(role: str, zone_id: str, target_id: str) -> str:
    zone_slug = zone_id.replace("zone-", "")
    target_slug = re.sub(r"[^a-z0-9-]+", "-", target_id.lower()).strip("-")
    return f"src-{zone_slug}-{role}-{target_slug}"[:80]


def _existing_source_ids(snapshots: list[dict[str, Any]]) -> set[str]:
    return {str(row.get("source_id", "")).strip() for row in snapshots if isinstance(row, dict)}


def _existing_urls(snapshots: list[dict[str, Any]]) -> set[str]:
    urls: set[str] = set()
    for row in snapshots:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url", "")).strip().lower()
        if url:
            urls.add(url.split("#", 1)[0])
    return urls


def _zone_seed_snapshot(snapshots: list[dict[str, Any]], zone_id: str) -> dict[str, Any] | None:
    for row in snapshots:
        if not isinstance(row, dict):
            continue
        if str(row.get("entity_id", "")) == zone_id and str(row.get("entity_type", "")) == "zone":
            if not str(row.get("auxiliary_role", "")).strip():
                return row
    return None


def _build_manifest_row(
    *,
    zone_snapshot: dict[str, Any],
    source_id: str,
    source_url: str,
    auxiliary_role: str,
    auxiliary_target_id: str,
    traversal_origin: str,
    page_title: str,
    priority: int = 5,
    cluster_id: str = "",
    quest_node_id: str = "",
) -> dict[str, Any]:
    row = {
        "entity_id": str(zone_snapshot.get("entity_id", "")),
        "entity_type": "zone",
        "slug": str(zone_snapshot.get("slug", "")),
        "name": str(zone_snapshot.get("name", "")),
        "source_id": source_id,
        "source_url": source_url,
        "url": source_url,
        "source_class": "warcraft_wiki",
        "priority": priority,
        "selection_version": str(zone_snapshot.get("selection_version", "traversal-v1")),
        "policy_version": str(zone_snapshot.get("policy_version", "wiki-first-v1")),
        "manifest_run_id": str(zone_snapshot.get("manifest_run_id", "unknown")),
        "parent_zone_id": str(zone_snapshot.get("entity_id", "")),
        "auxiliary_role": auxiliary_role,
        "auxiliary_target_id": auxiliary_target_id,
        "traversal_origin": traversal_origin,
        "page_title": page_title,
    }
    if cluster_id:
        row["cluster_id"] = cluster_id
    if quest_node_id:
        row["quest_node_id"] = quest_node_id
    return row


def _snapshot_from_fetch(
    *,
    manifest_row: dict[str, Any],
    body: str,
    revision_id: str,
    locator: str,
    section_blocks: list[dict[str, str]],
    wiki_links: list[str],
    structured_links: list[dict[str, str]],
    captured_at: str,
    parse_html: str = "",
    parse_html_truncated: bool = False,
    quest_lore_blocks: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    cleaned_blocks: list[dict[str, str]] = []
    for block in section_blocks:
        cleaned_blocks.append(
            {
                "section_role": str(block.get("section_role", "other")),
                "text": clean_wiki_snippet(str(block.get("text", ""))),
            }
        )
    snapshot = {
        "entity_id": manifest_row["entity_id"],
        "entity_type": manifest_row["entity_type"],
        "slug": manifest_row["slug"],
        "name": manifest_row["name"],
        "source_id": manifest_row["source_id"],
        "source_class": manifest_row["source_class"],
        "url": manifest_row["source_url"],
        "revision_id": revision_id,
        "captured_at": captured_at,
        "locator": locator,
        "body": clean_wiki_snippet(body),
        "section_blocks": cleaned_blocks,
        "wiki_links": wiki_links,
        "structured_links": structured_links,
        "retrieval_mode": "traversal",
        "selection_version": manifest_row["selection_version"],
        "policy_version": manifest_row["policy_version"],
        "manifest_run_id": manifest_row["manifest_run_id"],
        "parent_zone_id": manifest_row["parent_zone_id"],
        "requested_revision_id": "",
        "priority": int(manifest_row.get("priority", 5)),
        "auxiliary_role": manifest_row.get("auxiliary_role", ""),
        "auxiliary_target_id": manifest_row.get("auxiliary_target_id", ""),
        "traversal_origin": manifest_row.get("traversal_origin", ""),
        "page_title": manifest_row.get("page_title", manifest_row.get("name", "")),
    }
    if parse_html:
        snapshot["parse_html"] = parse_html
    if parse_html_truncated:
        snapshot["parse_html_truncated"] = True
    if manifest_row.get("cluster_id"):
        snapshot["cluster_id"] = manifest_row["cluster_id"]
    if manifest_row.get("quest_node_id"):
        snapshot["quest_node_id"] = manifest_row["quest_node_id"]
    if quest_lore_blocks:
        snapshot["quest_lore_blocks"] = quest_lore_blocks
    return snapshot


def _find_snapshot_by_url(snapshots: list[dict[str, Any]], url: str) -> dict[str, Any] | None:
    normalized = url.lower().split("#", 1)[0]
    for row in snapshots:
        if str(row.get("url", "")).strip().lower().split("#", 1)[0] == normalized:
            return row
    return None


def _upgrade_storyline_snapshot(
    *,
    existing: dict[str, Any],
    url: str,
    report_rows: list[dict[str, Any]],
    link: str,
) -> dict[str, Any] | None:
    if str(existing.get("auxiliary_role", "")).strip() == "storyline" and str(
        existing.get("parse_html", "")
    ).strip():
        report_rows.append(
            {"status": "skipped", "link": link, "reason": "duplicate_url", "role": "storyline"}
        )
        return existing
    try:
        body, revision_id, locator, section_blocks, wiki_links, structured_from_fetch, raw_html = (
            _fetch_url_text(url, "warcraft_wiki")
        )
    except RuntimeError as exc:
        report_rows.append({"status": "error", "link": link, "reason": repr(exc), "role": "storyline"})
        return None
    existing["auxiliary_role"] = "storyline"
    existing["body"] = clean_wiki_snippet(body)
    existing["revision_id"] = revision_id
    existing["locator"] = locator
    existing["section_blocks"] = [
        {
            "section_role": str(block.get("section_role", "other")),
            "text": clean_wiki_snippet(str(block.get("text", ""))),
        }
        for block in section_blocks
    ]
    existing["wiki_links"] = wiki_links
    existing["structured_links"] = structured_from_fetch or build_structured_links_from_sections(
        section_blocks, wiki_links
    )
    if raw_html:
        existing["parse_html_truncated"] = len(raw_html) > 524288
        existing["parse_html"] = raw_html[:524288]
    report_rows.append({"status": "upgraded", "link": link, "role": "storyline"})
    return existing


def _manifest_instance_titles(manifest_rows: list[dict[str, Any]]) -> frozenset[str]:
    titles: set[str] = set()
    for row in manifest_rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("entity_type", "")).strip() != "instance":
            continue
        name = str(row.get("name", "")).strip()
        if name:
            titles.add(name)
    return frozenset(titles)


def _fetch_and_append(
    *,
    zone_snapshot: dict[str, Any],
    link: str,
    auxiliary_role: str,
    auxiliary_target_id: str,
    traversal_origin: str,
    page_title: str,
    snapshots: list[dict[str, Any]],
    manifest_rows: list[dict[str, Any]],
    existing_source_ids: set[str],
    existing_urls: set[str],
    captured_at: str,
    report_rows: list[dict[str, Any]],
    allowed_instance_titles: frozenset[str] | None = None,
    cluster_id: str = "",
    quest_node_id: str = "",
    hub_resolved_from: str = "",
    source_section_role: str = "other",
) -> dict[str, Any] | None:
    if is_bogus_traversal_link(link):
        report_rows.append({"status": "skipped", "link": link, "reason": "bogus_link", "role": auxiliary_role})
        return None
    zone_name = str(zone_snapshot.get("name", ""))
    skip, skip_reasons = should_skip_registry_traversal(
        link,
        auxiliary_role=auxiliary_role,
        zone_name=zone_name,
        allowed_instance_titles=allowed_instance_titles,
    )
    if skip:
        report_rows.append(
            {
                "status": "skipped",
                "link": link,
                "reason": skip_reasons[0] if skip_reasons else "registry_block",
                "role": auxiliary_role,
            }
        )
        return None
    if auxiliary_role == "location_profile":
        title = page_title.strip() or _wiki_title(link)
        reject, reject_reasons = should_reject_location_title(
            title,
            zone_name=zone_name,
            source_section_role=source_section_role,
        )
        if reject:
            report_rows.append(
                {
                    "status": "skipped",
                    "link": link,
                    "reason": reject_reasons[0] if reject_reasons else "location_reject",
                    "role": auxiliary_role,
                }
            )
            return None
    if auxiliary_role == "quest":
        valid, reasons = is_valid_quest_graph_link(link, zone_name=zone_name)
        if not valid:
            report_rows.append(
                {
                    "status": "skipped",
                    "link": link,
                    "reason": reasons[0] if reasons else "invalid_quest_link",
                    "role": auxiliary_role,
                }
            )
            return None
    url = _absolute_wiki_url(link)
    if url.lower() in existing_urls:
        if auxiliary_role == "storyline":
            existing = _find_snapshot_by_url(snapshots, url)
            if existing is not None:
                return _upgrade_storyline_snapshot(
                    existing=existing,
                    url=url,
                    report_rows=report_rows,
                    link=link,
                )
        report_rows.append({"status": "skipped", "link": link, "reason": "duplicate_url", "role": auxiliary_role})
        return None
    source_id = _source_id_for(auxiliary_role, str(zone_snapshot.get("entity_id", "")), auxiliary_target_id)
    if source_id in existing_source_ids:
        suffix = 2
        while f"{source_id}-{suffix}" in existing_source_ids:
            suffix += 1
        source_id = f"{source_id}-{suffix}"
    manifest_row = _build_manifest_row(
        zone_snapshot=zone_snapshot,
        source_id=source_id,
        source_url=url,
        auxiliary_role=auxiliary_role,
        auxiliary_target_id=auxiliary_target_id,
        traversal_origin=traversal_origin,
        page_title=page_title,
        cluster_id=cluster_id,
        quest_node_id=quest_node_id,
    )
    try:
        body, revision_id, locator, section_blocks, wiki_links, structured_from_fetch, raw_html = _fetch_url_text(
            url, "warcraft_wiki"
        )
    except RuntimeError as exc:
        report_rows.append({"status": "error", "link": link, "reason": repr(exc), "role": auxiliary_role})
        return None
    parse_html = ""
    parse_html_truncated = False
    if auxiliary_role == "storyline" and raw_html:
        parse_html_truncated = len(raw_html) > 524288
        parse_html = raw_html[:524288]
    structured_links = structured_from_fetch or build_structured_links_from_sections(section_blocks, wiki_links)
    quest_lore_blocks: list[dict[str, str]] | None = None
    if auxiliary_role == "quest":
        lore_record = build_quest_lore_record(
            zone_id=str(zone_snapshot.get("entity_id", "")),
            cluster_id=cluster_id,
            node_id=quest_node_id or auxiliary_target_id,
            quest_title=page_title,
            source_link=link,
            section_blocks=section_blocks,
        )
        quest_lore_blocks = lore_record.get("snippets", [])
    snapshot = _snapshot_from_fetch(
        manifest_row=manifest_row,
        body=body,
        revision_id=revision_id,
        locator=locator,
        section_blocks=section_blocks,
        wiki_links=wiki_links,
        structured_links=structured_links,
        captured_at=captured_at,
        parse_html=parse_html,
        parse_html_truncated=parse_html_truncated,
        quest_lore_blocks=quest_lore_blocks if isinstance(quest_lore_blocks, list) else None,
    )
    snapshots.append(snapshot)
    manifest_rows.append(manifest_row)
    existing_source_ids.add(source_id)
    existing_urls.add(url.lower())
    entry: dict[str, Any] = {
        "status": "fetched",
        "link": link,
        "source_id": source_id,
        "role": auxiliary_role,
        "traversal_origin": traversal_origin,
    }
    if hub_resolved_from:
        entry["hub_resolved_from"] = hub_resolved_from
    report_rows.append(entry)
    return snapshot


def _load_traverse_state(context: RunContext) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    set[str],
    set[str],
    list[dict[str, Any]],
    frozenset[str],
]:
    ingest_dir = context.stage_dir("ingest")
    snapshots_path = ingest_dir / "source_snapshots.json"
    manifest_path = ingest_dir / "source_manifest.json"
    if not snapshots_path.exists() or not manifest_path.exists():
        raise RuntimeError("traverse requires ingest snapshots and source_manifest.json")
    snapshots_blob = _load_json(snapshots_path)
    manifest_blob = _load_json(manifest_path)
    if not isinstance(snapshots_blob, list) or not isinstance(manifest_blob, list):
        raise RuntimeError("ingest artifacts must be JSON arrays")
    snapshots: list[dict[str, Any]] = [row for row in snapshots_blob if isinstance(row, dict)]
    manifest_rows: list[dict[str, Any]] = [row for row in manifest_blob if isinstance(row, dict)]
    report_path = context.data_dir / "ingest" / "traversal_report.json"
    report_rows: list[dict[str, Any]] = []
    if report_path.exists():
        blob = _load_json(report_path)
        if isinstance(blob, dict) and isinstance(blob.get("entries"), list):
            report_rows = [row for row in blob["entries"] if isinstance(row, dict)]
    return (
        snapshots,
        manifest_rows,
        _existing_source_ids(snapshots),
        _existing_urls(snapshots),
        report_rows,
        _manifest_instance_titles(manifest_rows),
    )


def _persist_traverse_state(
    context: RunContext,
    *,
    snapshots: list[dict[str, Any]],
    manifest_rows: list[dict[str, Any]],
    report_rows: list[dict[str, Any]],
) -> dict[str, Path]:
    ingest_dir = context.stage_dir("ingest")
    snapshots_path = ingest_dir / "source_snapshots.json"
    manifest_path = ingest_dir / "source_manifest.json"
    snapshots_path.write_text(json.dumps(snapshots, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest_rows, indent=2), encoding="utf-8")
    _validate_manifest_schema(manifest_rows)
    run_normalize_source(context, snapshots_path)
    report_path = context.data_dir / "ingest" / "traversal_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps({"run_id": context.run_id, "entries": report_rows}, indent=2),
        encoding="utf-8",
    )
    return {"traversal_report": report_path, "source_snapshots": snapshots_path, "source_manifest": manifest_path}


def _ordered_v3_quest_nodes(v3_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    quests = [row for row in v3_rows if isinstance(row, dict) and row.get("node_type") == "quest"]
    quests.sort(
        key=lambda row: (
            str(row.get("zone_id", "")),
            int(row.get("cluster_order", 0) or 0),
            int(row.get("order_in_cluster", 0) or 0),
        )
    )
    seen_links: set[str] = set()
    ordered: list[dict[str, Any]] = []
    for row in quests:
        link = str(row.get("source_link", "")).strip()
        if not link or link in seen_links:
            continue
        seen_links.add(link)
        ordered.append(row)
    return ordered


def run_traverse_seed(context: RunContext) -> dict[str, Path]:
    """Fetch storyline, faction, and location auxiliary pages (no quest pages)."""
    snapshots, manifest_rows, existing_source_ids, existing_urls, report_rows, allowed_instance_titles = (
        _load_traverse_state(context)
    )
    captured_at = datetime.now(UTC).isoformat()
    discovery_dir = context.data_dir / "discovery"
    faction_targets = _load_json(discovery_dir / "faction_profile_targets.json")
    location_targets = _load_json(discovery_dir / "location_profile_targets.json")
    storyline_targets = _load_json(discovery_dir / "storyline_traversal_targets.json")
    location_decisions = _load_json(context.data_dir / "decisions" / "location_significance_decisions.json")

    decision_by_location: dict[str, str] = {}
    if isinstance(location_decisions, list):
        for row in location_decisions:
            if isinstance(row, dict):
                decision_by_location[str(row.get("subject_id", ""))] = str(row.get("final_decision", ""))

    counts_by_zone_role: dict[tuple[str, str], int] = {}

    def _within_cap(zone_id: str, role: str, cap: int) -> bool:
        return counts_by_zone_role.get((zone_id, role), 0) < cap

    def _increment(zone_id: str, role: str) -> None:
        key = (zone_id, role)
        counts_by_zone_role[key] = counts_by_zone_role.get(key, 0) + 1

    if isinstance(storyline_targets, list):
        seen_storyline_by_zone: set[str] = set()
        for target in storyline_targets:
            if not isinstance(target, dict):
                continue
            zone_id = str(target.get("zone_id", "")).strip()
            link = str(target.get("source_link", "")).strip()
            title = str(target.get("title", "")).strip()
            if not zone_id or not link or zone_id in seen_storyline_by_zone:
                continue
            if not _within_cap(zone_id, "storyline", _MAX_STORYLINE):
                continue
            zone_snap = _zone_seed_snapshot(snapshots, zone_id)
            if zone_snap is None:
                continue
            preferred = link
            if "_storyline" not in link.lower():
                zone_name = str(zone_snap.get("name", ""))
                preferred = f"/wiki/{zone_name.replace(' ', '_')}_storyline"
            snapshot = _fetch_and_append(
                zone_snapshot=zone_snap,
                link=preferred,
                auxiliary_role="storyline",
                auxiliary_target_id=str(target.get("storyline_id", _to_entity_id("storyline", title))),
                traversal_origin="storyline_traversal_targets",
                page_title=title or _wiki_title(preferred),
                snapshots=snapshots,
                manifest_rows=manifest_rows,
                existing_source_ids=existing_source_ids,
                existing_urls=existing_urls,
                captured_at=captured_at,
                report_rows=report_rows,
                allowed_instance_titles=allowed_instance_titles,
            )
            if snapshot is None:
                continue
            seen_storyline_by_zone.add(zone_id)
            _increment(zone_id, "storyline")

    if isinstance(faction_targets, list):
        seen_faction: set[tuple[str, str]] = set()
        for target in faction_targets:
            if not isinstance(target, dict):
                continue
            zone_id = str(target.get("zone_id", "")).strip()
            link = str(target.get("source_link", "")).strip()
            faction_id = str(target.get("faction_id", "")).strip()
            key = (zone_id, faction_id)
            if not zone_id or not link or key in seen_faction:
                continue
            if not _within_cap(zone_id, "faction_profile", _MAX_FACTION):
                continue
            zone_snap = _zone_seed_snapshot(snapshots, zone_id)
            if zone_snap is None:
                continue
            if _fetch_and_append(
                zone_snapshot=zone_snap,
                link=link,
                auxiliary_role="faction_profile",
                auxiliary_target_id=faction_id,
                traversal_origin="faction_profile_targets",
                page_title=str(target.get("name", "")),
                snapshots=snapshots,
                manifest_rows=manifest_rows,
                existing_source_ids=existing_source_ids,
                existing_urls=existing_urls,
                captured_at=captured_at,
                report_rows=report_rows,
                allowed_instance_titles=allowed_instance_titles,
            ):
                seen_faction.add(key)
                _increment(zone_id, "faction_profile")

    if isinstance(location_targets, list):
        seen_location: set[tuple[str, str]] = set()
        for target in location_targets:
            if not isinstance(target, dict):
                continue
            zone_id = str(target.get("zone_id", "")).strip()
            link = str(target.get("source_link", "")).strip()
            location_id = str(target.get("location_id", "")).strip()
            decision = decision_by_location.get(location_id, "defer")
            if decision != "include":
                continue
            key = (zone_id, location_id)
            if not zone_id or not link or key in seen_location:
                continue
            if not _within_cap(zone_id, "location_profile", _MAX_LOCATION):
                continue
            zone_snap = _zone_seed_snapshot(snapshots, zone_id)
            if zone_snap is None:
                continue
            if _fetch_and_append(
                zone_snapshot=zone_snap,
                link=link,
                auxiliary_role="location_profile",
                auxiliary_target_id=location_id,
                traversal_origin="location_profile_targets",
                page_title=str(target.get("name", "")),
                source_section_role=str(target.get("source_section_role", "other")),
                snapshots=snapshots,
                manifest_rows=manifest_rows,
                existing_source_ids=existing_source_ids,
                existing_urls=existing_urls,
                captured_at=captured_at,
                report_rows=report_rows,
                allowed_instance_titles=allowed_instance_titles,
            ):
                seen_location.add(key)
                _increment(zone_id, "location_profile")

    return _persist_traverse_state(
        context,
        snapshots=snapshots,
        manifest_rows=manifest_rows,
        report_rows=report_rows,
    )


def run_traverse_quests(context: RunContext) -> dict[str, Path]:
    """Fetch quest pages listed in zone_quest_graph_v3.json, with optional hub resolution."""
    snapshots, manifest_rows, existing_source_ids, existing_urls, report_rows, allowed_instance_titles = (
        _load_traverse_state(context)
    )
    captured_at = datetime.now(UTC).isoformat()
    v3_path = context.data_dir / "discovery" / "zone_quest_graph_v3.json"
    v3_blob = _load_json(v3_path)
    if not isinstance(v3_blob, list):
        raise RuntimeError("zone_quest_graph_v3.json must exist and be a JSON array before quest traverse")

    counts_by_zone_role: dict[tuple[str, str], int] = {}

    def _within_cap(zone_id: str, role: str, cap: int) -> bool:
        return counts_by_zone_role.get((zone_id, role), 0) < cap

    def _increment(zone_id: str, role: str) -> None:
        key = (zone_id, role)
        counts_by_zone_role[key] = counts_by_zone_role.get(key, 0) + 1

    for node in _ordered_v3_quest_nodes(v3_blob):
        zone_id = str(node.get("zone_id", "")).strip()
        quest_link = str(node.get("source_link", "")).strip()
        if not zone_id or not quest_link:
            continue
        if not _within_cap(zone_id, "quest", _MAX_QUEST):
            continue
        zone_snap = _zone_seed_snapshot(snapshots, zone_id)
        if zone_snap is None:
            continue
        zone_name = str(zone_snap.get("name", zone_id))
        snapshot = _fetch_and_append(
            zone_snapshot=zone_snap,
            link=quest_link,
            auxiliary_role="quest",
            auxiliary_target_id=str(node.get("node_id", "")),
            traversal_origin="v3_graph",
            page_title=str(node.get("title", "")),
            snapshots=snapshots,
            manifest_rows=manifest_rows,
            existing_source_ids=existing_source_ids,
            existing_urls=existing_urls,
            captured_at=captured_at,
            report_rows=report_rows,
            allowed_instance_titles=allowed_instance_titles,
            cluster_id=str(node.get("cluster_id", "")),
            quest_node_id=str(node.get("node_id", "")),
        )
        if snapshot is None:
            continue
        _increment(zone_id, "quest")
        child_links = resolve_hub_child_links(
            snapshot.get("section_blocks", []),
            parse_html=str(snapshot.get("parse_html", "")),
            wiki_links=list(snapshot.get("wiki_links", []) or []),
            structured_links=list(snapshot.get("structured_links", []) or []),
            zone_name=zone_name,
        )
        for child_link in child_links:
            if not _within_cap(zone_id, "quest", _MAX_QUEST):
                break
            child_snapshot = _fetch_and_append(
                zone_snapshot=zone_snap,
                link=child_link,
                auxiliary_role="quest",
                auxiliary_target_id=_to_entity_id("quest", _wiki_title(child_link)),
                traversal_origin="hub_resolved",
                page_title=_wiki_title(child_link),
                snapshots=snapshots,
                manifest_rows=manifest_rows,
                existing_source_ids=existing_source_ids,
                existing_urls=existing_urls,
                captured_at=captured_at,
                report_rows=report_rows,
                allowed_instance_titles=allowed_instance_titles,
                cluster_id=str(node.get("cluster_id", "")),
                quest_node_id=_to_entity_id("quest", _wiki_title(child_link)),
                hub_resolved_from=quest_link,
            )
            if child_snapshot is not None:
                _increment(zone_id, "quest")

    return _persist_traverse_state(
        context,
        snapshots=snapshots,
        manifest_rows=manifest_rows,
        report_rows=report_rows,
    )


def run_traverse_wiki(context: RunContext) -> dict[str, Path]:
    """Backward-compatible alias: seed traverse only."""
    return run_traverse_seed(context)
