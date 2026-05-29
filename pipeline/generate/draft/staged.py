"""Staged planner → workers → stitcher orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pipeline.common.run_context import RunContext
from pipeline.generate.draft.planner import run_sub_zone_plan, run_zone_plan
from pipeline.generate.draft.stitcher import stitch_sub_zone_draft, stitch_zone_draft
from pipeline.generate.draft.trace import DraftTraceContext
from pipeline.generate.draft.workers import (
    persist_workers_snapshot,
    run_all_workers,
    workers_snapshot_path,
)


def staged_zone_draft(
    fact_pack: dict[str, Any],
    *,
    context: RunContext | None = None,
    trace: DraftTraceContext | None = None,
) -> tuple[dict[str, Any], str]:
    entity_id = str(fact_pack["entity_id"])
    plan_path: Path | None = None
    if context is not None:
        plan_path = context.data_dir / "drafts" / "_plans" / f"{entity_id}.json"
    plan = run_zone_plan(fact_pack, trace=trace, plan_path=plan_path)
    worker_parts = run_all_workers(fact_pack, plan, trace=trace)
    if context is not None:
        persist_workers_snapshot(
            workers_snapshot_path(context.data_dir / "drafts", entity_id),
            worker_parts,
        )
    draft = stitch_zone_draft(fact_pack, plan, worker_parts)
    return draft, "openai"


def staged_sub_zone_draft(
    fact_pack: dict[str, Any],
    *,
    context: RunContext | None = None,
    trace: DraftTraceContext | None = None,
) -> tuple[dict[str, Any], str]:
    entity_id = str(fact_pack["entity_id"])
    plan_path: Path | None = None
    if context is not None:
        plan_path = context.data_dir / "drafts" / "_plans" / f"{entity_id}.json"
    plan = run_sub_zone_plan(fact_pack, trace=trace, plan_path=plan_path)
    worker_parts = run_all_workers(fact_pack, {**plan, "expansion": ""}, trace=trace)
    if context is not None:
        persist_workers_snapshot(
            workers_snapshot_path(context.data_dir / "drafts", entity_id),
            worker_parts,
        )
    draft = stitch_sub_zone_draft(fact_pack, plan, worker_parts)
    return draft, "openai"
