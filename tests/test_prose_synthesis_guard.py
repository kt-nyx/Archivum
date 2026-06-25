from __future__ import annotations

from typing import Any

from pipeline.generate.draft.prose_synthesis import enforce_non_passthrough

# A >=25-word source paragraph so a verbatim copy of it clears the anti-passthrough word floor.
SOURCE = (
    "After the Second War the keep at Caer Darrow was restored as the seat of House Barov, "
    "whose holdings stretched through Brill and Southshore until the family bargained with "
    "Kelthuzad to preserve their wealth and dominion well beyond the reach of death itself."
)
PARAPHRASE = (
    "Rebuilt once the fighting ended, the Barov estate again crowned its island lake. Their "
    "reach spanned several northern towns, yet dread of mortality drove them into a pact with a "
    "lich, trading everything they owned for endless unlife."
)


def _result(body: str) -> dict[str, Any]:
    return {"sections": [{"heading": "Era", "body": body}], "used_evidence_ids": []}


def _bodies(payload: dict[str, Any]) -> list[str]:
    return [str(section["body"]) for section in payload["sections"]]


def test_enforce_passes_clean_first_attempt_without_retry() -> None:
    calls: list[str] = []

    def call(reinforce: str) -> dict[str, Any]:
        calls.append(reinforce)
        return _result(PARAPHRASE)

    out = enforce_non_passthrough(
        _result(PARAPHRASE),
        call=call,
        extract_bodies=_bodies,
        source_snippets=[SOURCE],
    )
    assert _bodies(out) == [PARAPHRASE]
    assert calls == []  # clean first attempt never triggers the retry call


def test_enforce_reprompts_once_and_accepts_clean_retry() -> None:
    calls: list[str] = []

    def call(reinforce: str) -> dict[str, Any]:
        calls.append(reinforce)
        return _result(PARAPHRASE)

    out = enforce_non_passthrough(
        _result(SOURCE),  # first attempt is a verbatim copy
        call=call,
        extract_bodies=_bodies,
        source_snippets=[SOURCE],
    )
    assert _bodies(out) == [PARAPHRASE]
    assert len(calls) == 1  # exactly one retry
    assert "your own words" in calls[0].lower()  # carried the paraphrase feedback


def test_enforce_returns_retry_for_finalize_gate_when_still_verbatim() -> None:
    # If the retry still copies, the guard returns an attempt (one retry only) rather than raising —
    # the caller's finalize-level passthrough gate rejects it gracefully instead of crashing the stage.
    calls: list[str] = []

    def call(reinforce: str) -> dict[str, Any]:
        calls.append(reinforce)
        return _result(SOURCE)  # retry still copies

    out = enforce_non_passthrough(
        _result(SOURCE),
        call=call,
        extract_bodies=_bodies,
        source_snippets=[SOURCE],
    )
    assert _bodies(out) == [SOURCE]
    assert len(calls) == 1  # retried exactly once, no infinite loop


def _history_lint(payload: dict[str, Any]) -> list[str]:
    from pipeline.generate.draft.prose_lint import lint_history_sections

    return lint_history_sections(payload["sections"], max_sections=8)


# A clean past-tense section and a present-tense section, both >=25 words and non-verbatim, so only
# the lint dimension differs.
PAST_SECTION = {
    "heading": "Fall",
    "body": (
        "The Scourge razed the keep and slaughtered the household, then the survivors fled south "
        "while the blighted fields were abandoned and the old roads fell silent for many long years."
    ),
}
PRESENT_SECTION = {
    "heading": "Now",
    "body": (
        "The order maintains its grip on the academy and its acolytes study the dark arts, while "
        "patrols guard every corridor and necromancers raise the dead to serve the masters who rule here."
    ),
}


def test_enforce_reprompts_on_lint_and_keeps_corrected_retry() -> None:
    # A present-tense first attempt fails lint (not the passthrough gate); the retry returns a clean
    # past-tense section and is preferred. The feedback echoes the lint reason.
    calls: list[str] = []

    def call(reinforce: str) -> dict[str, Any]:
        calls.append(reinforce)
        return {"sections": [PAST_SECTION], "used_evidence_ids": []}

    out = enforce_non_passthrough(
        {"sections": [PRESENT_SECTION], "used_evidence_ids": []},
        call=call,
        extract_bodies=_bodies,
        source_snippets=[SOURCE],  # not copied, so only lint drives the retry
        lint_reasons=_history_lint,
    )
    assert out["sections"] == [PAST_SECTION]
    assert len(calls) == 1
    assert "past tense" in calls[0].lower()


def test_enforce_keeps_original_when_lint_retry_is_no_better() -> None:
    # If the retry fails lint just as badly, keep the original attempt (tie → original), still one call.
    calls: list[str] = []

    def call(reinforce: str) -> dict[str, Any]:
        calls.append(reinforce)
        return {"sections": [PRESENT_SECTION], "used_evidence_ids": []}

    first = {"sections": [dict(PRESENT_SECTION, heading="First")], "used_evidence_ids": []}
    out = enforce_non_passthrough(
        first,
        call=call,
        extract_bodies=_bodies,
        source_snippets=[SOURCE],
        lint_reasons=_history_lint,
    )
    assert out is first  # tie keeps the original
    assert len(calls) == 1


def test_passthrough_corpus_disabled_offline(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    import pipeline.generate.draft.prose_synthesis as ps

    # Offline there is no LLM to paraphrase, so the finalize gate must stay disabled (None) and let
    # the deterministic fallbacks borrow source prose — else every offline page would gate-fail.
    assert ps.llm_synthesis_active() is False
    assert ps.passthrough_corpus([{"snippet": "alpha beta"}]) is None


def test_passthrough_corpus_active_in_llm_run(monkeypatch) -> None:
    monkeypatch.delenv("WOW_LORE_WIKI_FIRST_NO_LLM", raising=False)
    import pipeline.generate.draft.prose_synthesis as ps

    monkeypatch.setattr(ps, "load_ai_settings", lambda: type("S", (), {"openai_ready": True})())
    assert ps.llm_synthesis_active() is True
    assert ps.passthrough_corpus([{"snippet": "alpha"}, {"snippet": "beta"}]) == ["alpha", "beta"]


def test_sections_trip_gate_rejects_verbatim_only_with_corpus() -> None:
    from pipeline.generate.draft.pages.cards import _sections_trip_gate

    source = (
        "After the Second War the keep at Caer Darrow was restored as the seat of House Barov, "
        "whose holdings stretched through Brill and Southshore until the family bargained with "
        "Kelthuzad to preserve their wealth and dominion well beyond the reach of death itself."
    )
    verbatim = [{"body": source}]
    # With the source corpus the copied body is rejected; without it (offline) the borrow passes.
    assert _sections_trip_gate(verbatim, [source]) is True
    assert _sections_trip_gate(verbatim, None) is False


def test_enforce_noop_without_source_snippets() -> None:
    def call(reinforce: str) -> dict[str, Any]:  # pragma: no cover - must not be called
        raise AssertionError("retry must not run when there are no sources to compare against")

    out = enforce_non_passthrough(
        _result(SOURCE),
        call=call,
        extract_bodies=_bodies,
        source_snippets=[],
    )
    assert _bodies(out) == [SOURCE]
