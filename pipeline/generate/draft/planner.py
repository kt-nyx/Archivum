"""Structure-only planner pass for staged zone/sub-zone drafts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pipeline.generate.draft.common import claims_text, entity_header
from pipeline.generate.draft.limits import cap_prompt_hint, load_draft_limits
from pipeline.generate.draft.llm import llm_json_with_retry
from pipeline.generate.draft.schemas import sub_zone_draft_plan_schema, zone_draft_plan_schema
from pipeline.generate.draft.trace import DraftTraceContext


def run_zone_plan(
    fact_pack: dict[str, Any],
    *,
    trace: DraftTraceContext | None = None,
    plan_path: Path | None = None,
) -> dict[str, Any]:
    limits = load_draft_limits()
    plan = llm_json_with_retry(
        required_keys=(
            "expansion",
            "major_questlines_alliance",
            "major_questlines_horde",
            "major_questlines_shared",
            "major_characters",
            "instances",
            "major_landmarks",
            "glossary",
        ),
        response_json_schema=zone_draft_plan_schema(),
        system_prompt=(
            "Produce a WoW zone content plan as JSON only. No long prose sections—only "
            "structure: expansion, questline stubs, link stubs, glossary term_ids."
        ),
        user_prompt=(
            f"{entity_header(fact_pack)}"
            f"{cap_prompt_hint(limits)}\n"
            "Questline stubs: id, faction, title, include_decision (include|exclude).\n"
            f"Claims:\n{claims_text(fact_pack)}"
        ),
        response_schema_name="zone_draft_plan",
        trace=trace,
        substep="plan",
    )
    if plan_path is not None:
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return plan


def run_sub_zone_plan(
    fact_pack: dict[str, Any],
    *,
    trace: DraftTraceContext | None = None,
    plan_path: Path | None = None,
) -> dict[str, Any]:
    parent_zone_id = str(fact_pack.get("parent_zone_id", "")).strip()
    if not parent_zone_id:
        raise RuntimeError(
            f"sub-zone draft requires parent_zone_id for entity '{fact_pack['entity_id']}'"
        )
    limits = load_draft_limits()
    plan = llm_json_with_retry(
        required_keys=(
            "major_questlines_alliance",
            "major_questlines_horde",
            "major_questlines_shared",
            "major_characters",
            "instances",
            "major_landmarks",
            "glossary",
        ),
        response_json_schema=sub_zone_draft_plan_schema(),
        system_prompt=(
            "Produce a WoW sub-zone content plan as JSON only. No long prose—structure only."
        ),
        user_prompt=(
            f"{entity_header(fact_pack)}"
            f"Parent zone id: {parent_zone_id}\n"
            f"{cap_prompt_hint(limits)}\n"
            f"Claims:\n{claims_text(fact_pack)}"
        ),
        response_schema_name="sub_zone_draft_plan",
        trace=trace,
        substep="plan",
    )
    if plan_path is not None:
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return plan
