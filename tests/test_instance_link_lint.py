from __future__ import annotations

from pipeline.generate.draft.instance_link_lint import (
    is_generic_instance_link_summary,
    lint_instance_link_summary,
)


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
