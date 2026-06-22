"""Deterministic prose-quality gate for synthesized draft prose.

Runs after the LLM prose workers and catches artifact classes the per-field
lints miss, using pure string analysis (no second LLM call):

1. **Script mixing** — stray letters from a non-Latin alphabet injected into
   otherwise-Latin prose (e.g. the Cyrillic ``смeded`` seen in a Scholomance
   run, where Cyrillic ``с``/``е`` masquerade as Latin ``c``/``e``). The addon
   is retail-WoW English/Latin, so any Cyrillic/Greek/Cyrillic-homoglyph letter
   mixed into Latin words is an injection artifact.
2. **Dangling terminal word** — a sentence that ends on a function word such as
   an article, coordinating conjunction, or (non-particle) preposition
   (e.g. ``...the war in the toward.``). Complements
   ``lint_passthrough_fragment``, which only checks that *a* terminator exists,
   not that the word before it is a real sentence ending.
3. **Mid-sentence gap** — a preposition/article stranded mid-sentence by a naive
   zone-name strip (``...the call to, where``); see :func:`detect_midsentence_gap`.
4. **List/navbox shape** — a near-zero-connective place-name dump masquerading as
   prose (the Argent Crusade navbox defect); see :func:`detect_list_shape`.
5. **Copy passthrough** — a summary that is the ``"<name> features prominently in
   ...: <raw snippet>"`` splice, or (when ``source_snippets`` are supplied) a
   near-verbatim copy of its source evidence.

The gate reports violations (a list of issue strings, mirroring the ``lint_*``
helpers); callers treat a non-empty result like a lint failure and fall back to
deterministic prose.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from pipeline.common.text_sim import max_similarity_against_sources

# Function words that should never be the final word of a finished sentence.
# Curated for precision: articles, coordinating conjunctions, and prepositions
# that are *not* also adverbial particles. Particle-prone words (out, in, on,
# up, down, off, over, under, back, through, around) are deliberately excluded
# so legitimate imperative CTAs ("...and drive them out.") are not rejected.
_DANGLING_TERMINAL_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "nor",
        "of",
        "to",
        "for",
        "with",
        "without",
        "toward",
        "towards",
        "into",
        "onto",
        "upon",
        "from",
        "as",
        "than",
        "amid",
        "amidst",
        "unto",
        "versus",
        "via",
        "atop",
        "beside",
        "besides",
        "beneath",
        "despite",
        "unlike",
        "amongst",
        "between",
        "against",
        "during",
    }
)

_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)

# Function words that must never sit immediately before sentence punctuation, nor leave an
# article stranded directly before a conjunction. A naive zone-name substring strip that
# deletes the object of a preposition/article leaves exactly these gaps — "...the call to,
# where" and "contest the and every road" — *mid*-sentence, where ``detect_dangling_terminal``
# (tail-only) never looks.
_MIDSENTENCE_GAP_RE = re.compile(
    r"\b(?:a|an|the|to|into|onto|unto|upon|of|for|with|without|from|at|by|in|on|across|"
    r"through|throughout|within|toward|towards|against|amid|amidst|between|beneath|beside|"
    r"besides|despite|during|over|under|near|around)\s*[,;:]"
    r"|\b(?:a|an|the)\s+(?:and|or|but|nor)\b",
    re.IGNORECASE,
)


def detect_midsentence_gap(text: str) -> bool:
    """True when a function word is stranded mid-sentence (dangling preposition/article).

    Catches the breakage a naive zone-name substring strip leaves behind — a preposition or
    article immediately before punctuation (``"...the call to, where"``), or an article
    directly followed by a conjunction (``"contest the and every road"``). Complements
    :func:`detect_dangling_terminal`, which only inspects the final word of the string.
    """
    return bool(_MIDSENTENCE_GAP_RE.search(text))


# Connective/function words whose presence signals genuine connected prose. A navbox or
# place-name list ("Chillwind Camp Hearthglen Northridge Lumber Camp ...") carries almost
# none; ordinary English prose runs ~25-50% function words. A long span with near-zero
# connective density is therefore a list/navbox dump masquerading as a sentence, not prose.
_FUNCTION_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "nor",
        "of",
        "to",
        "for",
        "with",
        "in",
        "on",
        "at",
        "by",
        "from",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "that",
        "this",
        "these",
        "those",
        "it",
        "its",
        "he",
        "she",
        "they",
        "them",
        "his",
        "her",
        "their",
        "who",
        "which",
        "when",
        "where",
        "while",
        "after",
        "before",
        "during",
        "into",
        "over",
        "under",
        "against",
        "between",
        "through",
        "has",
        "have",
        "had",
        "not",
        "no",
        "than",
        "then",
        "there",
        "here",
        "out",
        "upon",
        "amid",
        "about",
        "across",
        "within",
        "without",
        "because",
        "so",
    }
)
# A list is judged only once it is long enough to be unambiguous; below this token count a
# terse-but-real summary could trip the ratio test, so we abstain.
_LIST_SHAPE_MIN_TOKENS = 8
_LIST_SHAPE_FUNCTION_RATIO = 0.10


def detect_list_shape(text: str) -> bool:
    """True when text reads like a navbox/place-name list rather than connected prose.

    Uses function-word density: a navbox of proper nouns has near-zero connectives, while
    real English prose runs ~25-50%. Short spans abstain (too little signal to judge).
    Shared by the deterministic prose gate and the faction/key-character prose fallbacks so
    the heuristic lives in one place.
    """
    words = _WORD_RE.findall(text)
    n = len(words)
    if n < _LIST_SHAPE_MIN_TOKENS:
        return False
    function_words = sum(1 for word in words if word.lower() in _FUNCTION_WORDS)
    return function_words / n < _LIST_SHAPE_FUNCTION_RATIO


# The deterministic key-character fallback used to colon-splice a raw, word-truncated evidence
# snippet after a generic frame (``"<boss> features prominently in <instance>: <raw snippet>"`` —
# defect #4). Fix C stopped emitting it; this regex is the gate backstop so the splice can never
# ship again, even if another fallback reintroduces the shape.
_SPLICE_PASSTHROUGH_RE = re.compile(r"\bfeatures prominently in\b[^:]*:\s+\S", re.IGNORECASE)

# A synthesized summary that is ~identical to one of its source evidence snippets is a verbatim
# copy, not synthesis (defect #2/#4). Tuned high: deterministic fallbacks legitimately *borrow* a
# clean sentence (moderate overlap), so only near-total token overlap counts as passthrough.
_COPY_PASSTHROUGH_THRESHOLD = 0.85


def detect_splice_passthrough(text: str) -> bool:
    """True when text is the ``"<name> features prominently in <x>: <raw snippet>"`` splice."""
    return bool(_SPLICE_PASSTHROUGH_RE.search(text))


def detect_source_passthrough(text: str, source_snippets: Iterable[str]) -> bool:
    """True when text is a near-verbatim copy of any source evidence snippet.

    Uses whitespace-token Jaccard against each source; only near-total overlap trips it, so a
    deterministic fallback that borrows a single clean sentence is not mistaken for a raw copy.
    """
    if not text.strip():
        return False
    return max_similarity_against_sources(text, source_snippets) >= _COPY_PASSTHROUGH_THRESHOLD


def _letter_script(ch: str) -> str | None:
    """Return the alphabet name (LATIN/CYRILLIC/GREEK/...) for an alphabetic char.

    Unicode letter names lead with their script, e.g. ``LATIN SMALL LETTER A`` or
    ``CYRILLIC SMALL LETTER ES``. Accented Latin (``é`` → ``LATIN SMALL LETTER E
    WITH ACUTE``) still resolves to ``LATIN``. Non-letters return ``None``.
    """
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return None
    if "LETTER" not in name:
        return None
    return name.split(" ", 1)[0]


def detect_script_mixing(text: str) -> bool:
    """True when Latin prose is contaminated with letters from another alphabet."""
    scripts: set[str] = set()
    for ch in text:
        script = _letter_script(ch)
        if script:
            scripts.add(script)
    return "LATIN" in scripts and bool(scripts - {"LATIN"})


def detect_dangling_terminal(text: str) -> bool:
    """True when the prose ends on a function word (article/conjunction/preposition)."""
    cleaned = text.strip()
    if not cleaned:
        return False
    words = _WORD_RE.findall(cleaned)
    if not words:
        return False
    return words[-1].lower() in _DANGLING_TERMINAL_WORDS


def prose_gate_violations(
    text: str, *, source_snippets: Iterable[str] | None = None
) -> list[str]:
    """Report prose-quality artifacts. Empty/whitespace input has no violations.

    Pass ``source_snippets`` (the evidence the prose was synthesized from) to additionally reject
    a summary that is a near-verbatim copy of its source. Without it, the source-passthrough check
    is skipped (the other detectors are text-only).
    """
    issues: list[str] = []
    if not text.strip():
        return issues
    if detect_script_mixing(text):
        issues.append("prose gate: mixed-script letters (non-Latin injection)")
    if detect_dangling_terminal(text):
        issues.append("prose gate: sentence ends on a dangling function word")
    if detect_midsentence_gap(text):
        issues.append("prose gate: mid-sentence gap (dangling preposition/article)")
    if detect_list_shape(text):
        issues.append("prose gate: list/navbox-shaped text (near-zero connective density)")
    if detect_splice_passthrough(text):
        issues.append("prose gate: verbatim evidence splice ('features prominently in ...:')")
    if source_snippets is not None and detect_source_passthrough(text, source_snippets):
        issues.append("prose gate: near-verbatim copy of source evidence")
    return issues


def prose_gate_rejects(text: str, *, source_snippets: Iterable[str] | None = None) -> bool:
    """Convenience boolean form of :func:`prose_gate_violations`."""
    return bool(prose_gate_violations(text, source_snippets=source_snippets))
