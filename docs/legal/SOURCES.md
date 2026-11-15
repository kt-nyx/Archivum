# Sources and attribution

## Warcraft Wiki

[Warcraft Wiki](https://warcraft.wiki.gg) is the primary source for retail lore and the preferred source for new manifests (`warcraft_wiki`). The pipeline uses the MediaWiki parse endpoint for canonical articles. It uses article facts for discovery and evidence-bound original writing. Legacy `wowpedia` manifests remain supported for migration and tests.

Keep attribution in the project documentation and maintain source pointers in generated data with `source_id`, `locator`, `revision_id`, and `excerpt_hash`. The in-game design provides a copyable canonical article URL on the page and reference cards. Verify those links once the runtime loads generated data.

## Distribution

Current bundles contain JSON/text payloads and navigation indexes. They ship without external binary assets. Any future third-party asset needs license metadata, a source pointer, a reference URL showing permitted use, and a recorded reason for including it.

Confirm the required credit and distribution terms for the actual shipped material before release. A finalized player-facing disclaimer and distribution notices are still pending. See the [content policy](CONTENT_POLICY.md) for writing and evidence rules.
