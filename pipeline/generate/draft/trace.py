"""Per-LLM-call tracing for the draft stage."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_TRACE_LOCK = threading.Lock()


@dataclass
class DraftTraceContext:
    """Accumulates LLM call metrics for one entity draft."""

    entity_id: str
    pipeline_mode: str
    trace_path: Path | None = None
    llm_call_count: int = 0
    total_llm_duration_ms: int = 0
    _rows: list[dict[str, Any]] = field(default_factory=list)

    def record(
        self,
        *,
        substep: str,
        schema_name: str,
        duration_ms: int,
        attempt: int = 1,
        model: str = "",
        reasoning_effort: str | None = None,
        verbosity: str | None = None,
        request_bytes: int | None = None,
        response_bytes: int | None = None,
    ) -> None:
        self.llm_call_count += 1
        self.total_llm_duration_ms += duration_ms
        row: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "entity_id": self.entity_id,
            "pipeline_mode": self.pipeline_mode,
            "substep": substep,
            "schema_name": schema_name,
            "duration_ms": duration_ms,
            "attempt": attempt,
            "model": model,
        }
        if reasoning_effort:
            row["reasoning_effort"] = reasoning_effort
        if verbosity:
            row["verbosity"] = verbosity
        if request_bytes is not None:
            row["request_bytes"] = request_bytes
        if response_bytes is not None:
            row["response_bytes"] = response_bytes
        self._rows.append(row)
        if self.trace_path is not None:
            with _TRACE_LOCK:
                self.trace_path.parent.mkdir(parents=True, exist_ok=True)
                with self.trace_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def decision_metadata(self) -> dict[str, object]:
        return {
            "draft_pipeline_mode": self.pipeline_mode,
            "llm_call_count": self.llm_call_count,
            "total_llm_duration_ms": self.total_llm_duration_ms,
        }
