"""Baseline tests for staged vs legacy draft pipelines (mocked LLM)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline.common.run_context import ensure_run_context
from pipeline.contracts.models import Zone
from pipeline.generate.draft.instance_lint import MIN_OVERVIEW_WORDS
from pipeline.generate.draft_writer import run_draft_writer
from tests.draft_llm_mocks import fake_draft_chat_by_schema


def _mock_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SimpleNamespace(
        openai_ready=True,
        openai_model="gpt-5.5",
        openai_reasoning_effort=None,
        openai_verbosity=None,
        openai_draft_reasoning_effort=None,
        openai_draft_verbosity=None,
        openai_use_responses_api=False,
        openai_request_timeout_seconds=600,
    )
    for target in (
        "pipeline.generate.draft_writer.load_ai_settings",
        "pipeline.generate.draft.llm.load_ai_settings",
    ):
        monkeypatch.setattr(target, lambda: settings)

    def fake_chat(*args: object, **kwargs: object) -> dict[str, object] | None:
        return fake_draft_chat_by_schema(*args, **kwargs)

    for target in (
        "pipeline.generate.draft.llm.chat_json_completion",
        "pipeline.generate.draft_writer.chat_json_completion",
    ):
        monkeypatch.setattr(target, fake_chat)


@pytest.mark.parametrize("pipeline_mode", ["staged", "legacy"])
def test_zone_draft_baseline_validates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    pipeline_mode: str,
) -> None:
    monkeypatch.setenv("WOW_LORE_DRAFT_MODE", pipeline_mode)
    _mock_draft(monkeypatch)
    context = ensure_run_context(
        f"run-test-draft-baseline-{pipeline_mode}",
        artifacts_root=tmp_path / "runs",
    )
    fixture = Path("tests/fixtures/draft/zone_fact_pack_minimal.json")
    extract_dir = context.data_dir / "extracted"
    extract_dir.mkdir(parents=True, exist_ok=True)
    fact_pack_path = extract_dir / "zone-western-plaguelands.json"
    fact_pack_path.write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")

    outputs = run_draft_writer(context, [fact_pack_path], max_entity_concurrency=1)
    assert len(outputs) == 1
    draft = json.loads(outputs[0].read_text(encoding="utf-8"))
    Zone.model_validate(draft)

    decisions = json.loads(
        (context.data_dir / "drafts" / "draft_decisions.json").read_text(encoding="utf-8")
    )
    assert decisions[0]["draft_pipeline_mode"] == pipeline_mode
    trace_path = context.data_dir / "drafts" / "draft_llm_trace.jsonl"
    assert trace_path.is_file()
    if pipeline_mode == "staged":
        # plan + prose + links + at least one non-empty questline bucket
        assert int(decisions[0]["llm_call_count"]) >= 4
    else:
        assert int(decisions[0]["llm_call_count"]) >= 1

    if pipeline_mode == "staged":
        plan_path = context.data_dir / "drafts" / "_plans" / "zone-western-plaguelands.json"
        assert plan_path.is_file()


def test_wiki_first_draft_writer_populates_sections_from_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    context = ensure_run_context(
        "run-test-wiki-first-draft-writer",
        artifacts_root=tmp_path / "runs",
    )
    extract_dir = context.data_dir / "extracted"
    extract_dir.mkdir(parents=True, exist_ok=True)
    zone_fact_pack = {
        "entity_id": "zone-western-plaguelands",
        "entity_type": "zone",
        "name": "Western Plaguelands",
        "source_urls": {"src-zone": "https://warcraft.wiki.gg/wiki/Western_Plaguelands"},
        "source_ids": ["src-zone"],
        "revision_ids": ["mw:1"],
        "claims": ["Zone has active faction conflict and associated instance content."],
    }
    instance_fact_pack = {
        "entity_id": "instance-scholomance",
        "entity_type": "instance",
        "name": "Scholomance",
        "parent_zone_id": "zone-western-plaguelands",
        "source_urls": {"src-instance": "https://warcraft.wiki.gg/wiki/Scholomance"},
        "source_ids": ["src-instance"],
        "revision_ids": ["mw:2"],
        "claims": ["This raid remains tied to necromantic threats."],
    }
    zone_fact_path = extract_dir / "zone-western-plaguelands.json"
    instance_fact_path = extract_dir / "instance-scholomance.json"
    zone_fact_path.write_text(json.dumps(zone_fact_pack, indent=2), encoding="utf-8")
    instance_fact_path.write_text(json.dumps(instance_fact_pack, indent=2), encoding="utf-8")

    evidence_dir = context.data_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence_rows = [
        {
            "subject_id": "zone-western-plaguelands",
            "subject_type": "zone",
            "field_name": "history_digest",
            "evidence_items": [
                {
                    "source_url": "https://warcraft.wiki.gg/wiki/Western_Plaguelands",
                    "source_title": "Western Plaguelands",
                    "snippet": (
                        "The zone was blighted for years before coordinated campaigns by local "
                        "factions, crusader patrols, and restoration groups slowly reclaimed key "
                        "roads, farms, and defensive positions."
                    ),
                    "section_role": "history",
                    "confidence": 1.0,
                }
            ],
            "constraints": {"max_tokens": 1200, "forbidden_extrapolation": True},
            "build_meta": {"run_id": context.run_id, "source_id": "src-zone"},
        },
        {
            "subject_id": "zone-western-plaguelands",
            "subject_type": "zone",
            "field_name": "location_pool",
            "evidence_items": [
                {
                    "source_url": "https://warcraft.wiki.gg/wiki/Hearthglen",
                    "source_title": "Hearthglen",
                    "snippet": (
                        "Hearthglen is a fortified city and major settlement in the Western Plaguelands "
                        "where crusader commanders coordinate patrols, supply lines, and defensive "
                        "operations across the surrounding blighted farmland and broken keeps."
                    ),
                    "section_role": "maps_subregions",
                    "confidence": 1.0,
                }
            ],
            "constraints": {"max_tokens": 1200, "forbidden_extrapolation": True},
            "build_meta": {
                "run_id": context.run_id,
                "source_id": "src-location-hearthglen",
                "location_id": "location-hearthglen",
                "location_name": "Hearthglen",
            },
        },
        {
            "subject_id": "zone-western-plaguelands",
            "subject_type": "zone",
            "field_name": "at_a_glance_input",
            "evidence_items": [
                {
                    "source_url": "https://warcraft.wiki.gg/wiki/Western_Plaguelands",
                    "source_title": "Western Plaguelands",
                    "snippet": "Western Plaguelands remains a contested blighted region.",
                    "section_role": "lead",
                    "confidence": 1.0,
                }
            ],
            "constraints": {"max_tokens": 1200, "forbidden_extrapolation": True},
            "build_meta": {"run_id": context.run_id, "source_id": "src-zone"},
        },
        {
            "subject_id": "zone-western-plaguelands",
            "subject_type": "zone",
            "field_name": "currently_input",
            "evidence_items": [
                {
                    "source_url": "https://warcraft.wiki.gg/wiki/Western_Plaguelands",
                    "source_title": "Western Plaguelands",
                    "snippet": "Alliance and Horde campaigns still clash around Andorhal.",
                    "section_role": "quests_edit",
                    "confidence": 1.0,
                }
            ],
            "constraints": {"max_tokens": 1200, "forbidden_extrapolation": True},
            "build_meta": {"run_id": context.run_id, "source_id": "src-zone"},
        },
        {
            "subject_id": "zone-western-plaguelands",
            "subject_type": "zone",
            "field_name": "questline_pool",
            "evidence_items": [
                {
                    "source_url": "https://warcraft.wiki.gg/wiki/Into_the_Woods",
                    "source_title": "Into the Woods",
                    "snippet": "Into the Woods begins the Alliance push through the region.",
                    "section_role": "quests_or_storyline",
                    "confidence": 1.0,
                }
            ],
            "constraints": {"max_tokens": 1200, "forbidden_extrapolation": True},
            "build_meta": {"run_id": context.run_id, "source_id": "src-quest"},
        },
        {
            "subject_id": "instance-scholomance",
            "subject_type": "instance",
            "field_name": "at_a_glance_input",
            "evidence_items": [
                {
                    "source_url": "https://warcraft.wiki.gg/wiki/Scholomance",
                    "source_title": "Scholomance",
                    "snippet": (
                        "Scholomance is a haunted academy where necromancers and hostile instructors "
                        "still train recruits beneath blighted lecture halls."
                    ),
                    "section_role": "lead",
                    "confidence": 1.0,
                }
            ],
            "constraints": {"max_tokens": 1200, "forbidden_extrapolation": True},
            "build_meta": {
                "run_id": context.run_id,
                "source_id": "src-instance",
                "source_kind": "seed",
            },
        },
        {
            "subject_id": "instance-scholomance",
            "subject_type": "instance",
            "field_name": "history_digest",
            "evidence_items": [
                {
                    "source_url": "https://warcraft.wiki.gg/wiki/Scholomance",
                    "source_title": "Scholomance",
                    "snippet": (
                        "Scholomance was founded as a school for battle-mages who studied forbidden necromancy "
                        "after Lordaeron fell to plague and civil war. Its founders claimed they could control "
                        "death itself, training students in rituals that bound spirits to stone halls and shadowed "
                        "lecture chambers beneath the Western Plaguelands. Over decades the institution became a "
                        "stronghold for hostile instructors, rival cabals, and experiments that threatened every "
                        "nearby settlement. Crusader patrols, adventurers, and local militias repeatedly assaulted "
                        "the academy yet its inner vaults endured, guarded by fanatical wardens and archivists who "
                        "preserved grim curricula. Each campaign left deeper scars across the region while survivors "
                        "warned that the institution's leaders still coordinate recruitment, battlefield reinforcement, "
                        "and ritual escalation beyond its crumbling gates."
                    ),
                    "section_role": "history",
                    "confidence": 1.0,
                }
            ],
            "constraints": {"max_tokens": 1200, "forbidden_extrapolation": True},
            "build_meta": {
                "run_id": context.run_id,
                "source_id": "src-instance",
                "source_kind": "seed",
            },
        },
        {
            "subject_id": "instance-scholomance",
            "subject_type": "instance",
            "field_name": "boss_pool",
            "evidence_items": [
                {
                    "source_url": "https://warcraft.wiki.gg/wiki/Scholomance",
                    "source_title": "Scholomance",
                    "snippet": (
                        "Bosses include /wiki/Darkmaster_Gandling and /wiki/Instructor_Malicia within Scholomance."
                    ),
                    "section_role": "adventurers",
                    "confidence": 1.0,
                }
            ],
            "constraints": {"max_tokens": 1200, "forbidden_extrapolation": True},
            "build_meta": {
                "run_id": context.run_id,
                "source_id": "src-instance",
                "source_kind": "seed",
            },
        },
    ]
    (evidence_dir / "evidence_packs.jsonl").write_text(
        "\n".join(json.dumps(row) for row in evidence_rows) + "\n",
        encoding="utf-8",
    )

    discovery_dir = context.data_dir / "discovery"
    discovery_dir.mkdir(parents=True, exist_ok=True)
    (discovery_dir / "zone_quest_graph_v3.json").write_text(
        json.dumps(
            [
                {
                    "zone_id": "zone-western-plaguelands",
                    "node_id": "quest-into-the-woods",
                    "title": "Into the Woods",
                    "node_type": "quest",
                    "source_link": "/wiki/Into_the_Woods",
                    "faction_binding": "alliance",
                    "cluster_id": "cluster-main",
                    "cluster_title": "Main storylines",
                    "cluster_order": 1,
                    "order_in_cluster": 1,
                }
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    (discovery_dir / "zone_location_classification.json").write_text(
        json.dumps(
            [
                {
                    "zone_id": "zone-western-plaguelands",
                    "location_id": "location-hearthglen",
                    "name": "Hearthglen",
                    "classification": "major_location_candidate",
                    "hard_reject_reasons": [],
                    "typing_signals": {"source_section_role": "maps_subregions"},
                }
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    (discovery_dir / "zone_location_candidates.json").write_text(
        json.dumps(
            [
                {
                    "zone_id": "zone-western-plaguelands",
                    "location_id": "location-hearthglen",
                    "name": "Hearthglen",
                    "source_link": "/wiki/Hearthglen",
                    "source_section_role": "maps_subregions",
                }
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    (discovery_dir / "zone_instance_registry.json").write_text(
        json.dumps(
            [
                {
                    "instance_id": "instance-scholomance",
                    "name": "Scholomance",
                    "source_zone_id": "zone-western-plaguelands",
                    "source_link": "/wiki/Scholomance",
                    "instance_type": "dungeon",
                    "variant_cluster_key": "scholomance",
                }
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    (discovery_dir / "instance_lore_source_map.json").write_text(
        json.dumps(
            [
                {
                    "instance_id": "instance-scholomance",
                    "lore_source": "instance_page",
                    "fallback_reason": None,
                    "source_link": "/wiki/Scholomance",
                }
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    decisions_dir = context.data_dir / "decisions"
    decisions_dir.mkdir(parents=True, exist_ok=True)
    (decisions_dir / "location_significance_decisions.json").write_text(
        json.dumps(
            [
                {
                    "subject_id": "location-hearthglen",
                    "subject_type": "location",
                    "run_id": context.run_id,
                    "algorithm_version": "v1",
                    "features": {"source_section_role": "maps_subregions"},
                    "hard_reject": False,
                    "hard_reject_reasons": [],
                    "score": 0.75,
                    "thresholds": {"include_min": 0.7},
                    "borderline_adjudication": None,
                    "final_decision": "include",
                    "reason_codes": ["score_based"],
                }
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    (decisions_dir / "questline_inclusion_decisions.json").write_text(
        json.dumps(
            [
                {
                    "subject_id": "zone-western-plaguelands",
                    "subject_type": "zone_questline_set",
                    "run_id": context.run_id,
                    "algorithm_version": "v1",
                    "features": {"quest_graph_depth": 1},
                    "hard_reject": False,
                    "hard_reject_reasons": [],
                    "score": 0.8,
                    "thresholds": {"include_min": 0.7},
                    "borderline_adjudication": None,
                    "final_decision": "include",
                    "reason_codes": ["graph_depth"],
                }
            ],
            indent=2,
        ),
        encoding="utf-8",
    )

    outputs = run_draft_writer(
        context, [zone_fact_path, instance_fact_path], max_entity_concurrency=1
    )
    assert len(outputs) == 2
    zone_output = next(path for path in outputs if path.parent.name == "zone_page")
    instance_output = next(path for path in outputs if path.parent.name == "instance_page")
    zone_draft = json.loads(zone_output.read_text(encoding="utf-8"))
    instance_draft = json.loads(instance_output.read_text(encoding="utf-8"))

    assert zone_draft["history_sections"]
    assert zone_draft["location_cards"]
    assert zone_draft["instance_links"]
    assert zone_draft["sources"]
    assert "reclaimed" in zone_draft["history_sections"][0]["body"].lower()
    assert instance_draft["history_sections"]
    assert instance_draft["key_characters"]
    assert instance_draft["sources"]
    assert len(str(instance_draft.get("overview", "")).split()) >= MIN_OVERVIEW_WORDS
    enemy_names = {row["name"] for row in instance_draft["key_characters"]}
    assert "Darkmaster Gandling" in enemy_names
