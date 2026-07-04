from __future__ import annotations

from typing import Any

from pipeline.generate.draft.prose_synthesis import (
    SYNTHESIS_MAX_ATTEMPTS,
    synthesize_with_validation,
)

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


def test_driver_passes_clean_first_attempt_without_retry() -> None:
    calls: list[str] = []

    def call(reinforce: str) -> dict[str, Any]:
        calls.append(reinforce)
        return _result(PARAPHRASE)

    out = synthesize_with_validation(
        call=call,
        extract_bodies=_bodies,
        source_snippets=[SOURCE],
    )
    assert out.ok
    assert _bodies(out.payload) == [PARAPHRASE]
    assert out.attempts == 1
    assert calls == [""]  # clean first attempt: one call, no reinforcement


def test_driver_reprompts_on_copy_and_accepts_clean_retry() -> None:
    calls: list[str] = []
    attempts = iter([_result(SOURCE), _result(PARAPHRASE)])

    def call(reinforce: str) -> dict[str, Any]:
        calls.append(reinforce)
        return next(attempts)

    out = synthesize_with_validation(
        call=call,
        extract_bodies=_bodies,
        source_snippets=[SOURCE],
    )
    assert out.ok
    assert _bodies(out.payload) == [PARAPHRASE]
    assert out.attempts == 2
    assert "your own words" in calls[1].lower()  # retry carried the paraphrase feedback


def test_driver_fails_explicitly_when_all_attempts_copy() -> None:
    # RC1 contract: when every attempt copies source prose, the driver returns an explicit
    # failure — it never accepts the borrow. The caller maps this to null + field_status.
    calls: list[str] = []

    def call(reinforce: str) -> dict[str, Any]:
        calls.append(reinforce)
        return _result(SOURCE)

    out = synthesize_with_validation(
        call=call,
        extract_bodies=_bodies,
        source_snippets=[SOURCE],
    )
    assert not out.ok
    assert out.attempts == SYNTHESIS_MAX_ATTEMPTS
    assert len(calls) == SYNTHESIS_MAX_ATTEMPTS
    assert any("verbatim" in reason for reason in out.reasons)
    # The best attempt is still exposed for diagnostics, but ok=False means "do not ship".
    assert _bodies(out.payload) == [SOURCE]


def test_driver_fails_explicitly_on_persistently_empty_output() -> None:
    out = synthesize_with_validation(
        call=lambda reinforce: _result(""),
        extract_bodies=_bodies,
        source_snippets=[SOURCE],
    )
    assert not out.ok
    assert any("empty" in reason for reason in out.reasons)


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


def test_driver_reprompts_on_lint_and_accepts_corrected_retry() -> None:
    # A present-tense first attempt fails the validator (not the copy gate); the retry returns a
    # clean past-tense section and passes. The feedback echoes the concrete lint reason.
    calls: list[str] = []
    attempts = iter(
        [
            {"sections": [PRESENT_SECTION], "used_evidence_ids": []},
            {"sections": [PAST_SECTION], "used_evidence_ids": []},
        ]
    )

    def call(reinforce: str) -> dict[str, Any]:
        calls.append(reinforce)
        return next(attempts)

    out = synthesize_with_validation(
        call=call,
        extract_bodies=_bodies,
        validate=_history_lint,
        source_snippets=[SOURCE],  # not copied, so only lint drives the retry
    )
    assert out.ok
    assert out.payload["sections"] == [PAST_SECTION]
    assert out.attempts == 2
    assert "past tense" in calls[1].lower()


def test_driver_fails_and_keeps_best_attempt_when_lint_never_passes() -> None:
    calls: list[str] = []

    def call(reinforce: str) -> dict[str, Any]:
        calls.append(reinforce)
        return {"sections": [PRESENT_SECTION], "used_evidence_ids": []}

    out = synthesize_with_validation(
        call=call,
        extract_bodies=_bodies,
        validate=_history_lint,
        source_snippets=[SOURCE],
    )
    assert not out.ok
    assert len(calls) == SYNTHESIS_MAX_ATTEMPTS
    assert out.payload["sections"] == [PRESENT_SECTION]  # best attempt kept for diagnostics
    assert out.reasons  # concrete lint reasons surfaced


def test_driver_skips_copy_check_without_source_snippets() -> None:
    # Offline (or corpus-less) callers pass no snippets: a verbatim body is then only judged by
    # the validator, so a clean-linting borrow passes in one attempt.
    calls: list[str] = []

    def call(reinforce: str) -> dict[str, Any]:
        calls.append(reinforce)
        return _result(SOURCE)

    out = synthesize_with_validation(
        call=call,
        extract_bodies=_bodies,
        source_snippets=None,
    )
    assert out.ok
    assert _bodies(out.payload) == [SOURCE]
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
