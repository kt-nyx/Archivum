"""Shared JSON read/write helpers.

Canonical on-disk JSON policy (decision D-4): ``indent=2``, ``ensure_ascii=False``
(human-readable unicode), a trailing newline, and LF line endings regardless of
platform. Using :func:`write_json` everywhere keeps hand-authored fixtures and
pipeline output from diverging.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    """Parse the JSON document at ``path``."""
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, obj: Any, *, sort_keys: bool = False) -> None:
    """Write ``obj`` as canonical JSON (indent=2, unicode, trailing LF newline)."""
    text = json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=sort_keys)
    path.write_text(text + "\n", encoding="utf-8", newline="\n")
