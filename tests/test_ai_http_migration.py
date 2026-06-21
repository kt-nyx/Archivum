"""Behavior tests for the AI clients after the httpx transport migration (WS-D.http)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from pipeline.ai import openai_client, responses_client


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        openai_ready=True,
        openai_model="gpt-test",
        openai_base_url="https://api.test/v1",
        openai_api_key="sk-test",
        openai_temperature=None,
        openai_reasoning_effort=None,
        openai_verbosity=None,
        openai_request_timeout_seconds=30,
    )


def _req() -> httpx.Request:
    return httpx.Request("POST", "https://api.test/v1/chat/completions")


def test_chat_completion_success(monkeypatch: pytest.MonkeyPatch) -> None:
    content = json.dumps({"result": "ok"})
    resp = httpx.Response(
        200, json={"choices": [{"message": {"content": content}}]}, request=_req()
    )
    monkeypatch.setattr("pipeline.common.http.send", lambda *a, **k: resp)
    out = openai_client.chat_json_completion(_settings(), system_prompt="s", user_prompt="u")
    assert out == {"result": "ok"}


def test_chat_completion_http_status_error_message(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = httpx.Response(500, text="server boom", request=_req())
    err = httpx.HTTPStatusError("500", request=_req(), response=resp)

    def boom(*_a, **_k):
        raise err

    monkeypatch.setattr("pipeline.common.http.send", boom)
    with pytest.raises(RuntimeError, match="OpenAI chat completion failed: HTTP 500"):
        openai_client.chat_json_completion(_settings(), system_prompt="s", user_prompt="u")


def test_chat_completion_timeout_message(monkeypatch: pytest.MonkeyPatch) -> None:
    def slow(*_a, **_k):
        raise httpx.TimeoutException("slow")

    monkeypatch.setattr("pipeline.common.http.send", slow)
    with pytest.raises(RuntimeError, match="timed out"):
        openai_client.chat_json_completion(_settings(), system_prompt="s", user_prompt="u")


def test_responses_falls_back_to_chat_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a, **_k):
        raise httpx.ConnectError("down", request=_req())

    monkeypatch.setattr("pipeline.common.http.send", boom)
    monkeypatch.setattr(
        "pipeline.ai.responses_client.chat_json_completion",
        lambda *a, **k: {"fallback": True},
    )
    out = responses_client.responses_json_completion(
        _settings(),
        instructions="i",
        user_input="u",
        response_json_schema={"type": "object"},
        response_schema_name="x",
    )
    assert out == {"fallback": True}
