"""Reusable OpenAI client helpers."""

from __future__ import annotations

import json
from typing import Any
from urllib.request import Request, urlopen

from pipeline.ai.config import AISettings


def chat_json_completion(
    settings: AISettings,
    *,
    system_prompt: str,
    user_prompt: str,
    model: str | None = None,
    timeout_seconds: int = 30,
    response_json_schema: dict[str, Any] | None = None,
    response_schema_name: str = "structured_output",
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
    body = {
        "model": resolved_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0,
        "response_format": response_format,
    }
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
    with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
        payload = json.loads(response.read().decode("utf-8"))
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
