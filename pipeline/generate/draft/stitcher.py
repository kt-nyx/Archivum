"""Deterministic merge of staged draft worker outputs."""

from __future__ import annotations

from typing import Any

from pipeline.generate.draft.common import (
    assign_questline_factions,
    normalize_questline_criteria_breakdowns,
    source_entries,
)
from pipeline.generate.draft.limits import apply_body_caps, load_draft_limits
from pipeline.generate.draft.provenance import sub_zone_provenance, zone_provenance


def _planned_questline_ids(plan: dict[str, Any], bucket: str) -> set[str]:
    stubs = plan.get(bucket, [])
    if not isinstance(stubs, list):
        return set()
    return {str(s["id"]) for s in stubs if isinstance(s, dict) and s.get("id")}


def _enforce_plan_questlines(
    body: dict[str, Any],
    plan: dict[str, Any],
    *,
    entity_id: str,
) -> None:
    for bucket in (
        "major_questlines_alliance",
        "major_questlines_horde",
        "major_questlines_shared",
    ):
        allowed = _planned_questline_ids(plan, bucket)
        cards = body.get(bucket, [])
        if not isinstance(cards, list):
            raise RuntimeError(f"stitcher missing {bucket} for '{entity_id}'")
        extra = [str(c.get("id", "")) for c in cards if isinstance(c, dict)]
        unexpected = [i for i in extra if i and i not in allowed]
        if unexpected:
            raise RuntimeError(
                f"stitcher questline ids not in plan for '{entity_id}'/{bucket}: "
                f"{', '.join(unexpected)}"
            )


def stitch_zone_draft(
    fact_pack: dict[str, Any],
    plan: dict[str, Any],
    worker_parts: dict[str, Any],
) -> dict[str, Any]:
    fact_items = [item for item in fact_pack.get("fact_items", []) if isinstance(item, dict)]
    prose = worker_parts.get("prose", {})
    links = worker_parts.get("links", {})
    if not isinstance(prose, dict) or not isinstance(links, dict):
        raise RuntimeError(f"stitcher invalid worker parts for '{fact_pack['entity_id']}'")

    body: dict[str, Any] = {
        "expansion": str(plan.get("expansion", "retail")),
        "at_a_glance": str(prose.get("at_a_glance", "")),
        "currently": str(prose.get("currently", "")),
        "history": str(prose.get("history", "")),
        "major_questlines_alliance": worker_parts.get("major_questlines_alliance", []),
        "major_questlines_horde": worker_parts.get("major_questlines_horde", []),
        "major_questlines_shared": worker_parts.get("major_questlines_shared", []),
        "major_characters": links.get("major_characters", []),
        "instances": links.get("instances", []),
        "major_landmarks": links.get("major_landmarks", []),
        "glossary": links.get("glossary", []),
    }
    apply_body_caps(body, load_draft_limits())
    normalize_questline_criteria_breakdowns(body)
    _enforce_plan_questlines(body, plan, entity_id=str(fact_pack["entity_id"]))
    assign_questline_factions(body)

    draft = {
        "id": str(fact_pack["entity_id"]),
        "slug": str(fact_pack["slug"]),
        "name": str(fact_pack["name"]),
        "expansion": str(body["expansion"]),
        "at_a_glance": str(body["at_a_glance"]),
        "currently": str(body["currently"]),
        "history": str(body["history"]),
        "major_questlines_alliance": body["major_questlines_alliance"],
        "major_questlines_horde": body["major_questlines_horde"],
        "major_questlines_shared": body["major_questlines_shared"],
        "major_characters": body["major_characters"],
        "instances": body["instances"],
        "major_landmarks": body["major_landmarks"],
        "glossary": body["glossary"],
        "sources": source_entries(fact_pack),
    }
    draft["provenance"] = zone_provenance(fact_items=fact_items, draft=draft)
    return draft


def stitch_sub_zone_draft(
    fact_pack: dict[str, Any],
    plan: dict[str, Any],
    worker_parts: dict[str, Any],
) -> dict[str, Any]:
    draft = stitch_zone_draft(fact_pack, {**plan, "expansion": "n/a"}, worker_parts)
    parent_zone_id = str(fact_pack.get("parent_zone_id", "")).strip()
    draft.pop("expansion", None)
    draft["parent_zone_id"] = parent_zone_id
    fact_items = [item for item in fact_pack.get("fact_items", []) if isinstance(item, dict)]
    draft["provenance"] = sub_zone_provenance(fact_items=fact_items, draft=draft)
    return draft
