"""Tests for pipeline.common.http (httpx + tenacity retry helper)."""

from __future__ import annotations

import httpx
import pytest

from pipeline.common import http


def _response(status: int, text: str, url: str = "https://example.test/x") -> httpx.Response:
    return httpx.Response(status, text=text, request=httpx.Request("GET", url))


def test_get_text_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(http.httpx, "get", lambda *a, **k: _response(200, "hello"))
    assert http.get_text("https://example.test/x", timeout=5) == "hello"


def test_get_text_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def fake_get(*_a, **_k):
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectError("boom", request=httpx.Request("GET", "https://example.test/x"))
        return _response(200, "ok")

    monkeypatch.setattr(http.httpx, "get", fake_get)
    assert http.get_text("https://example.test/x", timeout=5, retries=3, backoff_base=0) == "ok"
    assert calls["n"] == 3


def test_get_text_retries_on_5xx_then_reraises(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def fake_get(*_a, **_k):
        calls["n"] += 1
        return _response(503, "unavailable")

    monkeypatch.setattr(http.httpx, "get", fake_get)
    with pytest.raises(httpx.HTTPStatusError):
        http.get_text("https://example.test/x", timeout=5, retries=2, backoff_base=0)
    assert calls["n"] == 3  # initial + 2 retries


def test_get_text_no_retry_reraises_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def fake_get(*_a, **_k):
        calls["n"] += 1
        raise httpx.ConnectError("boom", request=httpx.Request("GET", "https://example.test/x"))

    monkeypatch.setattr(http.httpx, "get", fake_get)
    with pytest.raises(httpx.ConnectError):
        http.get_text("https://example.test/x", timeout=5)
    assert calls["n"] == 1


def test_send_raises_for_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(http.httpx, "request", lambda *a, **k: _response(500, "err"))
    with pytest.raises(httpx.HTTPStatusError):
        http.send("POST", "https://example.test/x", timeout=5)


def test_send_returns_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(http.httpx, "request", lambda *a, **k: _response(200, '{"ok": true}'))
    resp = http.send("POST", "https://example.test/x", timeout=5)
    assert resp.json() == {"ok": True}
