"""Loader for the externalized discovery classification vocabulary (WS-C / D-6).

The classification keyword lists that survive the D-6 gate (no structural
category/infobox/section signal at the pre-fetch link-decision point, no viable
statistical signal for a short title) live in
``pipeline/data/discovery_classification_vocab.v1.json`` rather than inline in
code. This module reads them once and exposes them as immutable tuples so call
sites keep the same shape they had as module-level constants.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pipeline.common.io import read_json

_VOCAB_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "discovery_classification_vocab.v1.json"
)


@lru_cache(maxsize=1)
def _vocab() -> dict[str, object]:
    blob = read_json(_VOCAB_PATH)
    if not isinstance(blob, dict):  # pragma: no cover - corrupt data file
        raise RuntimeError(f"discovery vocab must be a JSON object: {_VOCAB_PATH}")
    return blob


def _tokens(key: str) -> tuple[str, ...]:
    entry = _vocab().get(key)
    if not isinstance(entry, dict):  # pragma: no cover - corrupt data file
        raise RuntimeError(f"discovery vocab missing entry: {key}")
    tokens = entry.get("tokens")
    if not isinstance(tokens, list):  # pragma: no cover - corrupt data file
        raise RuntimeError(f"discovery vocab entry {key!r} missing 'tokens' list")
    return tuple(str(token) for token in tokens)


def _frozenset(key: str) -> frozenset[str]:
    return frozenset(_tokens(key))


def quest_alliance_binding_tokens() -> tuple[str, ...]:
    return _tokens("quest_alliance_binding_tokens")


def quest_horde_binding_tokens() -> tuple[str, ...]:
    return _tokens("quest_horde_binding_tokens")


def entry_quest_title_keywords() -> frozenset[str]:
    return _frozenset("entry_quest_title_keywords")


def non_canon_body_markers() -> tuple[str, ...]:
    return _tokens("non_canon_body_markers")
