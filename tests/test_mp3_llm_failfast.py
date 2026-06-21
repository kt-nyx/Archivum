import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from pipeline.common.run_context import ensure_run_context
from pipeline.ingest.fetch_wiki import FetchedSource
from pipeline.orchestrator.stages import (
    run_coalesce_stage,
    run_draft_stage,
    run_ingest_stage,
)
from tests.draft_llm_mocks import fake_draft_chat_by_schema


def _pilot_manifest_fixture() -> list[dict[str, object]]:
    fixture_path = Path("tests/fixtures/pilot/source_manifest.json")
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    return cast(list[dict[str, object]], payload) if isinstance(payload, list) else []


def _seed_pilot_manifest(context_root: Path) -> None:
    (context_root / "source_manifest.json").write_text(
        json.dumps(_pilot_manifest_fixture(), indent=2),
        encoding="utf-8",
    )


def _mock_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_fetch(url: str, source_class: str) -> FetchedSource:
        return FetchedSource(
            f"{source_class} source evidence for {url} with zone chronology and conflict context.",
            "mw:654321",
            "section:lead paragraph:1",
            [{"section_role": "lead", "text": "Lead section evidence."}],
            [],
            [],
            "",
        )

    monkeypatch.setattr("pipeline.ingest.fetch_wiki._fetch_url_text", fake_fetch)


def _mock_coalesce_llm(
    monkeypatch: pytest.MonkeyPatch,
    *,
    openai_ready: bool,
    chat_result: dict[str, Any] | None = None,
) -> None:
    settings = SimpleNamespace(openai_ready=openai_ready, openai_model="gpt-5.5")
    monkeypatch.setattr(
        "pipeline.coalesce.resolve_entities.load_ai_settings",
        lambda: settings,
    )

    def fake_chat(*_args: object, **kwargs: object) -> dict[str, Any] | None:
        _ = kwargs
        return chat_result

    monkeypatch.setattr(
        "pipeline.coalesce.resolve_entities.chat_json_completion",
        fake_chat,
    )


def _draft_settings(*, openai_ready: bool) -> SimpleNamespace:
    return SimpleNamespace(
        openai_ready=openai_ready,
        openai_model="gpt-5.5",
        openai_reasoning_effort=None,
        openai_verbosity=None,
        openai_draft_reasoning_effort=None,
        openai_draft_verbosity=None,
        openai_use_responses_api=False,
        openai_request_timeout_seconds=600,
    )


def _mock_draft_llm(
    monkeypatch: pytest.MonkeyPatch,
    *,
    openai_ready: bool,
    chat_result: dict[str, Any] | None = None,
) -> None:
    settings = _draft_settings(openai_ready=openai_ready)
    for target in (
        "pipeline.generate.draft_writer.load_ai_settings",
        "pipeline.generate.draft.llm.load_ai_settings",
    ):
        monkeypatch.setattr(target, lambda: settings)

    def fake_chat(*args: object, **kwargs: object) -> dict[str, Any] | None:
        return fake_draft_chat_by_schema(*args, chat_result=chat_result, **kwargs)

    for target in (
        "pipeline.generate.draft.llm.chat_json_completion",
        "pipeline.generate.draft_writer.chat_json_completion",
    ):
        monkeypatch.setattr(target, fake_chat)


def test_mp3_generation_succeeds_when_llm_available(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ensure_run_context("run-test-mp3-llm-pass", artifacts_root=tmp_path / "runs")
    _seed_pilot_manifest(context.root_dir)
    _mock_fetch(monkeypatch)
    _mock_coalesce_llm(
        monkeypatch,
        openai_ready=True,
        chat_result={"claims": ["Claim one."]},
    )
    _mock_draft_llm(
        monkeypatch,
        openai_ready=True,
        chat_result=None,
    )

    ingest_output = run_ingest_stage(context)
    fact_pack_paths = run_coalesce_stage(
        context,
        ingest_output["source_manifest_path"],
        max_entity_concurrency=4,
    )
    outputs = run_draft_stage(context, fact_pack_paths, max_entity_concurrency=4)

    assert outputs
    decisions = json.loads((context.data_dir / "drafts" / "draft_decisions.json").read_text())
    assert all(row["generation_mode"] == "openai" for row in decisions)


def test_mp3_coalesce_fails_when_llm_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ensure_run_context(
        "run-test-mp3-coalesce-llm-missing",
        artifacts_root=tmp_path / "runs",
    )
    _seed_pilot_manifest(context.root_dir)
    _mock_fetch(monkeypatch)
    _mock_coalesce_llm(monkeypatch, openai_ready=False)

    ingest_output = run_ingest_stage(context)
    with pytest.raises(RuntimeError, match="coalesce requires OpenAI"):
        run_coalesce_stage(context, ingest_output["source_manifest_path"], max_entity_concurrency=4)


def test_mp3_draft_fails_when_llm_output_stays_invalid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ensure_run_context(
        "run-test-mp3-draft-invalid-output",
        artifacts_root=tmp_path / "runs",
    )
    _seed_pilot_manifest(context.root_dir)
    _mock_fetch(monkeypatch)
    _mock_coalesce_llm(
        monkeypatch,
        openai_ready=True,
        chat_result={"claims": ["Claim one.", "Claim two."]},
    )
    _mock_draft_llm(monkeypatch, openai_ready=True, chat_result={})

    ingest_output = run_ingest_stage(context)
    fact_pack_paths = run_coalesce_stage(
        context,
        ingest_output["source_manifest_path"],
        max_entity_concurrency=4,
    )

    with pytest.raises(RuntimeError, match="draft LLM generation failed"):
        run_draft_stage(context, fact_pack_paths, max_entity_concurrency=4)


def test_ingest_fails_when_manifest_is_missing(tmp_path: Path) -> None:
    context = ensure_run_context(
        "run-test-mp3-manifest-missing",
        artifacts_root=tmp_path / "runs",
    )
    with pytest.raises(RuntimeError, match="missing ingest manifest"):
        run_ingest_stage(context)


def test_ingest_fails_when_manifest_missing_required_handoff_fields(
    tmp_path: Path,
) -> None:
    context = ensure_run_context(
        "run-test-mp3-manifest-invalid",
        artifacts_root=tmp_path / "runs",
    )
    invalid_manifest = [
        {
            "entity_id": "zone-sample",
            "entity_type": "zone",
            "slug": "sample-zone",
            "name": "Sample Zone",
            "source_id": "src-sample",
            "source_class": "warcraft_wiki",
        }
    ]
    (context.root_dir / "source_manifest.json").write_text(
        json.dumps(invalid_manifest, indent=2),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="schema error|missing required fields"):
        run_ingest_stage(context)


def test_ingest_fails_when_manifest_breaks_json_schema_types(tmp_path: Path) -> None:
    context = ensure_run_context(
        "run-test-mp3-manifest-schema-type-error",
        artifacts_root=tmp_path / "runs",
    )
    invalid_manifest = [
        {
            "entity_id": "zone-sample",
            "entity_type": "zone",
            "slug": "sample-zone",
            "name": "Sample Zone",
            "source_id": "src-sample",
            "source_url": "https://example.test/sample-zone",
            "source_class": "warcraft_wiki",
            "selection_version": 123,
            "policy_version": "policy-v1",
            "manifest_run_id": "manifest-v1",
        }
    ]
    (context.root_dir / "source_manifest.json").write_text(
        json.dumps(invalid_manifest, indent=2),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="schema error"):
        run_ingest_stage(context)


def test_ingest_uses_revision_pinned_oldid_url_when_revision_is_supplied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ensure_run_context(
        "run-test-mp3-ingest-revision-pinned",
        artifacts_root=tmp_path / "runs",
    )
    manifest = _pilot_manifest_fixture()
    manifest[0]["revision_id"] = "mw:123456"
    (context.root_dir / "source_manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    captured_urls: list[str] = []

    def fake_fetch(url: str, source_class: str) -> FetchedSource:
        _ = source_class
        captured_urls.append(url)
        return FetchedSource(
            "Pinned revision body text.", "mw:123456", "section:lead paragraph:1", [], [], [], ""
        )

    monkeypatch.setattr("pipeline.ingest.fetch_wiki._fetch_url_text", fake_fetch)
    run_ingest_stage(context)
    assert captured_urls
    assert "oldid=123456" in captured_urls[0]


def test_ingest_fails_when_requested_revision_does_not_match_fetched_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ensure_run_context(
        "run-test-mp3-ingest-revision-mismatch",
        artifacts_root=tmp_path / "runs",
    )
    manifest = _pilot_manifest_fixture()
    manifest[0]["revision_id"] = "mw:111111"
    (context.root_dir / "source_manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )

    def fake_fetch(_url: str, _source_class: str) -> FetchedSource:
        return FetchedSource("Body text.", "mw:222222", "section:lead paragraph:1", [], [], [], "")

    monkeypatch.setattr("pipeline.ingest.fetch_wiki._fetch_url_text", fake_fetch)
    with pytest.raises(RuntimeError, match="expected revision"):
        run_ingest_stage(context)


def test_ingest_priority_fallback_stays_within_contract_range_for_large_manifests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ensure_run_context(
        "run-test-mp3-ingest-priority-range",
        artifacts_root=tmp_path / "runs",
    )
    manifest_rows = [
        {
            "entity_id": f"zone-priority-{index}",
            "entity_type": "zone",
            "slug": f"zone-priority-{index}",
            "name": f"Zone Priority {index}",
            "source_id": f"src-priority-{index}",
            "source_url": f"https://example.test/zone-priority-{index}",
            "source_class": "warcraft_wiki",
            "selection_version": "sel-v1",
            "policy_version": "pol-v1",
            "manifest_run_id": "run-v1",
        }
        for index in range(1, 14)
    ]
    (context.root_dir / "source_manifest.json").write_text(
        json.dumps(manifest_rows, indent=2),
        encoding="utf-8",
    )

    def fake_fetch(url: str, source_class: str) -> FetchedSource:
        return FetchedSource(
            f"{source_class} evidence for {url}",
            "mw:654321",
            "section:lead paragraph:1",
            [],
            [],
            [],
            "",
        )

    monkeypatch.setattr("pipeline.ingest.fetch_wiki._fetch_url_text", fake_fetch)
    run_ingest_stage(context)
    snapshots = json.loads((context.stage_dir("ingest") / "source_snapshots.json").read_text())
    normalized_manifest = json.loads(
        (context.stage_dir("ingest") / "source_manifest.json").read_text()
    )
    assert all(1 <= int(row["priority"]) <= 10 for row in snapshots)
    assert all(1 <= int(row["priority"]) <= 10 for row in normalized_manifest)
    expected = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 1, 2, 3]
    assert [row["priority"] for row in snapshots] == expected
    assert [row["priority"] for row in normalized_manifest] == expected


def test_mp3_draft_retries_until_schema_valid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ensure_run_context(
        "run-test-mp3-draft-schema-retry",
        artifacts_root=tmp_path / "runs",
    )
    _seed_pilot_manifest(context.root_dir)
    _mock_fetch(monkeypatch)
    _mock_coalesce_llm(
        monkeypatch,
        openai_ready=True,
        chat_result={"claims": ["Claim one.", "Claim two."]},
    )
    monkeypatch.setenv("WOW_LORE_DRAFT_MODE", "legacy")
    _mock_draft_llm(monkeypatch, openai_ready=True)
    zone_attempts = {"count": 0}

    def flaky_draft_chat(*args: object, **kwargs: object) -> dict[str, Any] | None:
        schema_name = str(kwargs.get("response_schema_name", ""))
        if schema_name == "zone_draft_body":
            zone_attempts["count"] += 1
            if zone_attempts["count"] == 1:
                return {
                    "expansion": "retail",
                    "at_a_glance": "Short zone summary.",
                    "currently": "Current state summary for validation retry behavior.",
                    "history": "History summary for validation retry behavior.",
                    "major_questlines_alliance": [],
                    "major_questlines_horde": [],
                    "major_questlines_shared": [],
                    "major_characters": "invalid-type",
                    "instances": [],
                    "major_landmarks": [],
                    "glossary": [],
                }
        return fake_draft_chat_by_schema(*args, **kwargs)

    for target in (
        "pipeline.generate.draft.llm.chat_json_completion",
        "pipeline.generate.draft_writer.chat_json_completion",
    ):
        monkeypatch.setattr(target, flaky_draft_chat)

    ingest_output = run_ingest_stage(context)
    fact_pack_paths = run_coalesce_stage(
        context,
        ingest_output["source_manifest_path"],
        max_entity_concurrency=4,
    )
    outputs = run_draft_stage(context, fact_pack_paths, max_entity_concurrency=4)

    assert outputs
    assert zone_attempts["count"] >= 2


def test_mp3_draft_fails_for_unknown_entity_type(tmp_path: Path) -> None:
    context = ensure_run_context(
        "run-test-mp3-draft-unsupported-entity",
        artifacts_root=tmp_path / "runs",
    )
    extract_dir = context.data_dir / "extracted"
    extract_dir.mkdir(parents=True, exist_ok=True)
    fact_pack_path = extract_dir / "character-sample.json"
    fact_pack_path.write_text(
        json.dumps(
            {
                "entity_id": "vehicle-sample",
                "entity_type": "vehicle",
                "slug": "vehicle-sample",
                "name": "Vehicle Sample",
                "source_ids": ["src-1"],
                "revision_ids": ["mw:1"],
                "source_urls": {"src-1": "https://example.test/vehicle"},
                "claims": ["Sample claim"],
                "fact_items": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="does not support entity_type"):
        run_draft_stage(context, [fact_pack_path], max_entity_concurrency=4)


def test_mp3_draft_supports_additional_entity_types(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ensure_run_context(
        "run-test-mp3-draft-additional-types",
        artifacts_root=tmp_path / "runs",
    )
    _mock_draft_llm(monkeypatch, openai_ready=True)

    extract_dir = context.data_dir / "extracted"
    extract_dir.mkdir(parents=True, exist_ok=True)
    common_fact_items = [
        {
            "claim": "Sample claim for additional entity generation coverage.",
            "source_id": "src-1",
            "url": "https://example.test/source-1",
            "revision_id": "mw:1",
            "locator": "section:lead paragraph:1",
            "excerpt_hash": "sha1:1111111111111111",
        },
        {
            "claim": "Second supporting claim for provenance pointer generation.",
            "source_id": "src-2",
            "url": "https://example.test/source-2",
            "revision_id": "mw:2",
            "locator": "section:lead paragraph:2",
            "excerpt_hash": "sha1:2222222222222222",
        },
    ]
    payloads = [
        {
            "entity_id": "subzone-andorhal",
            "entity_type": "sub_zone",
            "slug": "andorhal",
            "name": "Andorhal",
            "parent_zone_id": "zone-western-plaguelands",
        },
        {
            "entity_id": "character-thassarian",
            "entity_type": "character",
            "slug": "thassarian",
            "name": "Thassarian",
        },
        {
            "entity_id": "term-plaguelands-campaign",
            "entity_type": "glossary_term",
            "slug": "plaguelands-campaign",
            "name": "Plaguelands Campaign",
        },
        {
            "entity_id": "asset-plaguelands-map",
            "entity_type": "asset",
            "slug": "plaguelands-map",
            "name": "Plaguelands Strategic Map",
        },
    ]
    fact_pack_paths: list[Path] = []
    for payload in payloads:
        row = {
            **payload,
            "source_ids": ["src-1", "src-2"],
            "revision_ids": ["mw:1", "mw:2"],
            "source_urls": {
                "src-1": "https://example.test/source-1",
                "src-2": "https://example.test/source-2",
            },
            "claims": [item["claim"] for item in common_fact_items],
            "fact_items": common_fact_items,
            "coalesce_mode": "openai",
        }
        path = extract_dir / f"{payload['entity_id']}.json"
        path.write_text(json.dumps(row, indent=2), encoding="utf-8")
        fact_pack_paths.append(path)

    outputs = run_draft_stage(context, fact_pack_paths, max_entity_concurrency=4)
    assert len(outputs) == 4
    entity_types = {path.parent.name for path in outputs}
    assert entity_types == {"sub_zone", "character", "glossary_term", "asset"}
