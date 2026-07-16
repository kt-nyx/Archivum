"""Strict release-gate rules (generalization-quality-recovery Slice 8).

These are the deterministic hard-fail gates that stop a run from being marked a *strict* success
while it still emits an invalid card kind, a card whose identity is not owned by its own evidence,
a key-character that is not a named actor with in-instance retail presence, a questline with no
setup evidence, a duplicate card label, or a malformed final CTA clause.

Every check consults the selection/evidence sidecars carried in the validation context
(``release_*`` keys built by :func:`pipeline.validate.context.release_gate_entity_flags`). The
rules run only under ``release_gate`` — a warning-only exploration profile is deliberately not held
to these contracts. Each check is *sidecar-gated*: when the relevant sidecar was not loaded for the
run (e.g. a unit payload validated in isolation), the check no-ops rather than inventing a failure.
The rules are entirely card-family/kind driven; they encode no zone, instance, title, race, or
species knowledge.
"""

from __future__ import annotations

import re
from typing import Any

from pipeline.contracts.models import InstancePage, ZonePage
from pipeline.validate.types import ValidationIssue, ValidationSeverity

_WS_RE = re.compile(r"\s+")


def _hard(code: str, message: str, path: str) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        message=message,
        severity=ValidationSeverity.HARD_FAIL,
        path=path,
    )


def _normalized_label(value: str) -> str:
    return _WS_RE.sub(" ", value).strip().casefold()


def _pack_issues(
    *,
    card_id: str,
    expected_type: str,
    packs: dict[str, Any],
    packs_present: bool,
    path: str,
) -> list[ValidationIssue]:
    """Item 1(c)/item 2: a rendered card must own a sufficient, correctly-typed evidence pack.

    Skipped when the run produced no packs at all (the sidecar is absent from this context).
    """
    if not packs_present:
        return []
    pack = packs.get(card_id)
    if not isinstance(pack, dict):
        return [
            _hard(
                "release_gate.card_missing_evidence_pack",
                f"rendered card '{card_id}' has no card evidence pack; final rendering must not "
                "create a card the selection/evidence sidecar does not contain",
                path,
            )
        ]
    issues: list[ValidationIssue] = []
    if str(pack.get("card_type", "")) != expected_type:
        issues.append(
            _hard(
                "release_gate.card_pack_kind_mismatch",
                f"card '{card_id}' evidence pack is '{pack.get('card_type')}', expected "
                f"'{expected_type}'",
                path,
            )
        )
    if (
        str(pack.get("sufficiency", "")) != "ok"
        or not pack.get("identity_evidence")
        or not pack.get("provenance_ids")
    ):
        issues.append(
            _hard(
                "release_gate.card_missing_identity_evidence",
                f"card '{card_id}' evidence pack lacks direct identity evidence "
                f"(sufficiency={pack.get('sufficiency')!r})",
                path,
            )
        )
    return issues


def _duplicate_label_issues(labels: list[tuple[str, str]]) -> list[ValidationIssue]:
    """Item 1(g): no two rendered cards *in the same family* may share a normalized label.

    Detection is per family (factions, locations, questlines, key characters) because a cross-family
    collision — an organization named after a place, say — can be legitimate, while a within-family
    collision is the degenerate/generic-roster defect this gate targets.
    """
    issues: list[ValidationIssue] = []
    seen: dict[str, str] = {}
    for label, path in labels:
        normalized = _normalized_label(label)
        if not normalized:
            continue
        if normalized in seen:
            issues.append(
                _hard(
                    "release_gate.duplicate_card_label",
                    f"card label '{label}' duplicates a card already rendered at "
                    f"{seen[normalized].removeprefix('$.')}",
                    path,
                )
            )
        else:
            seen[normalized] = path
    return issues


def _card_id_to_cluster_id(context: dict[str, Any]) -> dict[str, str]:
    metadata_by_cluster = context.get("questline_card_metadata_by_cluster") or {}
    mapping: dict[str, str] = {}
    for cluster_id, row in metadata_by_cluster.items():
        card_id = str((row or {}).get("card_id", "")).strip()
        if card_id:
            mapping[card_id] = str(cluster_id).strip()
    return mapping


def _validate_zone_page(zone_page: ZonePage, context: dict[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    packs = context.get("release_card_evidence_packs") or {}
    packs_present = bool(context.get("release_card_packs_present"))
    location_selection = context.get("release_location_selection_by_id") or {}

    for index, loc_card in enumerate(zone_page.location_cards):
        path = f"$.location_cards[{index}]"
        issues.extend(
            _pack_issues(
                card_id=loc_card.id,
                expected_type="location",
                packs=packs,
                packs_present=packs_present,
                path=path,
            )
        )
        if location_selection:
            decision = location_selection.get(loc_card.id)
            if not isinstance(decision, dict):
                # Item 2: a rendered location the selection sidecar never recorded.
                issues.append(
                    _hard(
                        "release_gate.location_card_unselected",
                        f"location card '{loc_card.id}' is not present in the location selection "
                        "sidecar",
                        path,
                    )
                )
            else:
                if str(decision.get("entity_kind", "")) != "place":
                    # Item 1(a): only `place`-kind entities may be location cards.
                    issues.append(
                        _hard(
                            "release_gate.location_card_not_place",
                            f"location card '{loc_card.id}' has entity kind "
                            f"'{decision.get('entity_kind')}', not 'place'",
                            path,
                        )
                    )
                if str(decision.get("state", "")) != "selected":
                    issues.append(
                        _hard(
                            "release_gate.location_card_unselected",
                            f"location card '{loc_card.id}' selection state is "
                            f"'{decision.get('state')}', not 'selected'",
                            path,
                        )
                    )

    for index, faction_card in enumerate(zone_page.major_factions):
        issues.extend(
            _pack_issues(
                card_id=faction_card.id,
                expected_type="faction",
                packs=packs,
                packs_present=packs_present,
                path=f"$.major_factions[{index}]",
            )
        )

    card_to_cluster = _card_id_to_cluster_id(context)
    setup_clusters = context.get("release_questline_setup_clusters") or set()
    entry_state_present = bool(context.get("release_entry_state_present"))
    for index, ql_card in enumerate(zone_page.major_questlines):
        path = f"$.major_questlines[{index}]"
        issues.extend(
            _pack_issues(
                card_id=ql_card.id,
                expected_type="questline",
                packs=packs,
                packs_present=packs_present,
                path=path,
            )
        )
        # Item 1(f): a rendered questline card requires non-empty setup evidence in its entry-state
        # contract. Checked only when both the metadata card→cluster map and the entry-state
        # contract were loaded for this entity.
        if entry_state_present and card_to_cluster:
            cluster_id = card_to_cluster.get(ql_card.id, "")
            if cluster_id and cluster_id not in setup_clusters:
                issues.append(
                    _hard(
                        "release_gate.questline_setup_evidence_empty",
                        f"questline card '{ql_card.id}' (cluster '{cluster_id}') has no non-empty "
                        "setup evidence in its entry-state contract",
                        path,
                    )
                )

    # Item 1(h): a persisted final CTA clause that still fails lint.
    if context.get("release_cta_lint_failed"):
        issues.append(
            _hard(
                "release_gate.questline_cta_lint_failed",
                "a finalized questline CTA clause failed final lint (see prose_finalize_decisions)",
                "$.major_questlines",
            )
        )

    issues.extend(
        _duplicate_label_issues(
            [(f.name, f"$.major_factions[{i}]") for i, f in enumerate(zone_page.major_factions)]
        )
    )
    issues.extend(
        _duplicate_label_issues(
            [(loc.name, f"$.location_cards[{i}]") for i, loc in enumerate(zone_page.location_cards)]
        )
    )
    issues.extend(
        _duplicate_label_issues(
            [(q.title, f"$.major_questlines[{i}]") for i, q in enumerate(zone_page.major_questlines)]
        )
    )
    return issues


def _validate_instance_page(
    instance_page: InstancePage, context: dict[str, Any]
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    packs = context.get("release_card_evidence_packs") or {}
    packs_present = bool(context.get("release_card_packs_present"))
    participants = context.get("release_instance_participants") or {}
    participants_present = bool(context.get("release_instance_decision_present"))

    for index, kc_card in enumerate(instance_page.key_characters):
        path = f"$.key_characters[{index}]"
        issues.extend(
            _pack_issues(
                card_id=kc_card.id,
                expected_type="key_character",
                packs=packs,
                packs_present=packs_present,
                path=path,
            )
        )
        if not participants_present:
            continue
        decision = participants.get(kc_card.id)
        if not isinstance(decision, dict):
            # Item 2: a rendered key-character the admission sidecar never recorded.
            issues.append(
                _hard(
                    "release_gate.key_character_unselected",
                    f"key-character card '{kc_card.id}' is not present in the instance "
                    "key-character admission sidecar",
                    path,
                )
            )
            continue
        if str(decision.get("entity_kind", "")) != "named_actor":
            # Item 1(b): only named actors may be key-character cards.
            issues.append(
                _hard(
                    "release_gate.key_character_not_named_actor",
                    f"key-character card '{kc_card.id}' has entity kind "
                    f"'{decision.get('entity_kind')}', not 'named_actor'",
                    path,
                )
            )
        if str(decision.get("retail_scope", "")) != "retail_confirmed" or not decision.get(
            "instance_presence_evidence"
        ):
            # Item 1(d): invalid instance-presence / retail-scope data.
            issues.append(
                _hard(
                    "release_gate.key_character_invalid_instance_scope",
                    f"key-character card '{kc_card.id}' lacks confirmed retail scope or direct "
                    "instance-presence evidence",
                    path,
                )
            )
        if str(decision.get("admission", "")) != "eligible" or not decision.get("emitted"):
            # Item 2: the card must correspond to an eligible, emitted admission.
            issues.append(
                _hard(
                    "release_gate.key_character_not_admitted",
                    f"key-character card '{kc_card.id}' admission is "
                    f"'{decision.get('admission')}' / emitted={decision.get('emitted')}",
                    path,
                )
            )
        elif str(decision.get("final_role", "")) != str(kc_card.role):
            # Item 2: role bounds must agree with the recorded selection.
            issues.append(
                _hard(
                    "release_gate.key_character_role_mismatch",
                    f"key-character card '{kc_card.id}' role '{kc_card.role}' disagrees with the "
                    f"selection role '{decision.get('final_role')}'",
                    path,
                )
            )

    for index, card in enumerate(instance_page.major_factions):
        issues.extend(
            _pack_issues(
                card_id=card.id,
                expected_type="faction",
                packs=packs,
                packs_present=packs_present,
                path=f"$.major_factions[{index}]",
            )
        )

    issues.extend(
        _duplicate_label_issues(
            [
                (kc.name, f"$.key_characters[{i}]")
                for i, kc in enumerate(instance_page.key_characters)
            ]
        )
    )
    issues.extend(
        _duplicate_label_issues(
            [(f.name, f"$.major_factions[{i}]") for i, f in enumerate(instance_page.major_factions)]
        )
    )
    return issues


def validate_release_gate_rules(
    entity_type: str,
    parsed_entity: Any,
    *,
    validation_context: dict[str, Any] | None = None,
) -> list[ValidationIssue]:
    """Strict release-gate hard-fails. No-op unless ``release_gate`` is set in the context."""
    context = dict(validation_context or {})
    if not context.get("release_gate"):
        return []
    if entity_type == "zone_page" and isinstance(parsed_entity, ZonePage):
        return _validate_zone_page(parsed_entity, context)
    if entity_type == "instance_page" and isinstance(parsed_entity, InstancePage):
        return _validate_instance_page(parsed_entity, context)
    return []
