import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline.coalesce.resolve_entities import run_resolve_entities
from pipeline.common.run_context import ensure_run_context
from pipeline.ingest.fetch_wiki import FetchedSource
from pipeline.ingest.normalize_source import run_normalize_source
from pipeline.orchestrator.stages import (
    run_coalesce_stage,
    run_discovery_enrich_stage,
    run_discovery_stage,
    run_draft_stage,
    run_ingest_stage,
    run_linker_stage,
    run_traverse_quests_stage,
    run_traverse_seed_stage,
    run_validate_stage,
)
from tests.draft_llm_mocks import fake_draft_chat_by_schema
from tests.factories.snapshots import with_required_snapshot_schema

STORYLINE_HTML = Path("tests/fixtures/storyline/western_plaguelands_storyline.html").read_text(
    encoding="utf-8"
)

# Minimal Questbox parse tree so quest fetches yield a structured QuestRecord.
QUEST_PARSETREE = (
    "<root><template><title>Questbox</title>"
    "<part><name> start </name><equals>=</equals>"
    "<value> [[Quest Giver]] {{Co|50.0|50.0|Example Zone}}\n</value></part>"
    "<part><name> category </name><equals>=</equals><value> Example Zone\n</value></part>"
    "</template>\n</root>\n"
)


def _seed_manifest(context_root: Path) -> None:
    fixture = Path("tests/fixtures/pilot/source_manifest.json")
    context_root.joinpath("source_manifest.json").write_text(
        fixture.read_text(encoding="utf-8"),
        encoding="utf-8",
    )


def _mock_generation_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    ready_settings = SimpleNamespace(
        openai_ready=True,
        openai_model="gpt-5.5",
        openai_reasoning_effort=None,
        openai_verbosity=None,
        openai_draft_reasoning_effort=None,
        openai_draft_verbosity=None,
        openai_use_responses_api=False,
        openai_request_timeout_seconds=600,
    )
    monkeypatch.setattr(
        "pipeline.coalesce.resolve_entities.load_ai_settings",
        lambda: ready_settings,
    )
    for target in (
        "pipeline.generate.draft_writer.load_ai_settings",
        "pipeline.generate.draft.llm.load_ai_settings",
    ):
        monkeypatch.setattr(target, lambda: ready_settings)

    def fake_fetch(
        url: str, source_class: str, *, include_parsetree: bool = False
    ) -> FetchedSource:
        if "storyline" in url.lower():
            return FetchedSource(
                "Example Zone storyline overview.",
                "mw:storyline",
                "section:lead paragraph:1",
                [{"section_role": "part_1", "text": "Part 1 - The first battle for Andorhal"}],
                [],
                [],
                STORYLINE_HTML,
            )
        section_blocks = [
            {"section_role": "lead", "text": "Lead evidence."},
            {
                "section_role": "history",
                "text": "Historical arc about the capital district and undead forces.",
            },
            {
                "section_role": "quests_edit",
                "text": "Current quest activity around the capital district.",
            },
            {
                "section_role": "cataclysm_edit",
                "text": "Cataclysm recovery efforts continue across the zone.",
            },
        ]
        base = (
            f"{source_class} source evidence for {url} with campaign chronology and factions.",
            "mw:123456",
            "section:lead paragraph:1",
            section_blocks,
            ["/wiki/Example_Zone_storyline"],
            [
                {
                    "href": "/wiki/Example_Zone_storyline",
                    "section_role": "quests",
                    "label": "storyline",
                }
            ],
            "",
        )
        if include_parsetree:
            return FetchedSource(*base, parse_tree=QUEST_PARSETREE)
        return FetchedSource(*base)

    def fake_coalesce_chat(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {
            "claims": [
                "The region remains contested by military and undead forces.",
                "Faction campaigns emphasize route security and recovery operations.",
            ]
        }

    def fake_draft_chat(*args: object, **kwargs: object) -> dict[str, object] | None:
        result = fake_draft_chat_by_schema(*args, **kwargs)
        assert result is not None
        return result

    monkeypatch.setattr("pipeline.ingest.fetch_wiki._fetch_url_text", fake_fetch)
    monkeypatch.setattr("pipeline.ingest.traverse_wiki._fetch_url_text", fake_fetch)
    monkeypatch.setattr("pipeline.ingest.traverse_wiki._throttle", lambda seconds: None)
    monkeypatch.setattr(
        "pipeline.coalesce.resolve_entities.chat_json_completion",
        fake_coalesce_chat,
    )
    for target in (
        "pipeline.generate.draft.llm.chat_json_completion",
        "pipeline.generate.draft_writer.chat_json_completion",
    ):
        monkeypatch.setattr(target, fake_draft_chat)


def test_ingest_to_validate_stage_chain_emits_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_generation_dependencies(monkeypatch)
    context = ensure_run_context("run-test-stage-chain", artifacts_root=tmp_path / "runs")
    _seed_manifest(context.root_dir)
    ingest_output = run_ingest_stage(context)
    fact_pack_paths = run_coalesce_stage(
        context,
        ingest_output["source_manifest_path"],
        max_entity_concurrency=4,
    )
    draft_paths = run_draft_stage(context, fact_pack_paths, max_entity_concurrency=4)
    linker_report = run_linker_stage(context, draft_paths, max_entity_concurrency=4)
    validate_output = run_validate_stage(
        context,
        draft_paths,
        fact_check_profile="warn",
        no_llm_fact_check=True,
    )

    assert linker_report.exists()
    assert validate_output["validation_report_path"].exists()
    assert validate_output["fact_check_report_path"].exists()
    assert validate_output["fact_check_summary_path"].exists()

    validate_payload = json.loads(
        validate_output["validation_report_path"].read_text(encoding="utf-8")
    )
    assert validate_payload["run_id"] == "run-test-stage-chain"
    assert "entity_reports" in validate_payload
    assert validate_payload["no_llm_fact_check"] is True

    coalesce_decisions_path = context.data_dir / "coalesced" / "coalesce_decisions.json"
    assert coalesce_decisions_path.exists()
    coalesce_decisions = json.loads(coalesce_decisions_path.read_text(encoding="utf-8"))
    assert coalesce_decisions
    assert "tie_break_reason" in coalesce_decisions[0]


def test_wiki_first_stage_chain_includes_discovery_and_enrich(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_generation_dependencies(monkeypatch)
    context = ensure_run_context("run-test-discovery-chain", artifacts_root=tmp_path / "runs")
    _seed_manifest(context.root_dir)
    ingest_output = run_ingest_stage(context)
    discovery_outputs = run_discovery_stage(context, ingest_output["source_manifest_path"])
    assert discovery_outputs
    questline_seed = json.loads(
        (context.data_dir / "decisions" / "questline_inclusion_decisions.json").read_text(
            encoding="utf-8"
        )
    )
    assert questline_seed == []

    run_traverse_seed_stage(context)
    fact_pack_paths = run_coalesce_stage(
        context,
        ingest_output["source_manifest_path"],
        max_entity_concurrency=4,
    )
    assert fact_pack_paths
    assert all(path.exists() for path in fact_pack_paths)

    enrich_graph = run_discovery_enrich_stage(
        context,
        ingest_output["source_manifest_path"],
        phase="roster",
    )
    assert enrich_graph["zone_quest_graph_v3"].exists()
    v3_rows = json.loads(enrich_graph["zone_quest_graph_v3"].read_text(encoding="utf-8"))
    quest_titles = {
        str(row.get("title", "")).lower() for row in v3_rows if row.get("node_type") == "quest"
    }
    assert "the endless flow" in quest_titles
    assert "into the woods" not in quest_titles
    assert all(
        str(row.get("cluster_id", "")) == "unclustered"
        for row in v3_rows
        if row.get("node_type") == "quest"
    )

    traverse_quest_outputs = run_traverse_quests_stage(context)
    assert traverse_quest_outputs["traversal_report"].exists()
    assert traverse_quest_outputs["quest_records"].exists()

    cluster_outputs = run_discovery_enrich_stage(
        context,
        ingest_output["source_manifest_path"],
        phase="cluster",
    )
    assert cluster_outputs["zone_quest_clusters"].exists()

    significance_outputs = run_discovery_enrich_stage(
        context,
        ingest_output["source_manifest_path"],
        phase="significance",
    )
    assert significance_outputs["zone_quest_cluster_rankings"].exists()

    card_polish_outputs = run_discovery_enrich_stage(
        context,
        ingest_output["source_manifest_path"],
        phase="card_polish",
    )
    assert card_polish_outputs["zone_questline_card_metadata"].exists()
    metadata = json.loads(
        card_polish_outputs["zone_questline_card_metadata"].read_text(encoding="utf-8")
    )
    assert isinstance(metadata, list)
    decisions = json.loads(
        significance_outputs["questline_inclusion_decisions"].read_text(encoding="utf-8")
    )
    cluster_decisions = [row for row in decisions if row.get("subject_type") == "questline_cluster"]
    assert cluster_decisions
    assert any(row.get("final_decision") == "include" for row in cluster_decisions)

    clustered_v3 = json.loads(cluster_outputs["zone_quest_graph_v3"].read_text(encoding="utf-8"))
    quest_cluster_ids = {
        str(row.get("cluster_id", "")) for row in clustered_v3 if row.get("node_type") == "quest"
    }
    assert "unclustered" not in quest_cluster_ids
    assert len(quest_cluster_ids) >= 2

    enrich_outputs = run_discovery_enrich_stage(
        context,
        ingest_output["source_manifest_path"],
        phase="evidence_merge",
    )
    assert enrich_outputs["quest_records"].exists()
    evidence_path = enrich_outputs["evidence_packs"]
    field_names = set()
    for line in evidence_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            field_names.add(json.loads(line).get("field_name"))
    assert "history_digest" in field_names
    assert "at_a_glance_input" in field_names
    assert "currently_input" in field_names
    assert "quest_cluster_lore" in field_names or "quest_lore" in field_names


def test_validate_stage_strict_fails_with_contradiction_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_generation_dependencies(monkeypatch)
    context = ensure_run_context("run-test-strict-fail", artifacts_root=tmp_path / "runs")
    _seed_manifest(context.root_dir)
    ingest_output = run_ingest_stage(context)
    fact_pack_paths = run_coalesce_stage(
        context,
        ingest_output["source_manifest_path"],
        max_entity_concurrency=4,
    )
    draft_paths = run_draft_stage(context, fact_pack_paths, max_entity_concurrency=4)
    zone_path = next(path for path in draft_paths if path.parent.name == "zone")
    draft_payload = json.loads(zone_path.read_text(encoding="utf-8"))
    draft_payload["history"] = f"{draft_payload['history']} [CONTRADICTED]"
    zone_path.write_text(json.dumps(draft_payload, indent=2), encoding="utf-8")

    validate_output = run_validate_stage(context, draft_paths, fact_check_profile="strict")
    assert validate_output["passed"] is False


def test_validate_stage_handles_missing_id_without_crashing(tmp_path: Path) -> None:
    context = ensure_run_context("run-test-validate-missing-id", artifacts_root=tmp_path / "runs")
    draft_dir = context.data_dir / "drafts" / "zone"
    draft_dir.mkdir(parents=True, exist_ok=True)
    draft_path = draft_dir / "missing-id.json"
    draft_path.write_text(
        json.dumps(
            {
                "slug": "missing-id-zone",
                "name": "Missing Id Zone",
                "at_a_glance": "Short text.",
                "currently": "Current text.",
                "history": "History text.",
            }
        ),
        encoding="utf-8",
    )
    output = run_validate_stage(
        context,
        [draft_path],
        fact_check_profile="warn",
        no_llm_fact_check=True,
    )
    assert output["validation_report_path"].exists()
    report = json.loads(output["validation_report_path"].read_text(encoding="utf-8"))
    assert report["entity_reports"][0]["entity_id"] == "missing-id"
    assert report["entity_reports"][0]["passed"] is False


def test_validate_stage_requires_explicit_no_llm_override_for_warn_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_generation_dependencies(monkeypatch)
    context = ensure_run_context("run-test-validate-no-llm-guard", artifacts_root=tmp_path / "runs")
    _seed_manifest(context.root_dir)
    ingest_output = run_ingest_stage(context)
    fact_pack_paths = run_coalesce_stage(
        context,
        ingest_output["source_manifest_path"],
        max_entity_concurrency=4,
    )
    draft_paths = run_draft_stage(context, fact_pack_paths, max_entity_concurrency=4)
    with pytest.raises(RuntimeError, match="--no-llm-fact-check"):
        run_validate_stage(
            context,
            draft_paths,
            fact_check_profile="warn",
            fact_check_enable_llm=False,
            no_llm_fact_check=False,
        )


def test_validate_stage_uppercase_warn_requires_explicit_no_llm_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_generation_dependencies(monkeypatch)
    context = ensure_run_context(
        "run-test-validate-uppercase-guard",
        artifacts_root=tmp_path / "runs",
    )
    _seed_manifest(context.root_dir)
    ingest_output = run_ingest_stage(context)
    fact_pack_paths = run_coalesce_stage(
        context,
        ingest_output["source_manifest_path"],
        max_entity_concurrency=4,
    )
    draft_paths = run_draft_stage(context, fact_pack_paths, max_entity_concurrency=4)
    with pytest.raises(RuntimeError, match="--no-llm-fact-check"):
        run_validate_stage(
            context,
            draft_paths,
            fact_check_profile="WARN",
            fact_check_enable_llm=False,
            no_llm_fact_check=False,
        )


def test_validate_stage_rejects_invalid_profile_with_empty_drafts(tmp_path: Path) -> None:
    context = ensure_run_context(
        "run-test-validate-invalid-profile-empty-drafts",
        artifacts_root=tmp_path / "runs",
    )
    with pytest.raises(RuntimeError, match="expected one of: off, warn, strict"):
        run_validate_stage(
            context,
            [],
            fact_check_profile="banana",
        )


def test_validate_stage_accepts_case_variant_profile_with_empty_drafts(tmp_path: Path) -> None:
    context = ensure_run_context(
        "run-test-validate-case-profile-empty-drafts",
        artifacts_root=tmp_path / "runs",
    )
    output = run_validate_stage(
        context,
        [],
        fact_check_profile="WARN",
    )
    payload = json.loads(output["validation_report_path"].read_text(encoding="utf-8"))
    assert payload["fact_check_profile"] == "warn"
    assert output["passed"] is True


def test_validate_stage_records_release_gate_in_report(tmp_path: Path) -> None:
    context = ensure_run_context(
        "run-test-validate-release-gate-report",
        artifacts_root=tmp_path / "runs",
    )
    output = run_validate_stage(
        context,
        [],
        fact_check_profile="off",
        release_gate=True,
    )
    payload = json.loads(output["validation_report_path"].read_text(encoding="utf-8"))
    assert payload["release_gate"] is True
    assert output["passed"] is True


def test_coalesce_prefers_manifest_priority_for_tie_break(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ready_settings = SimpleNamespace(openai_ready=True, openai_model="gpt-5.5")
    monkeypatch.setattr(
        "pipeline.coalesce.resolve_entities.load_ai_settings",
        lambda: ready_settings,
    )
    monkeypatch.setattr(
        "pipeline.coalesce.resolve_entities.chat_json_completion",
        lambda *_args, **_kwargs: {"claims": ["Priority overlap claim"]},
    )
    context = ensure_run_context("run-test-coalesce-priority", artifacts_root=tmp_path / "runs")
    ingest_dir = context.stage_dir("ingest")
    snapshots_path = ingest_dir / "source_snapshots.json"
    snapshots_path.write_text(
        json.dumps(
            with_required_snapshot_schema([
                {
                    "entity_id": "zone-priority",
                    "entity_type": "zone",
                    "slug": "priority-zone",
                    "name": "Priority Zone",
                    "source_id": "src-high-priority",
                    "source_class": "warcraft_wiki",
                    "url": "https://example.test/high",
                    "revision_id": "mw:100",
                    "captured_at": "2026-01-01T00:00:00Z",
                    "locator": "section:lead paragraph:1",
                    "body": "Priority overlap claim source text",
                    "retrieval_mode": "live",
                    "selection_version": "sel-v1",
                    "policy_version": "pol-v1",
                    "manifest_run_id": "run-v1",
                    "parent_zone_id": "",
                    "requested_revision_id": "",
                    "priority": 1,
                },
                {
                    "entity_id": "zone-priority",
                    "entity_type": "zone",
                    "slug": "priority-zone",
                    "name": "Priority Zone",
                    "source_id": "src-low-priority",
                    "source_class": "warcraft_wiki",
                    "url": "https://example.test/low",
                    "revision_id": "mw:999",
                    "captured_at": "2026-01-01T00:00:00Z",
                    "locator": "section:lead paragraph:1",
                    "body": "Priority overlap claim source text",
                    "retrieval_mode": "live",
                    "selection_version": "sel-v1",
                    "policy_version": "pol-v1",
                    "manifest_run_id": "run-v1",
                    "parent_zone_id": "",
                    "requested_revision_id": "",
                    "priority": 5,
                },
            ])
        ),
        encoding="utf-8",
    )
    manifest_path = run_normalize_source(context, snapshots_path)
    normalized_rows = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert [row["priority"] for row in normalized_rows] == [1, 5]
    entities_path, _ = run_resolve_entities(context, manifest_path, max_entity_concurrency=2)
    rows = [
        json.loads(line)
        for line in entities_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert rows
    fact_items = rows[0]["fact_items"]
    assert fact_items
    assert fact_items[0]["source_id"] == "src-high-priority"


def test_normalize_source_uses_deterministic_fallback_priority_when_missing_or_invalid(
    tmp_path: Path,
) -> None:
    context = ensure_run_context(
        "run-test-normalize-priority-fallback",
        artifacts_root=tmp_path / "runs",
    )
    snapshots_path = context.stage_dir("ingest") / "source_snapshots.json"
    snapshots_path.write_text(
        json.dumps(
            with_required_snapshot_schema([
                {
                    "entity_id": "zone-one",
                    "entity_type": "zone",
                    "slug": "zone-one",
                    "name": "Zone One",
                    "source_id": "src-1",
                    "source_class": "warcraft_wiki",
                    "url": "https://example.test/1",
                    "revision_id": "mw:1",
                    "captured_at": "2026-01-01T00:00:00Z",
                    "locator": "section:lead paragraph:1",
                    "body": "one",
                    "retrieval_mode": "live",
                    "selection_version": "sel-v1",
                    "policy_version": "pol-v1",
                    "manifest_run_id": "run-v1",
                    "parent_zone_id": "",
                    "requested_revision_id": "",
                    "priority": "bad",
                },
                {
                    "entity_id": "zone-two",
                    "entity_type": "zone",
                    "slug": "zone-two",
                    "name": "Zone Two",
                    "source_id": "src-2",
                    "source_class": "warcraft_wiki",
                    "url": "https://example.test/2",
                    "revision_id": "mw:2",
                    "captured_at": "2026-01-01T00:00:00Z",
                    "locator": "section:lead paragraph:1",
                    "body": "two",
                    "retrieval_mode": "live",
                    "selection_version": "sel-v1",
                    "policy_version": "pol-v1",
                    "manifest_run_id": "run-v1",
                    "parent_zone_id": "",
                    "requested_revision_id": "",
                },
                {
                    "entity_id": "zone-three",
                    "entity_type": "zone",
                    "slug": "zone-three",
                    "name": "Zone Three",
                    "source_id": "src-3",
                    "source_class": "warcraft_wiki",
                    "url": "https://example.test/3",
                    "revision_id": "mw:3",
                    "captured_at": "2026-01-01T00:00:00Z",
                    "locator": "section:lead paragraph:1",
                    "body": "three",
                    "retrieval_mode": "live",
                    "selection_version": "sel-v1",
                    "policy_version": "pol-v1",
                    "manifest_run_id": "run-v1",
                    "parent_zone_id": "",
                    "requested_revision_id": "",
                    "priority": 2,
                },
            ])
        ),
        encoding="utf-8",
    )
    manifest_path = run_normalize_source(context, snapshots_path)
    normalized_rows = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert [row["priority"] for row in normalized_rows] == [1, 2, 2]


def test_stage_traces_include_entity_start_and_success_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_generation_dependencies(monkeypatch)
    context = ensure_run_context("run-test-stage-entity-traces", artifacts_root=tmp_path / "runs")
    _seed_manifest(context.root_dir)
    ingest_output = run_ingest_stage(context)
    fact_pack_paths = run_coalesce_stage(
        context,
        ingest_output["source_manifest_path"],
        max_entity_concurrency=4,
    )
    draft_paths = run_draft_stage(context, fact_pack_paths, max_entity_concurrency=4)
    run_validate_stage(
        context,
        draft_paths,
        fact_check_profile="warn",
        no_llm_fact_check=True,
    )
    trace_lines = [
        json.loads(line)
        for line in context.trace_log_path().read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert any(
        str(row["stage"]).startswith("coalesce:") and row["status"] == "start"
        for row in trace_lines
    )
    assert any(
        str(row["stage"]).startswith("coalesce:") and row["status"] == "success"
        for row in trace_lines
    )
    assert any(
        str(row["stage"]).startswith("draft:") and row["status"] == "start" for row in trace_lines
    )
    assert any(
        str(row["stage"]).startswith("draft:") and row["status"] == "success" for row in trace_lines
    )
