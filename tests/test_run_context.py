import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pipeline.common.run_context import append_trace_event, ensure_run_context


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
