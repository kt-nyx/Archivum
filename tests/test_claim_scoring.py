"""Tests for the deterministic coalesce claim-source scorer (S4)."""

from __future__ import annotations

from typing import Any

from pipeline.coalesce.claim_scoring import (
    score_claim_against_source,
    select_source_for_claim,
)

_CLAIM = "Andorhal was overrun by the Scourge and contested by Alliance and Horde forces."
_SUPPORTIVE = (
    "Andorhal is a town in the Western Plaguelands. After being overrun by the Scourge, "
    "it became a contested battleground between Alliance and Horde forces during the war."
)
_UNRELATED = (
    "Hearthglen is a region in the northern Western Plaguelands, home to the Argent Crusade "
    "and the Scarlet Crusade. It is largely free of the Scourge."
)


def _row(source_id: str, body: str, **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "source_id": source_id,
        "body": body,
        "source_class": "warcraft_wiki",
        "priority": 1,
        "revision_id": "mw:100",
    }
    row.update(overrides)
    return row


def test_score_is_bounded_and_blank_inputs_score_zero() -> None:
    assert score_claim_against_source(_CLAIM, _SUPPORTIVE) > 0.0
    assert score_claim_against_source(_CLAIM, _SUPPORTIVE) <= 1.0
    assert score_claim_against_source("", _SUPPORTIVE) == 0.0
    assert score_claim_against_source(_CLAIM, "   ") == 0.0


def test_score_discriminates_supportive_from_unrelated_source() -> None:
    assert score_claim_against_source(_CLAIM, _SUPPORTIVE) > score_claim_against_source(
        _CLAIM, _UNRELATED
    )


def test_score_is_robust_to_unrelated_padding() -> None:
    """A supportive body padded with filler still scores like the unpadded one."""
    padded = _SUPPORTIVE + (" Lorem ipsum dolor sit amet. " * 40)
    assert score_claim_against_source(_CLAIM, padded) == score_claim_against_source(
        _CLAIM, _SUPPORTIVE
    )


def test_score_tolerates_paraphrase_and_morphology() -> None:
    """Fuzzy token matching beats exact overlap on paraphrased/inflected claims."""
    claim = "The Scourge's necromancers raised the dead at Andorhal."
    supportive = "At Andorhal, Scourge necromancer forces raised undead and the dead rose again."
    unrelated = "Hearthglen hosts the Argent Crusade and remains free of undeath."
    assert score_claim_against_source(claim, supportive) > score_claim_against_source(
        claim, unrelated
    )


def test_select_prefers_higher_scoring_source_over_priority() -> None:
    """Claim score dominates: a supportive low-priority source beats an unrelated high one."""
    high_priority_unrelated = _row("src-unrelated", _UNRELATED, priority=1)
    low_priority_supportive = _row("src-supportive", _SUPPORTIVE, priority=9)
    selected, reason = select_source_for_claim(
        _CLAIM,
        [high_priority_unrelated, low_priority_supportive],
        contradiction_bias="prefer_higher_revision_id",
    )
    assert selected["source_id"] == "src-supportive"
    assert reason == "highest_claim_score"


def test_select_tie_breaks_by_priority_then_revision() -> None:
    """Identical bodies tie on score and fall through priority -> revision bias."""
    rows = [
        _row("src-low-priority", _SUPPORTIVE, priority=5, revision_id="mw:999"),
        _row("src-high-priority", _SUPPORTIVE, priority=1, revision_id="mw:100"),
    ]
    selected, reason = select_source_for_claim(
        _CLAIM, rows, contradiction_bias="prefer_higher_revision_id"
    )
    assert selected["source_id"] == "src-high-priority"
    assert reason == "tie_break_priority_source_class"


def test_select_revision_bias_breaks_equal_priority_tie() -> None:
    rows = [
        _row("src-older", _SUPPORTIVE, priority=1, revision_id="mw:100"),
        _row("src-newer", _SUPPORTIVE, priority=1, revision_id="mw:900"),
    ]
    selected, reason = select_source_for_claim(
        _CLAIM, rows, contradiction_bias="prefer_higher_revision_id"
    )
    assert selected["source_id"] == "src-newer"
    assert reason == "tie_break_priority_then_revision_id"


def test_selection_is_reproducible_across_runs() -> None:
    """Same input -> identical selection + reason on repeated evaluation (determinism gate)."""
    rows = [
        _row("src-a", _UNRELATED, priority=2),
        _row("src-b", _SUPPORTIVE, priority=3),
        _row("src-c", _SUPPORTIVE, priority=3),
    ]
    first = select_source_for_claim(_CLAIM, rows, contradiction_bias="prefer_higher_revision_id")
    second = select_source_for_claim(_CLAIM, rows, contradiction_bias="prefer_higher_revision_id")
    assert (first[0]["source_id"], first[1]) == (second[0]["source_id"], second[1])
