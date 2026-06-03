from pathlib import Path

from pipeline.common.run_context import ensure_run_context
from pipeline.orchestrator.flow import run_pipeline_flow


def test_run_pipeline_flow_passes_linker_report_to_validate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    context = ensure_run_context("run-test-flow-linker-handoff", artifacts_root=tmp_path / "runs")

    monkeypatch.setattr(
        "pipeline.orchestrator.flow.ensure_run_context",
        lambda _run_id=None: context,
    )

    ingest_manifest = context.stage_dir("ingest") / "source_manifest.json"
    ingest_manifest.write_text("[]", encoding="utf-8")
    coalesced_path = context.data_dir / "coalesced" / "entities.jsonl"
    coalesced_path.parent.mkdir(parents=True, exist_ok=True)
    coalesced_path.write_text("", encoding="utf-8")
    extracted_path = context.data_dir / "extracted" / "zone-western-plaguelands.json"
    extracted_path.parent.mkdir(parents=True, exist_ok=True)
    extracted_path.write_text("{}", encoding="utf-8")
    draft_path = context.data_dir / "drafts" / "zone" / "zone-western-plaguelands.json"
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    draft_path.write_text('{"id":"zone-western-plaguelands"}', encoding="utf-8")
    linker_path = context.stage_dir("linker") / "linker_qa_report.json"
    linker_path.write_text("{}", encoding="utf-8")
    validation_path = context.reports_dir / "validate" / "validation_report.json"
    fact_check_report_path = context.reports_dir / "validate" / "fact_check_report.json"
    fact_check_summary_path = context.reports_dir / "validate" / "fact_check_summary.md"
    validation_path.parent.mkdir(parents=True, exist_ok=True)
    validation_path.write_text("{}", encoding="utf-8")
    fact_check_report_path.write_text("{}", encoding="utf-8")
    fact_check_summary_path.write_text("# summary\n", encoding="utf-8")

    monkeypatch.setattr(
        "pipeline.orchestrator.flow.run_ingest_stage",
        lambda _context: {
            "snapshots_path": context.stage_dir("ingest") / "source_snapshots.json",
            "source_manifest_path": ingest_manifest,
        },
    )
    monkeypatch.setattr(
        "pipeline.orchestrator.flow.run_discovery_stage",
        lambda _context, _manifest_path: {},
    )
    monkeypatch.setattr(
        "pipeline.orchestrator.flow.run_traverse_seed_stage",
        lambda _context: {},
    )
    monkeypatch.setattr(
        "pipeline.orchestrator.flow.run_traverse_quests_stage",
        lambda _context: {},
    )
    monkeypatch.setattr(
        "pipeline.orchestrator.flow.run_discovery_enrich_stage",
        lambda _context, _manifest_path, **_kw: {},
    )
    monkeypatch.setattr(
        "pipeline.orchestrator.flow.run_coalesce_stage",
        lambda _context, _manifest_path, max_entity_concurrency=4, **_kw: coalesced_path,
    )
    monkeypatch.setattr(
        "pipeline.orchestrator.flow.run_extract_stage",
        lambda _context, _coalesced_path, max_entity_concurrency=4, **_kw: [extracted_path],
    )
    monkeypatch.setattr(
        "pipeline.orchestrator.flow.run_draft_stage",
        lambda _context, _extracted_paths, max_entity_concurrency=4, **_kw: [draft_path],
    )
    monkeypatch.setattr(
        "pipeline.orchestrator.flow.run_linker_stage",
        lambda _context, _draft_paths, max_entity_concurrency=4, **_kw: linker_path,
    )

    observed = {"linker_report_path": None}

    def fake_validate(
        _context,
        _draft_paths,
        *,
        linker_report_path=None,
        **_kwargs,
    ):
        observed["linker_report_path"] = linker_report_path
        return {
            "passed": True,
            "validation_report_path": validation_path,
            "fact_check_report_path": fact_check_report_path,
            "fact_check_summary_path": fact_check_summary_path,
        }

    monkeypatch.setattr("pipeline.orchestrator.flow.run_validate_stage", fake_validate)
    monkeypatch.setattr(
        "pipeline.orchestrator.flow.run_addon_bundle_stage",
        lambda _context: _context.root_dir / "build" / "lua",
    )

    result = run_pipeline_flow(run_id=context.run_id, retries_per_stage=0)
    assert result["validate"]["passed"] is True
    assert observed["linker_report_path"] == linker_path


def test_run_pipeline_flow_retries_failed_stage_once(tmp_path: Path, monkeypatch) -> None:
    context = ensure_run_context("run-test-flow-retry", artifacts_root=tmp_path / "runs")
    monkeypatch.setattr(
        "pipeline.orchestrator.flow.ensure_run_context",
        lambda _run_id=None: context,
    )

    attempts = {"ingest": 0}
    ingest_manifest = context.stage_dir("ingest") / "source_manifest.json"
    ingest_manifest.write_text("[]", encoding="utf-8")

    def flaky_ingest(_context):
        attempts["ingest"] += 1
        if attempts["ingest"] == 1:
            raise RuntimeError("transient ingest error")
        return {
            "snapshots_path": context.stage_dir("ingest") / "source_snapshots.json",
            "source_manifest_path": ingest_manifest,
        }

    monkeypatch.setattr("pipeline.orchestrator.flow.run_ingest_stage", flaky_ingest)
    monkeypatch.setattr(
        "pipeline.orchestrator.flow.run_discovery_stage",
        lambda _context, _manifest_path: {},
    )
    monkeypatch.setattr(
        "pipeline.orchestrator.flow.run_traverse_seed_stage",
        lambda _context: {},
    )
    monkeypatch.setattr(
        "pipeline.orchestrator.flow.run_traverse_quests_stage",
        lambda _context: {},
    )
    monkeypatch.setattr(
        "pipeline.orchestrator.flow.run_discovery_enrich_stage",
        lambda _context, _manifest_path, **_kw: {},
    )
    monkeypatch.setattr(
        "pipeline.orchestrator.flow.run_coalesce_stage",
        lambda _context, _manifest_path, max_entity_concurrency=4, **_kw: (
            context.data_dir / "coalesced" / "entities.jsonl"
        ),
    )
    monkeypatch.setattr(
        "pipeline.orchestrator.flow.run_extract_stage",
        lambda _context, _coalesced_path, max_entity_concurrency=4, **_kw: [],
    )
    monkeypatch.setattr(
        "pipeline.orchestrator.flow.run_draft_stage",
        lambda _context, _extracted_paths, max_entity_concurrency=4, **_kw: [],
    )
    monkeypatch.setattr(
        "pipeline.orchestrator.flow.run_linker_stage",
        lambda _context, _draft_paths, max_entity_concurrency=4, **_kw: (
            context.stage_dir("linker") / "linker_qa_report.json"
        ),
    )
    monkeypatch.setattr(
        "pipeline.orchestrator.flow.run_validate_stage",
        lambda _context, _draft_paths, **_kwargs: {
            "passed": True,
            "validation_report_path": context.reports_dir / "validate" / "validation_report.json",
            "fact_check_report_path": context.reports_dir / "validate" / "fact_check_report.json",
            "fact_check_summary_path": context.reports_dir / "validate" / "fact_check_summary.md",
        },
    )
    monkeypatch.setattr(
        "pipeline.orchestrator.flow.run_addon_bundle_stage",
        lambda _context: _context.root_dir / "build" / "lua",
    )

    result = run_pipeline_flow(run_id=context.run_id, retries_per_stage=1)
    assert result["validate"]["passed"] is True
    assert attempts["ingest"] == 2


def test_run_pipeline_flow_orders_enrich_phases_around_quest_traverse(
    tmp_path: Path,
    monkeypatch,
) -> None:
    context = ensure_run_context("run-test-flow-enrich-order", artifacts_root=tmp_path / "runs")
    monkeypatch.setattr(
        "pipeline.orchestrator.flow.ensure_run_context",
        lambda _run_id=None: context,
    )

    ingest_manifest = context.stage_dir("ingest") / "source_manifest.json"
    ingest_manifest.write_text("[]", encoding="utf-8")
    coalesced_path = context.data_dir / "coalesced" / "entities.jsonl"
    coalesced_path.parent.mkdir(parents=True, exist_ok=True)
    coalesced_path.write_text("", encoding="utf-8")
    validation_path = context.reports_dir / "validate" / "validation_report.json"
    fact_check_report_path = context.reports_dir / "validate" / "fact_check_report.json"
    fact_check_summary_path = context.reports_dir / "validate" / "fact_check_summary.md"
    validation_path.parent.mkdir(parents=True, exist_ok=True)
    validation_path.write_text("{}", encoding="utf-8")
    fact_check_report_path.write_text("{}", encoding="utf-8")
    fact_check_summary_path.write_text("# summary\n", encoding="utf-8")

    stage_calls: list[str] = []
    enrich_phases: list[str] = []

    def record(stage_name: str):
        def _runner(*_args, **_kwargs):
            stage_calls.append(stage_name)
            return {}

        return _runner

    def record_enrich(_context, _manifest_path, **kwargs):
        stage_calls.append("discovery_enrich")
        enrich_phases.append(str(kwargs.get("phase", "")))
        return {}

    monkeypatch.setattr(
        "pipeline.orchestrator.flow.run_ingest_stage",
        lambda _context: {
            "snapshots_path": context.stage_dir("ingest") / "source_snapshots.json",
            "source_manifest_path": ingest_manifest,
        },
    )
    monkeypatch.setattr("pipeline.orchestrator.flow.run_discovery_stage", record("discovery"))
    monkeypatch.setattr("pipeline.orchestrator.flow.run_traverse_seed_stage", record("traverse_seed"))
    monkeypatch.setattr("pipeline.orchestrator.flow.run_traverse_quests_stage", record("traverse_quests"))
    monkeypatch.setattr("pipeline.orchestrator.flow.run_discovery_enrich_stage", record_enrich)
    monkeypatch.setattr(
        "pipeline.orchestrator.flow.run_coalesce_stage",
        lambda _context, _manifest_path, max_entity_concurrency=4, **_kw: coalesced_path,
    )
    monkeypatch.setattr(
        "pipeline.orchestrator.flow.run_extract_stage",
        lambda _context, _coalesced_path, max_entity_concurrency=4, **_kw: [],
    )
    monkeypatch.setattr(
        "pipeline.orchestrator.flow.run_draft_stage",
        lambda _context, _extracted_paths, max_entity_concurrency=4, **_kw: [],
    )
    monkeypatch.setattr(
        "pipeline.orchestrator.flow.run_linker_stage",
        lambda _context, _draft_paths, max_entity_concurrency=4, **_kw: (
            context.stage_dir("linker") / "linker_qa_report.json"
        ),
    )
    monkeypatch.setattr(
        "pipeline.orchestrator.flow.run_validate_stage",
        lambda _context, _draft_paths, **_kwargs: {
            "passed": True,
            "validation_report_path": validation_path,
            "fact_check_report_path": fact_check_report_path,
            "fact_check_summary_path": fact_check_summary_path,
        },
    )
    monkeypatch.setattr(
        "pipeline.orchestrator.flow.run_addon_bundle_stage",
        lambda _context: _context.root_dir / "build" / "lua",
    )

    run_pipeline_flow(run_id=context.run_id, retries_per_stage=0)

    assert enrich_phases == ["roster", "evidence_merge"]
    first_enrich_idx = stage_calls.index("discovery_enrich")
    quests_idx = stage_calls.index("traverse_quests")
    second_enrich_idx = stage_calls.index("discovery_enrich", first_enrich_idx + 1)
    assert stage_calls.index("traverse_seed") < first_enrich_idx < quests_idx < second_enrich_idx
