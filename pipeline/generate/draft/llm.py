"""Draft-stage LLM calls with tracing and draft-specific OpenAI knobs."""

from __future__ import annotations

import json
import sys
import time
from typing import Any

from jsonschema import Draft202012Validator

from pipeline.ai.config import AISettings, load_ai_settings
from pipeline.ai.openai_client import chat_json_completion
from pipeline.generate.draft.mode import use_responses_api
from pipeline.generate.draft.trace import DraftTraceContext

_VERBOSE = False


def set_draft_verbose(enabled: bool) -> None:
    global _VERBOSE
    _VERBOSE = enabled


def _draft_openai_knobs(settings: AISettings) -> tuple[str | None, str | None]:
    effort = settings.openai_draft_reasoning_effort or settings.openai_reasoning_effort
    verbosity = settings.openai_draft_verbosity or settings.openai_verbosity
    return effort, verbosity


def draft_chat_json_completion(
    settings: AISettings,
    *,
    system_prompt: str,
    user_prompt: str,
    response_json_schema: dict[str, Any],
    response_schema_name: str,
    trace: DraftTraceContext | None = None,
    substep: str = "llm",
    model: str | None = None,
    previous_response_id: str | None = None,
) -> dict[str, Any] | None:
    """Single structured JSON completion for a draft substep."""
    if use_responses_api() or settings.openai_use_responses_api:
        from pipeline.ai.responses_client import responses_json_completion

        effort, verbosity = _draft_openai_knobs(settings)
        started = time.perf_counter()
        if _VERBOSE and trace is not None:
            print(
                f"[lore-pipeline] draft entity={trace.entity_id} substep={substep} "
                f"schema={response_schema_name} starting...",
                file=sys.stderr,
            )
        parsed = responses_json_completion(
            settings,
            instructions=system_prompt,
            user_input=user_prompt,
            response_json_schema=response_json_schema,
            response_schema_name=response_schema_name,
            model=model,
            reasoning_effort=effort,
            verbosity=verbosity,
            previous_response_id=previous_response_id,
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        if trace is not None:
            req_bytes = len(system_prompt.encode()) + len(user_prompt.encode())
            trace.record(
                substep=substep,
                schema_name=response_schema_name,
                duration_ms=duration_ms,
                model=model or settings.openai_model,
                reasoning_effort=effort,
                verbosity=verbosity,
                request_bytes=req_bytes,
            )
            if _VERBOSE:
                print(
                    f"[lore-pipeline] draft entity={trace.entity_id} substep={substep} "
                    f"done duration_ms={duration_ms}",
                    file=sys.stderr,
                )
        return parsed

    effort, verbosity = _draft_openai_knobs(settings)
    started = time.perf_counter()
    if _VERBOSE and trace is not None:
        print(
            f"[lore-pipeline] draft entity={trace.entity_id} substep={substep} "
            f"schema={response_schema_name} starting...",
            file=sys.stderr,
        )
    parsed = chat_json_completion(
        settings,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=model,
        response_json_schema=response_json_schema,
        response_schema_name=response_schema_name,
        reasoning_effort=effort,
        verbosity=verbosity,
    )
    duration_ms = int((time.perf_counter() - started) * 1000)
    if trace is not None:
        req_bytes = len(system_prompt.encode()) + len(user_prompt.encode())
        trace.record(
            substep=substep,
            schema_name=response_schema_name,
            duration_ms=duration_ms,
            model=model or settings.openai_model,
            reasoning_effort=effort,
            verbosity=verbosity,
            request_bytes=req_bytes,
        )
        if _VERBOSE:
            print(
                f"[lore-pipeline] draft entity={trace.entity_id} substep={substep} "
                f"done duration_ms={duration_ms}",
                file=sys.stderr,
            )
    return parsed


def llm_json_with_retry(
    *,
    required_keys: tuple[str, ...],
    response_json_schema: dict[str, Any],
    system_prompt: str,
    user_prompt: str,
    max_attempts: int = 3,
    response_schema_name: str = "draft_body",
    trace: DraftTraceContext | None = None,
    substep: str = "llm",
) -> dict[str, Any]:
    settings = load_ai_settings()
    if not settings.openai_ready:
        raise RuntimeError("draft stage requires OpenAI, but OPENAI_API_KEY is not configured")
    errors: list[str] = []
    schema_validator = Draft202012Validator(response_json_schema)
    for attempt in range(1, max_attempts + 1):
        parsed = draft_chat_json_completion(
            settings,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_json_schema=response_json_schema,
            response_schema_name=response_schema_name,
            trace=trace,
            substep=substep if attempt == 1 else f"{substep}_retry_{attempt}",
        )
        if not isinstance(parsed, dict):
            errors.append(f"attempt={attempt}: non-JSON response")
            continue
        schema_errors = list(schema_validator.iter_errors(parsed))
        if schema_errors:
            errors.append(f"attempt={attempt}: schema mismatch {schema_errors[0].message}")
            continue
        missing = [key for key in required_keys if key not in parsed]
        if missing:
            errors.append(f"attempt={attempt}: missing keys {', '.join(missing)}")
            continue
        return parsed
    joined_errors = "; ".join(errors)
    raise RuntimeError(
        f"draft LLM generation failed after {max_attempts} attempts ({joined_errors})"
    )


def estimate_request_bytes(system_prompt: str, user_prompt: str, schema: dict[str, Any]) -> int:
    schema_bytes = len(json.dumps(schema).encode())
    return len(system_prompt.encode()) + len(user_prompt.encode()) + schema_bytes
