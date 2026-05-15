"""Shared run context and artifact helpers for staged pipeline commands."""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

_TRACE_FILE_LOCKS: dict[str, threading.Lock] = {}
_TRACE_LOCKS_GUARD = threading.Lock()


def build_run_id() -> str:
    """Generate a sortable run identifier."""
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"run-{timestamp}-{uuid.uuid4().hex[:8]}"


@dataclass(frozen=True)
class RunContext:
    """Filesystem metadata shared across all stage commands."""

    run_id: str
    root_dir: Path

    @property
    def data_dir(self) -> Path:
        return self.root_dir / "data"

    @property
    def reports_dir(self) -> Path:
        return self.root_dir / "reports"

    @property
    def traces_dir(self) -> Path:
        return self.root_dir / "traces"

    def stage_dir(self, stage_name: str) -> Path:
        stage_root = self.data_dir / stage_name
        stage_root.mkdir(parents=True, exist_ok=True)
        return stage_root

    def stage_manifest_path(self, stage_name: str) -> Path:
        manifests_dir = self.traces_dir / "manifests"
        manifests_dir.mkdir(parents=True, exist_ok=True)
        return manifests_dir / f"{stage_name}.json"

    def trace_log_path(self) -> Path:
        self.traces_dir.mkdir(parents=True, exist_ok=True)
        return self.traces_dir / "stage_trace.jsonl"


def ensure_run_context(
    run_id: str | None = None,
    *,
    artifacts_root: Path | None = None,
) -> RunContext:
    """Create and return a run context rooted under artifacts/runs."""
    resolved_run_id = run_id or build_run_id()
    root = artifacts_root or Path("artifacts") / "runs"
    run_root = root / resolved_run_id
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "data").mkdir(exist_ok=True)
    (run_root / "reports").mkdir(exist_ok=True)
    (run_root / "traces").mkdir(exist_ok=True)
    return RunContext(run_id=resolved_run_id, root_dir=run_root)


def write_stage_manifest(
    context: RunContext,
    stage_name: str,
    *,
    status: str,
    inputs: list[str],
    outputs: list[str],
    retries: int = 0,
    escalated: bool = False,
    metadata: dict[str, object] | None = None,
) -> Path:
    """Persist stage input/output manifest for run traceability."""
    manifest = {
        "run_id": context.run_id,
        "stage_id": f"{context.run_id}:{stage_name}",
        "stage": stage_name,
        "status": status,
        "inputs": inputs,
        "outputs": outputs,
        "retries": retries,
        "escalated": escalated,
        "updated_at": datetime.now(UTC).isoformat(),
        "metadata": metadata or {},
    }
    manifest_path = context.stage_manifest_path(stage_name)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


def append_trace_event(
    context: RunContext,
    *,
    stage_name: str,
    attempt: int,
    status: str,
    details: dict[str, object] | None = None,
) -> None:
    """Append an event to the run-level stage trace log."""
    event = {
        "run_id": context.run_id,
        "stage_id": f"{context.run_id}:{stage_name}",
        "stage": stage_name,
        "attempt": attempt,
        "status": status,
        "timestamp": datetime.now(UTC).isoformat(),
        "details": details or {},
    }
    trace_path = context.trace_log_path()
    lock_key = str(trace_path.resolve())
    with _TRACE_LOCKS_GUARD:
        file_lock = _TRACE_FILE_LOCKS.setdefault(lock_key, threading.Lock())
    with file_lock:
        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event) + "\n")
