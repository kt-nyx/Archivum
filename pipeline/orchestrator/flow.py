"""Prefect orchestration flow for ingest-to-validate pipeline execution."""

from __future__ import annotations

import sys
from collections.abc import Callable
from time import perf_counter
from typing import Any

from prefect import flow

from pipeline.common.run_context import (
    append_trace_event,
    ensure_run_context,
    write_stage_manifest,
)
from pipeline.orchestrator.stages import (
    run_addon_bundle_stage,
    run_coalesce_stage,
    run_discovery_enrich_stage,
    run_discovery_stage,
    run_draft_stage,
    run_extract_stage,
    run_glossary_terms_stage,
    run_ingest_stage,
    run_linker_stage,
    run_traverse_quests_stage,
    run_traverse_seed_stage,
    run_validate_stage,
)


def _run_stage_with_retry[T](
    stage_name: str,
    stage_fn: Callable[[], T],
    *,
    retries: int,
    on_fail_manifest_inputs: list[str],
    on_fail_manifest_outputs: list[str],
    run_id: str,
    verbose: bool = False,
) -> T:
    context = ensure_run_context(run_id)
    for attempt in range(1, retries + 2):
        try:
            started_at = perf_counter()
            append_trace_event(
                context,
                stage_name=stage_name,
                attempt=attempt,
                status="start",
            )
            if verbose:
                print(
                    f"[lore-pipeline] run_id={run_id} stage={stage_name} attempt={attempt} "
                    "starting...",
                    file=sys.stderr,
                    flush=True,
                )
            result = stage_fn()
            duration_ms = int((perf_counter() - started_at) * 1000)
            append_trace_event(
                context,
                stage_name=stage_name,
                attempt=attempt,
                status="success",
                details={"duration_ms": duration_ms},
            )
            if verbose:
                print(
                    f"[lore-pipeline] run_id={run_id} stage={stage_name} attempt={attempt} "
                    f"done duration_ms={duration_ms}",
                    file=sys.stderr,
                    flush=True,
                )
            return result
        except Exception as exc:  # pragma: no cover - exercised by manual failures
            append_trace_event(
                context,
                stage_name=stage_name,
                attempt=attempt,
                status="error",
                details={"error": repr(exc)},
            )
            if attempt > retries:
                write_stage_manifest(
                    context,
                    stage_name,
                    status="failed",
                    inputs=on_fail_manifest_inputs,
                    outputs=on_fail_manifest_outputs,
                    retries=retries,
                    escalated=True,
                    metadata={"error": repr(exc)},
                )
                raise
    raise RuntimeError(f"stage {stage_name} did not run")


@flow(name="lore-pipeline-ingest-to-validate", log_prints=True)
def run_pipeline_flow(
    *,
    run_id: str | None = None,
    fact_check_profile: str = "warn",
    fact_check_web_search: bool = False,
    fact_check_max_web_results: int = 3,
    fact_check_enable_llm: bool | None = None,
    fact_check_llm_model: str = "gpt-5.5",
    max_entity_concurrency: int = 4,
    no_llm_fact_check: bool = False,
    retries_per_stage: int = 1,
    verbose: bool = False,
    release_gate: bool = False,
) -> dict[str, Any]:
    """Run staged ingest->validate flow with retries and trace artifacts."""
    context = ensure_run_context(run_id)

    ingest_output = _run_stage_with_retry(
        "ingest",
        lambda: run_ingest_stage(context),
        retries=retries_per_stage,
        on_fail_manifest_inputs=[],
        on_fail_manifest_outputs=[],
        run_id=context.run_id,
        verbose=verbose,
    )
    _run_stage_with_retry(
        "discovery",
        lambda: run_discovery_stage(context, ingest_output["source_manifest_path"]),
        retries=retries_per_stage,
        on_fail_manifest_inputs=[str(ingest_output["source_manifest_path"])],
        on_fail_manifest_outputs=[],
        run_id=context.run_id,
        verbose=verbose,
    )
    _run_stage_with_retry(
        "traverse_seed",
        lambda: run_traverse_seed_stage(context),
        retries=retries_per_stage,
        on_fail_manifest_inputs=[str(ingest_output["source_manifest_path"])],
        on_fail_manifest_outputs=[],
        run_id=context.run_id,
        verbose=verbose,
    )
    coalesced_path = _run_stage_with_retry(
        "coalesce",
        lambda: run_coalesce_stage(
            context,
            ingest_output["source_manifest_path"],
            max_entity_concurrency=max_entity_concurrency,
        ),
        retries=retries_per_stage,
        on_fail_manifest_inputs=[str(ingest_output["source_manifest_path"])],
        on_fail_manifest_outputs=[],
        run_id=context.run_id,
        verbose=verbose,
    )
    _run_stage_with_retry(
        "discovery_enrich",
        lambda: run_discovery_enrich_stage(
            context,
            ingest_output["source_manifest_path"],
            phase="roster",
        ),
        retries=retries_per_stage,
        on_fail_manifest_inputs=[str(coalesced_path)],
        on_fail_manifest_outputs=[],
        run_id=context.run_id,
        verbose=verbose,
    )
    _run_stage_with_retry(
        "traverse_quests",
        lambda: run_traverse_quests_stage(context),
        retries=retries_per_stage,
        on_fail_manifest_inputs=[str(context.data_dir / "discovery" / "zone_quest_graph_v3.json")],
        on_fail_manifest_outputs=[],
        run_id=context.run_id,
        verbose=verbose,
    )
    _run_stage_with_retry(
        "discovery_enrich",
        lambda: run_discovery_enrich_stage(
            context,
            ingest_output["source_manifest_path"],
            phase="cluster",
        ),
        retries=retries_per_stage,
        on_fail_manifest_inputs=[str(coalesced_path)],
        on_fail_manifest_outputs=[],
        run_id=context.run_id,
        verbose=verbose,
    )
    _run_stage_with_retry(
        "discovery_enrich",
        lambda: run_discovery_enrich_stage(
            context,
            ingest_output["source_manifest_path"],
            phase="evidence_merge",
        ),
        retries=retries_per_stage,
        on_fail_manifest_inputs=[str(coalesced_path)],
        on_fail_manifest_outputs=[],
        run_id=context.run_id,
        verbose=verbose,
    )
    extracted_paths = _run_stage_with_retry(
        "extract",
        lambda: run_extract_stage(
            context,
            coalesced_path,
            max_entity_concurrency=max_entity_concurrency,
        ),
        retries=retries_per_stage,
        on_fail_manifest_inputs=[str(coalesced_path)],
        on_fail_manifest_outputs=[],
        run_id=context.run_id,
        verbose=verbose,
    )
    draft_paths = _run_stage_with_retry(
        "draft",
        lambda: run_draft_stage(
            context,
            extracted_paths,
            max_entity_concurrency=max_entity_concurrency,
            verbose=verbose,
        ),
        retries=retries_per_stage,
        on_fail_manifest_inputs=[str(path) for path in extracted_paths],
        on_fail_manifest_outputs=[],
        run_id=context.run_id,
        verbose=verbose,
    )
    _run_stage_with_retry(
        "glossary_terms",
        lambda: run_glossary_terms_stage(context),
        retries=retries_per_stage,
        on_fail_manifest_inputs=[str(path) for path in draft_paths],
        on_fail_manifest_outputs=[],
        run_id=context.run_id,
        verbose=verbose,
    )
    linker_report_path = _run_stage_with_retry(
        "linker",
        lambda: run_linker_stage(
            context,
            draft_paths,
            max_entity_concurrency=max_entity_concurrency,
        ),
        retries=retries_per_stage,
        on_fail_manifest_inputs=[
            str(path) for path in draft_paths
        ] + [str(context.data_dir / "glossary" / "run_terms.jsonl")],
        on_fail_manifest_outputs=[],
        run_id=context.run_id,
        verbose=verbose,
    )
    validate_output = _run_stage_with_retry(
        "validate",
        lambda: run_validate_stage(
            context,
            draft_paths,
            linker_report_path=linker_report_path,
            fact_check_profile=fact_check_profile,
            fact_check_web_search=fact_check_web_search,
            fact_check_max_web_results=fact_check_max_web_results,
            fact_check_enable_llm=fact_check_enable_llm,
            fact_check_llm_model=fact_check_llm_model,
            max_entity_concurrency=max_entity_concurrency,
            no_llm_fact_check=no_llm_fact_check,
            release_gate=release_gate,
        ),
        retries=retries_per_stage,
        on_fail_manifest_inputs=[str(path) for path in draft_paths],
        on_fail_manifest_outputs=[],
        run_id=context.run_id,
        verbose=verbose,
    )
    addon_bundle_path = _run_stage_with_retry(
        "addon_bundle",
        lambda: run_addon_bundle_stage(context),
        retries=retries_per_stage,
        on_fail_manifest_inputs=[str(context.data_dir / "drafts")],
        on_fail_manifest_outputs=[],
        run_id=context.run_id,
        verbose=verbose,
    )

    append_trace_event(
        context,
        stage_name="pipeline",
        attempt=1,
        status="success" if validate_output["passed"] else "failed",
        details={"linker_report_path": str(linker_report_path)},
    )
    return {
        "run_id": context.run_id,
        "root_dir": str(context.root_dir),
        "addon_bundle_path": str(addon_bundle_path),
        "linker_report_path": str(linker_report_path),
        "validate": {
            "passed": bool(validate_output["passed"]),
            "validation_report_path": str(validate_output["validation_report_path"]),
            "fact_check_report_path": str(validate_output["fact_check_report_path"]),
            "fact_check_summary_path": str(validate_output["fact_check_summary_path"]),
        },
    }
