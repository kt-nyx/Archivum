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

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str, *, separator: str = "-", strip_result: bool = True) -> str:
    """Return a slug of ``text``: lowercased, non-alphanumerics collapsed to ``separator``.

    ``strip_result`` trims a leading/trailing ``separator`` (the common case).
    Pass ``strip_result=False`` to preserve a trailing separator.
    """
    slug = _NON_ALNUM_RE.sub(separator, text.strip().lower())
    return slug.strip(separator) if strip_result else slug
