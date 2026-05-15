"""Simple similarity checks for anti-verbatim safeguards."""

from __future__ import annotations

from collections.abc import Iterable


def jaccard_similarity(lhs: str, rhs: str) -> float:
    lhs_tokens = {token for token in lhs.lower().split() if token}
    rhs_tokens = {token for token in rhs.lower().split() if token}
    if not lhs_tokens and not rhs_tokens:
        return 1.0
    if not lhs_tokens or not rhs_tokens:
        return 0.0
    intersection = len(lhs_tokens.intersection(rhs_tokens))
    union = len(lhs_tokens.union(rhs_tokens))
    return intersection / float(union)


def max_similarity_against_sources(text: str, source_snippets: Iterable[str]) -> float:
    return max((jaccard_similarity(text, snippet) for snippet in source_snippets), default=0.0)
