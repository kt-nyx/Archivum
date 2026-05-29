"""OpenAI Responses API helper for structured JSON (draft pipeline opt-in)."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pipeline.ai.config import AISettings
from pipeline.ai.openai_client import chat_json_completion


def responses_json_completion(
    settings: AISettings,
    *,
    instructions: str,
    user_input: str,
    response_json_schema: dict[str, Any],
    response_schema_name: str,
    model: str | None = None,
    timeout_seconds: int | None = None,
    reasoning_effort: str | None = None,
    verbosity: str | None = None,
    previous_response_id: str | None = None,
) -> dict[str, Any] | None:
    """Request structured JSON via Responses API; falls back to Chat Completions on HTTP errors."""
    if not settings.openai_ready:
        return None
    resolved_model = model or settings.openai_model
    text_format: dict[str, Any] = {
        "type": "json_schema",
        "name": response_schema_name,
        "strict": True,
        "schema": response_json_schema,
    }
    body: dict[str, Any] = {
        "model": resolved_model,
        "instructions": instructions,
        "input": user_input,
        "text": {"format": text_format},
    }
    if previous_response_id:
        body["previous_response_id"] = previous_response_id
    if reasoning_effort:
        body["reasoning"] = {"effort": reasoning_effort}
    if verbosity:
        body["text"] = {**body.get("text", {}), "verbosity": verbosity}
    resolved_timeout = timeout_seconds
    if resolved_timeout is None:
        resolved_timeout = settings.openai_request_timeout_seconds
    endpoint = f"{settings.openai_base_url.rstrip('/')}/responses"
    request = Request(
        endpoint,
        method="POST",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=resolved_timeout) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
    except (TimeoutError, HTTPError, URLError):
        return chat_json_completion(
            settings,
            system_prompt=instructions,
            user_prompt=user_input,
            model=resolved_model,
            timeout_seconds=resolved_timeout,
            response_json_schema=response_json_schema,
            response_schema_name=response_schema_name,
            reasoning_effort=reasoning_effort,
            verbosity=verbosity,
        )
    output = payload.get("output")
    if not isinstance(output, list):
        return None
    for item in output:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") not in {"output_text", "text"}:
                continue
            text = block.get("text")
            if isinstance(text, str):
                parsed = json.loads(text)
                return parsed if isinstance(parsed, dict) else None
    return None
