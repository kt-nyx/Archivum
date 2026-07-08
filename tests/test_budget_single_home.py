"""Drift tripwires: every draft-side word budget derives from the contracts BudgetRules.

Slice 2 of the generalization refactor: budgets live in ``pipeline/contracts/models.py``
only, and the draft stage derives its lint constants from them. These tests pin the
registry values (so an accidental registry edit is a loud failure) and assert the draft
constants are the registry values (so a re-introduced literal duplicate is caught).
"""

from __future__ import annotations

from pipeline.contracts.models import (
    INSTANCE_BUDGET_RULES,
    PAGE_HISTORY_SECTION_BUDGET_RULE,
    ZONE_PAGE_BUDGET_RULES,
    BudgetSeverity,
)
from pipeline.generate.draft import faction_lint, faction_scoring, instance_link_lint, instance_lint
from pipeline.generate.draft.pages import cards
from pipeline.generate.draft.prose_lint import MAX_AT_A_GLANCE_WORDS


def test_key_character_budget_derives_from_registry() -> None:
    rule = INSTANCE_BUDGET_RULES["key_characters_card_summary"]
    assert (rule.min_words, rule.max_words) == (25, 115)
    assert instance_lint.MIN_KEY_CHARACTER_WORDS == rule.min_words
    assert instance_lint.MAX_KEY_CHARACTER_WORDS == rule.max_words


def test_instance_overview_budget_derives_from_registry() -> None:
    rule = INSTANCE_BUDGET_RULES["story_context"]
    assert (rule.min_words, rule.max_words) == (70, 160)
    assert instance_lint.MIN_OVERVIEW_WORDS == rule.min_words
    assert instance_lint.MAX_OVERVIEW_WORDS == rule.max_words


def test_history_section_budget_shared_between_draft_and_validate() -> None:
    rule = PAGE_HISTORY_SECTION_BUDGET_RULE
    assert (rule.min_words, rule.max_words) == (40, 110)
    assert rule.severity == BudgetSeverity.HARD_FAIL
    assert cards._HISTORY_SECTION_MIN_WORDS == rule.min_words
    assert cards._HISTORY_SECTION_MAX_WORDS == rule.max_words


def test_zone_page_budget_rules_pinned() -> None:
    at_a_glance = ZONE_PAGE_BUDGET_RULES["at_a_glance"]
    assert (at_a_glance.min_words, at_a_glance.max_words) == (18, 48)
    assert at_a_glance.severity == BudgetSeverity.WARN
    currently = ZONE_PAGE_BUDGET_RULES["currently"]
    assert (currently.min_words, currently.max_words) == (35, 90)
    assert currently.severity == BudgetSeverity.HARD_FAIL


def test_zone_at_a_glance_cap_derives_from_registry() -> None:
    assert MAX_AT_A_GLANCE_WORDS == ZONE_PAGE_BUDGET_RULES["at_a_glance"].max_words


def test_faction_summary_budget_derives_from_registry() -> None:
    rule = ZONE_PAGE_BUDGET_RULES["major_factions_card_summary"]
    assert (rule.min_words, rule.max_words) == (18, 48)
    assert faction_lint.MIN_FACTION_SUMMARY_WORDS == rule.min_words
    assert faction_lint.MAX_FACTION_SUMMARY_WORDS == rule.max_words
    # faction_scoring re-exports the faction_lint constant; a second literal home is drift.
    assert faction_scoring.MAX_FACTION_SUMMARY_WORDS == faction_lint.MAX_FACTION_SUMMARY_WORDS


def test_instance_link_budget_is_the_identity_header_rule() -> None:
    # The zone's instance-link card reuses the instance page's at_a_glance caption, so its
    # budget IS the identity_header rule (documented coupling, not coincidence).
    assert (
        ZONE_PAGE_BUDGET_RULES["instance_links_card_summary"]
        is INSTANCE_BUDGET_RULES["identity_header"]
    )
    assert (
        instance_link_lint.MAX_INSTANCE_LINK_WORDS
        == INSTANCE_BUDGET_RULES["identity_header"].max_words
    )


def test_instance_at_a_glance_cap_derives_from_registry() -> None:
    assert (
        instance_lint.MAX_AT_A_GLANCE_WORDS == INSTANCE_BUDGET_RULES["identity_header"].max_words
    )
