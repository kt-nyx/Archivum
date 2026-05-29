"""Reusable OpenAI client helpers."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pipeline.ai.config import AISettings


def chat_json_completion(
    settings: AISettings,
    *,
    system_prompt: str,
    user_prompt: str,
    model: str | None = None,
    timeout_seconds: int | None = None,
    response_json_schema: dict[str, Any] | None = None,
    response_schema_name: str = "structured_output",
    reasoning_effort: str | None = None,
    verbosity: str | None = None,
) -> dict[str, Any] | None:
    """Request a JSON object completion using the configured OpenAI provider."""
    if not settings.openai_ready:
        return None
    resolved_model = model or settings.openai_model
    response_format: dict[str, Any]
    if response_json_schema is not None:
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": response_schema_name,
                "strict": True,
                "schema": response_json_schema,
            },
        }
    else:
        response_format = {"type": "json_object"}
    body: dict[str, Any] = {
        "model": resolved_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": response_format,
    }
    temperature = getattr(settings, "openai_temperature", None)
    if temperature is not None:
        body["temperature"] = temperature
    resolved_reasoning = reasoning_effort
    if resolved_reasoning is None:
        resolved_reasoning = getattr(settings, "openai_reasoning_effort", None)
    if resolved_reasoning:
        body["reasoning_effort"] = resolved_reasoning
    resolved_verbosity = verbosity
    if resolved_verbosity is None:
        resolved_verbosity = getattr(settings, "openai_verbosity", None)
    if resolved_verbosity:
        body["verbosity"] = resolved_verbosity
    endpoint = f"{settings.openai_base_url.rstrip('/')}/chat/completions"
    request = Request(
        endpoint,
        method="POST",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
    )
    resolved_timeout = timeout_seconds
    if resolved_timeout is None:
        resolved_timeout = int(getattr(settings, "openai_request_timeout_seconds", 600))
    try:
        with urlopen(request, timeout=resolved_timeout) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
    except TimeoutError as exc:
        raise RuntimeError(
            f"OpenAI chat completion timed out after {resolved_timeout}s while reading the "
            "HTTP response. Large structured outputs and reasoning models can be slow; set "
            "OPENAI_TIMEOUT_SECONDS higher (e.g. 900) or use a faster model."
        ) from exc
    except HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:  # pragma: no cover - defensive
            detail = ""
        msg = f"OpenAI chat completion failed: HTTP {exc.code} {exc.reason}"
        if detail.strip():
            msg = f"{msg}: {detail.strip()}"
        raise RuntimeError(msg) from exc
    except URLError as exc:
        reason = getattr(exc, "reason", None)
        reason_str = repr(reason) if reason is not None else str(exc)
        if isinstance(reason, TimeoutError) or "timed out" in reason_str.lower():
            raise RuntimeError(
                f"OpenAI chat completion timed out after {resolved_timeout}s ({exc!r}). "
                "Increase OPENAI_TIMEOUT_SECONDS if the model is still generating."
            ) from exc
        raise RuntimeError(f"OpenAI chat completion request failed: {exc!r}") from exc
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        return None
    message = first_choice.get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if not isinstance(content, str):
        return None
    parsed = json.loads(content)
    return parsed if isinstance(parsed, dict) else None
