import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from pipeline.common.run_context import (
    RunArtifactsExistError,
    append_trace_event,
    create_run_context,
    ensure_run_context,
    record_stage_reexecution,
    write_stage_manifest,
)


def _trace_events(context) -> list[dict]:
    trace_path = context.trace_log_path()
    if not trace_path.exists():
        return []
    return [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_append_trace_event_is_thread_safe(tmp_path: Path) -> None:
    context = ensure_run_context("run-test-trace-thread-safety", artifacts_root=tmp_path / "runs")

    def _emit(index: int) -> None:
        append_trace_event(
            context,
            stage_name=f"validate:entity-{index}",
            attempt=1,
            status="success",
            details={"index": index},
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(_emit, idx) for idx in range(100)]
        for future in futures:
            future.result()

    trace_path = context.trace_log_path()
    lines = [line for line in trace_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 100
    payloads = [json.loads(line) for line in lines]
    assert len(payloads) == 100


def test_create_run_context_fresh_run_dir_proceeds(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    context = create_run_context("run-test-immutable-fresh", artifacts_root=runs_root)
    assert context.run_id == "run-test-immutable-fresh"
    assert context.root_dir == (runs_root / "run-test-immutable-fresh").resolve()

    # An existing but artifact-free run dir (e.g. mkdir'd then aborted) is also fine.
    again = create_run_context("run-test-immutable-fresh", artifacts_root=runs_root)
    assert again.run_id == "run-test-immutable-fresh"


def test_create_run_context_refuses_run_with_stage_manifests(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    context = ensure_run_context("run-test-immutable-guard", artifacts_root=runs_root)
    write_stage_manifest(context, "ingest", status="ok", inputs=[], outputs=["a.json"])

    with pytest.raises(RunArtifactsExistError, match="runs are immutable") as excinfo:
        create_run_context("run-test-immutable-guard", artifacts_root=runs_root)
    assert "ingest" in str(excinfo.value)


def test_create_run_context_force_new_suffix_allocates_next_free_id(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    for run_id in ("run-test-immutable-suffix", "run-test-immutable-suffix-2"):
        context = ensure_run_context(run_id, artifacts_root=runs_root)
        write_stage_manifest(context, "ingest", status="ok", inputs=[], outputs=[])

    suffixed = create_run_context(
        "run-test-immutable-suffix",
        artifacts_root=runs_root,
        force_new_suffix=True,
    )
    assert suffixed.run_id == "run-test-immutable-suffix-3"
    assert suffixed.root_dir == (runs_root / "run-test-immutable-suffix-3").resolve()


def test_record_stage_reexecution_traces_replaced_outputs(tmp_path: Path) -> None:
    context = ensure_run_context("run-test-reexec-trace", artifacts_root=tmp_path / "runs")
    write_stage_manifest(
        context,
        "draft",
        status="ok",
        inputs=["fact-pack.json"],
        outputs=["drafts/zone/zone-a.json", "drafts/zone/zone-b.json"],
    )

    record_stage_reexecution(context, "draft")

    events = _trace_events(context)
    assert len(events) == 1
    event = events[0]
    assert event["stage"] == "draft"
    assert event["status"] == "reexecute"
    assert event["attempt"] == 0
    assert event["details"]["replaced_outputs"] == [
        "drafts/zone/zone-a.json",
        "drafts/zone/zone-b.json",
    ]
    assert event["details"]["prior_status"] == "ok"


def test_record_stage_reexecution_noop_on_first_execution(tmp_path: Path) -> None:
    context = ensure_run_context("run-test-reexec-noop", artifacts_root=tmp_path / "runs")
    record_stage_reexecution(context, "draft")
    assert _trace_events(context) == []


def test_default_run_root_is_repo_relative_not_cwd(tmp_path: Path, monkeypatch) -> None:
    """Regression: cwd must not nest ``artifacts/runs`` under the current directory."""
    monkeypatch.chdir(tmp_path)
    run_id = "run-test-cwd-anchor"
    context = ensure_run_context(run_id)
    try:
        repo_marker = context.root_dir.parent.parent.parent / "pyproject.toml"
        assert repo_marker.is_file()
        assert context.root_dir.name == run_id
        assert context.root_dir.parts[-3:] == ("artifacts", "runs", run_id)
    finally:
        shutil.rmtree(context.root_dir, ignore_errors=True)
