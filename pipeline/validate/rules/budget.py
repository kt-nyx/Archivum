"""Budget validation rules for canonical entities."""

from __future__ import annotations

import re

from pydantic import BaseModel

from pipeline.contracts.models import (
    CHARACTER_BUDGET_RULES,
    CHARACTER_MAX_PAGE_WORDS,
    GLOSSARY_BUDGET_RULES,
    INSTANCE_BUDGET_RULES,
    INSTANCE_MAX_KEY_CHARACTERS,
    INSTANCE_MIN_KEY_CHARACTERS,
    ZONE_BUDGET_RULES,
    ZONE_MAX_MAJOR_CHARACTERS,
    ZONE_MAX_MAJOR_LANDMARKS,
    ZONE_MAX_TOTAL_QUESTLINE_CARDS,
    ZONE_MAX_TOTAL_QUESTLINE_WORDS,
    ZONE_MIN_MAJOR_CHARACTERS,
    ZONE_MIN_MAJOR_LANDMARKS,
    ZONE_MIN_TOTAL_QUESTLINE_CARDS,
    BudgetRule,
    BudgetSeverity,
    Character,
    GlossaryTerm,
    Instance,
    SubZone,
    Zone,
    ZonePage,
    InstancePage,
)
from pipeline.validate.types import ValidationIssue, ValidationSeverity

WORD_RE = re.compile(r"\b[\w']+\b")


def _word_count(text: str) -> int:
    return len(WORD_RE.findall(text))


def _rule_issue_count(
    rule: BudgetRule, actual_words: int, path: str, code: str
) -> ValidationIssue | None:
    if rule.min_words <= actual_words <= rule.max_words:
        return None
    severity = (
        ValidationSeverity.HARD_FAIL
        if rule.severity == BudgetSeverity.HARD_FAIL
        else ValidationSeverity.WARN
    )
    return ValidationIssue(
        code=code,
        message=(
            f"word count {actual_words} is outside budget "
            f"[{rule.min_words}, {rule.max_words}] (target {rule.target_words})"
        ),
        severity=severity,
        path=path,
    )


def _validate_zone(zone: Zone) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    for field_name in ("at_a_glance", "currently", "history"):
        rule = ZONE_BUDGET_RULES[field_name]
        issue = _rule_issue_count(
            rule, _word_count(getattr(zone, field_name)), f"$.{field_name}", "budget.section"
        )
        if issue:
            issues.append(issue)

    questline_buckets = (
        ("major_questlines_alliance", zone.major_questlines_alliance),
        ("major_questlines_horde", zone.major_questlines_horde),
        ("major_questlines_shared", zone.major_questlines_shared),
    )
    questline_rule = ZONE_BUDGET_RULES["major_questlines_card_hook"]
    total_hook_words = 0
    questline_cards: list = []
    for bucket_name, cards in questline_buckets:
        questline_cards.extend(cards)
        for index, card in enumerate(cards):
            card_words = _word_count(card.hook)
            total_hook_words += card_words
            issue = _rule_issue_count(
                questline_rule,
                card_words,
                f"$.{bucket_name}[{index}].hook",
                "budget.questline_card",
            )
            if issue:
                issues.append(issue)

    if not ZONE_MIN_TOTAL_QUESTLINE_CARDS <= len(questline_cards) <= ZONE_MAX_TOTAL_QUESTLINE_CARDS:
        issues.append(
            ValidationIssue(
                code="budget.questline_total_cards",
                message=(
                    "zone must contain "
                    f"{ZONE_MIN_TOTAL_QUESTLINE_CARDS}-{ZONE_MAX_TOTAL_QUESTLINE_CARDS} "
                    f"questline cards across faction buckets"
                ),
                severity=ValidationSeverity.HARD_FAIL,
                path="$.major_questlines_*",
            )
        )

    if not ZONE_MIN_MAJOR_CHARACTERS <= len(zone.major_characters) <= ZONE_MAX_MAJOR_CHARACTERS:
        issues.append(
            ValidationIssue(
                code="budget.major_characters_count",
                message=(
                    f"zone.major_characters must contain {ZONE_MIN_MAJOR_CHARACTERS}-"
                    f"{ZONE_MAX_MAJOR_CHARACTERS} cards"
                ),
                severity=ValidationSeverity.HARD_FAIL,
                path="$.major_characters",
            )
        )

    if not ZONE_MIN_MAJOR_LANDMARKS <= len(zone.major_landmarks) <= ZONE_MAX_MAJOR_LANDMARKS:
        issues.append(
            ValidationIssue(
                code="budget.major_landmarks_count",
                message=(
                    f"zone.major_landmarks must contain {ZONE_MIN_MAJOR_LANDMARKS}-"
                    f"{ZONE_MAX_MAJOR_LANDMARKS} cards"
                ),
                severity=ValidationSeverity.HARD_FAIL,
                path="$.major_landmarks",
            )
        )

    if total_hook_words > ZONE_MAX_TOTAL_QUESTLINE_WORDS:
        issues.append(
            ValidationIssue(
                code="budget.questline_total_words",
                message=(
                    f"total questline hook words {total_hook_words} exceed max "
                    f"{ZONE_MAX_TOTAL_QUESTLINE_WORDS}"
                ),
                severity=ValidationSeverity.HARD_FAIL,
                path="$.major_questlines_*",
            )
        )

    for index, character_card in enumerate(zone.major_characters):
        issue = _rule_issue_count(
            ZONE_BUDGET_RULES["major_characters_card_summary"],
            _word_count(character_card.summary),
            f"$.major_characters[{index}].summary",
            "budget.character_card",
        )
        if issue:
            issues.append(issue)

    for index, instance_card in enumerate(zone.instances):
        issue = _rule_issue_count(
            ZONE_BUDGET_RULES["instances_card_summary"],
            _word_count(instance_card.summary),
            f"$.instances[{index}].summary",
            "budget.instance_card",
        )
        if issue:
            issues.append(issue)

    for index, landmark_card in enumerate(zone.major_landmarks):
        issue = _rule_issue_count(
            ZONE_BUDGET_RULES["major_landmarks_card_summary"],
            _word_count(landmark_card.summary),
            f"$.major_landmarks[{index}].summary",
            "budget.landmark_card",
        )
        if issue:
            issues.append(issue)

    return issues


def _validate_instance(instance: Instance) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if (
        not INSTANCE_MIN_KEY_CHARACTERS
        <= len(instance.key_characters)
        <= INSTANCE_MAX_KEY_CHARACTERS
    ):
        issues.append(
            ValidationIssue(
                code="budget.instance_key_characters_count",
                message=(
                    f"instance.key_characters must contain {INSTANCE_MIN_KEY_CHARACTERS}-"
                    f"{INSTANCE_MAX_KEY_CHARACTERS} cards"
                ),
                severity=ValidationSeverity.HARD_FAIL,
                path="$.key_characters",
            )
        )

    for field_name in ("identity_header", "story_context"):
        rule = INSTANCE_BUDGET_RULES[field_name]
        issue = _rule_issue_count(
            rule, _word_count(getattr(instance, field_name)), f"$.{field_name}", "budget.section"
        )
        if issue:
            issues.append(issue)
    for index, card in enumerate(instance.key_characters):
        issue = _rule_issue_count(
            INSTANCE_BUDGET_RULES["key_characters_card_summary"],
            _word_count(card.summary),
            f"$.key_characters[{index}].summary",
            "budget.character_card",
        )
        if issue:
            issues.append(issue)
    return issues


def _validate_character(character: Character) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for field_name in ("summary", "short_history"):
        rule = CHARACTER_BUDGET_RULES[field_name]
        issue = _rule_issue_count(
            rule, _word_count(getattr(character, field_name)), f"$.{field_name}", "budget.section"
        )
        if issue:
            issues.append(issue)

    page_total = _word_count(character.summary) + _word_count(character.short_history)
    if page_total > CHARACTER_MAX_PAGE_WORDS:
        issues.append(
            ValidationIssue(
                code="budget.character_page_total",
                message=(
                    f"character page total words {page_total} exceed max {CHARACTER_MAX_PAGE_WORDS}"
                ),
                severity=ValidationSeverity.HARD_FAIL,
                path="$",
            )
        )
    return issues


def _validate_glossary_term(term: GlossaryTerm) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for field_name in ("summary", "brief_history"):
        rule = GLOSSARY_BUDGET_RULES[field_name]
        issue = _rule_issue_count(
            rule, _word_count(getattr(term, field_name)), f"$.{field_name}", "budget.section"
        )
        if issue:
            issues.append(issue)
    return issues


def _validate_sub_zone(sub_zone: SubZone) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    questline_buckets = (
        ("major_questlines_alliance", sub_zone.major_questlines_alliance),
        ("major_questlines_horde", sub_zone.major_questlines_horde),
        ("major_questlines_shared", sub_zone.major_questlines_shared),
    )

    for bucket_name, cards in questline_buckets:
        for index, card in enumerate(cards):
            hook_words = _word_count(card.hook)
            if hook_words < 40 or hook_words > 95:
                issues.append(
                    ValidationIssue(
                        code="sub_zone.questline_hook_budget",
                        message=(f"sub-zone questline hook words {hook_words} outside [40, 95]"),
                        severity=ValidationSeverity.HARD_FAIL,
                        path=f"$.{bucket_name}[{index}].hook",
                    )
                )

    return issues


def _validate_zone_page(zone_page: ZonePage) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for field_name in ("at_a_glance", "currently"):
        value = getattr(zone_page, field_name)
        words = _word_count(value)
        if field_name == "at_a_glance" and not (8 <= words <= 70):
            issues.append(
                ValidationIssue(
                    code="budget.section",
                    message=f"{field_name} word count {words} is outside budget [8, 70]",
                    severity=ValidationSeverity.WARN,
                    path=f"$.{field_name}",
                )
            )
        if field_name == "currently" and not (20 <= words <= 220):
            issues.append(
                ValidationIssue(
                    code="budget.section",
                    message=f"{field_name} word count {words} is outside budget [20, 220]",
                    severity=ValidationSeverity.HARD_FAIL,
                    path=f"$.{field_name}",
                )
            )
    for index, section in enumerate(zone_page.history_sections):
        words = _word_count(section.body)
        if not (25 <= words <= 260):
            issues.append(
                ValidationIssue(
                    code="budget.history_section",
                    message=f"history section word count {words} is outside budget [25, 260]",
                    severity=ValidationSeverity.HARD_FAIL,
                    path=f"$.history_sections[{index}].body",
                )
            )
    return issues


def _validate_instance_page(instance_page: InstancePage) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    at_a_glance_words = _word_count(instance_page.at_a_glance)
    if not (8 <= at_a_glance_words <= 70):
        issues.append(
            ValidationIssue(
                code="budget.section",
                message=f"at_a_glance word count {at_a_glance_words} is outside budget [8, 70]",
                severity=ValidationSeverity.WARN,
                path="$.at_a_glance",
            )
        )
    overview_words = _word_count(instance_page.overview)
    if not (20 <= overview_words <= 260):
        issues.append(
            ValidationIssue(
                code="budget.section",
                message=f"overview word count {overview_words} is outside budget [20, 260]",
                severity=ValidationSeverity.HARD_FAIL,
                path="$.overview",
            )
        )
    for index, section in enumerate(instance_page.history_sections):
        words = _word_count(section.body)
        if not (25 <= words <= 260):
            issues.append(
                ValidationIssue(
                    code="budget.history_section",
                    message=f"history section word count {words} is outside budget [25, 260]",
                    severity=ValidationSeverity.HARD_FAIL,
                    path=f"$.history_sections[{index}].body",
                )
            )
    return issues


def validate_budget_rules(entity_type: str, parsed_entity: BaseModel) -> list[ValidationIssue]:
    """Run budget checks for the parsed entity."""
    if entity_type == "zone":
        return _validate_zone(
            parsed_entity if isinstance(parsed_entity, Zone) else Zone.model_validate(parsed_entity)
        )
    if entity_type == "instance":
        return _validate_instance(
            parsed_entity
            if isinstance(parsed_entity, Instance)
            else Instance.model_validate(parsed_entity)
        )
    if entity_type == "character":
        return _validate_character(
            parsed_entity
            if isinstance(parsed_entity, Character)
            else Character.model_validate(parsed_entity)
        )
    if entity_type == "glossary_term":
        return _validate_glossary_term(
            parsed_entity
            if isinstance(parsed_entity, GlossaryTerm)
            else GlossaryTerm.model_validate(parsed_entity)
        )
    if entity_type == "sub_zone":
        return _validate_sub_zone(
            parsed_entity
            if isinstance(parsed_entity, SubZone)
            else SubZone.model_validate(parsed_entity)
        )
    if entity_type == "zone_page":
        return _validate_zone_page(
            parsed_entity
            if isinstance(parsed_entity, ZonePage)
            else ZonePage.model_validate(parsed_entity)
        )
    if entity_type == "instance_page":
        return _validate_instance_page(
            parsed_entity
            if isinstance(parsed_entity, InstancePage)
            else InstancePage.model_validate(parsed_entity)
        )
    return []
