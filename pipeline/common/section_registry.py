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


def section_narrative_kind(section_role: str, parent_section_role: str = "") -> str:
    """Return the narrative_kind ('history'/'background'/'identity'/… or '') for a section.

    Own label first, then the parent (top-level ancestor). Only registry narrative labels carry a
    narrative_kind; everything else returns ''.
    """
    for role in (section_role, parent_section_role):
        entry = _labels().get(normalize_section_label(role))
        if isinstance(entry, dict) and entry.get("narrative_kind"):
            return str(entry["narrative_kind"])
    return ""


def is_media_section(section_role: str, parent_section_role: str = "") -> bool:
    """True for adaptation / expanded-universe prose (novels, comics, 'Exploring Azeroth')."""
    return section_content_class(section_role, parent_section_role) == "media"


# The narrative_kind values that name a generic history *container* rather than a distinctive
# era/event subsection. Sentinels are the pipeline's own synthetic role values (never wiki labels).
_GENERIC_NARRATIVE_KINDS = frozenset({"history", "background", "overview", "identity"})
_GENERIC_HEADING_SENTINELS = frozenset({"other", "historical_era"})


def is_generic_history_heading(heading: str) -> bool:
    """True when a heading is a bare container/era label, not a distinctive subsection title.

    Registry-derived (replaces the three hand-kept generic-heading sets). Generic =
    the synthetic sentinels ('other', 'Historical era'); any expansion-era label (bare expansion
    names — 'Cataclysm', 'Wrath of the Lich King', 'World of Warcraft', 'Vanilla'); any generic
    narrative container heading (narrative_kind history/background/overview/identity, e.g.
    'History', 'Lore', 'Background', 'Overview', 'Introduction'); and adaptation 'media' headings.
    A distinctive event/thematic title ('The Scourging', 'Battle for Andorhal') returns False so it
    can be used as a real section heading. Accepts display headings (spaces) or role slugs.
    """
    label = normalize_section_label(str(heading or "").replace(" ", "_"))
    if not label:
        return True
    if label in _GENERIC_HEADING_SENTINELS:
        return True
    # Expansion display names are stored with their leading article ("the_burning_crusade"); a
    # heading may drop it ("Burning Crusade"), so try both forms.
    variants = (label, label[4:]) if label.startswith("the_") else (label, f"the_{label}")
    for candidate in variants:
        cls = _lookup(candidate)
        if cls is None:
            continue
        if cls == "media":
            return True
        if cls == "narrative":
            entry = _labels().get(candidate)
            if isinstance(entry, dict):
                if str(entry.get("temporality") or "") == "expansion_era":
                    return True
                if str(entry.get("narrative_kind") or "") in _GENERIC_NARRATIVE_KINDS:
                    return True
    return False


def is_bare_history_container(section_role: str) -> bool:
    """True when the section's *own* label is a generic narrative container (History, Background,
    Overview, Introduction, Lead) rather than a distinctive subsection.

    Own-label only (no parent inheritance): a distinctive subsection ("The Scourging") is absent
    from the registry so it is not bare, while an expansion-era heading ("Cataclysm") names a
    specific era and is likewise not bare. Used to tell a reservable *named* history section apart
    from a bare container.
    """
    entry = _labels().get(normalize_section_label(section_role))
    if not isinstance(entry, dict):
        return False
    if entry.get("content_class") != "narrative":
        return False
    if entry.get("temporality") == "expansion_era":
        return False
    return str(entry.get("narrative_kind") or "") in _GENERIC_NARRATIVE_KINDS


@lru_cache(maxsize=1)
def expansion_era_labels() -> tuple[str, ...]:
    """Registry labels marked ``temporality: expansion_era`` (the expansion display-name home)."""
    return tuple(
        sorted(
            label
            for label, entry in _labels().items()
            if isinstance(entry, dict) and entry.get("temporality") == "expansion_era"
        )
    )


def expansion_era_display_names() -> tuple[str, ...]:
    """Expansion labels as spaced display text ('wrath_of_the_lich_king' -> 'wrath of the lich king')."""
    return tuple(label.replace("_", " ") for label in expansion_era_labels())
