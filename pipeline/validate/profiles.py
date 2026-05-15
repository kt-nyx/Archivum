"""Validation profile support for toggleable fact-check behavior."""

from __future__ import annotations

from enum import StrEnum


class FactCheckProfile(StrEnum):
    OFF = "off"
    WARN = "warn"
    STRICT = "strict"


def parse_fact_check_profile(value: str | None) -> FactCheckProfile:
    """Parse and normalize a fact-check profile string."""
    if value is None:
        return FactCheckProfile.OFF
    normalized = value.strip().lower()
    if normalized in {"", FactCheckProfile.OFF}:
        return FactCheckProfile.OFF
    if normalized == FactCheckProfile.WARN:
        return FactCheckProfile.WARN
    if normalized == FactCheckProfile.STRICT:
        return FactCheckProfile.STRICT
    msg = f"unsupported fact-check profile '{value}', expected off|warn|strict"
    raise ValueError(msg)
