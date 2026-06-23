"""Content-role taxonomy for provenance locators (Option A).

Historically the discovery-stage ``section_role`` enum (``maps_subregions``,
``instances_or_dungeons``, ``quests_or_storyline``, ``notable_characters``,
``history`` ...) did double duty: it routed wiki links to output buckets during
discovery *and* was stamped into provenance locators (``section:{role} ...``).
Those are two different axes. Routing answers "what kind of entities does this
section list"; provenance answers "what kind of source prose did this snippet
come from". Reusing the routing enum under-resolved provenance — narrative
subsections like "Background" or "The Scourging" collapsed to ``other``.

``content_role`` is the dedicated provenance taxonomy. It is derived from the
raw wiki section header (``raw_section_role``), with parent-section inheritance,
falling back to the routing enum only when the header is uninformative. The
discovery routing field (``section_role``) is left untouched and keeps its own
vocabulary, so the two concerns can now evolve independently.
"""

from __future__ import annotations

CONTENT_ROLES: tuple[str, ...] = (
    "lead",
    "lore_history",
    "description",
    "mechanics",
    "quest_text",
    "in_the_rpg",
    "other",
)

# Exact raw-header slugs that denote a page's lead/identity prose.
_LEAD_SLUGS: frozenset[str] = frozenset({"lead", "introduction", "intro"})

# Ordered (role, substring-patterns) pairs, scanned highest-priority first so a
# header carrying multiple signals resolves deterministically (e.g. a
# "Background and history" slug resolves to ``lore_history`` before
# ``description``).
_CONTENT_ROLE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    # quest_text is scanned before lore_history so "storyline"/"questline" win
    # over the bare "story" narrative marker; a section literally named "Story"
    # carries no quest token and still resolves to lore_history below.
    (
        "quest_text",
        ("quest", "storyline", "questline", "objective", "walkthrough", "campaign"),
    ),
    (
        "lore_history",
        (
            "history",
            "lore",
            "background",
            "story",
            "origin",
            "creation",
            "legacy",
            "scourging",
            "cataclysm",
            "aftermath",
            "timeline",
            "the_past",
        ),
    ),
    (
        "mechanics",
        (
            "boss",
            "encounter",
            "adventure_guide",
            "dungeon_journal",
            "journal",
            "abilit",
            "strateg",
            "tactic",
            "denizen",
            "loot",
            "trash",
            "mechanic",
        ),
    ),
    (
        "description",
        (
            "overview",
            "summary",
            "description",
            "about",
            "geography",
            "subregion",
            "sub-region",
            "maps",
            "notable",
            "character",
            "npc",
            "inhabitant",
        ),
    ),
)

# Fallback used only when the raw header is uninformative: map the legacy
# routing enum to its closest content kind.
_ROUTING_TO_CONTENT: dict[str, str] = {
    "history": "lore_history",
    "quests_or_storyline": "quest_text",
    "instances_or_dungeons": "description",
    "maps_subregions": "description",
    "notable_characters": "description",
    "in_the_rpg": "in_the_rpg",
}


def _normalize_slug(value: str) -> str:
    lowered = str(value or "").strip().lower()
    if lowered.endswith("_edit"):
        lowered = lowered[: -len("_edit")]
    return lowered.strip("_")


def _match_slug(slug: str) -> str | None:
    if not slug:
        return None
    if slug in _LEAD_SLUGS:
        return "lead"
    for role, patterns in _CONTENT_ROLE_PATTERNS:
        if any(pattern in slug for pattern in patterns):
            return role
    return None


def classify_content_role(
    raw_section_role: str,
    section_role: str = "other",
    parent_section_role: str = "",
) -> str:
    """Resolve the provenance ``content_role`` for a source block.

    Args:
        raw_section_role: The normalized wiki section header the snippet came
            from (e.g. ``"background"``, ``"the_scourging"``, ``"lead"``).
        section_role: The legacy discovery routing enum, used only as a fallback
            when the raw header is uninformative.
        parent_section_role: The enclosing top-level section header, used so an
            unrecognized leaf subsection inherits its parent's content kind
            (mirrors the discovery Fix B parent-inheritance behaviour).

    Returns:
        One of :data:`CONTENT_ROLES`.
    """
    raw = _normalize_slug(raw_section_role)
    parent = _normalize_slug(parent_section_role)
    routing = _normalize_slug(section_role)

    if raw.startswith("in_the_rpg") or parent.startswith("in_the_rpg") or routing == "in_the_rpg":
        return "in_the_rpg"

    role = _match_slug(raw)
    if role is None and parent:
        role = _match_slug(parent)
    if role is not None:
        return role

    return _ROUTING_TO_CONTENT.get(routing, "other")
