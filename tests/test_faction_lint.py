from __future__ import annotations

from pipeline.generate.draft.faction_lint import (
    ensure_sentence_terminator,
    lint_faction_summary,
    trim_faction_summary,
)
from pipeline.generate.draft.prose_lint import word_count


def test_trim_faction_summary_adds_terminal_punctuation_when_truncated() -> None:
    snippet = " ".join(["reclamation"] * 50)
    summary = trim_faction_summary(snippet, max_words=40)
    assert summary.endswith(".")
    assert word_count(summary) <= 40


def test_ensure_sentence_terminator_preserves_existing_punctuation() -> None:
    assert ensure_sentence_terminator("Crusaders hold the line.") == "Crusaders hold the line."


def test_lint_faction_summary_accepts_zone_role_prose() -> None:
    summary = (
        "The Argent Crusade maintains fortified outposts across the contested frontier in Example Zone, "
        "coordinating reclamation efforts against undead forces throughout the ruined farmland."
    )
    assert not lint_faction_summary(summary, zone_name="Example Zone")


def test_lint_faction_summary_rejects_generic_filler() -> None:
    issues = lint_faction_summary("The Argent Crusade appears in this zone's active conflicts.")
    assert any("generic filler" in issue for issue in issues)
