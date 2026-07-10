"""Reusable stage runners for CLI and orchestration flow."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, cast

from pipeline.addon import build_addon_bundle
from pipeline.ai.config import load_ai_settings
from pipeline.coalesce.resolve_entities import run_resolve_entities
from pipeline.common.io import write_json
from pipeline.common.run_context import RunContext, append_trace_event, write_stage_manifest
from pipeline.discovery import run_discovery_workflow
from pipeline.discovery.enrich import EnrichPhase, run_discovery_enrich
from pipeline.discovery.instance_bosses import row_has_roster_role
from pipeline.generate.draft_writer import run_draft_writer
from pipeline.glossary.run_terms import build_run_terms
from pipeline.ingest.fetch_wiki import run_fetch_wiki
from pipeline.ingest.normalize_source import run_normalize_source
from pipeline.ingest.traverse_wiki import run_traverse_quests, run_traverse_seed
from pipeline.ingest.wiki_redirects import annotate_snapshots_with_canonical_identity
from pipeline.linker.linker import run_glossary_linker
from pipeline.validate.context import (
    build_entity_validation_context,
    load_validation_run_resources_from_context,
    resolve_draft_entity_id,
)
from pipeline.validate.engine import validate_payload


def run_ingest_stage(context: RunContext) -> dict[str, Path]:
    snapshots_path = run_fetch_wiki(context)
    redirect_meta = _resolve_instance_roster_identities(context, snapshots_path)
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
        metadata={
            "record_count": len(manifest_rows),
            "retrieval_modes": retrieval_modes,
            **redirect_meta,
        },
    )
    return {"snapshots_path": snapshots_path, "source_manifest_path": manifest_path}


def _resolve_instance_roster_identities(
    context: RunContext, snapshots_path: Path
) -> dict[str, Any]:
    """Resolve roster-link canonical identity (redirects/page ids) into snapshots.

    Best-effort: the core fetch already succeeded, so a wiki query hiccup must not
    fail ingest. On error we leave snapshots unannotated and record the reason.
    Disabled via ``WOW_LORE_INGEST_RESOLVE_REDIRECTS=0`` (tests default to off so
    they never reach the live wiki API).
    """
    if os.environ.get("WOW_LORE_INGEST_RESOLVE_REDIRECTS", "1").lower() in {"0", "false", "no"}:
        return {"redirect_resolution": "disabled"}
    try:
        snapshots = json.loads(snapshots_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"redirect_resolution": "skipped", "redirect_error": repr(exc)}
    if not isinstance(snapshots, list):
        return {"redirect_resolution": "skipped"}

    try:
        run_map = annotate_snapshots_with_canonical_identity(
            snapshots,
            roster_predicate=row_has_roster_role,
        )
    except Exception as exc:  # noqa: BLE001 - resolution is a best-effort enhancement
        return {"redirect_resolution": "error", "redirect_error": repr(exc)}

    write_json(snapshots_path, snapshots)
    map_path = context.stage_dir("ingest") / "wiki_redirect_map.json"
    write_json(map_path, run_map)
    return {"redirect_resolution": "ok", "redirect_resolved_count": len(run_map)}


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
        inputs=[
            str(source_manifest_path),
            str(context.stage_dir("ingest") / "source_snapshots.json"),
        ],
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
                for row in json.loads(outputs["traversal_report"].read_text(encoding="utf-8")).get(
                    "entries", []
                )
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
                for row in json.loads(outputs["traversal_report"].read_text(encoding="utf-8")).get(
                    "entries", []
                )
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
        inputs=[
            str(source_manifest_path),
            str(context.stage_dir("ingest") / "source_snapshots.json"),
        ],
        outputs=[str(path) for path in outputs.values()],
        metadata={"artifact_count": len(outputs), "phase": phase},
    )
    return outputs


def run_coalesce_stage(
    context: RunContext,
    source_manifest_path: Path,
    *,
    max_entity_concurrency: int = 4,
) -> list[Path]:
    """Run coalesce and return the fact-pack paths it writes (Extract folded in, S6)."""
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
        output_path, fact_pack_paths = run_resolve_entities(
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
        outputs=[str(output_path), *(str(path) for path in fact_pack_paths)],
        metadata={"max_entity_concurrency": max_entity_concurrency},
    )
    return fact_pack_paths


def run_draft_stage(
    context: RunContext,
    fact_pack_paths: list[Path],
    *,
    max_entity_concurrency: int = 4,
    verbose: bool = False,
    release_gate: bool = False,
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
        if release_gate:
            forced_no_llm = os.environ.get("WOW_LORE_WIKI_FIRST_NO_LLM", "").lower() in {
                "1",
                "true",
                "yes",
            }
            settings = load_ai_settings()
            if forced_no_llm or not getattr(settings, "openai_ready", False):
                raise RuntimeError(
                    "release-gate draft requires OpenAI-backed prose synthesis; "
                    "unset WOW_LORE_WIKI_FIRST_NO_LLM and configure OPENAI_API_KEY"
                )
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
        metadata={"max_entity_concurrency": max_entity_concurrency, "release_gate": release_gate},
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
    release_gate: bool = False,
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
    resources = load_validation_run_resources_from_context(context)
    linker_manual_review_by_entity = resources.linker_manual_review_by_entity
    fact_check_target_entity_ids = resources.fact_check_target_entity_ids

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

    def _validate_one(draft_path: Path) -> tuple[dict[str, Any], dict[str, Any] | None]:
        raw_payload = json.loads(draft_path.read_text(encoding="utf-8"))
        payload = raw_payload if isinstance(raw_payload, dict) else {}
        entity_id = resolve_draft_entity_id(draft_path, payload)
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
                validation_context=build_entity_validation_context(
                    entity_id=entity_id,
                    fact_check_profile=normalized_fact_check_profile,
                    release_gate=release_gate,
                    resources=resources,
                    fact_check_web_search=fact_check_web_search,
                    fact_check_max_web_results=fact_check_max_web_results,
                    fact_check_enable_llm=bool(resolved_enable_llm),
                    fact_check_llm_model=fact_check_llm_model,
                ),
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
                "$.glossary_refs" if entity_type in {"zone_page", "instance_page"} else "$.glossary"
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

    # Slice 8, item 5: a run is *release-certified* only when every entity passed under the strict
    # release gate. A warn/off pass remains useful for exploration but is never labelled equivalent
    # to a strict successful run.
    release_certified = all_passed and release_gate and normalized_fact_check_profile == "strict"

    report_dir = context.reports_dir / "validate"
    report_dir.mkdir(parents=True, exist_ok=True)

    validation_report_path = report_dir / "validation_report.json"
    write_json(
        validation_report_path,
        {
            "run_id": context.run_id,
            "fact_check_profile": normalized_fact_check_profile,
            "release_gate": release_gate,
            "no_llm_fact_check": no_llm_fact_check,
            "llm_model": fact_check_llm_model,
            "fact_check_target_entity_count": len(fact_check_target_entity_ids),
            "fact_check_target_entity_ids": fact_check_target_entity_ids,
            "max_entity_concurrency": max_entity_concurrency,
            "entity_reports": report_rows,
            "passed": all_passed,
            "release_certified": release_certified,
        },
    )

    fact_check_report_path = report_dir / "fact_check_report.json"
    write_json(
        fact_check_report_path,
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
            "release_certified": release_certified,
            "fact_check_profile": normalized_fact_check_profile,
            "release_gate": release_gate,
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
        "release_gate": release_gate,
        "fact_check_profile": normalized_fact_check_profile,
        "release_certified": release_certified,
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
