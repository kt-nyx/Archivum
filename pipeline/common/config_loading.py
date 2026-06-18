"""Shared YAML configuration loading.

Single entry point for reading the pipeline's YAML config files, replacing the
ad-hoc line-by-line parsing that previously lived in each consumer. Callers read
the parsed structure with :func:`load_yaml` and then navigate/coerce it against
their own defaults.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_yaml(path: Path, *, default: Any = None) -> Any:
    """Return the parsed YAML at ``path``, or ``default`` when absent/empty.

    ``default`` falls back to an empty dict when not supplied. Malformed YAML
    raises :class:`yaml.YAMLError` rather than being silently ignored: a broken
    config file is a bug to surface, not to paper over with defaults.
    """
    fallback: Any = {} if default is None else default
    if not path.exists():
        return fallback
    parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    if parsed is None:
        return fallback
    return parsed


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    """Return the parsed YAML at ``path`` as a mapping, or ``{}``.

    Convenience wrapper for the common case where a config file is expected to be
    a top-level mapping; non-mapping or missing content yields an empty dict.
    """
    parsed = load_yaml(path, default={})
    return parsed if isinstance(parsed, dict) else {}


def coerce_float(value: Any, default: float) -> float:
    """Return ``value`` as a float, falling back to ``default`` on bad/None input."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
