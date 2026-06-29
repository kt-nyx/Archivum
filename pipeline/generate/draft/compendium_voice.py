"""Compendium Voice prompt fragments for wiki-first zone prose synthesis."""

from __future__ import annotations

COMPENDIUM_VOICE_CORE = (
    "Write in Compendium Voice: official in-universe lore description (like Blizzard zone reference copy). "
    "Treat the world as real. Moderate drama — clear stakes, readable prose, not walkthrough or wiki manual tone. "
    "Always reframe evidence into this voice; never copy source phrasing or adopt source tone. "
    "Named expansion eras (Cataclysm, Fourth War, etc.) are acceptable historical labels. "
    "Prefer era or event references over exact ADP/BDP year dates unless two close events in the same era need distinction. "
    "No player meta, reputation/achievement language, or quest walkthrough steps."
)

# Generation-time completeness guard for the short, budget-bounded fields (key-character summary,
# questline cta hook) where the model occasionally emits an incomplete final clause ending on a
# transitive verb that still expects its object ("...whose death can break.", "...and help keep.").
# Prevention, not detection: a post-hoc check cannot distinguish a transitive verb-final clause from
# a valid intransitive one ("the empire collapsed.", "the defenders could retreat.") without a verb
# lexicon, so a detector would reject good prose — this list-free mandate fixes it at the source.
COMPLETE_CLAUSE_MANDATE = (
    " End on a grammatically complete clause: never finish on a verb that still needs an object "
    "(avoid trailing fragments like '...can break.' or '...help keep.')."
)

# Tense discipline for the past-tense fields (at_a_glance, history). The model tends to default to
# gratuitous past-perfect ("had been a scarred remnant", "had been spared"). Past-perfect should mark
# anteriority between two past events, not serve as the baseline narrative tense.
SIMPLE_PAST_DISCIPLINE = (
    " Use simple past as the default (was, fell, became, rose); reserve past-perfect (had been, "
    "had fallen) only to mark an event that precedes another past event you also state."
)

AT_A_GLANCE_VOICE = (
    "Zone flavor caption. Past tense only. 1–2 sentences tracing historical identity before the player enters the current content. "
    "Do not describe present retail state — that belongs in currently. "
    'Example shape: "Once the breadbasket of Lordaeron, these lands were consumed by the Scourge..."'
    + SIMPLE_PAST_DISCIPLINE
)

CURRENTLY_VOICE = (
    "Zone flavor summary. Present tense only. Active conflict, recovery, or faction dynamics at the player's entry state. "
    "Capture the zone's overall present state — the principal factions, recovery efforts, and conflicts that define it now — "
    "rather than fixating on a single battle or questline. "
    "Do not restate the historical identity arc from at_a_glance. Name factions explicitly when describing conflict. "
    'Example shape: "The Argent Crusade and Cenarion Circle work to heal the blighted soil while Horde and Alliance forces contest..."'
)

HISTORY_VOICE = (
    "Reference-chronicle blend. Past tense only. 3–5 sentences (~60–120 words) per era section. "
    "Include factual name-checks (eras, key factions, places) and readable narrative flow. "
    'Example shape: "During the Third War, the Scourge under Arthas overran..., ending Lordaeron\'s hold..." '
    "Never use present-activity verbs (maintains, struggles, continues to hold) in historical bodies."
    + SIMPLE_PAST_DISCIPLINE
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
    "Instance story-context overview. Convey what this place IS and, in broad strokes, how it came "
    "to be that way — its essential identity, significance, and the stakes for those who enter. Keep "
    "it high-level: summarize the arc, do not chronicle it. Defer specific events and the detailed "
    "sequence to the history sections (name that corruption befell a place, not each disaster in "
    "turn). Readable in-universe prose, no walkthrough framing."
)

KEY_CHARACTER_VOICE = (
    "Key-character card. State who this figure is in-universe, why they are present in this setting, "
    "and their entry-state relationship to those who enter. Do not explain gameplay or narrative function. "
    "Characterize background, motive, and local role, not combat tactics or abilities." + COMPLETE_CLAUSE_MANDATE
)

INSTANCE_FACTION_VOICE = (
    "Faction role within this instance. Describe what this faction is and what it does here in "
    "the instance's story — its stake, allegiance, and aims. Name opposing factions when "
    "evidence supports it. No geography lists or out-of-instance plot."
)


QUESTLINE_CTA_VOICE = (
    "Questline card hook. One imperative sentence (max 35 words). Spoiler-light: stakes and invitation, "
    "not walkthrough steps or quest-by-quest spoilers. No zone-name filler, no meta, no achievement language. "
    "Do not repeat the arc title verbatim; do not copy evidence phrasing." + COMPLETE_CLAUSE_MANDATE
)


def instance_system_prompt(*, field_voice: str, task_lines: str) -> str:
    """Compose an instance synthesis system prompt.

    Mirrors ``zone_system_prompt`` but always prepends the shared
    ``NO_META_NO_PASSTHROUGH`` clause so every instance prose field carries identical
    anti-passthrough / anti-meta discipline.
    """
    return f"{COMPENDIUM_VOICE_CORE} {NO_META_NO_PASSTHROUGH} {field_voice} {task_lines}".strip()
