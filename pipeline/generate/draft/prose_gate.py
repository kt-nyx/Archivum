"""Deterministic prose-quality gate for synthesized draft prose.

Runs after the LLM prose workers and catches two artifact classes the per-field
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

The gate reports violations (a list of issue strings, mirroring the ``lint_*``
helpers); callers treat a non-empty result like a lint failure and fall back to
deterministic prose.
"""

from __future__ import annotations

import re
import unicodedata

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


def prose_gate_violations(text: str) -> list[str]:
    """Report prose-quality artifacts. Empty/whitespace input has no violations."""
    issues: list[str] = []
    if not text.strip():
        return issues
    if detect_script_mixing(text):
        issues.append("prose gate: mixed-script letters (non-Latin injection)")
    if detect_dangling_terminal(text):
        issues.append("prose gate: sentence ends on a dangling function word")
    return issues


def prose_gate_rejects(text: str) -> bool:
    """Convenience boolean form of :func:`prose_gate_violations`."""
    return bool(prose_gate_violations(text))
