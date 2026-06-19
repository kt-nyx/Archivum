"""Prefect orchestration flow for ingest-to-validate pipeline execution."""

from __future__ import annotations

import sys
from collections.abc import Callable
from time import perf_counter
from typing import Any

from prefect import flow, task
from prefect.runtime import task_run

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
    """Run a stage as a Prefect task with native ``retries=``.

    Retry orchestration is delegated to Prefect (``retries`` + zero delay). The custom
    per-attempt trace events (``start`` / ``success`` / ``error``) and the escalation manifest
    written when all attempts are exhausted are preserved as before — attempts are read from the
    Prefect runtime (``task_run.run_count``, 1-based and incremented per attempt) and the
    final-failure manifest is emitted from the task's ``on_failure`` hook.
    """
    context = ensure_run_context(run_id)
    last_error: dict[str, BaseException | None] = {"exc": None}

    def _escalate_on_failure(_task: Any, _task_run: Any, _state: Any) -> None:
        write_stage_manifest(
            context,
            stage_name,
            status="failed",
            inputs=on_fail_manifest_inputs,
            outputs=on_fail_manifest_outputs,
            retries=retries,
            escalated=True,
            metadata={"error": repr(last_error["exc"])},
        )

    @task(
        name=stage_name,
        retries=retries,
        retry_delay_seconds=0,
        on_failure=[_escalate_on_failure],
    )
    def _stage_task() -> T:
        attempt = task_run.run_count
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
        try:
            result = stage_fn()
        except Exception as exc:
            last_error["exc"] = exc
            append_trace_event(
                context,
                stage_name=stage_name,
                attempt=attempt,
                status="error",
                details={"error": repr(exc)},
            )
            raise
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

    return _stage_task()


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
    # Coalesce now writes fact packs directly (Extract folded in, S6); it returns
    # the fact-pack paths. The coalesced entity graph stays at this known path,
    # referenced by the downstream enrich failure manifests.
    coalesce_entities_path = context.data_dir / "coalesced" / "entities.jsonl"
    fact_pack_paths = _run_stage_with_retry(
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
        on_fail_manifest_inputs=[str(coalesce_entities_path)],
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
        on_fail_manifest_inputs=[str(coalesce_entities_path)],
        on_fail_manifest_outputs=[],
        run_id=context.run_id,
        verbose=verbose,
    )
    _run_stage_with_retry(
        "discovery_enrich",
        lambda: run_discovery_enrich_stage(
            context,
            ingest_output["source_manifest_path"],
            phase="significance",
        ),
        retries=retries_per_stage,
        on_fail_manifest_inputs=[str(coalesce_entities_path)],
        on_fail_manifest_outputs=[],
        run_id=context.run_id,
        verbose=verbose,
    )
    _run_stage_with_retry(
        "discovery_enrich",
        lambda: run_discovery_enrich_stage(
            context,
            ingest_output["source_manifest_path"],
            phase="card_polish",
        ),
        retries=retries_per_stage,
        on_fail_manifest_inputs=[str(coalesce_entities_path)],
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
        on_fail_manifest_inputs=[str(coalesce_entities_path)],
        on_fail_manifest_outputs=[],
        run_id=context.run_id,
        verbose=verbose,
    )
    draft_paths = _run_stage_with_retry(
        "draft",
        lambda: run_draft_stage(
            context,
            fact_pack_paths,
            max_entity_concurrency=max_entity_concurrency,
            verbose=verbose,
        ),
        retries=retries_per_stage,
        on_fail_manifest_inputs=[str(path) for path in fact_pack_paths],
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
