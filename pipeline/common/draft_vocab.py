"""Loader for the externalized draft classification vocabulary (WS-C / D-6).

Reads ``pipeline/data/draft_classification_vocab.v1.json`` once and exposes the
lists that survived the D-6 gate as immutable tuples, so call sites keep the same
shape they had as module-level constants.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pipeline.common.io import read_json

_VOCAB_PATH = Path(__file__).resolve().parents[1] / "data" / "draft_classification_vocab.v1.json"


@lru_cache(maxsize=1)
def _vocab() -> dict[str, object]:
    blob = read_json(_VOCAB_PATH)
    if not isinstance(blob, dict):  # pragma: no cover - corrupt data file
        raise RuntimeError(f"draft vocab must be a JSON object: {_VOCAB_PATH}")
    return blob


def _tokens(key: str) -> tuple[str, ...]:
    entry = _vocab().get(key)
    if not isinstance(entry, dict):  # pragma: no cover - corrupt data file
        raise RuntimeError(f"draft vocab missing entry: {key}")
    tokens = entry.get("tokens")
    if not isinstance(tokens, list):  # pragma: no cover - corrupt data file
        raise RuntimeError(f"draft vocab entry {key!r} missing 'tokens' list")
    return tuple(str(token) for token in tokens)


def era_section_role_tokens() -> tuple[str, ...]:
    return _tokens("era_section_role_tokens")


def expansion_release_order() -> tuple[str, ...]:
    """WoW expansion shorthands in chronological release order (index = rank).

    Unlike :func:`era_section_role_tokens` (a membership set), order is meaningful: later index
    means a later expansion. Used as a soft relative recency signal in temporal classification.
    """
    return _tokens("expansion_release_order")
