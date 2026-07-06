"""Shared text-similarity helpers.

Consolidates the duplicated Jaccard/token-overlap implementations. Two distinct
behaviours are preserved under explicit names:

- :func:`token_jaccard` — significant-token (len >= 4) Jaccard, used by prose and
  structure anti-repetition checks.
- :func:`whitespace_jaccard` — whitespace-split Jaccard with ``1.0`` for two empty
  inputs, used by the anti-verbatim source comparison.

Slice 8 adds the lemmatized *support* variants (:func:`lemma_support_containment`,
:func:`lemma_support_ratio`) — the one home for lemma-level fallback scoring used by the
fact-check pass and the coalesce claim-source selector. They score retrieval support only,
never contradiction, and their token set keeps proper nouns and adpositions as surface text
(see :func:`pipeline.common.linguistics.support_tokens`) so spatial assertions like
"above"/"beneath" stay distinguishable.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from rapidfuzz import fuzz

from pipeline.common.linguistics import support_tokens

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


def _significant_support_tokens(text: str) -> list[str]:
    """Lemmatized support tokens, minus the short function words the surface heuristics also
    drop (>= 3 chars keeps "above"/"beneath"/"near" but sheds "of"/"in"/"by", whose ubiquity
    would inflate every support score)."""
    return [token for token in support_tokens(text) if len(token) >= 3]


def lemma_support_containment(claim: str, evidence: str) -> float:
    """Fraction of the claim's lemmatized support tokens found in the evidence's.

    Deterministic fallback support signal for inflection/paraphrase cases the surface
    overlap misses ("gained"/"gain", "necromancers"/"necromancer"); ``0.0`` when either
    side has no support tokens. Never a contradiction judge.
    """
    claim_tokens = set(_significant_support_tokens(claim))
    if not claim_tokens:
        return 0.0
    evidence_tokens = set(_significant_support_tokens(evidence))
    if not evidence_tokens:
        return 0.0
    return len(claim_tokens & evidence_tokens) / len(claim_tokens)


def lemma_support_ratio(claim: str, evidence: str) -> float:
    """rapidfuzz ``token_set_ratio`` over lemmatized support tokens, in ``[0.0, 1.0]``.

    The lemma-level sibling of the coalesce selector's surface token-set score; same
    determinism guarantees (identical inputs give bit-identical floats).
    """
    claim_tokens = _significant_support_tokens(claim)
    evidence_tokens = _significant_support_tokens(evidence)
    if not claim_tokens or not evidence_tokens:
        return 0.0
    return fuzz.token_set_ratio(" ".join(claim_tokens), " ".join(evidence_tokens)) / 100.0


def _word_shingles(value: str, k: int) -> list[tuple[str, ...]]:
    words = _TOKEN_RE.findall(value.lower())
    if k < 1 or len(words) < k:
        return []
    return [tuple(words[i : i + k]) for i in range(len(words) - k + 1)]


def shingle_containment(text: str, source: str, *, k: int = 5) -> float:
    """Fraction of ``text``'s ``k``-word shingles that also occur in ``source``.

    Near ``1.0`` when ``text`` reproduces contiguous runs of ``source`` (a verbatim copy),
    near ``0.0`` for genuine paraphrase. Unlike set Jaccard this is insensitive to how much
    *longer* the source is, so it still catches a short body lifted from a large article (where
    Jaccard is diluted by the source's union). Returns ``0.0`` when either side has < ``k`` words.
    """
    text_shingles = _word_shingles(text, k)
    if not text_shingles:
        return 0.0
    source_shingles = set(_word_shingles(source, k))
    if not source_shingles:
        return 0.0
    matched = sum(1 for shingle in text_shingles if shingle in source_shingles)
    return matched / len(text_shingles)


def max_shingle_containment_against_sources(
    text: str, source_snippets: Iterable[str], *, k: int = 5
) -> float:
    """Highest :func:`shingle_containment` of ``text`` against any source snippet."""
    return max(
        (shingle_containment(text, snippet, k=k) for snippet in source_snippets),
        default=0.0,
    )
