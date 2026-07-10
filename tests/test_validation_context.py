from __future__ import annotations

import json

import pytest

from pipeline.generate.draft.model_versions import PROSE_FINALIZE_DECISION_SCHEMA
from pipeline.validate.context import load_validation_run_resources


def test_prose_finalize_decisions_are_versioned_and_fail_closed(tmp_path) -> None:
    decisions = tmp_path / "data" / "decisions"
    decisions.mkdir(parents=True)
    artifact = decisions / "prose_finalize_decisions.json"
    artifact.write_text(json.dumps([]), encoding="utf-8")

    with pytest.raises(ValueError, match="prose_finalize_decisions artifact from draft_writer"):
        load_validation_run_resources(tmp_path)

    artifact.write_text(
        json.dumps(
            {
                "schema_version": PROSE_FINALIZE_DECISION_SCHEMA,
                "producer": "draft_writer",
                "decisions": [
                    {
                        "entity_id": "zone-synthetic",
                        "stage": "major_factions.candidates",
                        "candidates": [{"name": "Lantern Wardens"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    resources = load_validation_run_resources(tmp_path)
    assert resources.faction_candidate_names_by_entity == {
        "zone-synthetic": ["Lantern Wardens"]
    }
