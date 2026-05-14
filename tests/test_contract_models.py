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


def test_zone_fixture_parses_with_canonical_contract() -> None:
    payload = _load_fixture("happy", "zone_valid.json")
    zone = Zone.model_validate(payload)
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
