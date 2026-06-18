"""Shared HTTP helpers (httpx transport + tenacity retry).

Replaces the per-module urllib calls and hand-rolled retry/backoff loops. Two
entry points:

- :func:`get_text` — GET returning response text, with exponential-backoff retry
  on transient transport/timeout/HTTP-status errors (used by wiki ingest).
- :func:`send` — a single request (no retry) that raises for non-2xx, leaving
  bespoke error handling to the caller (used by the OpenAI POST clients, which
  manage their own fallback / error messages).
"""

from __future__ import annotations

import httpx
from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# Transient transport-level failures worth retrying (connection resets, DNS, timeouts).
_RETRYABLE_EXC: tuple[type[Exception], ...] = (httpx.TransportError, httpx.TimeoutException)


def send(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    content: bytes | None = None,
    timeout: float,
) -> httpx.Response:
    """Perform a single HTTP request and raise for non-2xx; no retry.

    Raises ``httpx.HTTPStatusError`` for 4xx/5xx, ``httpx.TimeoutException`` on
    timeout, and other ``httpx.RequestError`` subclasses on transport failure.
    """
    response = httpx.request(method, url, headers=headers, content=content, timeout=timeout)
    response.raise_for_status()
    return response


def get_text(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float,
    retries: int = 0,
    backoff_base: float = 0.0,
) -> str:
    """GET ``url`` and return the response body text.

    Retries up to ``retries`` additional times on transient transport/timeout
    errors and on non-2xx responses, with exponential backoff
    (``backoff_base * 2**attempt``). Re-raises the final ``httpx`` error when all
    attempts are exhausted.
    """

    def _attempt() -> str:
        response = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)
        response.raise_for_status()
        return response.text

    if retries <= 0:
        return _attempt()

    retryer = Retrying(
        reraise=True,
        stop=stop_after_attempt(retries + 1),
        wait=wait_exponential(multiplier=backoff_base, exp_base=2),
        retry=retry_if_exception_type((*_RETRYABLE_EXC, httpx.HTTPStatusError)),
    )
    return retryer(_attempt)
