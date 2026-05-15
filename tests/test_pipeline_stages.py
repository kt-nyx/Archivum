import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline.coalesce.resolve_entities import run_resolve_entities
from pipeline.common.run_context import ensure_run_context
from pipeline.ingest.normalize_source import run_normalize_source
from pipeline.orchestrator.stages import (
    run_coalesce_stage,
    run_draft_stage,
    run_extract_stage,
    run_ingest_stage,
    run_linker_stage,
    run_validate_stage,
)


def _seed_manifest(context_root: Path) -> None:
    fixture = Path("tests/fixtures/pilot/source_manifest.json")
    context_root.joinpath("source_manifest.json").write_text(
        fixture.read_text(encoding="utf-8"),
        encoding="utf-8",
    )


def _mock_generation_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    ready_settings = SimpleNamespace(openai_ready=True, openai_model="gpt-4.1-mini")
    monkeypatch.setattr(
        "pipeline.coalesce.resolve_entities.load_ai_settings",
        lambda: ready_settings,
    )
    monkeypatch.setattr(
        "pipeline.generate.draft_writer.load_ai_settings",
        lambda: ready_settings,
    )

    def fake_fetch(url: str, source_class: str) -> tuple[str, str, str]:
        return (
            f"{source_class} source evidence for {url} with campaign chronology and factions.",
            "mw:123456",
            "section:lead paragraph:1",
        )

    def fake_coalesce_chat(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {
            "claims": [
                "The region remains contested by military and undead forces.",
                "Faction campaigns emphasize route security and recovery operations.",
            ]
        }

    def fake_draft_chat(*_args: object, **kwargs: object) -> dict[str, object]:
        system_prompt = str(kwargs.get("system_prompt", ""))
        if "zone draft body" in system_prompt:
            return {
                "expansion": "retail",
                "at_a_glance": (
                    "A contested zone where military campaigns and undead pressure intersect."
                ),
                "currently": (
                    "Current developments center on route security, settlement recovery, and "
                    "command-level responses to sustained threats."
                ),
                "history": (
                    "Historical arcs track repeated conflict cycles, shifting command priorities, "
                    "and contested control over strategic ground."
                ),
                "major_questlines_alliance": [
                    {
                        "id": "ql-zone-alliance-core",
                        "faction": "alliance",
                        "title": "Alliance Core Campaign",
                        "hook": "Alliance forces consolidate strategic positions.",
                        "start_anchor": "Field Command",
                        "story_beats": ["Assess", "Stabilize", "Consolidate"],
                        "inclusion_decision": {
                            "inclusion_score": 8,
                            "criteria_breakdown": {
                                "importance": 2,
                                "coherence": 2,
                                "evidence": 2,
                                "relevance": 2,
                            },
                            "include_decision": "include",
                            "decision_reason": "Evidence-backed core arc.",
                            "source_refs": [],
                        },
                        "depends_on_parent_context": False,
                    }
                ],
                "major_questlines_horde": [],
                "major_questlines_shared": [],
                "major_characters": [
                    {
                        "id": "character-zone-figure-one",
                        "name": "Zone Figure One",
                        "summary": "Leads campaign stabilization efforts.",
                    },
                    {
                        "id": "character-zone-figure-two",
                        "name": "Zone Figure Two",
                        "summary": "Coordinates strategic responses.",
                    },
                    {
                        "id": "character-zone-figure-three",
                        "name": "Zone Figure Three",
                        "summary": "Documents conflict outcomes.",
                    },
                ],
                "instances": [
                    {
                        "id": "instance-zone-associated",
                        "name": "Associated Instance",
                        "summary": "Related conflict site tied to campaign outcomes.",
                    }
                ],
                "major_landmarks": [
                    {
                        "id": "landmark-zone-site-one",
                        "name": "Zone Site One",
                        "summary": "Strategic site under ongoing pressure.",
                    },
                    {
                        "id": "landmark-zone-site-two",
                        "name": "Zone Site Two",
                        "summary": "Operational hub for recovery efforts.",
                    },
                    {
                        "id": "landmark-zone-site-three",
                        "name": "Zone Site Three",
                        "summary": "Frontline location for active campaigns.",
                    },
                ],
                "glossary": [],
            }
        return {
            "type": "dungeon",
            "identity_header": "A high-risk instance with concentrated hostile leadership.",
            "story_context": (
                "The instance narrative connects strategic command pressure, prolonged conflict, "
                "and unstable recovery windows."
            ),
            "key_characters": [
                {
                    "id": "character-instance-key-one",
                    "name": "Instance Key One",
                    "summary": "Drives the instance's central conflict trajectory.",
                },
                {
                    "id": "character-instance-key-two",
                    "name": "Instance Key Two",
                    "summary": "Shapes the operational stakes within the dungeon.",
                },
            ],
            "glossary": [],
        }

    monkeypatch.setattr("pipeline.ingest.fetch_wiki._fetch_url_text", fake_fetch)
    monkeypatch.setattr(
        "pipeline.coalesce.resolve_entities.chat_json_completion",
        fake_coalesce_chat,
    )
    monkeypatch.setattr(
        "pipeline.generate.draft_writer.chat_json_completion",
        fake_draft_chat,
    )


def test_ingest_to_validate_stage_chain_emits_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_generation_dependencies(monkeypatch)
    context = ensure_run_context("run-test-stage-chain", artifacts_root=tmp_path / "runs")
    _seed_manifest(context.root_dir)
    ingest_output = run_ingest_stage(context)
    coalesced_path = run_coalesce_stage(
        context,
        ingest_output["source_manifest_path"],
        max_entity_concurrency=4,
    )
    extracted_paths = run_extract_stage(context, coalesced_path, max_entity_concurrency=4)
    draft_paths = run_draft_stage(context, extracted_paths, max_entity_concurrency=4)
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


def test_validate_stage_strict_fails_with_contradiction_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_generation_dependencies(monkeypatch)
    context = ensure_run_context("run-test-strict-fail", artifacts_root=tmp_path / "runs")
    _seed_manifest(context.root_dir)
    ingest_output = run_ingest_stage(context)
    coalesced_path = run_coalesce_stage(
        context,
        ingest_output["source_manifest_path"],
        max_entity_concurrency=4,
    )
    extracted_paths = run_extract_stage(context, coalesced_path, max_entity_concurrency=4)
    draft_paths = run_draft_stage(context, extracted_paths, max_entity_concurrency=4)
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
    coalesced_path = run_coalesce_stage(
        context,
        ingest_output["source_manifest_path"],
        max_entity_concurrency=4,
    )
    extracted_paths = run_extract_stage(context, coalesced_path, max_entity_concurrency=4)
    draft_paths = run_draft_stage(context, extracted_paths, max_entity_concurrency=4)
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
    coalesced_path = run_coalesce_stage(
        context,
        ingest_output["source_manifest_path"],
        max_entity_concurrency=4,
    )
    extracted_paths = run_extract_stage(context, coalesced_path, max_entity_concurrency=4)
    draft_paths = run_draft_stage(context, extracted_paths, max_entity_concurrency=4)
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


def test_coalesce_prefers_manifest_priority_for_tie_break(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ready_settings = SimpleNamespace(openai_ready=True, openai_model="gpt-4.1-mini")
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
            [
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
                    "source_class": "wowpedia",
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
            ]
        ),
        encoding="utf-8",
    )
    manifest_path = run_normalize_source(context, snapshots_path)
    normalized_rows = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert [row["priority"] for row in normalized_rows] == [1, 5]
    entities_path = run_resolve_entities(context, manifest_path, max_entity_concurrency=2)
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
            [
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
            ]
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
    coalesced_path = run_coalesce_stage(
        context,
        ingest_output["source_manifest_path"],
        max_entity_concurrency=4,
    )
    extracted_paths = run_extract_stage(context, coalesced_path, max_entity_concurrency=4)
    draft_paths = run_draft_stage(context, extracted_paths, max_entity_concurrency=4)
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
        str(row["stage"]).startswith("extract:") and row["status"] == "start" for row in trace_lines
    )
    assert any(
        str(row["stage"]).startswith("extract:") and row["status"] == "success"
        for row in trace_lines
    )
    assert any(
        str(row["stage"]).startswith("draft:") and row["status"] == "start" for row in trace_lines
    )
    assert any(
        str(row["stage"]).startswith("draft:") and row["status"] == "success" for row in trace_lines
    )
