"""Per-entity capture of prose-finalize decisions (diagnostic, not a draft payload).

The wiki-first prose workers (overview, history) try LLM synthesis, then fall back to a
deterministic borrow, then to a pool borrow. With the anti-verbatim gate active, a verbatim
fallback is rejected — so a field can end *empty* (gate-fail) and it is otherwise opaque *why*
(LLM returned nothing? LLM copied? lint/budget reject?). This records the decision trail for each
field so a run's ``data/decisions/prose_finalize_decisions.json`` answers that directly.

Implemented as a context-local sink so the deep finalize/synth functions can append a record
without threading a sink through every signature. ``begin``/``drain`` are called by the draft
writer around each entity build (in its worker thread); ``record`` is a no-op when nothing is
capturing (tests, other callers), so it is always safe to call.
"""

from __future__ import annotations

import contextvars
from typing import Any

_CTX: contextvars.ContextVar[tuple[str, list[dict[str, Any]]] | None] = contextvars.ContextVar(
    "prose_finalize_ctx", default=None
)


def begin(entity_id: str) -> None:
    """Start capturing finalize decisions for ``entity_id`` in the current context/thread."""
    _CTX.set((entity_id, []))


def record(stage: str, **detail: Any) -> None:
    """Append one decision record; no-op when no capture is active."""
    ctx = _CTX.get()
    if ctx is None:
        return
    entity_id, sink = ctx
    sink.append({"entity_id": entity_id, "stage": stage, **detail})


def drain() -> list[dict[str, Any]]:
    """Return the captured records and stop capturing."""
    ctx = _CTX.get()
    _CTX.set(None)
    return list(ctx[1]) if ctx else []
