"""CLI entrypoint for staged lore pipeline commands."""

import json

import typer

from pipeline.ai.config import load_ai_settings
from pipeline.common.run_context import (
    RunArtifactsExistError,
    ensure_run_context,
    record_stage_reexecution,
)
from pipeline.orchestrator.flow import run_pipeline_flow
from pipeline.orchestrator.stages import (
    run_addon_bundle_stage,
    run_coalesce_stage,
    run_discovery_enrich_stage,
    run_discovery_stage,
    run_draft_stage,
    run_glossary_terms_stage,
    run_ingest_stage,
    run_linker_stage,
    run_traverse_stage,
    run_validate_stage,
)

app = typer.Typer(help="WoW Lore Companion pipeline CLI.")


@app.callback()
def cli() -> None:
    """CLI command group."""


@app.command()
def health(
    json_output: bool = typer.Option(default=False, help="Emit JSON status output."),
) -> None:
    """Return a simple status for bootstrap verification."""
    settings = load_ai_settings()
    ai_health = settings.as_health_payload()
    payload = {"status": "ok", "ai": ai_health}
    if json_output:
        typer.echo(json.dumps(payload))
        return
    typer.echo(
        "ok "
        f"provider={ai_health['provider']} "
        f"provider_ready={ai_health['provider_ready']} "
        f"openai_ready={ai_health['openai_ready']} "
        f"google_ready={ai_health['google_ready']}"
    )


def _echo_run(context_run_id: str, stage: str) -> None:
    typer.echo(f"run_id={context_run_id} stage={stage}")


def _normalized_fact_check_profile(value: str) -> str:
    return value.strip().lower()


def _parse_fact_check_profile(value: str) -> str:
    normalized = _normalized_fact_check_profile(value)
    if normalized not in {"off", "warn", "strict"}:
        raise typer.BadParameter(
            "fact-check profile must be one of: off, warn, strict (case-insensitive)."
        )
    return normalized


@app.command()
def ingest(run_id: str | None = typer.Option(default=None, help="Existing run id.")) -> None:
    """Run ingest stage (fetch + normalize)."""
    context = ensure_run_context(run_id)
    record_stage_reexecution(context, "ingest")
    run_ingest_stage(context)
    _echo_run(context.run_id, "ingest")


@app.command()
def discovery(run_id: str = typer.Option(..., help="Existing run id.")) -> None:
    """Run deterministic discovery artifact stage."""
    context = ensure_run_context(run_id)
    record_stage_reexecution(context, "discovery")
    source_manifest_path = context.stage_dir("ingest") / "source_manifest.json"
    outputs = run_discovery_stage(context, source_manifest_path)
    typer.echo(f"run_id={context.run_id} stage=discovery outputs={len(outputs)}")


@app.command()
def traverse(run_id: str = typer.Option(..., help="Existing run id.")) -> None:
    """Fetch auxiliary wiki pages from discovery targets."""
    context = ensure_run_context(run_id)
    record_stage_reexecution(context, "traverse_seed")
    outputs = run_traverse_stage(context)
    typer.echo(f"run_id={context.run_id} stage=traverse outputs={len(outputs)}")


@app.command(name="discovery-enrich")
def discovery_enrich(run_id: str = typer.Option(..., help="Existing run id.")) -> None:
    """Rebuild discovery graphs, decisions, and evidence after traversal."""
    context = ensure_run_context(run_id)
    record_stage_reexecution(context, "discovery_enrich")
    source_manifest_path = context.stage_dir("ingest") / "source_manifest.json"
    outputs = run_discovery_enrich_stage(context, source_manifest_path)
    typer.echo(f"run_id={context.run_id} stage=discovery_enrich outputs={len(outputs)}")


@app.command()
def addon_bundle(run_id: str = typer.Option(..., help="Existing run id.")) -> None:
    """Build addon-ingestible data bundle from drafts."""
    context = ensure_run_context(run_id)
    record_stage_reexecution(context, "addon_bundle")
    output_root = run_addon_bundle_stage(context)
    typer.echo(f"run_id={context.run_id} stage=addon_bundle output={output_root}")


@app.command()
def coalesce(
    run_id: str = typer.Option(..., help="Existing run id."),
    max_entity_concurrency: int = typer.Option(
        default=4,
        min=2,
        max=6,
        help="Per-stage entity concurrency (default 4, tunable 2-6).",
    ),
) -> None:
    """Run coalesce stage using ingest output (writes fact packs directly, S6)."""
    context = ensure_run_context(run_id)
    record_stage_reexecution(context, "coalesce")
    source_manifest_path = context.stage_dir("ingest") / "source_manifest.json"
    fact_pack_paths = run_coalesce_stage(
        context,
        source_manifest_path,
        max_entity_concurrency=max_entity_concurrency,
    )
    typer.echo(f"run_id={context.run_id} stage=coalesce outputs={len(fact_pack_paths)}")


@app.command()
def draft(
    run_id: str = typer.Option(..., help="Existing run id."),
    max_entity_concurrency: int = typer.Option(
        default=4,
        min=2,
        max=6,
        help="Per-stage entity concurrency (default 4, tunable 2-6).",
    ),
) -> None:
    """Run draft stage from extracted fact packs."""
    context = ensure_run_context(run_id)
    record_stage_reexecution(context, "draft")
    extract_dir = context.data_dir / "extracted"
    fact_pack_paths = sorted(extract_dir.glob("*.json"))
    outputs = run_draft_stage(
        context,
        fact_pack_paths,
        max_entity_concurrency=max_entity_concurrency,
    )
    typer.echo(f"run_id={context.run_id} stage=draft outputs={len(outputs)}")


@app.command(name="glossary-terms")
def glossary_terms_stage(
    run_id: str = typer.Option(..., help="Existing run id."),
) -> None:
    """Build run-scoped glossary terms from drafts and discovery artifacts."""
    context = ensure_run_context(run_id)
    record_stage_reexecution(context, "glossary_terms")
    output = run_glossary_terms_stage(context)
    typer.echo(f"run_id={context.run_id} stage=glossary_terms output={output}")


@app.command(name="link")
def link_stage(
    run_id: str = typer.Option(..., help="Existing run id."),
    max_entity_concurrency: int = typer.Option(
        default=4,
        min=2,
        max=6,
        help="Per-stage entity concurrency (default 4, tunable 2-6).",
    ),
) -> None:
    """Run glossary linker first pass."""
    context = ensure_run_context(run_id)
    record_stage_reexecution(context, "glossary_terms")
    record_stage_reexecution(context, "linker")
    run_glossary_terms_stage(context)
    draft_paths = sorted((context.data_dir / "drafts").glob("*/*.json"))
    output = run_linker_stage(
        context,
        draft_paths,
        max_entity_concurrency=max_entity_concurrency,
    )
    typer.echo(f"run_id={context.run_id} stage=linker output={output}")


@app.command()
def validate(
    run_id: str = typer.Option(..., help="Existing run id."),
    fact_check_profile: str = typer.Option(
        default="warn",
        help="Fact-check profile (off|warn|strict).",
    ),
    fact_check_web_search: bool = typer.Option(
        default=False,
        help="Enable Google web search evidence retrieval for fact-check.",
    ),
    fact_check_max_web_results: int = typer.Option(
        default=3,
        min=1,
        max=10,
        help="Max Google Custom Search hits per claim.",
    ),
    fact_check_enable_llm: bool = typer.Option(
        default=True,
        help=(
            "Enable OpenAI adjudication for unresolved claims. "
            "warn/strict profiles require LLM unless --no-llm-fact-check is set."
        ),
    ),
    no_llm_fact_check: bool = typer.Option(
        default=False,
        help="Disable LLM fact-check adjudication even for warn/strict profiles.",
    ),
    fact_check_llm_model: str = typer.Option(
        default="gpt-5.5",
        help="OpenAI model used for claim adjudication.",
    ),
    max_entity_concurrency: int = typer.Option(
        default=4,
        min=2,
        max=6,
        help="Per-stage entity concurrency (default 4, tunable 2-6).",
    ),
    release_gate: bool = typer.Option(
        False,
        "--release-gate",
        help="Apply release-gate validation severity (pointer caps and unresolved overrides hard-fail).",
    ),
) -> None:
    """Run validation stage over generated drafts."""
    normalized_profile = _parse_fact_check_profile(fact_check_profile)
    if (
        normalized_profile in {"warn", "strict"}
        and fact_check_enable_llm is False
        and not no_llm_fact_check
    ):
        raise typer.BadParameter(
            "warn/strict requires LLM adjudication by default; "
            "set --no-llm-fact-check for explicit local/dev override"
        )
    context = ensure_run_context(run_id)
    record_stage_reexecution(context, "validate")
    draft_paths = sorted((context.data_dir / "drafts").glob("*/*.json"))
    linker_report_path = context.stage_dir("linker") / "linker_qa_report.json"
    result = run_validate_stage(
        context,
        draft_paths,
        linker_report_path=linker_report_path if linker_report_path.exists() else None,
        fact_check_profile=normalized_profile,
        fact_check_web_search=fact_check_web_search,
        fact_check_max_web_results=fact_check_max_web_results,
        fact_check_enable_llm=fact_check_enable_llm,
        no_llm_fact_check=no_llm_fact_check,
        fact_check_llm_model=fact_check_llm_model,
        max_entity_concurrency=max_entity_concurrency,
        release_gate=release_gate,
    )
    typer.echo(
        f"run_id={context.run_id} stage=validate passed={result['passed']} "
        f"profile={normalized_profile} release_gate={release_gate}"
    )


@app.command(name="run")
def run_all(
    run_id: str | None = typer.Option(default=None, help="Optional run id."),
    fact_check_profile: str = typer.Option(
        default="warn",
        help="Fact-check profile (off|warn|strict).",
    ),
    fact_check_web_search: bool = typer.Option(
        default=False,
        help="Enable Google web search evidence retrieval for fact-check.",
    ),
    fact_check_max_web_results: int = typer.Option(
        default=3,
        min=1,
        max=10,
        help="Max Google Custom Search hits per claim.",
    ),
    fact_check_enable_llm: bool = typer.Option(
        default=True,
        help=(
            "Enable OpenAI adjudication for unresolved claims. "
            "warn/strict profiles require LLM unless --no-llm-fact-check is set."
        ),
    ),
    no_llm_fact_check: bool = typer.Option(
        default=False,
        help="Disable LLM fact-check adjudication even for warn/strict profiles.",
    ),
    fact_check_llm_model: str = typer.Option(
        default="gpt-5.5",
        help="OpenAI model used for claim adjudication.",
    ),
    max_entity_concurrency: int = typer.Option(
        default=4,
        min=2,
        max=6,
        help="Per-stage entity concurrency (default 4, tunable 2-6).",
    ),
    retries_per_stage: int = typer.Option(default=1, min=0, help="Retries per stage."),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Print each pipeline stage start/finish to stderr (helps during long LLM calls).",
    ),
    retail_only: bool = typer.Option(
        True,
        help="Enable retail-only filtering policy in discovery/classification stages.",
    ),
    instance_variant_policy: str = typer.Option(
        "option_a",
        help="Instance variant split policy selector (currently supports: option_a).",
    ),
    release_gate: bool = typer.Option(
        False,
        "--release-gate",
        help="Apply release-gate validation severity (pointer caps and unresolved overrides hard-fail).",
    ),
    force_new_suffix: bool = typer.Option(
        False,
        "--force-new-suffix",
        help=(
            "If the run id already has stage artifacts, auto-suffix a fresh run id "
            "(-2, -3, ...) instead of failing. Runs are immutable; there is no overwrite."
        ),
    ),
) -> None:
    """Run ingest->validate orchestration flow."""
    normalized_profile = _parse_fact_check_profile(fact_check_profile)
    if (
        normalized_profile in {"warn", "strict"}
        and fact_check_enable_llm is False
        and not no_llm_fact_check
    ):
        raise typer.BadParameter(
            "warn/strict requires LLM adjudication by default; "
            "set --no-llm-fact-check for explicit local/dev override"
        )
    try:
        result = run_pipeline_flow(
            run_id=run_id,
            fact_check_profile=normalized_profile,
            fact_check_web_search=fact_check_web_search,
            fact_check_max_web_results=fact_check_max_web_results,
            fact_check_enable_llm=fact_check_enable_llm,
            no_llm_fact_check=no_llm_fact_check,
            fact_check_llm_model=fact_check_llm_model,
            max_entity_concurrency=max_entity_concurrency,
            retries_per_stage=retries_per_stage,
            verbose=verbose,
            release_gate=release_gate,
            force_new_suffix=force_new_suffix,
        )
    except RunArtifactsExistError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        f"run_id={result['run_id']} validate_passed={result['validate']['passed']} "
        f"profile={normalized_profile} release_gate={release_gate} retail_only={retail_only} "
        f"instance_variant_policy={instance_variant_policy}"
    )


def main() -> None:
    """Script entrypoint used by `lore-pipeline`."""
    app()


if __name__ == "__main__":
    main()
