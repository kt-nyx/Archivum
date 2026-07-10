"""Zone-neutral promotion validation for generated questline cards."""

from __future__ import annotations

from typing import Any

from pipeline.contracts.models import IncludeDecision, ZonePage
from pipeline.discovery.questline_promotion_gate import (
    QuestlineRunArtifacts,
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
            "start_anchor": card.start_anchor,
            "chain_refs": list(card.chain_refs),
            "include_decision": card.include_decision.value,
        }
        for card in zone_page.major_questlines
    ]


def _artifacts_from_context(entity_id: str, context: dict[str, Any]) -> QuestlineRunArtifacts:
    metadata_by_cluster = dict(context.get("questline_card_metadata_by_cluster") or {})
    return QuestlineRunArtifacts(
        zone_id=entity_id,
        cards=[],
        included_cluster_ids=list(context.get("questline_included_cluster_ids") or []),
        metadata_by_cluster=metadata_by_cluster,
        card_id_to_cluster_id={
            str(row.get("card_id", "")).strip(): cluster_id
            for cluster_id, row in metadata_by_cluster.items()
            if str(row.get("card_id", "")).strip()
        },
        excluded_cluster_ids=set(context.get("questline_excluded_cluster_ids") or []),
        v3_quest_rows=[],
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
    artifacts = _artifacts_from_context(str(parsed_entity.zone_id), context)
    artifacts.cards = _cards_from_zone_page(parsed_entity)
    issues: list[ValidationIssue] = []
    seen_ids: set[str] = set()

    for index, card in enumerate(parsed_entity.major_questlines):
        path_prefix = f"$.major_questlines[{index}]"
        if card.id in seen_ids:
            issues.append(ValidationIssue(
                code="questline_promotion.duplicate_id",
                message="questline card ids must be unique",
                severity=ValidationSeverity.HARD_FAIL,
                path=f"{path_prefix}.id",
            ))
        seen_ids.add(card.id)
        if artifacts.metadata_by_cluster and not card.id.startswith("ql-"):
            issues.append(ValidationIssue(
                code="questline_promotion.graph_id",
                message="questline card id must derive from its graph cluster (ql-*)",
                severity=ValidationSeverity.HARD_FAIL,
                path=f"{path_prefix}.id",
            ))
        if card.include_decision != IncludeDecision.INCLUDE:
            issues.append(ValidationIssue(
                code="questline_promotion.include_decision",
                message="questline card must resolve to include",
                severity=ValidationSeverity.HARD_FAIL,
                path=f"{path_prefix}.include_decision",
            ))
        if not card.chain_refs or len(card.chain_refs) > _MAX_CHAIN_REFS:
            issues.append(ValidationIssue(
                code="questline_promotion.chain_refs",
                message=f"chain_refs must contain 1-{_MAX_CHAIN_REFS} graph nodes",
                severity=ValidationSeverity.HARD_FAIL,
                path=f"{path_prefix}.chain_refs",
            ))
        cluster_id = cluster_id_from_card_id(card.id, artifacts.card_id_to_cluster_id)
        if cluster_id in artifacts.excluded_cluster_ids:
            issues.append(ValidationIssue(
                code="questline_promotion.excluded_cluster",
                message="questline card maps to an excluded graph cluster",
                severity=ValidationSeverity.HARD_FAIL,
                path=path_prefix,
            ))
        metadata = artifacts.metadata_by_cluster.get(cluster_id, {})
        expected_id = str(metadata.get("card_id", "")).strip()
        if expected_id and card.id != expected_id and not card.id.startswith(f"{expected_id}-segment-"):
            issues.append(ValidationIssue(
                code="questline_promotion.metadata_card_id",
                message="questline card id does not derive from its metadata cluster id",
                severity=ValidationSeverity.HARD_FAIL,
                path=f"{path_prefix}.id",
            ))

    for warning in warn_questline_promotion(artifacts):
        issues.append(ValidationIssue(
            code="questline_promotion.weak_start_anchor",
            message=warning,
            severity=ValidationSeverity.WARN,
            path="$.major_questlines",
        ))
    return issues
