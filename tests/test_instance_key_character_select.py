from __future__ import annotations

from pipeline.discovery.instance_bosses import BossCandidate
from pipeline.generate.draft import wiki_first_workers as workers


def _candidate(
    name: str,
    *,
    role: str = "denizens",
    snippets: list[str] | None = None,
) -> BossCandidate:
    candidate = BossCandidate(
        boss_id=f"character-{name.lower().replace(' ', '-')}",
        name=name,
        wiki_url=f"https://warcraft.wiki.gg/wiki/{name.replace(' ', '_')}",
        source_section_role=role,
    )
    if snippets is not None:
        candidate.profile_pool = [
            {"snippet": text, "section_role": role, "source_id": "src-instance"}
            for text in snippets
        ]
    return candidate


def test_select_pool_no_llm_uses_deterministic_order(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    pool = [
        _candidate("Loken", role="bosses"),
        _candidate("Thorim", role="denizens"),
    ]
    selected = workers.select_key_characters_from_pool(
        pool,
        instance_name="Ulduar",
        context_text="Thorim Thorim allied with adventurers while Loken fell.",
        max_count=1,
    )
    assert selected == ["Thorim"]


def test_select_pool_llm_allowlist(monkeypatch) -> None:
    monkeypatch.delenv("WOW_LORE_WIKI_FIRST_NO_LLM", raising=False)
    monkeypatch.setattr(workers, "load_ai_settings", lambda: type("S", (), {"openai_ready": True})())
    monkeypatch.setattr(
        workers,
        "llm_json_with_retry",
        lambda **kwargs: {"selected": ["Loken", "Made Up Name", "yogg-saron"]},
    )
    pool = [
        _candidate("Yogg-Saron"),
        _candidate("Loken"),
        _candidate("Thorim"),
    ]
    selected = workers.select_key_characters_from_pool(
        pool,
        instance_name="Ulduar",
        max_count=10,
    )
    assert selected == ["Loken", "Yogg-Saron"]


def test_select_pool_max_count_zero(monkeypatch) -> None:
    monkeypatch.setattr(
        workers,
        "llm_json_with_retry",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("LLM should not run")),
    )
    selected = workers.select_key_characters_from_pool(
        [_candidate("Loken")],
        instance_name="Ulduar",
        max_count=0,
    )
    assert selected == []


def test_select_pool_empty_response_fallback(monkeypatch) -> None:
    monkeypatch.delenv("WOW_LORE_WIKI_FIRST_NO_LLM", raising=False)
    monkeypatch.setattr(workers, "load_ai_settings", lambda: type("S", (), {"openai_ready": True})())
    monkeypatch.setattr(workers, "llm_json_with_retry", lambda **kwargs: {"selected": []})
    pool = [
        _candidate("Marquee Boss", role="bosses"),
        _candidate("Trash Mob", role="denizens"),
    ]
    selected = workers.select_key_characters_from_pool(
        pool,
        instance_name="Test Keep",
        context_text="Marquee Boss Marquee Boss commands the keep.",
        max_count=1,
    )
    assert selected == ["Marquee Boss"]


def test_select_pool_exclude_names(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    pool = [
        _candidate("Floor Boss", role="dungeon_journal"),
        _candidate("Optional Boss", role="bosses"),
    ]
    selected = workers.select_key_characters_from_pool(
        pool,
        instance_name="Test Keep",
        max_count=2,
        exclude_names=["Floor Boss"],
    )
    assert selected == ["Optional Boss"]
    assert "Floor Boss" not in selected


def test_format_prompt_snippet_cap() -> None:
    long_snippet = "x" * 500
    prompt = workers._format_pool_selection_user_prompt(
        [_candidate("Archivist Maelor", snippets=[long_snippet])],
        "",
    )
    assert len(long_snippet) > workers._POOL_SELECTION_SNIPPET_MAX_CHARS
    assert "x" * 201 not in prompt
    assert "x" * 200 in prompt


def test_prompt_has_no_pilot_zone_strings() -> None:
    system = workers._pool_selection_system_prompt(instance_name="Archive Vault", max_count=5)
    user = workers._format_pool_selection_user_prompt(
        [_candidate("Archivist Maelor", snippets=["Guards the stacks."])],
        "A hidden vault beneath the mountains.",
    )
    combined = system + user
    for forbidden in workers._FORBIDDEN_PILOT_PROMPT_STRINGS:
        assert forbidden not in combined


def test_llm_path_uses_pool_selection_substep(monkeypatch) -> None:
    monkeypatch.delenv("WOW_LORE_WIKI_FIRST_NO_LLM", raising=False)
    monkeypatch.setattr(workers, "load_ai_settings", lambda: type("S", (), {"openai_ready": True})())
    captured: dict[str, str] = {}

    def _capture(**kwargs):
        captured["substep"] = str(kwargs.get("substep", ""))
        captured["response_schema_name"] = str(kwargs.get("response_schema_name", ""))
        return {"selected": ["Loken"]}

    monkeypatch.setattr(workers, "llm_json_with_retry", _capture)
    workers.select_key_characters_from_pool(
        [_candidate("Loken")],
        instance_name="Ulduar",
        max_count=1,
    )
    assert captured["substep"] == "wiki_first_key_character_pool_selection"
    assert captured["response_schema_name"] == "wiki_first_key_character_pool_selection"
