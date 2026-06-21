from __future__ import annotations

from pipeline.generate.draft.location_lint import lint_location_summary, trim_location_summary


def test_lint_accepts_zone_anchored_landmark_summary() -> None:
    summary = trim_location_summary(
        "Northwatch Hold is a fortified outpost in Example Zone where alliance patrols "
        "coordinate supply lines and defensive operations across the contested frontier."
    )
    assert not lint_location_summary(
        summary, zone_name="Example Zone", location_name="Northwatch Hold"
    )


def test_lint_rejects_generic_filler() -> None:
    summary = "Northwatch Hold is a major location located in the region."
    issues = lint_location_summary(
        summary, zone_name="Example Zone", location_name="Northwatch Hold"
    )
    assert any("generic filler" in issue for issue in issues)


def test_lint_rejects_dating_convention_text() -> None:
    summary = (
        "Northwatch Hold was rebuilt after the Third War (28 ADP) and remains a key outpost "
        "in Example Zone where patrols coordinate defensive operations across the frontier."
    )
    issues = lint_location_summary(
        summary, zone_name="Example Zone", location_name="Northwatch Hold"
    )
    assert any("dating-convention" in issue for issue in issues)
