from __future__ import annotations

from typing import Any

from pipeline.generate.draft.pages import cards


def _section(heading: str, body: str) -> dict[str, Any]:
    return {"heading": heading, "body": body, "source_refs": []}


# Bodies are kept in the validate word budget (40..110) so the pre-lint budget pass does not absorb
# them — mirroring full-length LLM sections — leaving three distinct clean sections to salvage.
_CLEAN = [
    _section(
        "Scourging",
        "The Scourge razed Andorhal and slaughtered its people as the plague consumed the surrounding "
        "farmlands. Arthas marched his undead legions through the heartland, and the defenders who "
        "remained were overwhelmed within days as crops withered and the once-fertile valley darkened.",
    ),
    _section(
        "Aftermath",
        "Survivors fled west toward Hearthglen while the Alliance abandoned the eastern villages to the "
        "undead. Whole families perished on the roads, and the settlements that endured were besieged "
        "for years as the blight spread and the living retreated behind hastily raised walls.",
    ),
    _section(
        "Reclamation",
        "The Argent forces marched east and cleansed the blighted soil over many long seasons. They "
        "rebuilt the ruined chapels, buried the fallen, and reclaimed the farmsteads one by one, until "
        "the worst of the plague had receded and travelers ventured the old roads once again.",
    ),
]
_BAD_PRESENT = _section(
    "Now",
    "The academy stands today and the Scourge controls its halls while necromancers raise the dead. "
    "Acolytes study dark arts in the lower vaults, the dead serve their masters, and patrols guard "
    "every corridor as the order maintains its grip and recruits new students from the surrounding land.",
)


def test_history_finalize_salvages_clean_llm_sections(monkeypatch) -> None:
    """A single failing section must not discard the whole clean LLM batch.

    The LLM returns three clean past-tense sections plus one present-dominant section that trips lint.
    Salvage keeps the three clean ones (>= MIN_HISTORY_SECTIONS) and never falls to the deterministic
    fallback — which we monkeypatch to a sentinel that proves it was not used.
    """
    monkeypatch.setattr(
        cards, "synthesize_history_sections", lambda pool, **kw: (_CLEAN + [_BAD_PRESENT], ["used"])
    )

    def _sentinel_fallback(pool, **kw):  # pragma: no cover - asserted not called
        raise AssertionError("deterministic fallback should not run when salvage succeeds")

    monkeypatch.setattr(cards, "fallback_history_sections", _sentinel_fallback)

    sections, _used = cards._finalize_history_sections(
        history_pool=[{"text": "x"}], evidence_rows=[], max_history=4
    )

    headings = [s["heading"] for s in sections]
    assert "Now" not in headings
    assert len(sections) == 3


def test_history_finalize_falls_through_when_too_few_clean(monkeypatch) -> None:
    """Below MIN_HISTORY_SECTIONS clean sections, salvage declines and the fallback path runs."""
    monkeypatch.setattr(
        cards,
        "synthesize_history_sections",
        lambda pool, **kw: (_CLEAN[:1] + [_BAD_PRESENT, _BAD_PRESENT], ["used"]),
    )
    called: dict[str, bool] = {}

    def _fallback(pool, **kw):
        called["yes"] = True
        return _CLEAN, ["used"]

    monkeypatch.setattr(cards, "fallback_history_sections", _fallback)

    sections, _used = cards._finalize_history_sections(
        history_pool=[{"text": "x"}], evidence_rows=[], max_history=4
    )
    assert called.get("yes") is True
    assert len(sections) == 3
