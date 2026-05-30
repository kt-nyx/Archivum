"""Compendium Voice prompt fragments for wiki-first zone prose synthesis."""

from __future__ import annotations

COMPENDIUM_VOICE_CORE = (
    "Write in Compendium Voice: official in-universe lore description (like Blizzard zone reference copy). "
    "Treat the world as real. Moderate drama — clear stakes, readable prose, not walkthrough or wiki manual tone. "
    "Always reframe evidence into this voice; never copy source phrasing or adopt source tone. "
    "Named expansion eras (Cataclysm, Fourth War, etc.) are acceptable historical labels. "
    "No player meta, reputation/achievement language, or quest walkthrough steps."
)

AT_A_GLANCE_VOICE = (
    "Zone flavor caption. Past tense only. 1–2 sentences tracing historical identity through the latest era in evidence. "
    "Do not describe present retail state — that belongs in currently. "
    'Example shape: "Once the breadbasket of Lordaeron, these lands were consumed by the Scourge..."'
)

CURRENTLY_VOICE = (
    "Zone flavor summary. Present tense only. Active conflict, recovery, or faction dynamics at the latest era. "
    "Do not restate the historical identity arc from at_a_glance. Name factions explicitly when describing conflict. "
    'Example shape: "The Argent Crusade and Cenarion Circle work to heal the blighted soil while Horde and Alliance forces contest..."'
)

HISTORY_VOICE = (
    "Reference-chronicle blend. Past tense only. 3–5 sentences (~60–120 words) per era section. "
    "Include factual name-checks (eras, key factions, places) and readable narrative flow. "
    'Example shape: "During the Third War, the Scourge under Arthas overran..., ending Lordaeron\'s hold..." '
    "Never use present-activity verbs (maintains, struggles, continues to hold) in historical bodies."
)


def zone_system_prompt(*, field_voice: str, task_lines: str) -> str:
    """Compose a zone-core synthesis system prompt from Compendium Voice fragments."""
    return f"{COMPENDIUM_VOICE_CORE} {field_voice} {task_lines}".strip()
