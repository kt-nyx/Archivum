from __future__ import annotations

from pipeline.generate.draft.faction_lint import lint_faction_summary
from pipeline.generate.draft.prose_lint import (
    has_adp_date,
    lint_adp_date_style,
    lint_history_sections,
)


def test_adp_date_style_lint_flags_exact_dates() -> None:
    assert has_adp_date("During the third invasion in 32 ADP, the cult returned.")
    assert lint_adp_date_style("In Year 24 ADP, the crusade attacked.")


def test_history_and_card_lints_include_adp_reason() -> None:
    history_issues = lint_history_sections(
        [
            {
                "heading": "Return",
                "body": "During the Third War, the region fell. In 24 ADP, the crusade returned.",
            }
        ]
    )
    faction_issues = lint_faction_summary(
        (
            "The Argent Crusade coordinates patrols in Example Zone while older reports date "
            "its arrival to 24 ADP."
        ),
        zone_name="Example Zone",
    )

    assert any("ADP" in issue or "dating" in issue for issue in history_issues)
    assert any("ADP" in issue or "dating" in issue for issue in faction_issues)
