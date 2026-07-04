"""Loader + classifier for the externalized section-label registry.

The registry (``pipeline/data/section_label_registry.v1.json``) enumerates recurring *top-level*
section types only. :func:`section_content_class` classifies a block by its own label; on a miss it
falls back to the parent (top-level ancestor) section's class; on a further miss it defaults to
``meta`` (excluded from lore prose). Nested subsections — expansion timelines, event sections,
faction subgroups, cultural facets — are intentionally absent and inherit from their parent. This
replaces the scattered keyword helpers in ``discovery/enrich.py`` and removes the substring
false-positives (``crimson_legion`` inherits ``roster`` from ``Organization``, not ``narrative``
from the token "legion").
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from pipeline.common.io import read_json

_REGISTRY_PATH = Path(__file__).resolve().parents[1] / "data" / "section_label_registry.v1.json"

_DEFAULT_CLASS = "meta"
_LORE_CLASSES = frozenset({"narrative", "roster", "geography"})


@lru_cache(maxsize=1)
def _registry() -> dict[str, Any]:
    blob = read_json(_REGISTRY_PATH)
    if not isinstance(blob, dict):  # pragma: no cover - corrupt data file
        raise RuntimeError(f"section registry must be a JSON object: {_REGISTRY_PATH}")
    return blob


@lru_cache(maxsize=1)
def _labels() -> dict[str, dict[str, Any]]:
    labels = _registry().get("labels")
    if not isinstance(labels, dict):  # pragma: no cover - corrupt data file
        raise RuntimeError("section registry missing 'labels' object")
    return labels


@lru_cache(maxsize=1)
def _prefix_rules() -> tuple[tuple[str, str], ...]:
    rules = _registry().get("prefix_rules") or {}
    out: list[tuple[str, str]] = []
    if isinstance(rules, dict):
        for prefix, spec in rules.items():
            if isinstance(spec, dict) and spec.get("content_class"):
                out.append((str(prefix), str(spec["content_class"])))
    return tuple(out)


def normalize_section_label(section_role: str) -> str:
    """Registry key form: lowercased, trailing ``_edit`` (HTML edit-link artifact) stripped."""
    lowered = str(section_role or "").strip().lower()
    if lowered.endswith("_edit"):
        lowered = lowered[: -len("_edit")]
    return lowered


def _lookup(label: str) -> str | None:
    if not label:
        return None
    for prefix, cls in _prefix_rules():
        if label.startswith(prefix):
            return cls
    entry = _labels().get(label)
    if isinstance(entry, dict):
        return str(entry.get("content_class") or "") or None
    return None


def section_content_class(section_role: str, parent_section_role: str = "") -> str:
    """Return the content_class for a section, inheriting from the parent on a miss.

    Order: the block's own label, then the parent (top-level ancestor) section's label, then the
    conservative default (``meta`` — excluded from lore prose).
    """
    own = _lookup(normalize_section_label(section_role))
    if own is not None:
        return own
    if parent_section_role:
        inherited = _lookup(normalize_section_label(parent_section_role))
        if inherited is not None:
            return inherited
    return _DEFAULT_CLASS


def is_lore_prose_section(section_role: str, parent_section_role: str = "") -> bool:
    """True when the section is in-universe lore content (narrative/roster/geography)."""
    return section_content_class(section_role, parent_section_role) in _LORE_CLASSES


def is_narrative_section(section_role: str, parent_section_role: str = "") -> bool:
    """True when the section is in-universe narrative prose (admissible to lore summary pools)."""
    return section_content_class(section_role, parent_section_role) == "narrative"


def section_temporality(section_role: str, parent_section_role: str = "") -> str:
    """Return the temporality hint ('expansion_era' or '') for a section, inheriting on a miss."""
    for role in (section_role, parent_section_role):
        entry = _labels().get(normalize_section_label(role))
        if isinstance(entry, dict) and entry.get("temporality"):
            return str(entry["temporality"])
    return ""
