from __future__ import annotations

from pipeline.generate.draft import prose_synthesis as ps


class _Settings:
    openai_ready = True


def _view(text: str, section_role: str) -> dict:
    return {
        "snippet": text,
        "claim_text": text,
        "raw_section_role": section_role,
        "section_role": section_role,
        "is_claim_view": True,
    }


def _views(count: int) -> list[dict]:
    return [_view(f"beat{i}", "cataclysm_edit") for i in range(count)]


def test_beat_ranker_noop_when_within_limit() -> None:
    # Nothing to rank when the pool already fits the budget: caller keeps deterministic order.
    assert (
        ps.select_salient_key_character_beats_llm(
            _views(3), boss_name="X", instance_name="Y", limit=14
        )
        is None
    )


def test_beat_ranker_noop_without_claim_views() -> None:
    paragraph_pool = [{"snippet": f"p{i}", "claim_text": f"p{i}"} for i in range(20)]
    assert (
        ps.select_salient_key_character_beats_llm(
            paragraph_pool, boss_name="X", instance_name="Y", limit=14
        )
        is None
    )


def test_beat_ranker_selects_requested_ids(monkeypatch) -> None:
    monkeypatch.setattr(ps, "load_ai_settings", lambda: _Settings())
    monkeypatch.setattr(ps, "_wiki_first_no_llm", lambda: False)
    monkeypatch.setattr(ps, "llm_json_with_retry", lambda **_kwargs: {"keep_ids": [2, 5, 7]})

    out = ps.select_salient_key_character_beats_llm(
        _views(20), boss_name="X", instance_name="Y", limit=14
    )
    assert out is not None
    assert [row["claim_text"] for row in out] == ["beat2", "beat5", "beat7"]


def test_beat_ranker_falls_back_when_llm_returns_nothing(monkeypatch) -> None:
    monkeypatch.setattr(ps, "load_ai_settings", lambda: _Settings())
    monkeypatch.setattr(ps, "_wiki_first_no_llm", lambda: False)
    monkeypatch.setattr(ps, "llm_json_with_retry", lambda **_kwargs: {"keep_ids": []})

    assert (
        ps.select_salient_key_character_beats_llm(
            _views(20), boss_name="X", instance_name="Y", limit=14
        )
        is None
    )


def test_beat_ranker_ignores_out_of_range_ids_and_caps(monkeypatch) -> None:
    monkeypatch.setattr(ps, "load_ai_settings", lambda: _Settings())
    monkeypatch.setattr(ps, "_wiki_first_no_llm", lambda: False)
    # 999 is out of range and must be ignored; the result is capped to the limit.
    monkeypatch.setattr(
        ps, "llm_json_with_retry", lambda **_kwargs: {"keep_ids": [999, 0, 1, 2, 3]}
    )

    out = ps.select_salient_key_character_beats_llm(
        _views(20), boss_name="X", instance_name="Y", limit=3
    )
    assert out is not None
    assert [row["claim_text"] for row in out] == ["beat0", "beat1", "beat2"]
