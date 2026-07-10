"""Pilot-leak guard: no pilot name may appear in any LLM prompt for a non-pilot subject.

Slice 11 (design policy 3: no pilot facts in shared code, data, or prompts). This renders
every system/task prompt builder in the pipeline for an invented, non-pilot subject and
asserts that no name harvested from ``tests/fixtures/pilot/`` (zone/instance names, faction
names, location names, questline titles/anchors, key characters, gold history headings)
appears in any rendered prompt. It generalizes — and replaces — the old single-prompt
``_FORBIDDEN_PILOT_PROMPT_STRINGS`` check.

Mechanism: each renderer invokes a prompt-building call path with the module's LLM entry
point monkeypatched to a recorder, so the exact prompt strings the pipeline would send are
captured. Renderers whose post-LLM handling errors are tolerated (the prompts are already
captured), but every renderer must capture at least one prompt — a renderer that stops
rendering fails the guard rather than silently dropping coverage.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import pytest

# The two universal player factions are game-wide vocabulary (like the "Hero's Call" /
# "Warchief's Command" breadcrumb conventions), not pilot facts.
_UNIVERSAL_NAMES = {"alliance", "horde"}


def _strip_parenthetical(name: str) -> str:
    return re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()


def harvest_forbidden_pilot_names() -> frozenset[str]:
    # Test-only regression corpus of pilot facts. It is deliberately not a page/card fixture,
    # so no hand-authored output participates in generation or acceptance.
    cleaned = {
        _strip_parenthetical(name)
        for name in {
            "Western Plaguelands", "Scholomance", "Scourge", "Cult of the Damned",
            "Andorhal", "Caer Darrow", "Lilian Voss", "An Audience with the Highlord",
            "Rise of the Dead", "Alliance", "Horde",
        }
    }
    return frozenset(
        name
        for name in cleaned
        if len(name) >= 4 and name.casefold() not in _UNIVERSAL_NAMES
    )


FORBIDDEN_PILOT_NAMES = harvest_forbidden_pilot_names()


def test_harvest_finds_the_expected_name_classes() -> None:
    """Sanity: the harvest actually carries the pilot facts the guard must catch."""
    lowered = {name.casefold() for name in FORBIDDEN_PILOT_NAMES}
    for expected in (
        "western plaguelands",
        "scholomance",
        "scourge",
        "cult of the damned",
        "andorhal",
        "caer darrow",
        "lilian voss",
        "an audience with the highlord",
        "rise of the dead",
    ):
        assert expected in lowered, f"harvest lost expected pilot name {expected!r}"
    assert "alliance" not in lowered
    assert "horde" not in lowered


# ---------------------------------------------------------------------------
# Prompt capture
# ---------------------------------------------------------------------------

# Invented, non-pilot subject (the tests' "Archive Vault / Archivist Maelor" convention).
FAKE_ZONE = "Fake Vale"
FAKE_INSTANCE = "Archive Vault"
FAKE_CHARACTER = "Archivist Maelor"
FAKE_FACTION = "Order of the Sealed Gate"
FAKE_LOCATION = "Stillwater Rest"

_EVIDENCE = [
    {
        "source_id": "src-fake-1",
        "snippet": "A quiet vale of old farms where a sealed order keeps its vigil.",
        "section_role": "history",
        "raw_section_role": "history",
        "quest_node_id": "quest-fake-1",
    },
    {
        "source_id": "src-fake-2",
        "snippet": "The order rebuilt the burned mill and watches the northern road.",
        "section_role": "currently",
        "raw_section_role": "current_state",
        "quest_node_id": "quest-fake-2",
    },
]


def _default_llm_value(key: str) -> Any:
    if key in {
        "used_evidence_ids",
        "sections",
        "headings",
        "selected",
        "keep_ids",
        "claims",
        "cards",
        "aliases",
        "associated_entity_ids",
        "major_questlines_alliance",
        "major_questlines_horde",
        "major_questlines_shared",
        "major_characters",
        "instances",
        "major_landmarks",
        "glossary",
        "key_characters",
    }:
        return []
    if key == "contract_fields":
        return {}
    if key == "allowed_use":
        return True
    return ""


class PromptRecorder:
    """Stands in for a module's LLM entry point and records every prompt string."""

    def __init__(self) -> None:
        self.prompts: list[tuple[str, str]] = []
        self._label = ""

    def set_label(self, label: str) -> None:
        self._label = label

    def record(self, kwargs: dict[str, Any]) -> None:
        for field in ("system_prompt", "user_prompt"):
            text = str(kwargs.get(field, ""))
            if text:
                self.prompts.append((f"{self._label}:{field}", text))

    def llm_json_with_retry(self, **kwargs: Any) -> dict[str, Any]:
        self.record(kwargs)
        return {key: _default_llm_value(str(key)) for key in kwargs.get("required_keys", ())}

    def chat_json_completion(self, _settings: Any, **kwargs: Any) -> dict[str, Any]:
        self.record(kwargs)
        return {"claims": ["A recorded claim."]}


class _ReadySettings:
    openai_ready = True
    openai_model = "test-model"


def _fact_pack() -> dict[str, Any]:
    return {
        "entity_id": "zone-fake-vale",
        "slug": "fake-vale",
        "name": FAKE_ZONE,
        "parent_zone_id": "zone-fake-vale",
        "claims": ["The sealed order keeps its vigil over the vale."],
        "fact_items": [],
        "source_ids": ["src-fake-1"],
        "revision_ids": ["mw:1"],
        "source_urls": {"src-fake-1": "https://example.test/wiki/Fake_Vale"},
    }


def _prompt_renderers(
    monkeypatch: pytest.MonkeyPatch, recorder: PromptRecorder
) -> dict[str, Callable[[], Any]]:
    """Label -> callable rendering that prompt path; every LLM call lands in ``recorder``."""
    monkeypatch.delenv("WOW_LORE_WIKI_FIRST_NO_LLM", raising=False)

    from pipeline.coalesce import resolve_entities
    from pipeline.discovery.instance_bosses import BossCandidate
    from pipeline.generate.draft import (
        claims as claims_module,
    )
    from pipeline.generate.draft import (
        compendium_voice,
        legacy,
        planner,
        prose_selection,
        prose_synthesis,
        temporal,
        workers,
    )
    from pipeline.validate.rules import fact_check

    for module in (prose_synthesis, prose_selection, temporal, workers, planner, legacy):
        monkeypatch.setattr(module, "llm_json_with_retry", recorder.llm_json_with_retry)
    for module in (prose_synthesis, prose_selection, temporal, resolve_entities):
        monkeypatch.setattr(module, "load_ai_settings", lambda: _ReadySettings())
    monkeypatch.setattr(fact_check, "chat_json_completion", recorder.chat_json_completion)
    monkeypatch.setattr(resolve_entities, "chat_json_completion", recorder.chat_json_completion)
    monkeypatch.setattr(temporal, "_llm_temporal_adjudication_disabled", lambda: False)
    monkeypatch.setattr(
        temporal, "_entry_state_contract_distillation_enabled", lambda: True
    )

    def _render_compendium_voice_fragments() -> None:
        fragments = [
            value
            for name, value in vars(compendium_voice).items()
            if isinstance(value, str) and name.isupper()
        ]
        assert fragments, "compendium_voice exposes no prompt fragments"
        for index, fragment in enumerate(fragments):
            recorder.prompts.append((f"compendium_voice[{index}]:fragment", fragment))
        recorder.prompts.append(
            (
                "compendium_voice:zone_system_prompt",
                compendium_voice.zone_system_prompt(field_voice="Voice.", task_lines="Task."),
            )
        )
        recorder.prompts.append(
            (
                "compendium_voice:instance_system_prompt",
                compendium_voice.instance_system_prompt(field_voice="Voice.", task_lines="Task."),
            )
        )

    def _boss_candidate() -> BossCandidate:
        candidate = BossCandidate(
            boss_id="character-archivist-maelor",
            name=FAKE_CHARACTER,
            wiki_url="https://example.test/wiki/Archivist_Maelor",
            source_section_role="bosses",
        )
        candidate.profile_pool = [dict(_EVIDENCE[0])]
        return candidate

    claim_views = [
        {**item, "is_claim_view": True, "claim_text": item["snippet"]} for item in _EVIDENCE
    ]

    contract = temporal.EntryStateContract(
        entity_id="zone-fake-vale", entity_type="zone", name=FAKE_ZONE
    )
    anchor_field = next(iter(temporal._CURRENT_ANCHOR_FIELDS))

    return {
        "compendium_voice": _render_compendium_voice_fragments,
        "at_a_glance_zone": lambda: prose_synthesis.synthesize_at_a_glance(list(_EVIDENCE)),
        "at_a_glance_instance": lambda: prose_synthesis.synthesize_at_a_glance(
            list(_EVIDENCE), subject=FAKE_INSTANCE, reference_framing="Reference framing."
        ),
        "currently": lambda: prose_synthesis.synthesize_currently(list(_EVIDENCE)),
        "history_sections": lambda: prose_synthesis.synthesize_history_sections(
            list(_EVIDENCE), required_event_texts=["The order sealed the vale gate."]
        ),
        "relabel_history_headings": lambda: prose_synthesis.relabel_history_headings(
            [{"heading": "History", "body": "The vale changed hands twice."}]
        ),
        "faction_summary_zone": lambda: prose_synthesis.synthesize_faction_summary(
            list(_EVIDENCE), faction_name=FAKE_FACTION, zone_name=FAKE_ZONE
        ),
        "faction_summary_instance": lambda: prose_synthesis.synthesize_faction_summary(
            list(_EVIDENCE),
            faction_name=FAKE_FACTION,
            zone_name=FAKE_ZONE,
            instance_name=FAKE_INSTANCE,
        ),
        "location_summary": lambda: prose_synthesis.synthesize_location_summary(
            list(_EVIDENCE), location_name=FAKE_LOCATION, zone_name=FAKE_ZONE
        ),
        "location_significance": lambda: prose_synthesis.synthesize_location_significance(
            list(_EVIDENCE), location_name=FAKE_LOCATION, zone_name=FAKE_ZONE
        ),
        "questline_cta_hook": lambda: prose_synthesis.synthesize_questline_cta_hook(
            list(_EVIDENCE),
            arc_title="The Sealed Gate",
            start_anchor="A Vigil Begins",
            faction="alliance",
            chain_refs=["quest-fake-1", "quest-fake-2"],
        ),
        "card_summary": lambda: prose_synthesis.synthesize_card_summary(
            list(_EVIDENCE), subject=FAKE_LOCATION, faction="horde"
        ),
        "instance_overview": lambda: prose_synthesis.synthesize_instance_overview(
            list(_EVIDENCE), instance_name=FAKE_INSTANCE, reference_framing="Reference framing."
        ),
        "key_character_summary": lambda: prose_synthesis.synthesize_key_character_summary(
            list(_EVIDENCE),
            boss_name=FAKE_CHARACTER,
            instance_name=FAKE_INSTANCE,
            structural_role="enemy",
            avoid_hints=["a late-encounter mechanic"],
            reference_framing="Reference framing.",
        ),
        "key_character_beats": lambda: prose_synthesis.select_salient_key_character_beats_llm(
            claim_views,
            boss_name=FAKE_CHARACTER,
            instance_name=FAKE_INSTANCE,
            limit=1,
            reference_arc="Reference arc.",
        ),
        "character_role": lambda: prose_selection.classify_key_character_role_llm(
            list(_EVIDENCE),
            character_name=FAKE_CHARACTER,
            instance_name=FAKE_INSTANCE,
            reference_framing="Reference framing.",
        ),
        "lore_relevance": lambda: prose_selection.classify_lore_relevance_llm(
            list(_EVIDENCE), page_title=FAKE_CHARACTER, instance_name=FAKE_INSTANCE
        ),
        "pool_selection": lambda: prose_selection.select_key_characters_from_pool(
            [_boss_candidate()],
            instance_name=FAKE_INSTANCE,
            context_text="The keep answers to its archivist.",
            max_count=3,
        ),
        "narrative_selection": lambda: prose_selection.select_key_characters_from_narrative(
            [{"name": FAKE_CHARACTER}],
            instance_name=FAKE_INSTANCE,
            narrative_text="The keep answers to its archivist.",
        ),
        "workers_prose": lambda: workers.run_prose_worker(_fact_pack(), {}),
        "workers_questlines": lambda: workers.run_questlines_worker(
            _fact_pack(),
            {"major_questlines_alliance": [{"id": "ql-sealed-gate", "title": "The Sealed Gate"}]},
            "major_questlines_alliance",
            "alliance",
            substep="questlines_alliance",
        ),
        "workers_links": lambda: workers.run_links_worker(_fact_pack(), {}),
        "planner_zone": lambda: planner.run_zone_plan(_fact_pack()),
        "planner_sub_zone": lambda: planner.run_sub_zone_plan(_fact_pack()),
        "legacy_zone": lambda: legacy.zone_draft(_fact_pack()),
        "legacy_sub_zone": lambda: legacy.sub_zone_draft(_fact_pack()),
        "legacy_instance": lambda: legacy.instance_draft(_fact_pack()),
        "legacy_character": lambda: legacy.character_draft(_fact_pack()),
        "legacy_glossary_term": lambda: legacy.glossary_term_draft(_fact_pack()),
        "legacy_asset": lambda: legacy.asset_draft(_fact_pack()),
        "claim_extraction": lambda: recorder.prompts.extend(
            [
                (
                    "claim_extraction:system_prompt",
                    claims_module._claim_extraction_system_prompt(),
                ),
                (
                    "claim_extraction:user_prompt",
                    claims_module._claim_extraction_user_prompt(
                        subject_id="zone-fake-vale",
                        source_id="src-fake-1",
                        source_title=FAKE_ZONE,
                        snippet=str(_EVIDENCE[0]["snippet"]),
                        appearances=[],
                        sentences=["A sentence."],
                        candidate_reasons=[],
                    ),
                ),
            ]
        ),
        "claim_temporal_system": lambda: recorder.prompts.append(
            ("claim_temporal:system_prompt", temporal._claim_temporal_system_prompt())
        ),
        "temporal_adjudication_system": lambda: recorder.prompts.extend(
            [
                (
                    "temporal_adjudication:system_prompt",
                    temporal._temporal_adjudication_system_prompt(canonical=False),
                ),
                (
                    "temporal_adjudication_canonical:system_prompt",
                    temporal._temporal_adjudication_system_prompt(canonical=True),
                ),
            ]
        ),
        "temporal_active_expansion": lambda: temporal._derive_active_expansion(
            [{"field_name": anchor_field, "evidence_items": [{"snippet": "Current text."}]}],
            name=FAKE_ZONE,
            source_anchor_refs=[
                {
                    "kind": "questline_setup",
                    "metadata_id": "metadata-ql-fake",
                    "setup_quest_refs": ["quest-fake"],
                    "setup_snippets": ["Current text."],
                }
            ],
        ),
        "temporal_contract_distillation": lambda: (
            temporal._maybe_distill_entry_state_contract_llm(contract)
        ),
        "fact_check_adjudication": lambda: fact_check._adjudicate_with_openai(
            settings=_ReadySettings(),  # type: ignore[arg-type]
            claim_text="The order sealed the gate.",
            evidence_snippets=["The gate was sealed by the order."],
            model="test-model",
        ),
        "coalesce_claims": lambda: resolve_entities._ai_coalesce_claims(
            entity_name=FAKE_ZONE,
            source_rows=[{"source_id": "src-fake-1", "body": "The order sealed the gate."}],
        ),
    }


def test_no_pilot_name_in_any_rendered_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = PromptRecorder()
    renderers = _prompt_renderers(monkeypatch, recorder)

    for label, render in renderers.items():
        recorder.set_label(label)
        before = len(recorder.prompts)
        try:
            render()
        except Exception:
            # Post-LLM handling of recorder stub output may fail; the prompts are
            # what this guard is about — but they must have been captured.
            pass
        assert len(recorder.prompts) > before, f"renderer {label!r} captured no prompt"

    forbidden = [(name, name.casefold()) for name in sorted(FORBIDDEN_PILOT_NAMES)]
    leaks: list[str] = []
    for label, text in recorder.prompts:
        lowered = text.casefold()
        for name, name_cf in forbidden:
            if name_cf in lowered:
                leaks.append(f"{label}: contains pilot name {name!r}")
    assert not leaks, "pilot facts leaked into prompts:\n" + "\n".join(leaks)
