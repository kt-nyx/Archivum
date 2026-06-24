from __future__ import annotations

import pipeline.generate.draft.prose_synthesis as synth
from pipeline.generate.draft.prose_synthesis import (
    _heading_is_generic,
    relabel_history_headings,
)


def test_heading_is_generic_flags_era_and_toc_labels() -> None:
    for generic in (
        "History",
        "World of Warcraft",
        "Cataclysm",
        "Legion",
        "Exploring Azeroth",
        "Historical era",
        "",
    ):
        assert _heading_is_generic(generic), generic


def test_heading_is_generic_keeps_thematic_titles() -> None:
    for thematic in (
        "Before the Scourge",
        "Scourging of Lordaeron",
        "Coming of the Argent Dawn",
        "Battle for Andorhal",
    ):
        assert not _heading_is_generic(thematic), thematic


def test_relabel_is_noop_without_openai(monkeypatch) -> None:
    monkeypatch.setattr(
        synth, "load_ai_settings", lambda: type("S", (), {"openai_ready": False})()
    )
    sections = [{"heading": "Cataclysm", "body": "The Cataclysm reshaped the land.", "source_refs": []}]
    out = relabel_history_headings(sections)
    assert out[0]["heading"] == "Cataclysm"


def test_relabel_replaces_generic_keeps_thematic(monkeypatch) -> None:
    monkeypatch.setattr(
        synth, "load_ai_settings", lambda: type("S", (), {"openai_ready": True})()
    )

    def fake_llm(**kwargs: object) -> dict[str, object]:
        # One target (the generic heading at index 1); the thematic one is not sent.
        return {"headings": [{"index": 1, "heading": "Rise of the Dead"}]}

    monkeypatch.setattr(synth, "llm_json_with_retry", fake_llm)
    sections = [
        {"heading": "Scourging of Lordaeron", "body": "Kel'Thuzad spread the plague.", "source_refs": []},
        {"heading": "Cataclysm", "body": "The undead rose anew across the fields.", "source_refs": []},
    ]
    out = relabel_history_headings(sections)
    assert out[0]["heading"] == "Scourging of Lordaeron"  # thematic preserved
    assert out[1]["heading"] == "Rise of the Dead"  # generic relabeled from body
    # Original input not mutated.
    assert sections[1]["heading"] == "Cataclysm"


def test_relabel_rejects_generic_llm_output(monkeypatch) -> None:
    monkeypatch.setattr(
        synth, "load_ai_settings", lambda: type("S", (), {"openai_ready": True})()
    )
    monkeypatch.setattr(
        synth,
        "llm_json_with_retry",
        lambda **kwargs: {"headings": [{"index": 1, "heading": "Legion"}]},
    )
    sections = [{"heading": "World of Warcraft", "body": "Heroes fought the plague.", "source_refs": []}]
    out = relabel_history_headings(sections)
    # LLM returned another era label -> keep the original rather than swap noise for noise.
    assert out[0]["heading"] == "World of Warcraft"
