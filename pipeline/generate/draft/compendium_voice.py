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


# Shared anti-passthrough / anti-meta clause for instance prose. Stronger than the core
# voice note: forbids verbatim source fragments AND every player-facing meta category.
NO_META_NO_PASSTHROUGH = (
    "Synthesize from the evidence in your own words — never copy source fragments, "
    "list bullets, or sentence shapes verbatim, and never start mid-sentence. "
    "Exclude all player-facing meta: loot, drops, quest walkthrough steps, achievements, "
    "patch notes, reputation/grind language, dungeon-journal tactics, difficulty modes, "
    "and encounter mechanics or boss ability descriptions."
)

INSTANCE_AT_A_GLANCE_VOICE = (
    "Instance identity caption. 1–2 sentences naming what this place is and why it matters "
    "in the world. State its nature and significance, not its mechanics. "
    'Example shape: "Carved into the roots of the World Tree, this sanctum guards the '
    'secrets the night elves would not surrender."'
)

INSTANCE_OVERVIEW_VOICE = (
    "Instance story-context overview. Explain the narrative significance, stakes, and the "
    "world-events that make this place matter. Trace why adventurers come here and what hangs "
    "in the balance — not how to clear it. Readable in-universe prose, no walkthrough framing."
)

KEY_CHARACTER_VOICE = (
    "Key-character card. State who this figure is and their role within the instance's story — "
    "whether they oppose, aid, or stand neutral toward those who enter, and why they matter. "
    "Characterize motive and significance, not combat tactics or abilities."
)

INSTANCE_FACTION_VOICE = (
    "Faction role within this instance. Describe what this faction is and what it does here in "
    "the instance's story — its stake, allegiance, and aims. Name opposing factions when "
    "evidence supports it. No geography lists or out-of-instance plot."
)


QUESTLINE_CTA_VOICE = (
    "Questline card hook. One imperative sentence (max 35 words). Spoiler-light: stakes and invitation, "
    "not walkthrough steps or quest-by-quest spoilers. No zone-name filler, no meta, no achievement language. "
    "Do not repeat the arc title verbatim; do not copy evidence phrasing."
)

def instance_system_prompt(*, field_voice: str, task_lines: str) -> str:
    """Compose an instance synthesis system prompt.

    Mirrors ``zone_system_prompt`` but always prepends the shared
    ``NO_META_NO_PASSTHROUGH`` clause so every instance prose field carries identical
    anti-passthrough / anti-meta discipline.
    """
    return f"{COMPENDIUM_VOICE_CORE} {NO_META_NO_PASSTHROUGH} {field_voice} {task_lines}".strip()
