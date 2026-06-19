"""Deterministic claim-source scoring for the coalesce stage.

Replaces the previous bag-of-words token-overlap selector
(``|claim_tokens ∩ body_tokens| / |claim_tokens|``) with a rapidfuzz
token-set similarity. The token-set score is:

- **length-robust** — set-based, so a supportive source padded with unrelated
  text scores the same as the unpadded one (bag-of-words containment shares this
  trait, but ``token_sort``/``partial`` ratios do not);
- **paraphrase/morphology tolerant** — LLM claims paraphrase the source, so
  ``Scourge's``/``Scourge`` and ``necromancers``/``necromancer`` still match,
  which exact token overlap misses;
- **deterministic** — rapidfuzz returns bit-identical floats for identical
  inputs, so selection is reproducible run-to-run.

The selector keeps the established tie-break chain unchanged:
``claim score → priority → source_class → contradiction bias (revision)``.
"""

from __future__ import annotations

from typing import Any

from rapidfuzz import fuzz


def score_claim_against_source(claim: str, body: str) -> float:
    """Deterministic ``[0.0, 1.0]`` support score of ``body`` for ``claim``.

    Returns ``0.0`` when either side is blank (an empty claim cannot be
    supported, matching the old overlap behaviour where it scored every source
    ``0.0`` and fell through to the tie-break chain).
    """
    if not claim.strip() or not body.strip():
        return 0.0
    return fuzz.token_set_ratio(claim, body) / 100.0


def _priority_rank(row: dict[str, Any]) -> int:
    raw_priority = row.get("priority")
    if isinstance(raw_priority, int):
        return raw_priority
    if isinstance(raw_priority, str):
        return int(raw_priority) if raw_priority.isdigit() else 999
    return 999


def _source_class_rank(row: dict[str, Any]) -> int:
    source_class = str(row.get("source_class", "")).strip().lower()
    if source_class == "warcraft_wiki":
        return 0
    return 1


def _revision_rank(row: dict[str, Any]) -> int:
    revision_id = str(row.get("revision_id", "0"))
    if revision_id.startswith("mw:"):
        revision_id = revision_id.split(":", 1)[1]
    return int("".join(ch for ch in revision_id if ch.isdigit()) or "0")


def select_source_for_claim(
    claim: str,
    source_rows: list[dict[str, Any]],
    *,
    contradiction_bias: str,
) -> tuple[dict[str, Any], str]:
    """Pick the best source row for ``claim`` and report the selection reason.

    Highest :func:`score_claim_against_source` wins; ties resolve by priority,
    then ``source_class`` (warcraft_wiki first), then the contradiction bias
    (highest revision id when ``prefer_higher_revision_id``), then source id.
    """
    scored = [
        (score_claim_against_source(claim, str(row.get("body", ""))), row) for row in source_rows
    ]
    scored.sort(key=lambda item: item[0], reverse=True)
    best_score = scored[0][0]
    tied_rows = [row for score, row in scored if score == best_score]
    if len(tied_rows) == 1:
        return tied_rows[0], "highest_claim_score"

    tied_rows = sorted(
        tied_rows,
        key=lambda row: (
            _priority_rank(row),
            _source_class_rank(row),
            str(row.get("source_id", "")),
        ),
    )
    best_priority = _priority_rank(tied_rows[0])
    best_class_rank = _source_class_rank(tied_rows[0])
    same_priority_rows = [
        row
        for row in tied_rows
        if _priority_rank(row) == best_priority and _source_class_rank(row) == best_class_rank
    ]
    if len(same_priority_rows) == 1:
        return same_priority_rows[0], "tie_break_priority_source_class"

    if contradiction_bias == "prefer_higher_revision_id":
        selected = max(same_priority_rows, key=_revision_rank)
        return selected, "tie_break_priority_then_revision_id"
    return same_priority_rows[0], "tie_break_first_source"
