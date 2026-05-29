"""Retrieval profile definitions for source ingest."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievalProfile:
    name: str
    timeout_seconds: int
    max_chars: int
    retries: int
    retry_backoff_seconds: float


DEFAULT_RETRIEVAL_PROFILE = RetrievalProfile(
    name="default",
    timeout_seconds=15,
    max_chars=7000,
    retries=2,
    retry_backoff_seconds=0.5,
)

WARCRAFT_WIKI_PROFILE = RetrievalProfile(
    name="warcraft_wiki",
    timeout_seconds=15,
    max_chars=9000,
    retries=2,
    retry_backoff_seconds=0.5,
)

def profile_for_source_class(source_class: str) -> RetrievalProfile:
    normalized = source_class.strip().lower()
    if normalized == "warcraft_wiki":
        return WARCRAFT_WIKI_PROFILE
    return DEFAULT_RETRIEVAL_PROFILE
