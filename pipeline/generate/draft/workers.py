"""Parallel worker passes for staged draft generation."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from pipeline.generate.draft.common import (
    entity_header,
    filter_claims_for_keywords,
)
from pipeline.generate.draft.limits import cap_prompt_hint, load_draft_limits
from pipeline.generate.draft.llm import llm_json_with_retry
from pipeline.generate.draft.schemas import (
    zone_draft_links_schema,
    zone_draft_prose_schema,
    zone_draft_questlines_bucket_schema,
)
from pipeline.generate.draft.trace import DraftTraceContext

_QUESTLINE_BUCKETS = (
    ("major_questlines_alliance", "alliance", "questlines_alliance"),
    ("major_questlines_horde", "horde", "questlines_horde"),
    ("major_questlines_shared", "shared", "questlines_shared"),
)


def _stub_titles(plan: dict[str, Any], bucket: str) -> list[str]:
    stubs = plan.get(bucket, [])
    if not isinstance(stubs, list):
        return []
    return [str(s.get("title", "")) for s in stubs if isinstance(s, dict) and s.get("title")]


def run_prose_worker(
    fact_pack: dict[str, Any],
    plan: dict[str, Any],
    *,
    trace: DraftTraceContext | None = None,
) -> dict[str, Any]:
    outline = plan.get("prose_outline", [])
    outline_hint = ""
    if isinstance(outline, list) and outline:
        outline_hint = "Outline:\n" + "\n".join(f"- {b}" for b in outline[:8]) + "\n"
    return llm_json_with_retry(
        required_keys=("at_a_glance", "currently", "history"),
        response_json_schema=zone_draft_prose_schema(),
        system_prompt=(
            "Produce zone prose sections as JSON only: at_a_glance, currently, history. "
            "Original WoW lore voice; respect word budgets."
        ),
        user_prompt=(
            f"{entity_header(fact_pack)}"
            f"Expansion: {plan.get('expansion', '')}\n"
            f"{outline_hint}"
            f"Claims:\n{filter_claims_for_keywords(fact_pack, [])}"
        ),
        response_schema_name="zone_draft_prose",
        trace=trace,
        substep="prose",
    )


def run_questlines_worker(
    fact_pack: dict[str, Any],
    plan: dict[str, Any],
    bucket: str,
    faction: str,
    *,
    trace: DraftTraceContext | None = None,
    substep: str,
) -> list[dict[str, Any]]:
    stubs = plan.get(bucket, [])
    if not isinstance(stubs, list) or not stubs:
        return []
    included = [
        s for s in stubs if isinstance(s, dict) and s.get("include_decision") != "exclude"
    ]
    if not included:
        return []
    titles = [str(s.get("title", "")) for s in included]
    ids = [str(s.get("id", "")) for s in included]
    result = llm_json_with_retry(
        required_keys=("cards",),
        response_json_schema=zone_draft_questlines_bucket_schema(),
        system_prompt=(
            f"Produce full questline cards for faction={faction} as JSON. "
            "Each card must match a planned id from the user message."
        ),
        user_prompt=(
            f"{entity_header(fact_pack)}"
            f"{cap_prompt_hint(load_draft_limits())}\n"
            f"Planned ids: {', '.join(ids)}\n"
            f"Planned titles: {', '.join(titles)}\n"
            f"Claims:\n{filter_claims_for_keywords(fact_pack, titles + ids)}"
        ),
        response_schema_name=f"zone_draft_{substep}",
        trace=trace,
        substep=substep,
    )
    cards = result.get("cards", [])
    if not isinstance(cards, list):
        return []
    allowed_ids = {i for i in ids if i}
    filtered = [c for c in cards if isinstance(c, dict) and str(c.get("id", "")) in allowed_ids]
    return filtered


def run_links_worker(
    fact_pack: dict[str, Any],
    plan: dict[str, Any],
    *,
    trace: DraftTraceContext | None = None,
) -> dict[str, Any]:
    link_ids: list[str] = []
    for bucket in ("major_characters", "instances", "major_landmarks"):
        stubs = plan.get(bucket, [])
        if isinstance(stubs, list):
            for stub in stubs:
                if isinstance(stub, dict) and stub.get("id"):
                    link_ids.append(str(stub["id"]))
    glossary = plan.get("glossary", [])
    term_ids: list[str] = []
    if isinstance(glossary, list):
        for row in glossary:
            if isinstance(row, dict) and row.get("term_id"):
                term_ids.append(str(row["term_id"]))
    return llm_json_with_retry(
        required_keys=(
            "major_characters",
            "instances",
            "major_landmarks",
            "glossary",
        ),
        response_json_schema=zone_draft_links_schema(),
        system_prompt=(
            "Produce link cards and glossary term_id rows as JSON. Match planned ids only."
        ),
        user_prompt=(
            f"{entity_header(fact_pack)}"
            f"Planned link ids: {', '.join(link_ids)}\n"
            f"Planned glossary term_ids: {', '.join(term_ids)}\n"
            f"Claims:\n{filter_claims_for_keywords(fact_pack, link_ids + term_ids)}"
        ),
        response_schema_name="zone_draft_links",
        trace=trace,
        substep="links",
    )


def run_all_workers(
    fact_pack: dict[str, Any],
    plan: dict[str, Any],
    *,
    trace: DraftTraceContext | None = None,
    max_workers: int = 4,
) -> dict[str, Any]:
    """Run prose, questline buckets, and links workers (partial merge)."""
    parts: dict[str, Any] = {}
    tasks: dict[str, Any] = {}

    def submit_prose() -> dict[str, Any]:
        return run_prose_worker(fact_pack, plan, trace=trace)

    def submit_links() -> dict[str, Any]:
        return run_links_worker(fact_pack, plan, trace=trace)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        tasks["prose"] = executor.submit(submit_prose)
        tasks["links"] = executor.submit(submit_links)
        for bucket, faction, substep in _QUESTLINE_BUCKETS:
            tasks[bucket] = executor.submit(
                run_questlines_worker,
                fact_pack,
                plan,
                bucket,
                faction,
                trace=trace,
                substep=substep,
            )
        for key, future in tasks.items():
            parts[key] = future.result()
    return parts


def workers_snapshot_path(stage_dir: Path, entity_id: str) -> Path:
    return stage_dir / "_workers" / f"{entity_id}.json"


def persist_workers_snapshot(path: Path, parts: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(parts, indent=2, default=list), encoding="utf-8")
