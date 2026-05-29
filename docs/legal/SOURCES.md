# Sources

## Canonical Source Policy (v1)

- Primary source class: `warcraft_wiki` (`https://warcraft.wiki.gg`).
- Ingestion method: MediaWiki `action=parse` for canonical article pages (`/wiki/...`).
- Stored provenance fields per source pointer: `source_id`, `locator`, `revision_id`, `excerpt_hash`.
- Retail-first filter policy is applied in deterministic discovery decisions.

## Transitional Compatibility

- Legacy `wowpedia` rows are still accepted for migration/test compatibility.
- Runtime target remains Warcraft Wiki-first; new production manifests should prefer `warcraft_wiki`.
