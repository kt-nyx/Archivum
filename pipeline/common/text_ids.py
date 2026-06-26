"""Shared slug / identifier helpers.

Single implementation of the ``[^a-z0-9]+ -> separator`` slug used to derive
entity ids, node ids, and section keys across the pipeline, replacing the copies
that previously lived in each module.

Note: this intentionally keeps the original ASCII-fold-by-deletion behaviour
(non-ASCII characters become separators, not transliterations). Adopting a
transliterating slugifier (e.g. ``python-slugify``) would change existing ids
for non-ASCII inputs and is deferred to a phase that can regenerate fixtures.
"""

from __future__ import annotations

import re

# Apostrophes (straight, curly, and the modifier-letter variant) are *deleted*, not
# collapsed to a separator, so an intra-word apostrophe joins the surrounding letters
# (Kel'Thuzad -> kelthuzad, Uther's Tomb -> uthers-tomb) instead of fracturing the
# slug (kel-thuzad, uther-s-tomb). This keeps entity/term ids aligned with the proper
# noun and stops cross-page references/dedup from diverging on the apostrophe.
_APOSTROPHE_RE = re.compile("['‘’ʼ]")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str, *, separator: str = "-", strip_result: bool = True) -> str:
    """Return a slug of ``text``: lowercased, apostrophes removed, other
    non-alphanumerics collapsed to ``separator``.

    ``strip_result`` trims a leading/trailing ``separator`` (the common case).
    Pass ``strip_result=False`` to preserve a trailing separator.
    """
    deapostrophized = _APOSTROPHE_RE.sub("", text.strip().lower())
    slug = _NON_ALNUM_RE.sub(separator, deapostrophized)
    return slug.strip(separator) if strip_result else slug
