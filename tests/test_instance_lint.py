from __future__ import annotations

from pipeline.generate.draft.instance_lint import (
    fallback_instance_overview,
    is_generic_overview,
    lint_key_character_summary,
    lint_overview,
)


def test_lint_overview_rejects_generic_stub() -> None:
    assert is_generic_overview(
        "Archive Vault contains key enemies and encounter stakes captured from Warcraft Wiki."
    )
    issues = lint_overview(
        "Archive Vault contains key enemies and encounter stakes captured from Warcraft Wiki.",
        instance_name="Archive Vault",
    )
    assert any("generic" in issue for issue in issues)


def test_fallback_instance_overview_meets_word_floor() -> None:
    items = [
        {
            "snippet": (
                "The Archive Vault was built to safeguard forbidden relics after the great war, "
                "and its halls still echo with the ambitions of rival scholars who sought to control "
                "its secrets across generations of conflict."
            ),
            "source_id": "src-instance",
        }
    ]
    text, used = fallback_instance_overview(items, instance_name="Archive Vault")
    assert "Archive Vault" in text
    assert len(text.split()) >= 170
    assert used == ["src-instance"]


def test_lint_key_character_summary_requires_boss_anchor() -> None:
    issues = lint_key_character_summary(
        "A major encounter shapes the instance narrative stakes.",
        boss_name="Archivist Maelor",
        instance_name="Archive Vault",
    )
    assert any("boss name" in issue for issue in issues)
