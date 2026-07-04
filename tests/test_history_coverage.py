from __future__ import annotations

from typing import Any

from pipeline.generate.draft.coverage import (
    build_section_coverage_decisions,
    covered_coverage_ids,
    missing_required_units,
    plan_history_coverage,
)
from pipeline.generate.draft.pages import cards
from pipeline.generate.draft.temporal import (
    ENTRY_STATE,
    HISTORY_BACKGROUND,
    HISTORY_SETUP_BRIDGE,
    PRE_ENTRY_HISTORY,
)


def _claim_view(
    *,
    source_id: str,
    claim_id: str,
    claim_text: str,
    block_index: int,
    history_eligibility: str,
    temporal_scope: str = PRE_ENTRY_HISTORY,
    section_role: str = "history",
    raw_section_role: str = "history",
) -> dict[str, Any]:
    return {
        "snippet": claim_text,
        "claim_text": claim_text,
        "source_excerpt": claim_text,
        "source_id": source_id,
        "field_name": "history_digest",
        "section_role": section_role,
        "raw_section_role": raw_section_role,
        "block_index": block_index,
        "canonical_evidence_id": f"canonical-{claim_id}",
        "claim_id": claim_id,
        "temporal_scope": temporal_scope,
        "history_eligibility": history_eligibility,
        "spoiler_safety": "safe_background",
        "is_claim_view": True,
    }


def _section(heading: str, body: str) -> dict[str, Any]:
    return {"heading": heading, "body": body, "source_refs": []}


# Three full-budget past-tense sections so the offline finalize keeps them as-is (no absorb/lint).
_LLM_SECTIONS = [
    _section(
        "Scourging",
        "The Scourge razed Andorhal and slaughtered its people as the plague consumed the "
        "surrounding farmlands. Arthas marched his undead legions through the heartland, and the "
        "defenders who remained were overwhelmed within days as the once-fertile valley darkened.",
    ),
    _section(
        "Cauldron Campaign",
        "The Argent Dawn established cauldrons across the blighted fields and waged a long campaign "
        "against the plague. Their agents struck at the necromancers who tended the cauldrons, and "
        "for years they held the line while the Scourge pressed in from every ruined village.",
    ),
    _section(
        "Cenarion Healing",
        "The Cenarion Circle arrived to cleanse the poisoned soil and coax life back into the dead "
        "land. They tended the ruined groves over many seasons, and slowly the blight receded as "
        "green returned to the fields the Scourge had long ago burned and salted.",
    ),
]

_BRIDGE_BODY = (
    "After the Lich King fell, the Argent Crusade fortified Hearthglen and made it their northern "
    "bastion, gathering refugees and veterans alike. They rebuilt its walls, garrisoned the keep, "
    "and from there pressed the long work of reclaiming the plaguelands that surrounded the town."
)


def _wpl_coverage_pool() -> list[dict[str, Any]]:
    return [
        _claim_view(
            source_id="src-scourging",
            claim_id="claim-scourging",
            claim_text="The Scourge razed Andorhal during the third war.",
            block_index=1,
            history_eligibility=HISTORY_BACKGROUND,
        ),
        _claim_view(
            source_id="src-cauldron",
            claim_id="claim-cauldron",
            claim_text="The Argent Dawn established cauldrons across the plaguelands.",
            block_index=2,
            history_eligibility=HISTORY_BACKGROUND,
        ),
        _claim_view(
            source_id="src-cenarion",
            claim_id="claim-cenarion",
            claim_text="The Cenarion Circle began healing the poisoned fields.",
            block_index=3,
            history_eligibility=HISTORY_BACKGROUND,
        ),
        _claim_view(
            source_id="src-gahrron",
            claim_id="claim-gahrron",
            claim_text="Gahrron's Withering remained a contested plague cauldron.",
            block_index=4,
            history_eligibility=HISTORY_BACKGROUND,
        ),
        _claim_view(
            source_id="src-hearthglen",
            claim_id="claim-hearthglen",
            claim_text=_BRIDGE_BODY,
            block_index=5,
            history_eligibility=HISTORY_SETUP_BRIDGE,
            temporal_scope=ENTRY_STATE,
        ),
    ]


def test_plan_history_coverage_marks_setup_bridge_required() -> None:
    units = plan_history_coverage(_wpl_coverage_pool())

    assert len(units) == 5
    # Source order preserved by block_index.
    assert [unit["source_id"] for unit in units] == [
        "src-scourging",
        "src-cauldron",
        "src-cenarion",
        "src-gahrron",
        "src-hearthglen",
    ]
    bridge = units[-1]
    assert bridge["required"] is True
    assert bridge["temporal_bucket"] == "setup_bridge"
    assert bridge["claim_ids"] == ["claim-hearthglen"]
    # Background-only units are never required.
    assert all(unit["required"] is False for unit in units[:-1])


def test_plan_history_coverage_ignores_paragraph_only_pool() -> None:
    paragraph_pool = [{"snippet": "A paragraph-only history item.", "source_id": "src-x"}]
    assert plan_history_coverage(paragraph_pool) == []


def test_covered_and_missing_required_units() -> None:
    units = plan_history_coverage(_wpl_coverage_pool())
    covered = covered_coverage_ids(units, ["src-scourging", "src-cauldron", "src-cenarion"])

    missing = missing_required_units(units, covered)
    assert [unit["source_id"] for unit in missing] == ["src-hearthglen"]


def test_finalize_appends_missing_setup_bridge(monkeypatch) -> None:
    """When synthesis drops the eligible setup bridge, finalize appends it deterministically."""
    monkeypatch.setattr(
        cards,
        "synthesize_history_sections",
        lambda pool, **kw: (
            list(_LLM_SECTIONS),
            ["src-scourging", "src-cauldron", "src-cenarion"],
        ),
    )

    sink: list[dict[str, Any]] = []
    sections, used, _status = cards._finalize_history_sections(
        history_pool=[{"snippet": "x", "source_id": "src-scourging"}],
        evidence_rows=[],
        max_history=3,
        coverage_pool=_wpl_coverage_pool(),
        subject_id="zone-western-plaguelands",
        coverage_sink=sink,
    )

    history_text = " ".join(str(section.get("body", "")) for section in sections)
    assert "Argent Crusade fortified Hearthglen" in history_text
    assert "src-hearthglen" in used

    assert len(sink) == 1
    decision = sink[0]
    assert decision["subject_id"] == "zone-western-plaguelands"
    assert decision["required_unit_count"] == 1
    assert decision["required_covered_count"] == 1
    assert decision["deterministic_bridge_count"] == 1
    bridge_row = next(
        row for row in decision["coverage_units"] if row["source_id"] == "src-hearthglen"
    )
    assert bridge_row["deterministic_bridge_appended"] is True
    assert bridge_row["covered"] is True


def test_finalize_bridge_card_carries_explicit_provenance(monkeypatch) -> None:
    """The appended bridge card gets its own source pointer, not a positional mis-credit."""
    monkeypatch.setattr(
        cards,
        "synthesize_history_sections",
        lambda pool, **kw: (
            list(_LLM_SECTIONS),
            ["src-scourging", "src-cauldron", "src-cenarion"],
        ),
    )

    def _pointer_builder(item: dict[str, Any], ordinal: int) -> dict[str, str]:
        return {"source_id": str(item.get("source_id", "")), "locator": f"mw:{ordinal}"}

    sections, _used, _status = cards._finalize_history_sections(
        history_pool=[{"snippet": "x", "source_id": "src-scourging"}],
        evidence_rows=[],
        max_history=3,
        coverage_pool=_wpl_coverage_pool(),
        subject_id="zone-western-plaguelands",
        coverage_sink=[],
        coverage_pointer_builder=_pointer_builder,
    )

    bridge = next(
        section
        for section in sections
        if "Argent Crusade fortified Hearthglen" in str(section.get("body", ""))
    )
    refs = bridge["source_refs"]
    assert refs and refs[0]["source_id"] == "src-hearthglen"


def test_finalize_llm_retry_covers_bridge_without_deterministic_append(monkeypatch) -> None:
    """In a live run, a coverage retry that represents the bridge avoids the deterministic card."""
    # Force the live-run signal so the retry branch is reachable offline.
    monkeypatch.setattr(cards, "passthrough_corpus", lambda pool: ["corpus-sentinel"])

    calls: dict[str, int] = {"n": 0}

    def _synth(pool, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            # First pass drops the setup bridge (only the first three sources used).
            return list(_LLM_SECTIONS), ["src-scourging", "src-cauldron", "src-cenarion"]
        # Retry must have received the required-event hint and now covers the bridge source.
        assert kw.get("required_event_texts")
        return list(_LLM_SECTIONS), ["src-scourging", "src-hearthglen", "src-cenarion"]

    monkeypatch.setattr(cards, "synthesize_history_sections", _synth)

    sink: list[dict[str, Any]] = []
    sections, used, _status = cards._finalize_history_sections(
        history_pool=[{"snippet": "x", "source_id": "src-scourging"}],
        evidence_rows=[],
        max_history=3,
        coverage_pool=_wpl_coverage_pool(),
        subject_id="zone-western-plaguelands",
        coverage_sink=sink,
    )

    assert calls["n"] == 2  # retry happened
    assert len(sections) == 3  # no deterministic bridge appended
    assert "src-hearthglen" in used
    assert sink[0]["deterministic_bridge_count"] == 0
    bridge_row = next(
        row for row in sink[0]["coverage_units"] if row["source_id"] == "src-hearthglen"
    )
    assert bridge_row["covered"] is True
    assert bridge_row["deterministic_bridge_appended"] is False


def test_finalize_no_append_when_setup_bridge_already_covered(monkeypatch) -> None:
    """An eligible setup bridge that synthesis already used needs no deterministic bridge card."""
    monkeypatch.setattr(
        cards,
        "synthesize_history_sections",
        lambda pool, **kw: (
            list(_LLM_SECTIONS),
            ["src-scourging", "src-cauldron", "src-hearthglen"],
        ),
    )

    sink: list[dict[str, Any]] = []
    sections, used, _status = cards._finalize_history_sections(
        history_pool=[{"snippet": "x", "source_id": "src-scourging"}],
        evidence_rows=[],
        max_history=3,
        coverage_pool=_wpl_coverage_pool(),
        subject_id="zone-western-plaguelands",
        coverage_sink=sink,
    )

    # No deterministic bridge card was appended; the LLM batch stands.
    assert len(sections) == 3
    assert sink[0]["deterministic_bridge_count"] == 0
    bridge_row = next(
        row for row in sink[0]["coverage_units"] if row["source_id"] == "src-hearthglen"
    )
    assert bridge_row["covered"] is True
    assert bridge_row["deterministic_bridge_appended"] is False


def test_finalize_paragraph_pool_records_no_coverage(monkeypatch) -> None:
    """A paragraph-only pool yields no coverage units and never touches the sink (legacy path)."""
    monkeypatch.setattr(
        cards,
        "synthesize_history_sections",
        lambda pool, **kw: (list(_LLM_SECTIONS), ["used"]),
    )

    sink: list[dict[str, Any]] = []
    cards._finalize_history_sections(
        history_pool=[{"snippet": "x", "source_id": "src-x"}],
        evidence_rows=[],
        max_history=3,
        coverage_pool=[{"snippet": "paragraph only", "source_id": "src-x"}],
        subject_id="zone-x",
        coverage_sink=sink,
    )

    assert sink == []


def test_append_setup_bridge_folds_into_last_section_at_ceiling() -> None:
    """At the hard section ceiling the bridge merges into the last section, keeping its pointer."""
    from pipeline.generate.draft.prose_lint import MAX_HISTORY_SECTIONS

    filler = (
        "The defenders held the line for many long years while the plague pressed in from every "
        "ruined village, and the survivors rebuilt what little they could before the next assault "
        "fell upon the weary and battered settlements that still remained standing in the valley."
    )
    full = [_section(f"Era {i}", filler) for i in range(MAX_HISTORY_SECTIONS)]
    units = plan_history_coverage(_wpl_coverage_pool())
    missing = [unit for unit in units if unit["source_id"] == "src-hearthglen"]

    def _pointer_builder(item: dict[str, Any], ordinal: int) -> dict[str, str]:
        return {"source_id": str(item.get("source_id", "")), "locator": f"mw:{ordinal}"}

    sections, used, appended = cards._append_setup_bridge_cards(
        full, ["e"] * MAX_HISTORY_SECTIONS, missing, pointer_builder=_pointer_builder
    )

    assert len(sections) == MAX_HISTORY_SECTIONS  # ceiling not exceeded
    assert "src-hearthglen" in used
    assert appended == {missing[0]["coverage_id"]}
    last_refs = sections[-1]["source_refs"]
    assert any(ref.get("source_id") == "src-hearthglen" for ref in last_refs)


def test_build_section_coverage_decisions_shape() -> None:
    units = plan_history_coverage(_wpl_coverage_pool())
    covered = covered_coverage_ids(units, ["src-scourging"])
    rows = build_section_coverage_decisions("zone-x", units, covered, {"coverage-05"})

    assert len(rows) == 1
    row = rows[0]
    assert row["coverage_unit_count"] == 5
    assert row["required_unit_count"] == 1
    assert row["deterministic_bridge_count"] == 1
    assert build_section_coverage_decisions("zone-x", [], set(), set()) == []
