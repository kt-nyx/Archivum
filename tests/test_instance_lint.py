from __future__ import annotations

from pipeline.generate.draft.instance_lint import (
    MAX_KEY_CHARACTER_WORDS,
    MIN_KEY_CHARACTER_WORDS,
    MIN_OVERVIEW_WORDS,
    assess_role_diversity,
    fallback_instance_overview,
    fallback_key_character_summary,
    is_generic_overview,
    lint_at_a_glance,
    lint_key_character_summary,
    lint_overview,
    lint_passthrough_fragment,
)
from pipeline.generate.draft.prose_lint import word_count


def test_fallback_key_character_summary_refuses_colon_spliced_fragment() -> None:
    # #4: the old fallback spliced a verbatim, word-truncated snippet after a colon
    # ("Barov features prominently in Scholomance: <fragment>"). It must never emit a
    # colon-spliced raw fragment; with no clean sentence it returns the generic summary.
    items = [
        {
            "snippet": "the noble house that once ruled Caer Darrow and bequeathed",
            "source_id": "src-frag",
        }
    ]
    summary, used = fallback_key_character_summary(
        items, boss_name="Darkmaster Gandling", instance_name="Scholomance"
    )
    assert ":" not in summary
    assert "Darkmaster Gandling" in summary
    assert lint_passthrough_fragment(summary) == []
    assert used == []


def test_fallback_key_character_summary_borrows_clean_leading_sentence() -> None:
    items = [
        {
            "snippet": (
                "Darkmaster Gandling rules Scholomance as its dreaded headmaster, presiding "
                "over the necromancers and dark students who study within its cursed halls. "
                "He commands the academy."
            ),
            "source_id": "src-clean",
        }
    ]
    summary, used = fallback_key_character_summary(
        items, boss_name="Darkmaster Gandling", instance_name="Scholomance"
    )
    assert ":" not in summary
    assert "headmaster" in summary
    assert used == ["src-clean"]


def test_fallback_key_character_summary_uses_generic_without_items() -> None:
    summary, used = fallback_key_character_summary(
        [], boss_name="Darkmaster Gandling", instance_name="Scholomance"
    )
    assert "Darkmaster Gandling" in summary
    assert used == []


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
    assert len(text.split()) >= MIN_OVERVIEW_WORDS
    assert used == ["src-instance"]


def test_lint_key_character_summary_requires_boss_anchor() -> None:
    issues = lint_key_character_summary(
        "A major encounter shapes the instance narrative stakes.",
        boss_name="Archivist Maelor",
        instance_name="Archive Vault",
    )
    assert any("boss name" in issue for issue in issues)


def test_lint_at_a_glance_flags_missing_anchor_for_in_range_text() -> None:
    # A normal-length at_a_glance that never names the instance must be flagged (the
    # anchor check was previously dead for text at/above the word minimum).
    text = (
        "Six months passed and the keep became decrepit, its halls overrun by dark undead "
        "beings while servants were twisted into grim experiments of plague and ruin."
    )
    issues = lint_at_a_glance(text, instance_name="Scholomance")
    assert any("instance anchor" in issue for issue in issues)


def test_lint_at_a_glance_accepts_anchored_abstract() -> None:
    text = (
        "Hidden in the ruins of Caer Darrow, Scholomance is a blighted school of necromancy "
        "whose dark teachings endured long after Lordaeron fell."
    )
    assert lint_at_a_glance(text, instance_name="Scholomance") == []


def test_lint_key_character_summary_rejects_over_registry_cap() -> None:
    # Slice 2: the word cap derives from the contracts BudgetRule ([25, 60]); the old
    # draft-only 110-word ceiling shipped cards that WARNed in validate.
    text = "Darkmaster Gandling was " + " ".join(["relentless"] * MAX_KEY_CHARACTER_WORDS) + "."
    issues = lint_key_character_summary(
        text, boss_name="Darkmaster Gandling", instance_name="Scholomance"
    )
    assert any(f"exceeds {MAX_KEY_CHARACTER_WORDS} words" in issue for issue in issues)


def test_fallback_key_character_generic_clears_registry_floor() -> None:
    # The sanctioned offline generic must clear the registry word floor even with short
    # names, or the fallback ladder drops every sparse-evidence card.
    summary, used = fallback_key_character_summary(
        [], boss_name="Rattlegore", instance_name="Scholomance"
    )
    assert word_count(summary) >= MIN_KEY_CHARACTER_WORDS
    assert used == []
    assert (
        lint_key_character_summary(summary, boss_name="Rattlegore", instance_name="Scholomance")
        == []
    )


def test_lint_key_character_summary_flags_hollow_characterization() -> None:
    text = (
        "Professor Slate is remembered in Scholomance as a bored student, neither guardian "
        "nor champion, but a sign of how its learning was twisted into stagnation and ruin."
    )
    issues = lint_key_character_summary(
        text, boss_name="Professor Slate", instance_name="Scholomance"
    )
    assert any("hollow" in issue for issue in issues)


def test_lint_passthrough_fragment_flags_mid_sentence_and_unterminated() -> None:
    issues = lint_passthrough_fragment("and the keep fell to the Scourge")
    assert any("mid-sentence" in issue for issue in issues)
    assert any("terminal punctuation" in issue for issue in issues)


def test_lint_passthrough_fragment_flags_bullet_markers() -> None:
    issues = lint_passthrough_fragment("- The keep fell to the Scourge.")
    assert any("list-bullet" in issue for issue in issues)


def test_lint_passthrough_fragment_passes_clean_prose() -> None:
    assert lint_passthrough_fragment("The keep fell to the Scourge during the Third War.") == []


def test_lint_passthrough_fragment_ignores_empty() -> None:
    assert lint_passthrough_fragment("   ") == []


def test_assess_role_diversity_fail_on_dropped_in_window() -> None:
    emitted = [{"name": "Enemy One", "role": "enemy"}]
    roster = [
        {"name": "Enemy One", "role": "enemy"},
        {"name": "Ally Two", "role": "ally"},
    ]
    severity, reason = assess_role_diversity(emitted, roster, window=10)
    assert severity == "fail"
    assert "Ally Two" in reason


def test_assess_role_diversity_warn_when_signal_only_outside_window() -> None:
    emitted = [{"name": "Enemy One", "role": "enemy"}]
    roster = [
        {"name": "Enemy One", "role": "enemy"},
        {"name": "Ally Two", "role": "ally"},
    ]
    severity, _ = assess_role_diversity(emitted, roster, window=1)
    assert severity == "warn"


def test_assess_role_diversity_ok_when_cast_includes_ally() -> None:
    emitted = [{"name": "Ally Two", "role": "ally"}]
    roster = [
        {"name": "Enemy One", "role": "enemy"},
        {"name": "Ally Two", "role": "ally"},
    ]
    severity, _ = assess_role_diversity(emitted, roster, window=10)
    assert severity == "ok"


def test_assess_role_diversity_ok_when_no_ally_available() -> None:
    emitted = [{"name": "Enemy One", "role": "enemy"}]
    roster = [
        {"name": "Enemy One", "role": "enemy"},
        {"name": "Enemy Two", "role": "enemy"},
    ]
    severity, _ = assess_role_diversity(emitted, roster, window=10)
    assert severity == "ok"


def test_assess_role_diversity_uses_emitted_card_role_over_stale_roster() -> None:
    # The emitted card was upgraded to ally by the LLM tiebreaker, but the roster sidecar
    # still records the pre-LLM "uncertain". The emitted ally must win => ok, even though a
    # different ally candidate was dropped from the in-window roster.
    emitted = [{"name": "Tribunal Voice", "role": "ally"}]
    roster = [
        {"name": "Tribunal Voice", "role": "uncertain"},
        {"name": "Helping Hand", "role": "ally"},
    ]
    severity, _ = assess_role_diversity(emitted, roster, window=10)
    assert severity == "ok"
