# world_registry.json — review guide

Generated from Warcraft Wiki via `scripts/build_world_registry.py`. **Do not edit by hand** — regenerate when taxonomy drifts.

## Regenerate

```bash
uv run python scripts/build_world_registry.py --summary
```

The builder writes a resumable fetch cache at `pipeline/discovery/.world_registry_category_cache.json` so interrupted runs can continue without re-fetching completed categories. Use `--no-cache` to rebuild from scratch.

## Current snapshot

| Kind | Count | Used for |
|------|------:|----------|
| zone | ~321 | Block as quest nodes; block quest/faction traversal |
| instance | ~265 | Block as quest nodes; allow manifest instance traversal |
| continent | ~15 | Block as quest/location traversal |
| capital | ~14 | Block quest traversal; block location_profile fetch |
| place | ~7600 | Subzone pages + lore locations; block quest traversal only |
| person | ~1967 | Lore characters + NPCs; block quest traversal only |

The registry is an optional positive source signal. Missing coverage never
classifies a link as a place; target-page categories and infobox structure can
provide the required affirmative evidence instead.

## Pilot-relevant entries (verify)

| Title | Expected kinds | Notes |
|-------|----------------|-------|
| Western Plaguelands | zone | |
| Eastern Plaguelands | zone | |
| Scholomance | instance, place | Manifest instance still fetched via ingest/allowlist |
| Andorhal | place | Allowed for location_profile; blocked for quest |
| Hearthglen | place | |
| Lordaeron | continent | |
| Ironforge | capital | |
| Hinterlands | zone | |
| High General Abbendis | person | Blocked for quest traversal |

## Known noise to prune in builder (optional follow-up)

Some auto-classified rows are meta or low-value (e.g. `Deadmines walkthrough`, `Delves`, PvP maps). They still safely block quest-graph pollution. Tighten `_should_skip_registry_title` / instance heuristics if these cause false positives.

## Traversal behavior (contextual)

| auxiliary_role | Skips registry kinds |
|----------------|-------------------|
| quest | zone, continent, capital, region, instance, **person, place** |
| faction_profile | zone, continent, instance |
| location_profile | zone, continent, instance (capitals too) |
| storyline | *(none — storyline URLs always attempted)* |
| instance_lore | zone, continent, capital, region |

**Allowlist:** instance names on the run manifest (`entity_type=instance`) may still be fetched for `location_profile` / `instance_lore` even when classified as instances.
