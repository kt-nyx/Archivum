"""Draft pipeline mode selection."""

from __future__ import annotations

import os

DraftPipelineMode = str


def draft_pipeline_mode() -> DraftPipelineMode:
    """Return ``legacy`` or ``staged`` (default ``staged``)."""
    raw = os.environ.get("WOW_LORE_DRAFT_MODE", "staged").strip().lower()
    if raw in {"legacy", "single", "monolith"}:
        return "legacy"
    return "staged"


def use_responses_api() -> bool:
    raw = os.environ.get("OPENAI_USE_RESPONSES_API", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}
