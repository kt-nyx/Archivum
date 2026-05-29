"""Shared AI provider configuration for pipeline stages."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

_DOTENV_LOCK = threading.Lock()
_DOTENV_LOADED = False


def _repo_root_from_package() -> Path:
    """Directory containing the installed `pipeline` package (repo root in editable installs)."""
    return Path(__file__).resolve().parents[2]


def _bootstrap_dotenv() -> None:
    """Load `.env` once: prefer repo-root file next to this package, else search upward from cwd.

    Uses ``override=False`` so variables already set in the process environment (shell, CI,
    container orchestration) win over file values.
    """
    global _DOTENV_LOADED
    with _DOTENV_LOCK:
        if _DOTENV_LOADED:
            return
        _DOTENV_LOADED = True

        if _dotenv_disabled():
            return

        repo_dotenv = _repo_root_from_package() / ".env"
        if repo_dotenv.is_file():
            load_dotenv(repo_dotenv, override=False)
        else:
            # Editable layout missing or wheel install: walk up from cwd for a `.env`
            discovered = find_dotenv(usecwd=True)
            if discovered:
                load_dotenv(discovered, override=False)


def _optional_env_float(name: str) -> float | None:
    """Parse a float env var; return None if unset or blank."""
    raw = os.environ.get(name)
    if raw is None:
        return None
    stripped = raw.strip()
    if not stripped:
        return None
    return float(stripped)


def _optional_env_strip(name: str) -> str | None:
    """Return stripped string or None if unset/blank."""
    raw = os.environ.get(name)
    if raw is None:
        return None
    stripped = raw.strip()
    return stripped or None


def _openai_timeout_seconds_from_env() -> int:
    """HTTP read timeout for OpenAI chat completions (entire request+body read).

    Large ``json_schema`` drafts and reasoning-class models often exceed 90s; the
    default is conservative for interactive runs. Override with ``OPENAI_TIMEOUT_SECONDS``.
    """
    raw = os.environ.get("OPENAI_TIMEOUT_SECONDS")
    if raw is None:
        return 600
    stripped = raw.strip()
    if not stripped:
        return 600
    return max(30, int(stripped))


def _dotenv_disabled() -> bool:
    """Opt out with ``WOW_LORE_DOTENV=0`` (e.g. tests that must not read a developer `.env`)."""
    raw = os.environ.get("WOW_LORE_DOTENV", "")
    if not raw:
        return False
    return raw.strip().lower() in {"0", "false", "no", "off"}


@dataclass(frozen=True)
class AISettings:
    """Environment-backed configuration for AI and retrieval providers."""

    provider: str
    openai_api_key: str
    openai_model: str
    openai_base_url: str
    # When set, sent as ``temperature`` on chat completions. When None, omitted so the API
    # model default applies (some models reject explicit temperature, e.g. only default 1).
    openai_temperature: float | None
    # GPT-5.x / reasoning models: optional Chat Completions knobs (see OpenAI reasoning guide).
    openai_reasoning_effort: str | None
    openai_verbosity: str | None
    openai_draft_reasoning_effort: str | None
    openai_draft_verbosity: str | None
    openai_use_responses_api: bool
    openai_request_timeout_seconds: int
    google_api_key: str
    google_cse_id: str

    @property
    def openai_ready(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def google_ready(self) -> bool:
        return bool(self.google_api_key and self.google_cse_id)

    @property
    def provider_ready(self) -> bool:
        if self.provider == "openai":
            return self.openai_ready
        return False

    def as_health_payload(self) -> dict[str, object]:
        """Return a compact payload suitable for CLI health output."""
        return {
            "provider": self.provider,
            "provider_ready": self.provider_ready,
            "openai_ready": self.openai_ready,
            "openai_model": self.openai_model,
            "google_ready": self.google_ready,
        }


def load_ai_settings() -> AISettings:
    """Load normalized AI settings from process environment (after optional ``.env`` load)."""
    _bootstrap_dotenv()
    provider = os.getenv("AI_PROVIDER", "openai").strip().lower() or "openai"
    return AISettings(
        provider=provider,
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-5.5"),
        openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        openai_temperature=_optional_env_float("OPENAI_TEMPERATURE"),
        openai_reasoning_effort=_optional_env_strip("OPENAI_REASONING_EFFORT"),
        openai_verbosity=_optional_env_strip("OPENAI_VERBOSITY"),
        openai_draft_reasoning_effort=_optional_env_strip("OPENAI_DRAFT_REASONING_EFFORT"),
        openai_draft_verbosity=_optional_env_strip("OPENAI_DRAFT_VERBOSITY"),
        openai_use_responses_api=os.getenv("OPENAI_USE_RESPONSES_API", "")
        .strip()
        .lower()
        in {"1", "true", "yes", "on"},
        openai_request_timeout_seconds=_openai_timeout_seconds_from_env(),
        google_api_key=os.getenv("GOOGLE_API_KEY", ""),
        google_cse_id=os.getenv("GOOGLE_CSE_ID", ""),
    )
