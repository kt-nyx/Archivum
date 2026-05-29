"""Responses API opt-in for draft LLM calls."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from pipeline.generate.draft.llm import draft_chat_json_completion
from tests.draft_llm_mocks import zone_draft_plan


def test_draft_uses_responses_client_when_flag_set(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SimpleNamespace(
        openai_ready=True,
        openai_model="gpt-5.5",
        openai_reasoning_effort=None,
        openai_verbosity=None,
        openai_draft_reasoning_effort="low",
        openai_draft_verbosity="low",
        openai_use_responses_api=True,
        openai_request_timeout_seconds=600,
    )
    calls: list[str] = []

    def fake_responses(*_args: object, **kwargs: object) -> dict[str, object]:
        calls.append(str(kwargs.get("response_schema_name", "")))
        return zone_draft_plan()

    monkeypatch.setattr(
        "pipeline.ai.responses_client.responses_json_completion",
        fake_responses,
    )
    monkeypatch.setenv("OPENAI_USE_RESPONSES_API", "1")

    result = draft_chat_json_completion(
        settings,
        system_prompt="plan",
        user_prompt="entity",
        response_json_schema={"type": "object"},
        response_schema_name="zone_draft_plan",
    )
    assert result is not None
    assert calls == ["zone_draft_plan"]
