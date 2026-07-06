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

# Tense discipline for the past-tense fields (history sections). The model tends to default to
# gratuitous past-perfect ("had been a scarred remnant", "had been spared"). Past-perfect should mark
# anteriority between two past events, not serve as the baseline narrative tense.
SIMPLE_PAST_DISCIPLINE = (
    " Use simple past as the default (was, fell, became, rose); reserve past-perfect (had been, "
    "had fallen) only to mark an event that precedes another past event you also state."
)

AT_A_GLANCE_VOICE = (
    "Zone essence caption: one or two short, punchy sentences (about 25–45 words total) that land the "
    "atmosphere and vibe of the place — what it FEELS like to stand here. Be direct: lead with a plain, "
    "concrete declarative line and let strong nouns and verbs carry the mood instead of stacked "
    "adjectives. Hit hard and stop — this is a caption, not a paragraph. "
    "Stay on essence, not events: this is NOT a report of who is fighting, holding, defending, or "
    "recovering the zone right now (that belongs in 'currently'), and NOT a roster of towns, keeps, or "
    "landmarks (those belong in the location cards). Do not name leaders or characters. You may evoke "
    "the defining force whose legacy still hangs over the land (e.g. the Hollow Court's blight) as part "
    "of the atmosphere, but only as mood and legacy, never as an actor doing something now. "
    "Keep it present and timeless; carry history through scarring/legacy phrasing rather than a "
    "play-by-play. Do NOT narrate the past with finite past-tense verbs (avoid 'the Hollow Court "
    "invaded', 'the farms fell', 'it was consumed'). "
    'Example shape: "The Hollow Court is gone, but its blight is not. Across fallen Vellmire\'s '
    "heartland, poisoned fields and silent ruins still ache with rot — even as the first green pushes "
    "back through the dead soil.\""
)

CURRENTLY_VOICE = (
    "Zone flavor summary. Present tense only. Active conflict, recovery, or faction dynamics at the player's entry state. "
    "Capture the zone's overall present state — the principal factions, recovery efforts, and conflicts that define it now — "
    "rather than fixating on a single battle or questline. "
    "Favor short, direct sentences; let strong verbs carry the tension rather than stacked adjectives. "
    "Do not restate the historical identity arc from at_a_glance. Name factions explicitly when describing conflict. "
    'Example shape: "The Lantern Wardens and the Emberwake Pact work to heal the blighted soil while Horde and Alliance forces contest..."'
)

HISTORY_VOICE = (
    "Encyclopedic reference voice. Past tense by default. 3–5 sentences (~60–120 words) per era "
    "section. "
    "Write like a neutral lore encyclopedia entry: state plainly and in order what happened, with "
    "factual name-checks (eras, key factions, places). Be thorough: include the relevant particulars "
    "and the connections between events, and combine closely related facts into fuller, flowing "
    "sentences rather than clipped, one-fact statements — plain and factual does not mean terse. Aim "
    "for the upper end of the length range when the evidence supports it. Do not dramatize — avoid "
    "literary flourishes, mood-setting adjectives, and reflective 'what it all meant' summations. Let "
    "each section end on its last concrete fact rather than a thematic closing flourish. "
    'Example shape: "During the Breaking of Vellmire, the magister Ordan Veil bound curse energies '
    "into portable reliquaries and tasked Archivist Maelor with hiding them in court-controlled "
    "villages. The Hollow Court tainted grain from Maelor's Crossing and positioned four large "
    'reliquaries among the region\'s major farmsteads." '
    "Never use present-activity verbs (maintains, struggles, continues to hold) in the past-tense "
    "background sections. One exception: if the final section is the present-state bridge — the "
    "chronicle reaching the zone's current, ongoing condition as it currently stands in the content "
    "(the state the content presents, not the latest point in the wider timeline) — write that "
    "one section in present tense, while every earlier background section stays past tense and any "
    "reference to a finished past event stays past tense even within it. "
    "Stay in-world throughout: describe the present state of the place itself, never framed by "
    "'the player' / 'adventurers' arriving and never in second person ('you', 'your')."
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
    "Instance identity caption: one or two short, punchy sentences (roughly 15–40 words) that land what "
    "this place is and why it matters — fast. Be direct: lead with a plain-spoken declarative line and "
    "let strong nouns and verbs carry the weight instead of stacked adjectives. State its nature and "
    "significance, not its mechanics; do not list bosses, wings, or factions. Hit hard and stop. "
    'Example shape: "The Archive Vault is the Hollow Court\'s school for curse-binders. Built into '
    "the bones of House Veldar above drowned Maelor's Crossing, it turns out masters of forbidden "
    "script — and rarely lets its dead rest.\""
)

INSTANCE_OVERVIEW_VOICE = (
    "Instance story-context overview: an encyclopaedic account of what this place IS and, in broad "
    "strokes, how it came to be that way — its essential identity, who holds it and to what end, and "
    "the stakes for those who enter. Lead with the concrete and stay informative: name the place's "
    "nature, its masters, and the purpose it now serves, and make every sentence carry a fact the "
    "reader did not already have. Keep it high-level — capture the overall arc rather than chronicling "
    "specific events in sequence (name that corruption befell a place, not each disaster in turn); "
    "that granular history belongs in the history sections. Write plainly and directly, letting "
    "strong, specific nouns and verbs do the work; evoke atmosphere through what is concretely true, "
    "not through mood-setting for its own sake. Avoid purple flourishes, ornate epithets, and hollow "
    "framing sentences that restate the mood without adding information (e.g. 'to enter is to step "
    "into the lingering shadow of a ruin that should have been reclaimed'). A full paragraph, but "
    "every clause earns its place. Readable in-universe prose, no walkthrough framing."
)

KEY_CHARACTER_VOICE = (
    "Key-character card: a compact in-universe biography of this figure, 1–4 sentences. Lead by "
    "describing who they are — their background, nature, and what defines them in the world — then "
    "follow the through-line that explains why they are present here now: the history, motivations, "
    "or allegiances that brought them to this place and define their role in it. Tell it in "
    "chronological order (origin first, then how they came to be here); do not open on the in-place "
    "moment and back-fill. Prioritize the "
    "details that lead to their presence here (what they want, who wronged them, what they came to do) "
    "over unrelated later-life events, honors, or offices they hold elsewhere. Spend more sentences on "
    "a figure whose relevant history is rich and let a minor figure stay to one or two — never pad. "
    "Use plain, grounded language: state what happened directly. Avoid ornate epithets, poetic "
    "metaphors, and purple flourishes (e.g. 'death-touched daughter of…', 'the afterlife of a house "
    "that bartered away its soul'). "
    "Treat the world as real; do not explain gameplay, narrative function, combat tactics, or "
    "abilities." + COMPLETE_CLAUSE_MANDATE
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
