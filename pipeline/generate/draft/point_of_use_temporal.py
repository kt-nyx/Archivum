"""Context-local wiring for point-of-use temporal adjudication of card pools (Slice 9, Cause C).

The classified ``CanonicalEvidenceRecord`` set produced during enrich is registered here once per
draft run; the deep card builders then call :func:`adjudicate_card_pool` after election, without
threading the record map through every ``build_*``/``finalize_*`` signature (same contextvar
rationale as :mod:`pipeline.generate.draft.finalize_trace`). Each adjudicated paragraph's decision
is appended to the per-entity finalize trace with a ``point_of_use`` marker, so a re-scoped or
excluded paragraph is always auditable (design policy 5).
"""

from __future__ import annotations

import contextvars
from typing import Any

from pipeline.generate.draft import finalize_trace
from pipeline.generate.draft.pool_policy import EXCLUDED_CARD_POOL_SCOPES
from pipeline.generate.draft.temporal import (
    CanonicalEvidenceRecord,
    adjudicate_pool_items_point_of_use,
)

_RECORDS: contextvars.ContextVar[dict[str, CanonicalEvidenceRecord] | None] = (
    contextvars.ContextVar("point_of_use_records", default=None)
)


def begin(records_by_canonical_id: dict[str, CanonicalEvidenceRecord]) -> None:
    """Register the run's canonical records so card builders can re-adjudicate elected pools."""
    _RECORDS.set(records_by_canonical_id)


def clear() -> None:
    """Stop point-of-use adjudication (no records registered)."""
    _RECORDS.set(None)


def adjudicate_card_pool(items: list[dict[str, Any]], *, label: str) -> None:
    """Adjudicate the still-ambiguous paragraphs among an elected card pool, in place.

    ``label`` identifies the pool (e.g. ``"faction.zone-...":`` for the trace record. No-op when
    no records are registered (tests / offline paths that never called :func:`begin`).
    """
    records = _RECORDS.get()
    if not records or not items:
        return
    decisions = adjudicate_pool_items_point_of_use(items, records)
    for decision in decisions:
        # Record whether the resolved scope bars the paragraph from card synthesis, so a dropped
        # paragraph is auditable at its rejected text (the exclusion concept lives in pool_policy).
        excluded = decision.get("temporal_scope") in EXCLUDED_CARD_POOL_SCOPES
        finalize_trace.record(
            "temporal.point_of_use", label=label, excluded_from_synthesis=excluded, **decision
        )
