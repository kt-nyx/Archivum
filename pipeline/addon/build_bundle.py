"""Build addon-ingestible data bundle from generated drafts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pipeline.common.run_context import RunContext
from pipeline.glossary.run_terms import load_run_terms, run_terms_metadata_map


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_static_glossary_term_metadata() -> dict[str, dict[str, str]]:
    dictionary_path = Path(__file__).resolve().parents[2] / "dictionary" / "glossary_aliases.v1.json"
    if not dictionary_path.exists():
        return {}
    payload = _load_json(dictionary_path)
    aliases = payload.get("aliases", []) if isinstance(payload, dict) else []
    metadata: dict[str, dict[str, str]] = {}
    if not isinstance(aliases, list):
        return metadata
    for row in aliases:
        if not isinstance(row, dict):
            continue
        term_id = str(row.get("term_id", "")).strip()
        alias = str(row.get("alias", "")).strip()
        alias_type = str(row.get("alias_type", "")).strip().lower()
        category = str(row.get("category", "")).strip().lower()
        if not term_id or not alias:
            continue
        existing = metadata.get(term_id)
        if existing and alias_type != "canonical":
            continue
        wiki_slug = alias.replace(" ", "_")
        metadata[term_id] = {
            "term_id": term_id,
            "label": alias,
            "wiki_url": f"https://warcraft.wiki.gg/wiki/{wiki_slug}",
            "category": category,
        }
    return metadata


def _load_glossary_term_metadata(context: RunContext) -> dict[str, dict[str, Any]]:
    metadata = run_terms_metadata_map(load_run_terms(context))
    if not metadata:
        metadata = _load_static_glossary_term_metadata()
    return metadata


def _metadata_for_ref(
    ref: dict[str, Any],
    *,
    metadata: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    term_id = str(ref.get("term_id", "")).strip()
    if not term_id:
        return {}
    base = dict(metadata.get(term_id, {"term_id": term_id}))
    label = str(ref.get("label", "")).strip()
    wiki_url = str(ref.get("wiki_url", "")).strip()
    if label:
        base["label"] = label
    if wiki_url:
        base["wiki_url"] = wiki_url
    base.setdefault("term_id", term_id)
    return base


def build_addon_bundle(context: RunContext) -> Path:
    output_root = context.root_dir / "build" / "lua"
    zones_dir = output_root / "zones"
    instances_dir = output_root / "instances"
    lookup_dir = output_root / "lookup"
    nav_dir = output_root / "nav"
    for directory in (zones_dir, instances_dir, lookup_dir, nav_dir):
        directory.mkdir(parents=True, exist_ok=True)

    draft_root = context.data_dir / "drafts"
    zone_pages = sorted((draft_root / "zone_page").glob("*.json"))
    instance_pages = sorted((draft_root / "instance_page").glob("*.json"))
    location_cards: dict[str, dict[str, Any]] = {}
    glossary_refs: dict[str, dict[str, Any]] = {}
    glossary_term_metadata = _load_glossary_term_metadata(context)
    static_metadata = _load_static_glossary_term_metadata()
    nav_edges: list[dict[str, str]] = []

    for zone_path in zone_pages:
        payload = _load_json(zone_path)
        zone_id = str(payload.get("zone_id", zone_path.stem))
        (zones_dir / f"{zone_id}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        for location in payload.get("location_cards", []):
            if not isinstance(location, dict):
                continue
            location_id = str(location.get("id", "")).strip()
            if location_id:
                location_cards[location_id] = location
        for instance in payload.get("instance_links", []):
            if not isinstance(instance, dict):
                continue
            nav_edges.append(
                {
                    "zone_id": zone_id,
                    "instance_id": str(instance.get("id", "")).strip(),
                }
            )
        for ref in payload.get("glossary_refs", []):
            if not isinstance(ref, dict):
                continue
            term_id = str(ref.get("term_id", "")).strip()
            if term_id:
                glossary_refs[term_id] = _metadata_for_ref(
                    ref,
                    metadata=glossary_term_metadata,
                )

    for instance_path in instance_pages:
        payload = _load_json(instance_path)
        instance_id = str(payload.get("instance_id", instance_path.stem))
        (instances_dir / f"{instance_id}.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
        for ref in payload.get("glossary_refs", []):
            if not isinstance(ref, dict):
                continue
            term_id = str(ref.get("term_id", "")).strip()
            if term_id:
                glossary_refs[term_id] = _metadata_for_ref(
                    ref,
                    metadata=glossary_term_metadata,
                )

    for term_id, row in glossary_refs.items():
        if "wiki_url" not in row and term_id in static_metadata:
            fallback = static_metadata[term_id]
            row.setdefault("label", fallback.get("label", term_id))
            row.setdefault("wiki_url", fallback.get("wiki_url", ""))
            row.setdefault("category", fallback.get("category", ""))

    (lookup_dir / "location_cards.json").write_text(
        json.dumps(location_cards, indent=2), encoding="utf-8"
    )
    (lookup_dir / "glossary_refs.json").write_text(
        json.dumps(glossary_refs, indent=2), encoding="utf-8"
    )
    (lookup_dir / "glossary_terms.json").write_text(
        json.dumps(glossary_refs, indent=2), encoding="utf-8"
    )
    (nav_dir / "index.json").write_text(json.dumps(nav_edges, indent=2), encoding="utf-8")

    manifest = {
        "schema_version": "v1",
        "zone_count": len(zone_pages),
        "instance_count": len(instance_pages),
        "location_card_count": len(location_cards),
        "glossary_ref_count": len(glossary_refs),
    }
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    validation_report = {"passed": False, "issues": ["validate_report_missing"]}
    validate_report_path = context.reports_dir / "validate" / "validation_report.json"
    if validate_report_path.exists():
        loaded_report = _load_json(validate_report_path)
        if isinstance(loaded_report, dict):
            validation_report = loaded_report
    (output_root / "validation_report.json").write_text(
        json.dumps(validation_report, indent=2), encoding="utf-8"
    )
    return output_root
