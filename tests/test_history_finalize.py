from __future__ import annotations

from typing import Any

from pipeline.generate.draft.pages import cards
from pipeline.generate.draft.prose_lint import word_count


def _section(heading: str, body: str) -> dict[str, Any]:
    return {"heading": heading, "body": body, "source_refs": []}


# Minimal contract-conforming pool item: paragraph identity is required (Slice 7).
_POOL_ITEM = {
    "snippet": "x",
    "source_id": "src-zone",
    "canonical_evidence_id": "canonical-x",
}


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
# Present-dominant sections that trip lint. They are placed mid-history (never the final slot), since
# the final section of a multi-section history is the legitimate present-state bridge and is exempt
# from the present-tense check — only a non-final present section is a lint failure to salvage.
_BAD_PRESENT = _section(
    "Now",
    "The academy stands today and the Scourge controls its halls while necromancers raise the dead. "
    "Acolytes study dark arts in the lower vaults, the dead serve their masters, and patrols guard "
    "every corridor as the order maintains its grip and recruits new students from the surrounding land.",
)
_BAD_PRESENT_2 = _section(
    "Today",
    "The order holds the keep and its agents roam the countryside while cultists gather in the crypts. "
    "Wardens patrol the walls, the faithful tend the shrines, and the masters direct their servants as "
    "the school endures and draws fresh recruits from the villages that still stand nearby.",
)


def test_history_finalize_salvages_clean_llm_sections(monkeypatch) -> None:
    """A single failing section must not discard the whole clean LLM batch.

    The LLM returns three clean past-tense sections plus one present-dominant section (placed
    mid-history, not final) that trips lint. Salvage keeps the three clean ones (>=
    MIN_HISTORY_SECTIONS) and never falls to the deterministic fallback — which we monkeypatch to a
    sentinel that proves it was not used.
    """
    monkeypatch.setattr(
        cards,
        "synthesize_history_sections",
        lambda pool, **kw: ([_CLEAN[0], _BAD_PRESENT, _CLEAN[1], _CLEAN[2]], ["used"]),
    )

    def _sentinel_fallback(pool, **kw):  # pragma: no cover - asserted not called
        raise AssertionError("deterministic fallback should not run when salvage succeeds")

    monkeypatch.setattr(cards, "fallback_history_sections", _sentinel_fallback)

    sections, _used, _status = cards._finalize_history_sections(
        history_pool=[_POOL_ITEM], evidence_rows=[], max_history=4
    )

    headings = [s["heading"] for s in sections]
    assert "Now" not in headings
    assert len(sections) == 3


def test_history_finalize_falls_through_when_too_few_clean(monkeypatch) -> None:
    """Below MIN_HISTORY_SECTIONS clean sections, salvage declines and the fallback path runs."""
    monkeypatch.setattr(
        cards,
        "synthesize_history_sections",
        lambda pool, **kw: ([_BAD_PRESENT, _BAD_PRESENT_2, _CLEAN[0]], ["used"]),
    )
    called: dict[str, bool] = {}

    def _fallback(pool, **kw):
        called["yes"] = True
        return _CLEAN, ["used"]

    monkeypatch.setattr(cards, "fallback_history_sections", _fallback)

    sections, _used, _status = cards._finalize_history_sections(
        history_pool=[_POOL_ITEM], evidence_rows=[], max_history=4
    )
    assert called.get("yes") is True
    assert len(sections) == 3


# A lint-clean past-tense section near the top of the word budget (96..110 words), so a
# trailing sub-floor section cannot be absorbed into it without breaking the cap.
_NEAR_CAP = _section(
    "Collapse",
    "The Scourge razed the farmsteads across the western valley and the defenders who stood "
    "against the tide were overwhelmed before the harvest could be gathered. Survivors abandoned "
    "the ruined villages and carried what little remained toward the western hills while the "
    "blight crept outward and consumed the fields behind them. The plagued soil hardened through "
    "the long winters and the roads that once carried grain wagons fell silent as the last of the "
    "caravans turned away. The old chapels crumbled into the mire and their bells were carried "
    "off by looters who braved the dead for whatever silver endured.",
)
# Lint-clean but far below the per-section word floor.
_SUB_FLOOR_BODY = "The village was razed and its people were scattered across the plagued farmland."


def test_history_finalize_retries_on_out_of_budget_section(monkeypatch) -> None:
    """An out-of-budget section the trim/absorb pass cannot repair is a retry reason (Slice 2).

    Attempt 1 ends with a sub-floor section whose neighbor is too full to absorb it; the
    driver must re-prompt with the actionable budget reason, and attempt 2's clean batch ships.
    """
    assert 96 <= word_count(_NEAR_CAP["body"]) <= cards._HISTORY_SECTION_MAX_WORDS
    assert word_count(_SUB_FLOOR_BODY) < cards._HISTORY_SECTION_MIN_WORDS

    monkeypatch.setattr(cards, "llm_synthesis_active", lambda: True)
    calls: list[str] = []

    def _synth(pool, **kw):
        calls.append(str(kw.get("reinforce", "")))
        if len(calls) == 1:
            return [_CLEAN[0], _NEAR_CAP, _section("Coda", _SUB_FLOOR_BODY)], ["canonical-x"]
        return _CLEAN, ["canonical-x"]

    monkeypatch.setattr(cards, "synthesize_history_sections", _synth)

    sections, _used, status = cards._finalize_history_sections(
        history_pool=[_POOL_ITEM], evidence_rows=[], max_history=4
    )

    assert len(calls) == 2
    assert "13 words" in calls[1]
    assert "40-110 words" in calls[1]
    assert status == "ok"
    assert [s["heading"] for s in sections] == ["Scourging", "Aftermath", "Reclamation"]


def test_apply_history_section_budget_absorbs_below_min_sections() -> None:
    """A sub-floor section is absorbed even when that drops the count below MIN_HISTORY_SECTIONS.

    Validate's own floor is one section; shipping a budget-violating section is the worse
    outcome (Slice 2). The old pass kept the violating section once the count reached the
    minimum, shipping a guaranteed ``budget.history_section`` hard-fail.
    """
    sections = [_CLEAN[0], _section("Coda", _SUB_FLOOR_BODY)]
    result = cards._apply_history_section_budget(sections)
    assert len(result) == 1
    assert _SUB_FLOOR_BODY in result[0]["body"]
    assert not cards._history_budget_reasons(result)


def test_apply_history_section_budget_keeps_unabsorbable_sub_floor_section() -> None:
    """A sub-floor section that cannot merge in-budget is kept (content is never dropped)."""
    sections = [_NEAR_CAP, _section("Coda", _SUB_FLOOR_BODY)]
    result = cards._apply_history_section_budget(sections)
    assert [s["heading"] for s in result] == ["Collapse", "Coda"]
    reasons = cards._history_budget_reasons(result)
    assert len(reasons) == 1
    assert "section 2" in reasons[0]
