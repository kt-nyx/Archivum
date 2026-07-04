"""Shared run context and artifact helpers for staged pipeline commands."""

from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha1
from pathlib import Path

from pipeline.common.io import write_json

_TRACE_FILE_LOCKS: dict[str, threading.Lock] = {}
_TRACE_LOCKS_GUARD = threading.Lock()


def build_run_id() -> str:
    """Generate a sortable run identifier."""
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"run-{timestamp}-{uuid.uuid4().hex[:8]}"


class RunArtifactsExistError(RuntimeError):
    """A new pipeline execution targeted a run id that already has stage artifacts."""


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


def _repository_root() -> Path:
    """Directory that contains the ``pipeline`` package (repository root in editable installs)."""
    return Path(__file__).resolve().parent.parent.parent


def _default_artifacts_runs_dir() -> Path:
    """Resolve ``artifacts/runs`` for CLI and library use.

    Defaults to ``<repository_root>/artifacts/runs`` so commands behave the same no matter which
    working directory the shell uses. Override with ``WOW_LORE_ARTIFACTS_ROOT`` (absolute or
    relative path to the ``runs`` directory — i.e. the parent of each ``<run_id>/`` folder).
    """
    raw = os.environ.get("WOW_LORE_ARTIFACTS_ROOT", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (_repository_root() / "artifacts" / "runs").resolve()


def ensure_run_context(
    run_id: str | None = None,
    *,
    artifacts_root: Path | None = None,
) -> RunContext:
    """Attach to (or create) a run directory under ``artifacts/runs``.

    Performs no immutability check: single-stage commands and in-flow stage tasks use
    this to attach to a run that already has artifacts. New pipeline executions must go
    through :func:`create_run_context`, which refuses to reuse a run id with existing
    stage manifests.
    """
    resolved_run_id = run_id or build_run_id()
    root = artifacts_root or _default_artifacts_runs_dir()
    run_root = (root / resolved_run_id).resolve()
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "data").mkdir(exist_ok=True)
    (run_root / "reports").mkdir(exist_ok=True)
    (run_root / "traces").mkdir(exist_ok=True)
    return RunContext(run_id=resolved_run_id, root_dir=run_root)


def _stage_manifests_in(run_root: Path) -> list[Path]:
    """Stage manifests recorded for a run directory (empty when none exist yet)."""
    manifests_dir = run_root / "traces" / "manifests"
    if not manifests_dir.is_dir():
        return []
    return sorted(manifests_dir.glob("*.json"))


def create_run_context(
    run_id: str | None = None,
    *,
    artifacts_root: Path | None = None,
    force_new_suffix: bool = False,
) -> RunContext:
    """Create a run context for a **new** pipeline execution — runs are immutable.

    Refuses to reuse a run id whose directory already contains stage manifests, so an
    existing run's artifacts can never be silently overwritten (regressions between
    generations stay provable). With ``force_new_suffix=True`` the run id is suffixed
    to the first free sibling (``<run_id>-2``, ``-3``, ...) instead of failing. There
    is deliberately no overwrite option; re-running a single stage in place goes
    through the stage commands, which trace the replacement
    (:func:`record_stage_reexecution`).
    """
    resolved_run_id = run_id or build_run_id()
    root = artifacts_root or _default_artifacts_runs_dir()
    existing = _stage_manifests_in((root / resolved_run_id).resolve())
    if existing:
        if not force_new_suffix:
            stage_names = ", ".join(path.stem for path in existing)
            raise RunArtifactsExistError(
                f"run '{resolved_run_id}' already contains stage artifacts ({stage_names}) "
                "and runs are immutable; choose a new run id, pass --force-new-suffix to "
                "auto-suffix one, or re-run a single stage via its stage command"
            )
        suffix = 2
        while _stage_manifests_in((root / f"{resolved_run_id}-{suffix}").resolve()):
            suffix += 1
        resolved_run_id = f"{resolved_run_id}-{suffix}"
    return ensure_run_context(resolved_run_id, artifacts_root=artifacts_root)


def record_stage_reexecution(context: RunContext, stage_name: str) -> None:
    """Trace a single-stage re-execution that will replace existing stage outputs.

    Re-running one stage against an existing run is a legitimate dev workflow, but it
    must stay auditable: when the stage already has a manifest, append a trace event
    recording which outputs are about to be replaced. No-op for a first execution.
    """
    manifest_path = context.stage_manifest_path(stage_name)
    if not manifest_path.exists():
        return
    try:
        prior = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        prior = {}
    if not isinstance(prior, dict):
        prior = {}
    append_trace_event(
        context,
        stage_name=stage_name,
        attempt=0,
        status="reexecute",
        details={
            "replaced_outputs": prior.get("outputs", []),
            "prior_status": prior.get("status"),
            "prior_updated_at": prior.get("updated_at"),
        },
    )


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
    normalized_metadata = metadata or {}
    config_hash = sha1(
        json.dumps(
            {
                "stage": stage_name,
                "inputs": inputs,
                "metadata": normalized_metadata,
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
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
        "metadata": normalized_metadata,
        "config_hash": config_hash,
    }
    manifest_path = context.stage_manifest_path(stage_name)
    write_json(manifest_path, manifest)
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
