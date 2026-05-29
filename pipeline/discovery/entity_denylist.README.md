# entity_denylist.json

Manual **supplements** to the generated `world_registry.json`. Geography zones, continents, capitals, and instances are loaded from the registry at runtime.

Add entries here only when:

- The title is not present in `world_registry.json` after regeneration
- The title is a false-positive edge case (river, subregion, NPC, faction mis-link)
- You need a temporary override before the registry builder is updated

Regenerate the world registry:

```bash
uv run python scripts/build_world_registry.py --summary
```
