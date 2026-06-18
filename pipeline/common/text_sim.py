"""Shared text-similarity helpers.

Consolidates the duplicated Jaccard/token-overlap implementations. Two distinct
behaviours are preserved under explicit names:

- :func:`token_jaccard` — significant-token (len >= 4) Jaccard, used by prose and
  structure anti-repetition checks.
- :func:`whitespace_jaccard` — whitespace-split Jaccard with ``1.0`` for two empty
  inputs, used by the anti-verbatim source comparison.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _significant_tokens(value: str) -> set[str]:
    return {token for token in _TOKEN_RE.findall(value.lower()) if len(token) >= 4}


def token_jaccard(left: str, right: str) -> float:
    """Jaccard overlap of significant (>=4 char) alphanumeric tokens; 0.0 if either empty."""
    left_tokens = _significant_tokens(left)
    right_tokens = _significant_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def whitespace_jaccard(lhs: str, rhs: str) -> float:
    """Jaccard over whitespace-split lowercased tokens; 1.0 when both inputs are empty."""
    lhs_tokens = {token for token in lhs.lower().split() if token}
    rhs_tokens = {token for token in rhs.lower().split() if token}
    if not lhs_tokens and not rhs_tokens:
        return 1.0
    if not lhs_tokens or not rhs_tokens:
        return 0.0
    return len(lhs_tokens & rhs_tokens) / len(lhs_tokens | rhs_tokens)


def max_similarity_against_sources(text: str, source_snippets: Iterable[str]) -> float:
    """Highest :func:`whitespace_jaccard` of ``text`` against any source snippet."""
    return max((whitespace_jaccard(text, snippet) for snippet in source_snippets), default=0.0)
