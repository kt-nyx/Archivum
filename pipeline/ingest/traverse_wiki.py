"""Fetch auxiliary wiki pages discovered during the seed pass."""

from __future__ import annotations

import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pipeline.common import wiki_html
from pipeline.common.io import write_json
from pipeline.common.retail import is_classic_categorized, is_non_retail_title
from pipeline.common.run_context import RunContext
from pipeline.common.text_normalize import clean_wiki_snippet
from pipeline.common.wiki_category_registry import classify_page_categories
from pipeline.contracts.models import QuestRecord
from pipeline.discovery.entity_typing import (
    is_bogus_traversal_link,
    is_valid_quest_graph_link,
    normalize_title,
    should_reject_location_title,
    should_skip_registry_traversal,
)
from pipeline.discovery.instance_bosses import (
    collect_character_pool,
    prefilter_character_pool,
)
from pipeline.discovery.lore_sources import (
    classify_lore_retail_eligibility,
    variant_cluster_key,
)
from pipeline.discovery.quest_hub import resolve_hub_child_links
from pipeline.discovery.quest_lore import build_quest_lore_record
from pipeline.discovery.quest_record import build_quest_record
from pipeline.discovery.storyline_parser import _to_entity_id, _wiki_title
from pipeline.discovery.workflow import _MAX_FACTION_PROFILE_TARGETS
from pipeline.ingest.fetch_wiki import (
    _category_lookup_key,
    _fetch_url_text,
    _validate_manifest_schema,
    build_structured_links_from_sections,
    fetch_categories_for_titles,
)
from pipeline.ingest.normalize_source import run_normalize_source
from pipeline.ingest.snapshots import load_source_snapshots

_WARCRAFT_WIKI_ORIGIN = "https://warcraft.wiki.gg"
_MAX_STORYLINE = 1
# Slice A removes the per-zone quest cap (D4: fetch all roster quests with
# throttling). A very high ceiling stays as a runaway guard, overridable via env.
_MAX_QUEST = int(os.environ.get("WOWLORE_MAX_QUESTS_PER_ZONE", "100000"))
# Slice 13: discovery emits a ranked, capped faction-target list; the crawl budget is that
# same cap (one home for N), so no ranked target is silently cut here.
_MAX_FACTION = _MAX_FACTION_PROFILE_TARGETS
_MAX_LOCATION = 8
# Slice D: per-page character-profile crawl cap. Sized to the instance key-character roster
# (INSTANCE_MAX_KEY_CHARACTERS) so every elected key character can pick up biographical evidence.
_MAX_CHARACTER = 8
_MAX_PARENT_LORE = 1
_MAX_RELATED_LORE = 3
# Politeness throttle between quest page fetches (seconds), env-overridable.
_QUEST_FETCH_SLEEP_SECONDS = float(os.environ.get("WOWLORE_QUEST_FETCH_SLEEP", "0.35"))

_LINK_CATEGORY_CACHE_NAME = "link_category_cache.json"
_LINK_NAMESPACE_PREFIXES: tuple[str, ...] = (
    "file:",
    "category:",
    "template:",
    "help:",
    "special:",
    "module:",
    "talk:",
    "user:",
    "portal:",
    "mediawiki:",
    "wikipedia:",
)


def _throttle(seconds: float) -> None:
    """Sleep between quest fetches (indirected so tests can stub it out)."""
    if seconds > 0:
        time.sleep(seconds)


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


def _wiki_path_from_link_or_title(link_or_title: str) -> str:
    """Normalize a ``/wiki/...`` href or bare page title to a wiki path."""
    cleaned = link_or_title.strip()
    if not cleaned:
        return ""
    if cleaned.startswith("http://") or cleaned.startswith("https://"):
        lowered = cleaned.split("#", 1)[0]
        wiki_idx = lowered.find("/wiki/")
        return lowered[wiki_idx:] if wiki_idx >= 0 else ""
    if cleaned.startswith("/wiki/"):
        return cleaned.split("#", 1)[0]
    return f"/wiki/{cleaned.replace(' ', '_')}"


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


def _instance_seed_snapshot(
    snapshots: list[dict[str, Any]], instance_id: str
) -> dict[str, Any] | None:
    for row in snapshots:
        if not isinstance(row, dict):
            continue
        if (
            str(row.get("entity_id", "")) == instance_id
            and str(row.get("entity_type", "")) == "instance"
        ):
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
    entity_type = str(zone_snapshot.get("entity_type", "zone")).strip() or "zone"
    parent_zone_id = str(zone_snapshot.get("parent_zone_id", "")).strip()
    if entity_type != "instance" and not parent_zone_id:
        parent_zone_id = str(zone_snapshot.get("entity_id", ""))
    row = {
        "entity_id": str(zone_snapshot.get("entity_id", "")),
        "entity_type": entity_type,
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
        "parent_zone_id": parent_zone_id,
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


def _persist_section_block(block: dict[str, Any]) -> dict[str, Any]:
    """Serialize a section block for the snapshot, preserving parent nesting.

    ``parent_section_role`` carries the enclosing top-level (H2) heading of a nested
    (H3+) subsection. Downstream, ``_effective_section_slug`` (enrich) falls back to it
    so an unrecognized or era-named subsection ("Cataclysm" under "Biography") inherits
    its parent's narrative/history role instead of collapsing to "other". Dropping it
    here silently disabled that inheritance for every crawled profile page.

    ``links`` (the block's inline article links) is required snapshot schema from
    Slice 12 on and is always emitted, empty when the block has none.
    """
    raw_links = block.get("links")
    persisted: dict[str, Any] = {
        "section_role": str(block.get("section_role", "other")),
        "text": clean_wiki_snippet(str(block.get("text", ""))),
        "links": raw_links if isinstance(raw_links, list) else [],
    }
    parent = str(block.get("parent_section_role", "")).strip()
    if parent:
        persisted["parent_section_role"] = parent
    return persisted


def _snapshot_from_fetch(
    *,
    manifest_row: dict[str, Any],
    body: str,
    revision_id: str,
    locator: str,
    section_blocks: list[dict[str, Any]],
    wiki_links: list[str],
    structured_links: list[dict[str, str]],
    captured_at: str,
    categories: list[str] | None = None,
    infobox: dict[str, str] | None = None,
    parse_html: str = "",
    parse_html_truncated: bool = False,
    quest_lore_blocks: list[dict[str, Any]] | None = None,
    quest_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cleaned_blocks: list[dict[str, Any]] = [
        _persist_section_block(block) for block in section_blocks
    ]
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
        "categories": categories or [],
        "infobox": infobox or {},
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
    if quest_record is not None:
        snapshot["quest_record"] = quest_record
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
    if (
        str(existing.get("auxiliary_role", "")).strip() == "storyline"
        and str(existing.get("parse_html", "")).strip()
    ):
        report_rows.append(
            {"status": "skipped", "link": link, "reason": "duplicate_url", "role": "storyline"}
        )
        return existing
    try:
        fetched = _fetch_url_text(url, "warcraft_wiki")
    except RuntimeError as exc:
        report_rows.append(
            {"status": "error", "link": link, "reason": repr(exc), "role": "storyline"}
        )
        return None
    section_blocks = fetched.section_blocks
    raw_html = fetched.html
    existing["auxiliary_role"] = "storyline"
    existing["body"] = clean_wiki_snippet(fetched.body)
    existing["revision_id"] = fetched.revision_id
    existing["locator"] = fetched.locator
    existing["section_blocks"] = [_persist_section_block(block) for block in section_blocks]
    existing["wiki_links"] = fetched.wiki_links
    existing["structured_links"] = fetched.structured_links or build_structured_links_from_sections(
        section_blocks, fetched.wiki_links
    )
    existing["categories"] = fetched.categories
    existing["infobox"] = wiki_html.parse_infobox(raw_html)
    if raw_html:
        existing["parse_html_truncated"] = len(raw_html) > 524288
        existing["parse_html"] = raw_html[:524288]
    report_rows.append({"status": "upgraded", "link": link, "role": "storyline"})
    return existing


def _drop_snapshot(
    snapshot: dict[str, Any],
    *,
    snapshots: list[dict[str, Any]],
    manifest_rows: list[dict[str, Any]],
    existing_source_ids: set[str],
    existing_urls: set[str],
    report_rows: list[dict[str, Any]],
    reason: str,
    role: str,
) -> None:
    """Undo a just-appended snapshot (e.g. a fetched page that proved Classic-only)."""
    source_id = str(snapshot.get("source_id", "")).strip()
    url = str(snapshot.get("url", "")).strip().lower().split("#", 1)[0]
    if snapshot in snapshots:
        snapshots.remove(snapshot)
    manifest_rows[:] = [
        row for row in manifest_rows if str(row.get("source_id", "")).strip() != source_id
    ]
    existing_source_ids.discard(source_id)
    existing_urls.discard(url)
    report_rows.append({"status": "skipped", "link": url, "reason": reason, "role": role})


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
    faction_binding: str = "shared",
) -> dict[str, Any] | None:
    if is_bogus_traversal_link(link):
        report_rows.append(
            {"status": "skipped", "link": link, "reason": "bogus_link", "role": auxiliary_role}
        )
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
        report_rows.append(
            {"status": "skipped", "link": link, "reason": "duplicate_url", "role": auxiliary_role}
        )
        return None
    source_id = _source_id_for(
        auxiliary_role, str(zone_snapshot.get("entity_id", "")), auxiliary_target_id
    )
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
    include_parsetree = auxiliary_role == "quest"
    try:
        fetched = _fetch_url_text(url, "warcraft_wiki", include_parsetree=include_parsetree)
    except RuntimeError as exc:
        report_rows.append(
            {"status": "error", "link": link, "reason": repr(exc), "role": auxiliary_role}
        )
        return None
    body = fetched.body
    revision_id = fetched.revision_id
    locator = fetched.locator
    section_blocks = fetched.section_blocks
    wiki_links = fetched.wiki_links
    structured_from_fetch = fetched.structured_links
    raw_html = fetched.html
    parse_tree = fetched.parse_tree
    parse_html = ""
    parse_html_truncated = False
    if auxiliary_role == "storyline" and raw_html:
        parse_html_truncated = len(raw_html) > 524288
        parse_html = raw_html[:524288]
    structured_links = structured_from_fetch or build_structured_links_from_sections(
        section_blocks, wiki_links
    )
    quest_lore_blocks: list[dict[str, Any]] | None = None
    quest_record: dict[str, Any] | None = None
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
        quest_record = build_quest_record(
            zone_id=str(zone_snapshot.get("entity_id", "")),
            node_id=quest_node_id or auxiliary_target_id,
            quest_title=page_title,
            source_link=link,
            parse_tree=parse_tree,
            section_blocks=section_blocks,
            faction_binding=faction_binding,
        )
    snapshot = _snapshot_from_fetch(
        manifest_row=manifest_row,
        body=body,
        revision_id=revision_id,
        locator=locator,
        section_blocks=section_blocks,
        wiki_links=wiki_links,
        structured_links=structured_links,
        captured_at=captured_at,
        categories=fetched.categories,
        infobox=wiki_html.parse_infobox(raw_html),
        parse_html=parse_html,
        parse_html_truncated=parse_html_truncated,
        quest_lore_blocks=quest_lore_blocks if isinstance(quest_lore_blocks, list) else None,
        quest_record=quest_record,
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


def _load_traverse_state(
    context: RunContext,
) -> tuple[
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
    snapshots: list[dict[str, Any]] = load_source_snapshots(snapshots_path)
    manifest_blob = _load_json(manifest_path)
    if not isinstance(manifest_blob, list):
        raise RuntimeError("ingest artifacts must be JSON arrays")
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
    quest_records: list[dict[str, Any]] | None = None,
    link_category_cache: dict[str, Any] | None = None,
) -> dict[str, Path]:
    ingest_dir = context.stage_dir("ingest")
    snapshots_path = ingest_dir / "source_snapshots.json"
    manifest_path = ingest_dir / "source_manifest.json"
    write_json(snapshots_path, snapshots)
    write_json(manifest_path, manifest_rows)
    _validate_manifest_schema(manifest_rows)
    run_normalize_source(context, snapshots_path)
    report_path = context.data_dir / "ingest" / "traversal_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(report_path, {"run_id": context.run_id, "entries": report_rows})
    outputs = {
        "traversal_report": report_path,
        "source_snapshots": snapshots_path,
        "source_manifest": manifest_path,
    }
    if link_category_cache is not None:
        link_category_cache_path = ingest_dir / _LINK_CATEGORY_CACHE_NAME
        write_json(link_category_cache_path, link_category_cache, sort_keys=True)
        outputs["link_category_cache"] = link_category_cache_path
    if quest_records is not None:
        discovery_dir = context.data_dir / "discovery"
        discovery_dir.mkdir(parents=True, exist_ok=True)
        quest_records_path = discovery_dir / "quest_records.jsonl"
        validated: list[dict[str, Any]] = []
        for row in quest_records:
            validated.append(QuestRecord.model_validate(row).model_dump(mode="json"))
        quest_records_path.write_text(
            ("\n".join(json.dumps(row) for row in validated) + "\n") if validated else "",
            encoding="utf-8",
        )
        outputs["quest_records"] = quest_records_path
    return outputs


def _title_from_wiki_url(url: str) -> str:
    """Return the spaced page title from a ``/wiki/Title`` url/href ('' when none)."""
    value = str(url or "").strip()
    if "/wiki/" not in value:
        return ""
    path = value.split("/wiki/", 1)[-1].split("#", 1)[0].strip().strip("/")
    return path.replace("_", " ").strip()


def _instance_seed_snapshots(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        snap
        for snap in snapshots
        if isinstance(snap, dict)
        and str(snap.get("entity_type", "")).strip() == "instance"
        and not str(snap.get("auxiliary_role", "")).strip()
    ]


def _instance_character_candidates(snapshot: dict[str, Any]) -> list[tuple[str, str]]:
    """Mine ``(normalized_name, page_title)`` character candidates from an instance page."""
    blocks = snapshot.get("section_blocks") or []
    if not isinstance(blocks, list):
        blocks = []
    structured = snapshot.get("structured_links") or []
    if not isinstance(structured, list):
        structured = []
    instance_name = str(snapshot.get("name", ""))
    pool = prefilter_character_pool(
        collect_character_pool(
            section_blocks=blocks,
            instance_name=instance_name,
            structured_links=structured,
        ),
        instance_name=instance_name,
    )
    candidates: list[tuple[str, str]] = []
    for candidate in pool:
        title = _title_from_wiki_url(candidate.wiki_url)
        if title:
            candidates.append((normalize_title(candidate.name), title))
    return candidates


def _exclude_classic_instance_characters(
    snapshots: list[dict[str, Any]],
    report_rows: list[dict[str, Any]],
) -> None:
    """S3 authoritative pass: tag each instance's Classic-categorized cast candidates.

    Mines every instance seed page's character candidates, batch-fetches their wiki
    categories, and records the Classic/legacy/removed ones on the snapshot as
    ``classic_excluded_characters`` so the offline draft stage can drop them from the
    cast. Network failures degrade to no exclusions (best-effort).
    """
    instances = _instance_seed_snapshots(snapshots)
    if not instances:
        return
    per_instance: dict[int, list[tuple[str, str]]] = {}
    title_by_key: dict[str, str] = {}
    for snap in instances:
        candidates = _instance_character_candidates(snap)
        per_instance[id(snap)] = candidates
        for _norm, title in candidates:
            title_by_key[_category_lookup_key(title)] = title
    if not title_by_key:
        return
    try:
        categories = fetch_categories_for_titles(sorted(title_by_key.values()))
    except Exception as exc:  # noqa: BLE001 - best-effort network category check
        report_rows.append(
            {
                "status": "skipped",
                "link": "<classic-category-check>",
                "reason": f"category_fetch_failed:{exc!r}",
                "role": "classic_filter",
            }
        )
        return
    for snap in instances:
        excluded = sorted(
            {
                norm
                for norm, title in per_instance[id(snap)]
                if is_classic_categorized(categories.get(_category_lookup_key(title), []))
            }
        )
        if excluded:
            snap["classic_excluded_characters"] = excluded
            report_rows.append(
                {
                    "status": "excluded_classic",
                    "link": str(snap.get("url", "")),
                    "reason": "classic_category",
                    "role": "classic_filter",
                    "names": excluded,
                }
            )


def _link_category_cache_path(context: RunContext) -> Path:
    return context.data_dir / "ingest" / _LINK_CATEGORY_CACHE_NAME


def _load_existing_link_category_cache(context: RunContext) -> dict[str, Any]:
    path = _link_category_cache_path(context)
    if not path.exists():
        return {"run_id": context.run_id, "entries": {}}
    blob = _load_json(path)
    if isinstance(blob, dict):
        return blob
    return {"run_id": context.run_id, "entries": {}}


def _add_unique_text(values: list[str], value: str) -> None:
    cleaned = value.strip()
    if cleaned and cleaned not in values:
        values.append(cleaned)


def _is_link_category_candidate(href: str, label: str) -> bool:
    if not href or not label:
        return False
    title = _wiki_title(href)
    if not title:
        return False
    lowered_title = title.casefold()
    lowered_label = label.casefold()
    if lowered_title.startswith(_LINK_NAMESPACE_PREFIXES) or lowered_label.startswith(
        _LINK_NAMESPACE_PREFIXES
    ):
        return False
    if is_non_retail_title(title) or is_non_retail_title(label):
        return False
    return "/wiki/" in href or not href.startswith(("http://", "https://"))


def _seed_link_category_targets(snapshots: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    targets: dict[str, dict[str, Any]] = {}
    for snapshot in snapshots:
        if str(snapshot.get("auxiliary_role", "")).strip():
            continue
        if str(snapshot.get("entity_type", "")).strip().lower() not in {"zone", "instance"}:
            continue
        links = snapshot.get("structured_links")
        if not isinstance(links, list):
            continue
        for link in links:
            if not isinstance(link, dict):
                continue
            section_role = str(link.get("section_role", "")).strip().lower()
            parent_role = str(link.get("parent_section_role", "")).strip().lower()
            if section_role.startswith("in_the_rpg") or parent_role.startswith("in_the_rpg"):
                continue
            href = str(link.get("canonical_path") or link.get("href") or "").strip()
            label = str(link.get("label", "")).strip()
            if not _is_link_category_candidate(href, label):
                continue
            title = _wiki_title(href)
            key = _category_lookup_key(title)
            target = targets.setdefault(key, {"title": title, "labels": [], "hrefs": []})
            _add_unique_text(target["labels"], label)
            _add_unique_text(target["hrefs"], href)
    return targets


def _entry_list(entry: dict[str, Any], key: str) -> list[str]:
    raw = entry.get(key)
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _entry_parent_map(entry: dict[str, Any]) -> dict[str, list[str]]:
    raw = entry.get("category_parents")
    if not isinstance(raw, dict):
        return {}
    parents: dict[str, list[str]] = {}
    for category, values in raw.items():
        if isinstance(values, list):
            cleaned = [str(value).strip() for value in values if str(value).strip()]
            parents[str(category)] = cleaned
    return parents


def _fetch_category_map(
    titles: list[str],
    *,
    report_rows: list[dict[str, Any]],
    role: str,
) -> dict[str, list[str]]:
    if not titles:
        return {}
    try:
        return fetch_categories_for_titles(titles, retries=1)
    except Exception as exc:  # noqa: BLE001 - best-effort category enrichment
        report_rows.append(
            {
                "status": "skipped",
                "link": f"<{role}>",
                "reason": f"category_fetch_failed:{exc!r}",
                "role": "link_category_cache",
            }
        )
        return {}


def _build_link_category_cache(
    context: RunContext,
    snapshots: list[dict[str, Any]],
    report_rows: list[dict[str, Any]],
    captured_at: str,
) -> dict[str, Any]:
    targets = _seed_link_category_targets(snapshots)
    existing = _load_existing_link_category_cache(context)
    raw_existing_entries = existing.get("entries")
    existing_entries: dict[str, Any] = (
        raw_existing_entries if isinstance(raw_existing_entries, dict) else {}
    )

    categories_by_key: dict[str, list[str]] = {}
    missing_titles: list[str] = []
    for key, target in targets.items():
        existing_entry = existing_entries.get(key)
        if isinstance(existing_entry, dict):
            categories_by_key[key] = _entry_list(existing_entry, "categories")
        if key not in categories_by_key:
            missing_titles.append(str(target.get("title", "")))

    fetched_categories = _fetch_category_map(
        sorted(title for title in missing_titles if title),
        report_rows=report_rows,
        role="link-category-cache",
    )
    for title in missing_titles:
        key = _category_lookup_key(title)
        categories_by_key[key] = fetched_categories.get(key, [])

    parent_map_by_category: dict[str, list[str]] = {}
    for key in targets:
        existing_entry = existing_entries.get(key)
        if isinstance(existing_entry, dict):
            for category, parents in _entry_parent_map(existing_entry).items():
                parent_map_by_category[_category_lookup_key(category)] = parents

    all_categories = sorted(
        {
            category
            for categories in categories_by_key.values()
            for category in categories
            if category.strip()
        }
    )
    missing_parent_titles = [
        f"Category:{category}"
        for category in all_categories
        if _category_lookup_key(category) not in parent_map_by_category
    ]
    fetched_parents = _fetch_category_map(
        missing_parent_titles,
        report_rows=report_rows,
        role="link-category-parent-cache",
    )
    for category in all_categories:
        category_key = _category_lookup_key(category)
        parent_title = f"Category:{category}"
        parent_map_by_category.setdefault(
            category_key,
            fetched_parents.get(_category_lookup_key(parent_title), []),
        )

    entries: dict[str, Any] = {}
    for key, target in sorted(targets.items()):
        categories = categories_by_key.get(key, [])
        category_parents = {
            category: parent_map_by_category.get(_category_lookup_key(category), [])
            for category in categories
        }
        signal = classify_page_categories(categories, category_parents)
        entries[key] = {
            "title": str(target.get("title", "")),
            "labels": sorted(_entry_list(target, "labels")),
            "hrefs": sorted(_entry_list(target, "hrefs")),
            "categories": categories,
            "category_parents": category_parents,
            "signal": signal.to_dict(),
        }

    return {
        "run_id": context.run_id,
        "generated_at": captured_at,
        "source": "seed_structured_links",
        "entries": entries,
    }


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
    (
        snapshots,
        manifest_rows,
        existing_source_ids,
        existing_urls,
        report_rows,
        allowed_instance_titles,
    ) = _load_traverse_state(context)
    captured_at = datetime.now(UTC).isoformat()
    discovery_dir = context.data_dir / "discovery"
    faction_targets = _load_json(discovery_dir / "faction_profile_targets.json")
    location_targets = _load_json(discovery_dir / "location_profile_targets.json")
    character_targets = _load_json(discovery_dir / "character_profile_targets.json")
    storyline_targets = _load_json(discovery_dir / "storyline_traversal_targets.json")
    location_decisions = _load_json(
        context.data_dir / "decisions" / "location_significance_decisions.json"
    )

    decision_by_location: dict[str, str] = {}
    if isinstance(location_decisions, list):
        for row in location_decisions:
            if isinstance(row, dict):
                decision_by_location[str(row.get("subject_id", ""))] = str(
                    row.get("final_decision", "")
                )

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
                auxiliary_target_id=str(
                    target.get("storyline_id", _to_entity_id("storyline", title))
                ),
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
        # The per-zone traversal budget (_MAX_LOCATION) is small, so order matters: visit the
        # lore-significant marquee landmarks (Hearthglen, Uther's Tomb, ...) before alphabetically
        # earlier farms/outposts, otherwise the budget is spent on trivia and the landmarks never get
        # a page snapshot (no categories to type them, no evidence pool to build their card).
        _location_role_rank = {"history": 3, "notable_characters": 3, "maps_subregions": 2}

        def _location_traverse_priority(target: dict[str, Any]) -> tuple[int, int, str]:
            lore_first = 0 if bool(target.get("lore_significant")) else 1
            role_rank = -_location_role_rank.get(
                str(target.get("source_section_role", "")).strip(), 1
            )
            return (lore_first, role_rank, str(target.get("name", "")).lower())

        location_targets = sorted(
            (target for target in location_targets if isinstance(target, dict)),
            key=_location_traverse_priority,
        )
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

    if isinstance(character_targets, list):
        seen_character: set[tuple[str, str]] = set()
        for target in character_targets:
            if not isinstance(target, dict):
                continue
            page_id = str(target.get("zone_id", "")).strip()
            link = str(target.get("source_link", "")).strip()
            character_id = str(target.get("character_id", "")).strip()
            key = (page_id, character_id)
            if not page_id or not link or character_id == "" or key in seen_character:
                continue
            if not _within_cap(page_id, "character_profile", _MAX_CHARACTER):
                continue
            # A character can be rostered on the zone page or an instance page; resolve whichever
            # seed snapshot it was linked from so provenance attaches to the right origin page.
            seed_snap = _zone_seed_snapshot(snapshots, page_id) or _instance_seed_snapshot(
                snapshots, page_id
            )
            if seed_snap is None:
                continue
            if _fetch_and_append(
                zone_snapshot=seed_snap,
                link=link,
                auxiliary_role="character_profile",
                auxiliary_target_id=character_id,
                traversal_origin="character_profile_targets",
                page_title=str(target.get("name", "")),
                snapshots=snapshots,
                manifest_rows=manifest_rows,
                existing_source_ids=existing_source_ids,
                existing_urls=existing_urls,
                captured_at=captured_at,
                report_rows=report_rows,
                allowed_instance_titles=allowed_instance_titles,
            ):
                seen_character.add(key)
                _increment(page_id, "character_profile")

    instance_lore_map = _load_json(discovery_dir / "instance_lore_source_map.json")
    if isinstance(instance_lore_map, list):
        seen_instance_lore: set[str] = set()
        for row in instance_lore_map:
            if not isinstance(row, dict):
                continue
            instance_id = str(row.get("instance_id", "")).strip()
            lore_source = str(row.get("lore_source", "")).strip()
            link = str(row.get("source_link", "")).strip()
            if lore_source != "linked_lore_page" or not instance_id or not link:
                continue
            if instance_id in seen_instance_lore:
                continue
            instance_snap = _instance_seed_snapshot(snapshots, instance_id)
            if instance_snap is None:
                continue
            if _fetch_and_append(
                zone_snapshot=instance_snap,
                link=link,
                auxiliary_role="instance_lore",
                auxiliary_target_id=instance_id,
                traversal_origin="instance_lore_source_map",
                page_title=_wiki_title(link),
                snapshots=snapshots,
                manifest_rows=manifest_rows,
                existing_source_ids=existing_source_ids,
                existing_urls=existing_urls,
                captured_at=captured_at,
                report_rows=report_rows,
                allowed_instance_titles=allowed_instance_titles,
            ):
                seen_instance_lore.add(instance_id)

    lore_targets = _load_json(discovery_dir / "lore_traversal_targets.json")
    if isinstance(lore_targets, list):
        seen_lore_targets: set[tuple[str, str]] = set()
        seen_lore_variants: set[tuple[str, str]] = set()
        for target in lore_targets:
            if not isinstance(target, dict):
                continue
            instance_id = str(target.get("instance_id", "")).strip()
            link = str(target.get("source_link", "")).strip()
            kind = str(target.get("candidate_kind", "")).strip()
            if not instance_id or not link or kind not in {"parent", "related"}:
                continue
            aux_role = "parent_lore" if kind == "parent" else "related_lore"
            cap = _MAX_PARENT_LORE if kind == "parent" else _MAX_RELATED_LORE
            key = (instance_id, link.lower())
            if key in seen_lore_targets:
                continue
            seen_lore_targets.add(key)
            # Collapse version variants of the same page so retail/Classic siblings of one
            # candidate are not both fetched for the same instance.
            title = str(target.get("title", "")).strip() or _wiki_title(link)
            variant_key = (instance_id, variant_cluster_key(title))
            if variant_key in seen_lore_variants:
                continue
            seen_lore_variants.add(variant_key)
            if not _within_cap(instance_id, aux_role, cap):
                continue
            instance_snap = _instance_seed_snapshot(snapshots, instance_id)
            if instance_snap is None:
                continue
            snapshot = _fetch_and_append(
                zone_snapshot=instance_snap,
                link=link,
                auxiliary_role=aux_role,
                auxiliary_target_id=_to_entity_id(kind, title),
                traversal_origin="lore_traversal_targets",
                page_title=title,
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
            eligibility = classify_lore_retail_eligibility(str(snapshot.get("body", "")))
            if eligibility != "eligible":
                _drop_snapshot(
                    snapshot,
                    snapshots=snapshots,
                    manifest_rows=manifest_rows,
                    existing_source_ids=existing_source_ids,
                    existing_urls=existing_urls,
                    report_rows=report_rows,
                    reason=eligibility,
                    role=aux_role,
                )
                continue
            _increment(instance_id, aux_role)

    _exclude_classic_instance_characters(snapshots, report_rows)
    link_category_cache = _build_link_category_cache(
        context,
        snapshots,
        report_rows,
        captured_at,
    )

    return _persist_traverse_state(
        context,
        snapshots=snapshots,
        manifest_rows=manifest_rows,
        report_rows=report_rows,
        link_category_cache=link_category_cache,
    )


def run_traverse_quests(context: RunContext) -> dict[str, Path]:
    """Fetch quest pages listed in zone_quest_graph_v3.json, with optional hub resolution."""
    (
        snapshots,
        manifest_rows,
        existing_source_ids,
        existing_urls,
        report_rows,
        allowed_instance_titles,
    ) = _load_traverse_state(context)
    captured_at = datetime.now(UTC).isoformat()
    v3_path = context.data_dir / "discovery" / "zone_quest_graph_v3.json"
    v3_blob = _load_json(v3_path)
    if not isinstance(v3_blob, list):
        raise RuntimeError(
            "zone_quest_graph_v3.json must exist and be a JSON array before quest traverse"
        )

    counts_by_zone_role: dict[tuple[str, str], int] = {}
    quest_records: list[dict[str, Any]] = []
    seen_record_links: set[str] = set()

    def _within_cap(zone_id: str, role: str, cap: int) -> bool:
        return counts_by_zone_role.get((zone_id, role), 0) < cap

    def _increment(zone_id: str, role: str) -> None:
        key = (zone_id, role)
        counts_by_zone_role[key] = counts_by_zone_role.get(key, 0) + 1

    def _process_record(snapshot: dict[str, Any]) -> list[str]:
        """Collect a real quest record, or return faction-mirror variant links.

        Pages without a Questbox produce no quest record (the not-a-quest filter
        keeps achievements/hatnotes out of ``quest_records.jsonl``), but their
        snapshot is retained so hub-child resolution can still run. A
        faction-disambiguation page returns its per-faction variant links so the
        caller fetches the real quest variants instead.
        """
        record = snapshot.get("quest_record")
        if not isinstance(record, dict):
            return []
        if not record.get("has_questbox", True):
            return [
                str(link).strip() for link in record.get("faction_mirror", []) if str(link).strip()
            ]
        link_key = str(record.get("source_link", "")).strip().lower().split("#", 1)[0]
        if link_key and link_key not in seen_record_links:
            seen_record_links.add(link_key)
            quest_records.append(record)
        return []

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
        node_faction = str(node.get("faction_binding", "shared"))
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
            faction_binding=node_faction,
        )
        _throttle(_QUEST_FETCH_SLEEP_SECONDS)
        if snapshot is None:
            continue
        _increment(zone_id, "quest")
        variant_links = _process_record(snapshot)
        for variant_link in variant_links:
            if not _within_cap(zone_id, "quest", _MAX_QUEST):
                break
            variant_path = _wiki_path_from_link_or_title(variant_link)
            if not variant_path:
                continue
            variant_title = _wiki_title(variant_path)
            variant_snapshot = _fetch_and_append(
                zone_snapshot=zone_snap,
                link=variant_path,
                auxiliary_role="quest",
                auxiliary_target_id=_to_entity_id("quest", variant_title),
                traversal_origin="faction_disambiguation",
                page_title=variant_title,
                snapshots=snapshots,
                manifest_rows=manifest_rows,
                existing_source_ids=existing_source_ids,
                existing_urls=existing_urls,
                captured_at=captured_at,
                report_rows=report_rows,
                allowed_instance_titles=allowed_instance_titles,
                cluster_id=str(node.get("cluster_id", "")),
                quest_node_id=_to_entity_id("quest", variant_title),
                hub_resolved_from=quest_link,
                faction_binding=node_faction,
            )
            _throttle(_QUEST_FETCH_SLEEP_SECONDS)
            if variant_snapshot is None:
                continue
            _increment(zone_id, "quest")
            _process_record(variant_snapshot)
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
                faction_binding=node_faction,
            )
            _throttle(_QUEST_FETCH_SLEEP_SECONDS)
            if child_snapshot is not None:
                _increment(zone_id, "quest")
                _process_record(child_snapshot)

    return _persist_traverse_state(
        context,
        snapshots=snapshots,
        manifest_rows=manifest_rows,
        report_rows=report_rows,
        quest_records=quest_records,
    )


def run_traverse_wiki(context: RunContext) -> dict[str, Path]:
    """Backward-compatible alias: seed traverse only."""
    return run_traverse_seed(context)
