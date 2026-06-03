"""Questline promotion validation rules for zone_page drafts (Slice E)."""

from __future__ import annotations

from typing import Any

from pipeline.contracts.models import IncludeDecision, ZonePage
from pipeline.discovery.questline_promotion_gate import (
    QuestlineRunArtifacts,
    check_questline_promotion,
    cluster_id_from_card_id,
    warn_questline_promotion,
)
from pipeline.validate.types import ValidationIssue, ValidationSeverity

_MAX_CHAIN_REFS = 12


def _cards_from_zone_page(zone_page: ZonePage) -> list[dict[str, Any]]:
    return [
        {
            "id": card.id,
            "title": card.title,
            "faction": card.faction.value if hasattr(card.faction, "value") else str(card.faction),
            "cta_hook": card.cta_hook,
            "start_anchor": card.start_anchor,
            "chain_refs": list(card.chain_refs),
            "include_decision": card.include_decision.value
            if hasattr(card.include_decision, "value")
            else str(card.include_decision),
            "reason_codes": list(card.reason_codes),
            "wiki_refs": list(card.wiki_refs),
        }
        for card in zone_page.major_questlines
    ]


def _artifacts_from_context(entity_id: str, context: dict[str, Any]) -> QuestlineRunArtifacts:
    metadata_by_cluster = dict(context.get("questline_card_metadata_by_cluster") or {})
    card_id_to_cluster_id = {
        str(row.get("card_id", "")).strip(): str(row.get("cluster_id", "")).strip()
        for row in metadata_by_cluster.values()
        if str(row.get("card_id", "")).strip() and str(row.get("cluster_id", "")).strip()
    }
    return QuestlineRunArtifacts(
        zone_id=entity_id,
        cards=[],
        included_cluster_ids=list(context.get("questline_included_cluster_ids") or []),
        metadata_by_cluster=metadata_by_cluster,
        card_id_to_cluster_id=card_id_to_cluster_id,
        excluded_cluster_ids=set(context.get("questline_excluded_cluster_ids") or []),
        v3_quest_rows=[],
        pilot_expectations=context.get("pilot_questline_expectations"),
    )


def validate_questline_promotion_rules(
    entity_type: str,
    parsed_entity: Any,
    *,
    validation_context: dict[str, Any] | None = None,
) -> list[ValidationIssue]:
    if entity_type != "zone_page" or not isinstance(parsed_entity, ZonePage):
        return []

    context = dict(validation_context or {})
    entity_id = str(parsed_entity.zone_id)
    cards = _cards_from_zone_page(parsed_entity)
    artifacts = _artifacts_from_context(entity_id, context)
    artifacts = QuestlineRunArtifacts(
        zone_id=artifacts.zone_id,
        cards=cards,
        included_cluster_ids=artifacts.included_cluster_ids,
        metadata_by_cluster=artifacts.metadata_by_cluster,
        card_id_to_cluster_id=artifacts.card_id_to_cluster_id,
        excluded_cluster_ids=artifacts.excluded_cluster_ids,
        v3_quest_rows=artifacts.v3_quest_rows,
        pilot_expectations=artifacts.pilot_expectations,
    )

    release_gate = bool(context.get("release_gate"))
    pilot_expectations = artifacts.pilot_expectations
    issues: list[ValidationIssue] = []

    for index, card in enumerate(parsed_entity.major_questlines):
        path_prefix = f"$.major_questlines[{index}]"
        if card.include_decision != IncludeDecision.INCLUDE:
            issues.append(
                ValidationIssue(
                    code="questline_promotion.include_decision",
                    message="questline card must resolve to include",
                    severity=ValidationSeverity.HARD_FAIL,
                    path=f"{path_prefix}.include_decision",
                )
            )
        if len(card.chain_refs) > _MAX_CHAIN_REFS:
            issues.append(
                ValidationIssue(
                    code="questline_promotion.chain_refs_cap",
                    message=f"chain_refs exceeds {_MAX_CHAIN_REFS}",
                    severity=ValidationSeverity.HARD_FAIL,
                    path=f"{path_prefix}.chain_refs",
                )
            )
        if card.id.endswith("-continued") and release_gate:
            issues.append(
                ValidationIssue(
                    code="questline_promotion.continued_card",
                    message="continued questline cards are not allowed at release gate",
                    severity=ValidationSeverity.HARD_FAIL,
                    path=f"{path_prefix}.id",
                )
            )

    for warning in warn_questline_promotion(artifacts):
        issues.append(
            ValidationIssue(
                code="questline_promotion.weak_start_anchor",
                message=warning,
                severity=ValidationSeverity.WARN,
                path="$.major_questlines",
            )
        )

    if release_gate:
        if pilot_expectations:
            emitted_ids = {card.id for card in parsed_entity.major_questlines}
            if emitted_ids != set(pilot_expectations.included_card_ids):
                issues.append(
                    ValidationIssue(
                        code="questline_promotion.pilot_card_ids",
                        message=(
                            "pilot card id set mismatch "
                            f"(got {sorted(emitted_ids)}, expected {sorted(pilot_expectations.included_card_ids)})"
                        ),
                        severity=ValidationSeverity.HARD_FAIL,
                        path="$.major_questlines",
                    )
                )
            if emitted_ids & set(pilot_expectations.excluded_card_ids):
                issues.append(
                    ValidationIssue(
                        code="questline_promotion.pilot_excluded_card",
                        message="excluded pilot registry card id present in draft",
                        severity=ValidationSeverity.HARD_FAIL,
                        path="$.major_questlines",
                    )
                )
            for card in parsed_entity.major_questlines:
                expected_anchor = pilot_expectations.anchor_by_card_id.get(card.id, "")
                if expected_anchor and card.start_anchor != expected_anchor:
                    issues.append(
                        ValidationIssue(
                            code="questline_promotion.pilot_start_anchor",
                            message=(
                                f"start_anchor for {card.id!r} must match registry "
                                f"(expected {expected_anchor!r})"
                            ),
                            severity=ValidationSeverity.HARD_FAIL,
                            path=f"$.major_questlines",
                        )
                    )

        if artifacts.included_cluster_ids and len(cards) != len(artifacts.included_cluster_ids):
            issues.append(
                ValidationIssue(
                    code="questline_promotion.included_count",
                    message=(
                        "major_questlines count does not match included_cluster_ids from rankings"
                    ),
                    severity=ValidationSeverity.HARD_FAIL,
                    path="$.major_questlines",
                )
            )

        for card in parsed_entity.major_questlines:
            cluster_id = cluster_id_from_card_id(card.id, artifacts.card_id_to_cluster_id)
            meta = artifacts.metadata_by_cluster.get(cluster_id, {})
            expected_id = str(meta.get("card_id", "")).strip()
            if expected_id and card.id != expected_id:
                issues.append(
                    ValidationIssue(
                        code="questline_promotion.metadata_card_id",
                        message=f"card id {card.id!r} does not match metadata {expected_id!r}",
                        severity=ValidationSeverity.HARD_FAIL,
                        path="$.major_questlines",
                    )
                )
            if cluster_id in artifacts.excluded_cluster_ids:
                issues.append(
                    ValidationIssue(
                        code="questline_promotion.excluded_cluster",
                        message=f"card maps to excluded cluster {cluster_id!r}",
                        severity=ValidationSeverity.HARD_FAIL,
                        path="$.major_questlines",
                    )
                )

        if pilot_expectations:
            for card_id in pilot_expectations.excluded_card_ids:
                if any(c.id == card_id for c in parsed_entity.major_questlines):
                    issues.append(
                        ValidationIssue(
                            code="questline_promotion.registry_excluded_id",
                            message=f"registry excluded card id present: {card_id!r}",
                            severity=ValidationSeverity.HARD_FAIL,
                            path="$.major_questlines",
                        )
                    )

    return issues
