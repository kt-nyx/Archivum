import json
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError

from pipeline.contracts.models import (
    ENTITY_MODEL_MAP,
    Asset,
    InclusionDecision,
    SourcePointer,
    Zone,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(*parts: str) -> dict[str, Any]:
    fixture_path = FIXTURES_DIR.joinpath(*parts)
    return cast(dict[str, Any], json.loads(fixture_path.read_text(encoding="utf-8")))


def test_entity_model_map_contains_locked_types() -> None:
    assert sorted(ENTITY_MODEL_MAP) == [
        "asset",
        "character",
        "glossary_term",
        "instance",
        "sub_zone",
        "zone",
    ]


def test_zone_contract_parses_minimal_inline_payload() -> None:
    zone = Zone.model_validate(
        {
            "id": "zone-western-plaguelands",
            "slug": "western-plaguelands",
            "name": "Western Plaguelands",
            "expansion": "cataclysm-state",
            "at_a_glance": "Blighted farmland contested by crusaders and undead remnants.",
            "currently": (
                "Argent operations continue to stabilize roads while hostile forces pressure key routes."
            ),
            "history": (
                "The region suffered catastrophic plague-era collapse before sustained military campaigns "
                "began long-term restoration efforts across reclaimed farmland and broken keeps."
            ),
            "major_questlines_alliance": [
                {
                    "id": "ql-andorhal-alliance",
                    "faction": "alliance",
                    "title": "Andorhal War Campaign",
                    "hook": (
                        "Alliance forces attempt to secure Andorhal through a sustained campaign that "
                        "combines plague containment, civilian extraction, supply-line defense, and repeated "
                        "assaults on fortified undead positions across the ruined city blocks."
                    ),
                    "start_anchor": "Andorhal",
                    "story_beats": ["Secure supply routes"],
                    "inclusion_decision": {
                        "inclusion_score": 8,
                        "criteria_breakdown": {
                            "importance": 2,
                            "coherence": 2,
                            "evidence": 2,
                            "relevance": 2,
                        },
                        "include_decision": "include",
                        "decision_reason": "Pilot-critical arc with sourced coverage.",
                        "source_refs": [],
                    },
                    "depends_on_parent_context": False,
                }
            ],
            "major_questlines_horde": [],
            "major_questlines_shared": [],
            "major_characters": [],
            "instances": [],
            "major_landmarks": [],
            "glossary": [],
            "sources": [],
            "provenance": {
                "at_a_glance": [],
                "currently": [],
                "history": [],
                "major_questlines_alliance": {},
                "major_questlines_horde": {},
                "major_questlines_shared": {},
                "major_characters": {},
                "instances": {},
                "major_landmarks": {},
                "glossary": {},
            },
        }
    )
    assert zone.id == "zone-western-plaguelands"
    assert len(zone.major_questlines_alliance) == 1


def test_source_pointer_requires_strict_four_fields() -> None:
    with pytest.raises(ValidationError):
        SourcePointer.model_validate(
            {
                "source_id": "src-wiki-wpl",
                "locator": "section:history paragraph:1",
                "excerpt_hash": "sha256:abc123",
            }
        )


def test_inclusion_decision_validates_breakdown_range() -> None:
    with pytest.raises(ValidationError):
        InclusionDecision.model_validate(
            {
                "inclusion_score": 6,
                "criteria_breakdown": {"importance": 3},
                "include_decision": "include",
                "decision_reason": "Fits pilot scope.",
                "source_refs": [],
            }
        )


def test_inclusion_decision_score_must_match_breakdown_total() -> None:
    with pytest.raises(ValidationError):
        InclusionDecision.model_validate(
            {
                "inclusion_score": 8,
                "criteria_breakdown": {"importance": 2, "coherence": 2},
                "include_decision": "include",
                "decision_reason": "Mismatch example.",
                "source_refs": [],
            }
        )


def test_inclusion_decision_accepts_score_matching_breakdown_total() -> None:
    decision = InclusionDecision.model_validate(
        {
            "inclusion_score": 4,
            "criteria_breakdown": {"importance": 2, "coherence": 2},
            "include_decision": "include",
            "decision_reason": "Aligned totals.",
            "source_refs": [],
        }
    )
    assert decision.inclusion_score == 4


def test_asset_requires_allowed_use_reason() -> None:
    with pytest.raises(ValidationError):
        Asset.model_validate(
            {
                "id": "asset-hearthglen",
                "asset_type": "image",
                "title": "Hearthglen Panorama",
                "source_url": "https://example.test/asset/hearthglen",
                "license": "CC-BY-SA",
                "credit": "Example Artist",
                "allowed_use": True,
                "proof_ref": "proof:asset-license-hearthglen",
                "associated_entity_ids": ["zone-western-plaguelands"],
                "sources": [
                    {
                        "source_id": "src-license-bundle",
                        "url": "https://example.test/legal/hearthglen-license-bundle",
                        "revision_id": "bundle-v3",
                    }
                ],
                "provenance": {"caption": [], "metadata": []},
            }
        )
