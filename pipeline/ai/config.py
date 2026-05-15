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
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        google_api_key=os.getenv("GOOGLE_API_KEY", ""),
        google_cse_id=os.getenv("GOOGLE_CSE_ID", ""),
    )
