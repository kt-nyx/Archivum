from __future__ import annotations

from pipeline.generate.draft.instance_link_lint import (
    MAX_INSTANCE_LINK_WORDS,
    is_generic_instance_link_summary,
    lint_instance_link_summary,
    trim_instance_link_summary,
)
from pipeline.generate.draft.instance_lint import MAX_AT_A_GLANCE_WORDS


def test_generic_instance_link_stub_detected() -> None:
    summary = "Scholomance anchors a key conflict thread linked to this zone."
    assert is_generic_instance_link_summary(summary)
    issues = lint_instance_link_summary(summary, instance_name="Scholomance", zone_name="Test Zone")
    assert any("generic stub" in issue for issue in issues)


def test_valid_instance_link_summary_passes_lint() -> None:
    summary = (
        "Scholomance is a necromantic academy where instructors train adepts and coordinate "
        "plague operations across the blighted countryside."
    )
    assert not is_generic_instance_link_summary(summary)
    assert not lint_instance_link_summary(
        summary, instance_name="Scholomance", zone_name="Test Zone"
    )


def test_instance_link_budget_matches_instance_at_a_glance() -> None:
    # The instance-link card reuses the instance page's own at_a_glance, so it must carry the same
    # word budget or it hard-trims the caption mid-sentence ("...and held its.").
    assert MAX_INSTANCE_LINK_WORDS == MAX_AT_A_GLANCE_WORDS


def test_instance_link_does_not_truncate_instance_at_a_glance_caption() -> None:
    caption = (
        "Rising above the abandoned city of Caer Darrow in the ruins of House Barov, Scholomance "
        "endures as the School of Necromancy, a vile academy where the Scourge once trained its "
        "future necromancers and held its last western stronghold."
    )
    trimmed = trim_instance_link_summary(caption)
    assert trimmed.endswith("last western stronghold.")
    assert "held its." not in trimmed
