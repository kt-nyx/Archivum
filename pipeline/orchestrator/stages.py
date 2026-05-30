"""Reusable stage runners for CLI and orchestration flow."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, cast

from pipeline.coalesce.resolve_entities import run_resolve_entities
from pipeline.common.run_context import RunContext, append_trace_event, write_stage_manifest
from pipeline.addon import build_addon_bundle
from pipeline.discovery import run_discovery_workflow
from pipeline.discovery.enrich import EnrichPhase, run_discovery_enrich
from pipeline.generate.draft_writer import run_draft_writer
from pipeline.generate.extract_facts import run_extract_facts
from pipeline.ingest.fetch_wiki import run_fetch_wiki
from pipeline.ingest.normalize_source import run_normalize_source
from pipeline.ingest.traverse_wiki import run_traverse_quests, run_traverse_seed
from pipeline.glossary.run_terms import build_run_terms
from pipeline.linker.linker import run_glossary_linker
from pipeline.validate.engine import validate_payload


def run_ingest_stage(context: RunContext) -> dict[str, Path]:
    snapshots_path = run_fetch_wiki(context)
    manifest_path = run_normalize_source(context, snapshots_path)
    manifest_rows = json.loads(manifest_path.read_text(encoding="utf-8"))
    retrieval_modes = sorted(
        {
            str(row.get("retrieval_mode", "unknown"))
            for row in manifest_rows
            if isinstance(row, dict)
        }
    )
    write_stage_manifest(
        context,
        "ingest",
        status="ok",
        inputs=[],
        outputs=[str(snapshots_path), str(manifest_path)],
        metadata={"record_count": len(manifest_rows), "retrieval_modes": retrieval_modes},
    )
    return {"snapshots_path": snapshots_path, "source_manifest_path": manifest_path}


def run_discovery_stage(context: RunContext, source_manifest_path: Path) -> dict[str, Path]:
    snapshots_path = context.stage_dir("ingest") / "source_snapshots.json"
    if not snapshots_path.exists():
        write_stage_manifest(
            context,
            "discovery",
            status="skipped",
            inputs=[str(source_manifest_path)],
            outputs=[],
            metadata={"reason": "missing_source_snapshots"},
        )
        return {}
    outputs = run_discovery_workflow(context, source_manifest_path)
    write_stage_manifest(
        context,
        "discovery",
        status="ok",
        inputs=[str(source_manifest_path), str(context.stage_dir("ingest") / "source_snapshots.json")],
        outputs=[str(path) for path in outputs.values()],
        metadata={"artifact_count": len(outputs), "phase": "seed"},
    )
    return outputs


def run_traverse_seed_stage(context: RunContext) -> dict[str, Path]:
    outputs = run_traverse_seed(context)
    write_stage_manifest(
        context,
        "traverse_seed",
        status="ok",
        inputs=[str(context.stage_dir("ingest") / "source_manifest.json")],
        outputs=[str(path) for path in outputs.values()],
        metadata={
            "fetched_count": sum(
                1
                for row in json.loads(outputs["traversal_report"].read_text(encoding="utf-8")).get("entries", [])
                if row.get("status") == "fetched"
            )
        },
    )
    return outputs


def run_traverse_quests_stage(context: RunContext) -> dict[str, Path]:
    outputs = run_traverse_quests(context)
    write_stage_manifest(
        context,
        "traverse_quests",
        status="ok",
        inputs=[str(context.data_dir / "discovery" / "zone_quest_graph_v3.json")],
        outputs=[str(path) for path in outputs.values()],
        metadata={
            "fetched_count": sum(
                1
                for row in json.loads(outputs["traversal_report"].read_text(encoding="utf-8")).get("entries", [])
                if row.get("status") == "fetched" and row.get("role") == "quest"
            )
        },
    )
    return outputs


def run_traverse_stage(context: RunContext) -> dict[str, Path]:
    """Backward-compatible alias for seed traverse only."""
    return run_traverse_seed_stage(context)


def run_discovery_enrich_stage(
    context: RunContext,
    source_manifest_path: Path,
    *,
    phase: EnrichPhase = "full",
) -> dict[str, Path]:
    outputs = run_discovery_enrich(context, source_manifest_path, phase=phase)
    write_stage_manifest(
        context,
        "discovery_enrich",
        status="ok",
        inputs=[str(source_manifest_path), str(context.stage_dir("ingest") / "source_snapshots.json")],
        outputs=[str(path) for path in outputs.values()],
        metadata={"artifact_count": len(outputs), "phase": phase},
    )
    return outputs


def run_coalesce_stage(
    context: RunContext,
    source_manifest_path: Path,
    *,
    max_entity_concurrency: int = 4,
) -> Path:
    manifest_blob = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    coalesce_entity_ids: list[str] = []
    if isinstance(manifest_blob, list):
        for index, row in enumerate(manifest_blob, start=1):
            if not isinstance(row, dict):
                continue
            entity_id = row.get("entity_id")
            if isinstance(entity_id, str) and entity_id.strip():
                coalesce_entity_ids.append(entity_id.strip())
            else:
                fallback = str(row.get("slug", "")).strip() or f"row-{index}"
                coalesce_entity_ids.append(f"unknown-{fallback}")
    for entity_id in coalesce_entity_ids:
        append_trace_event(
            context,
            stage_name=f"coalesce:{entity_id}",
            attempt=1,
            status="start",
        )
    try:
        output_path = run_resolve_entities(
            context,
            source_manifest_path,
            max_entity_concurrency=max_entity_concurrency,
        )
    except Exception as exc:
        for entity_id in coalesce_entity_ids:
            append_trace_event(
                context,
                stage_name=f"coalesce:{entity_id}",
                attempt=1,
                status="error",
                details={"error": repr(exc)},
            )
        raise
    coalesced_rows = [
        json.loads(line)
        for line in output_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for row in coalesced_rows:
        append_trace_event(
            context,
            stage_name=f"coalesce:{row['entity_id']}",
            attempt=1,
            status="success",
        )
    write_stage_manifest(
        context,
        "coalesce",
        status="ok",
        inputs=[str(source_manifest_path)],
        outputs=[str(output_path)],
        metadata={"max_entity_concurrency": max_entity_concurrency},
    )
    return output_path


def run_extract_stage(
    context: RunContext,
    entities_path: Path,
    *,
    max_entity_concurrency: int = 4,
) -> list[Path]:
    rows = [
        json.loads(line)
        for line in entities_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    extract_entity_ids = [
        str(row.get("entity_id", f"unknown-row-{index}"))
        for index, row in enumerate(rows, start=1)
        if isinstance(row, dict)
    ]
    for entity_id in extract_entity_ids:
        append_trace_event(
            context,
            stage_name=f"extract:{entity_id}",
            attempt=1,
            status="start",
        )
    try:
        outputs = run_extract_facts(
            context,
            entities_path,
            max_entity_concurrency=max_entity_concurrency,
        )
    except Exception as exc:
        for entity_id in extract_entity_ids:
            append_trace_event(
                context,
                stage_name=f"extract:{entity_id}",
                attempt=1,
                status="error",
                details={"error": repr(exc)},
            )
        raise
    for path in outputs:
        append_trace_event(
            context,
            stage_name=f"extract:{path.stem}",
            attempt=1,
            status="success",
        )
    write_stage_manifest(
        context,
        "extract",
        status="ok",
        inputs=[str(entities_path)],
        outputs=[str(path) for path in outputs],
        metadata={"max_entity_concurrency": max_entity_concurrency},
    )
    return outputs


def run_draft_stage(
    context: RunContext,
    fact_pack_paths: list[Path],
    *,
    max_entity_concurrency: int = 4,
    verbose: bool = False,
) -> list[Path]:
    draft_entity_ids = [path.stem for path in fact_pack_paths]
    for entity_id in draft_entity_ids:
        append_trace_event(
            context,
            stage_name=f"draft:{entity_id}",
            attempt=1,
            status="start",
        )
    try:
        outputs = run_draft_writer(
            context,
            fact_pack_paths,
            max_entity_concurrency=max_entity_concurrency,
            verbose=verbose,
        )
    except Exception as exc:
        for entity_id in draft_entity_ids:
            append_trace_event(
                context,
                stage_name=f"draft:{entity_id}",
                attempt=1,
                status="error",
                details={"error": repr(exc)},
            )
        raise
    for path in outputs:
        append_trace_event(
            context,
            stage_name=f"draft:{path.stem}",
            attempt=1,
            status="success",
        )
    write_stage_manifest(
        context,
        "draft",
        status="ok",
        inputs=[str(path) for path in fact_pack_paths],
        outputs=[str(path) for path in outputs],
        metadata={"max_entity_concurrency": max_entity_concurrency},
    )
    return outputs


def run_glossary_terms_stage(context: RunContext) -> Path:
    output_path = build_run_terms(context)
    write_stage_manifest(
        context,
        "glossary_terms",
        status="ok",
        inputs=[str(context.data_dir / "drafts")],
        outputs=[str(output_path)],
        metadata={},
    )
    return output_path


def run_linker_stage(
    context: RunContext,
    draft_paths: list[Path],
    *,
    max_entity_concurrency: int = 4,
) -> Path:
    run_terms_path = context.data_dir / "glossary" / "run_terms.jsonl"
    output = run_glossary_linker(
        context,
        draft_paths,
        max_entity_concurrency=max_entity_concurrency,
    )
    linker_inputs = [str(path) for path in draft_paths]
    if run_terms_path.exists():
        linker_inputs.append(str(run_terms_path))
    write_stage_manifest(
        context,
        "linker",
        status="ok",
        inputs=linker_inputs,
        outputs=[str(output)],
        metadata={"max_entity_concurrency": max_entity_concurrency},
    )
    return output


def run_validate_stage(
    context: RunContext,
    draft_paths: list[Path],
    *,
    linker_report_path: Path | None = None,
    fact_check_profile: str,
    fact_check_web_search: bool = False,
    fact_check_max_web_results: int = 3,
    fact_check_enable_llm: bool | None = None,
    fact_check_llm_model: str = "gpt-5.5",
    max_entity_concurrency: int = 4,
    no_llm_fact_check: bool = False,
) -> dict[str, Any]:
    normalized_fact_check_profile = fact_check_profile.strip().lower()
    if normalized_fact_check_profile not in {"off", "warn", "strict"}:
        raise RuntimeError(
            "unsupported fact-check profile; expected one of: off, warn, strict "
            f"(got '{fact_check_profile}')"
        )
    report_rows: list[dict[str, Any]] = []
    fact_check_rows: list[dict[str, Any]] = []
    all_passed = True
    snapshots_path = context.stage_dir("ingest") / "source_snapshots.json"
    source_snapshots: list[dict[str, Any]] = []
    if snapshots_path.exists():
        snapshots_blob = json.loads(snapshots_path.read_text(encoding="utf-8"))
        if isinstance(snapshots_blob, list):
            source_snapshots = [row for row in snapshots_blob if isinstance(row, dict)]
    linker_manual_review_by_entity: dict[str, int] = {}
    if linker_report_path is not None and linker_report_path.exists():
        linker_payload = json.loads(linker_report_path.read_text(encoding="utf-8"))
        manual_rows = linker_payload.get("manual_review_candidates", [])
        if isinstance(manual_rows, list):
            for row in manual_rows:
                if not isinstance(row, dict):
                    continue
                entity_id = row.get("entity_id")
                if isinstance(entity_id, str):
                    linker_manual_review_by_entity[entity_id] = (
                        linker_manual_review_by_entity.get(entity_id, 0) + 1
                    )
    fact_check_target_reasons: dict[str, set[str]] = {}
    for entity_id in linker_manual_review_by_entity:
        fact_check_target_reasons.setdefault(entity_id, set()).add("linker_manual_review")

    coalesce_decisions_path = context.data_dir / "coalesced" / "coalesce_decisions.json"
    if coalesce_decisions_path.exists():
        coalesce_blob = json.loads(coalesce_decisions_path.read_text(encoding="utf-8"))
        if isinstance(coalesce_blob, list):
            for row in coalesce_blob:
                if not isinstance(row, dict):
                    continue
                entity_id = row.get("entity_id")
                if not isinstance(entity_id, str) or not entity_id:
                    continue
                tie_break_events = row.get("tie_break_events")
                if isinstance(tie_break_events, int) and tie_break_events > 0:
                    fact_check_target_reasons.setdefault(entity_id, set()).add("coalesce_tie_break")
                confidence = row.get("confidence")
                if isinstance(confidence, (int, float)) and float(confidence) < 0.88:
                    fact_check_target_reasons.setdefault(entity_id, set()).add(
                        "coalesce_low_confidence"
                    )

    draft_decisions_path = context.data_dir / "drafts" / "draft_decisions.json"
    if draft_decisions_path.exists():
        draft_blob = json.loads(draft_decisions_path.read_text(encoding="utf-8"))
        if isinstance(draft_blob, list):
            for row in draft_blob:
                if not isinstance(row, dict):
                    continue
                entity_id = row.get("entity_id")
                if not isinstance(entity_id, str) or not entity_id:
                    continue
                if str(row.get("schema_repair_applied", "")).lower() == "yes":
                    fact_check_target_reasons.setdefault(entity_id, set()).add(
                        "draft_schema_repair"
                    )

    fact_check_target_entity_ids = sorted(fact_check_target_reasons)
    fact_check_target_reason_map = {
        entity_id: sorted(reasons) for entity_id, reasons in fact_check_target_reasons.items()
    }

    resolved_enable_llm = fact_check_enable_llm
    if resolved_enable_llm is None:
        resolved_enable_llm = normalized_fact_check_profile in {"warn", "strict"}
    if (
        normalized_fact_check_profile in {"warn", "strict"}
        and fact_check_enable_llm is False
        and not no_llm_fact_check
    ):
        raise RuntimeError(
            "warn/strict fact-check profiles require LLM adjudication by default; "
            "use --no-llm-fact-check for explicit local/dev override"
        )
    if no_llm_fact_check:
        resolved_enable_llm = False

    questline_decisions_path = context.data_dir / "decisions" / "questline_inclusion_decisions.json"
    location_decisions_path = context.data_dir / "decisions" / "location_significance_decisions.json"
    questline_decisions: list[dict[str, Any]] = []
    location_decisions: list[dict[str, Any]] = []
    if questline_decisions_path.exists():
        blob = json.loads(questline_decisions_path.read_text(encoding="utf-8"))
        if isinstance(blob, list):
            questline_decisions = [row for row in blob if isinstance(row, dict)]
    if location_decisions_path.exists():
        blob = json.loads(location_decisions_path.read_text(encoding="utf-8"))
        if isinstance(blob, list):
            location_decisions = [row for row in blob if isinstance(row, dict)]

    def _wiki_first_validation_context(entity_id: str) -> dict[str, Any]:
        questline_row = next(
            (row for row in questline_decisions if str(row.get("subject_id", "")) == entity_id),
            None,
        )
        location_include_count = sum(
            1
            for row in location_decisions
            if str(row.get("final_decision", "")) == "include"
        )
        return {
            "questline_expect_include": str((questline_row or {}).get("final_decision", "")) == "include",
            "location_expect_card_count": location_include_count,
        }

    def _validate_one(draft_path: Path) -> tuple[dict[str, Any], dict[str, Any] | None]:
        raw_payload = json.loads(draft_path.read_text(encoding="utf-8"))
        payload = raw_payload if isinstance(raw_payload, dict) else {}
        payload_id = payload.get("id")
        if isinstance(payload_id, str) and payload_id.strip():
            entity_id = payload_id.strip()
        else:
            entity_id = draft_path.stem or "unknown-entity"
        entity_type = draft_path.parent.name
        append_trace_event(
            context,
            stage_name=f"validate:{entity_id}",
            attempt=1,
            status="start",
        )
        try:
            if not isinstance(raw_payload, dict):
                raise RuntimeError("draft payload is not a JSON object")
            report = validate_payload(
                entity_type,
                payload,
                validation_context={
                    "fact_check_profile": normalized_fact_check_profile,
                    "fact_check_web_search": fact_check_web_search,
                    "fact_check_max_web_results": fact_check_max_web_results,
                    "fact_check_enable_llm": resolved_enable_llm,
                    "fact_check_llm_model": fact_check_llm_model,
                    "fact_check_source_snapshots": source_snapshots,
                    "fact_check_target_entity_ids": fact_check_target_entity_ids,
                    "fact_check_target_reasons": fact_check_target_reason_map,
                    # warn/strict: require ingest bodies for similarity; strict treats missing
                    # bodies as hard-fail (see similarity rules).
                    "similarity_require_snapshots": normalized_fact_check_profile
                    in {"warn", "strict"},
                    **_wiki_first_validation_context(entity_id),
                },
            )
        except Exception as exc:
            append_trace_event(
                context,
                stage_name=f"validate:{entity_id}",
                attempt=1,
                status="error",
                details={"error": repr(exc)},
            )
            error_row = {
                "entity_id": entity_id,
                "entity_type": entity_type,
                "passed": False,
                "hard_fail_count": 1,
                "warn_count": 0,
                "issues": [
                    {
                        "code": "validate.runtime_error",
                        "message": repr(exc),
                        "severity": "hard-fail",
                        "path": "$",
                    }
                ],
            }
            return error_row, None
        append_trace_event(
            context,
            stage_name=f"validate:{entity_id}",
            attempt=1,
            status="success" if report.passed else "failed",
            details={
                "hard_fail_count": report.hard_fail_count,
                "warn_count": report.warn_count,
            },
        )
        row: dict[str, Any] = {
            "entity_id": entity_id,
            "entity_type": entity_type,
            "passed": report.passed,
            "hard_fail_count": report.hard_fail_count,
            "warn_count": report.warn_count,
            "issues": [issue.model_dump(mode="json") for issue in report.issues],
        }
        linker_review_count = linker_manual_review_by_entity.get(entity_id, 0)
        if linker_review_count > 0:
            glossary_path = (
                "$.glossary_refs"
                if entity_type in {"zone_page", "instance_page"}
                else "$.glossary"
            )
            issues = cast(list[dict[str, Any]], row["issues"])
            issues.append(
                {
                    "code": "linker.manual_review_required",
                    "message": f"{linker_review_count} glossary link candidates require review",
                    "severity": "warn",
                    "path": glossary_path,
                }
            )
            warn_count_value = row["warn_count"]
            warn_count = int(warn_count_value) if isinstance(warn_count_value, int) else 0
            row["warn_count"] = warn_count + linker_review_count
        fact_check_row: dict[str, Any] | None = None
        if report.fact_check_report:
            fact_check_row = {"entity_id": entity_id, **report.fact_check_report}
        return row, fact_check_row

    with ThreadPoolExecutor(max_workers=max_entity_concurrency) as executor:
        futures = [executor.submit(_validate_one, path) for path in draft_paths]
        for future in futures:
            row, fact_check_row = future.result()
            report_rows.append(row)
            all_passed = all_passed and bool(row["passed"])
            if fact_check_row:
                fact_check_rows.append(fact_check_row)

    report_dir = context.reports_dir / "validate"
    report_dir.mkdir(parents=True, exist_ok=True)

    validation_report_path = report_dir / "validation_report.json"
    validation_report_path.write_text(
        json.dumps(
            {
                "run_id": context.run_id,
                "fact_check_profile": normalized_fact_check_profile,
                "no_llm_fact_check": no_llm_fact_check,
                "llm_model": fact_check_llm_model,
                "fact_check_target_entity_count": len(fact_check_target_entity_ids),
                "fact_check_target_entity_ids": fact_check_target_entity_ids,
                "max_entity_concurrency": max_entity_concurrency,
                "entity_reports": report_rows,
                "passed": all_passed,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    fact_check_report_path = report_dir / "fact_check_report.json"
    fact_check_report_path.write_text(
        json.dumps(
            {
                "run_id": context.run_id,
                "profile": normalized_fact_check_profile,
                "web_search_enabled": fact_check_web_search,
                "llm_enabled": resolved_enable_llm,
                "no_llm_fact_check": no_llm_fact_check,
                "llm_model": fact_check_llm_model,
                "target_entity_count": len(fact_check_target_entity_ids),
                "target_entity_ids": fact_check_target_entity_ids,
                "entities": fact_check_rows,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    summary_lines = [
        f"# Fact-check summary ({normalized_fact_check_profile})",
        "",
        f"Run ID: `{context.run_id}`",
        f"Entities checked: {len(fact_check_rows)}",
        "",
    ]
    for row in fact_check_rows:
        claims = row.get("claim_count", 0)
        review_queue = row.get("review_queue", [])
        summary_lines.append(
            f"- {row['entity_id']}: claims={claims}, review_queue={len(review_queue)}"
        )
    fact_check_summary_path = report_dir / "fact_check_summary.md"
    fact_check_summary_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    write_stage_manifest(
        context,
        "validate",
        status="ok" if all_passed else "failed",
        inputs=[str(path) for path in draft_paths],
        outputs=[
            str(validation_report_path),
            str(fact_check_report_path),
            str(fact_check_summary_path),
        ],
        metadata={
            "passed": all_passed,
            "fact_check_profile": normalized_fact_check_profile,
            "web_search_enabled": fact_check_web_search,
            "llm_enabled": resolved_enable_llm,
            "no_llm_fact_check": no_llm_fact_check,
            "llm_model": fact_check_llm_model,
            "fact_check_target_entity_count": len(fact_check_target_entity_ids),
            "max_entity_concurrency": max_entity_concurrency,
        },
    )
    return {
        "passed": all_passed,
        "validation_report_path": validation_report_path,
        "fact_check_report_path": fact_check_report_path,
        "fact_check_summary_path": fact_check_summary_path,
    }


def run_addon_bundle_stage(context: RunContext) -> Path:
    output_root = build_addon_bundle(context)
    write_stage_manifest(
        context,
        "addon_bundle",
        status="ok",
        inputs=[str(context.data_dir / "drafts")],
        outputs=[str(output_root)],
        metadata={},
    )
    return output_root
