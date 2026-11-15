# Addon Data Bundle

The bundle stage writes JSON under `artifacts/runs/<run-id>/build/lua/`. The Lua runtime data loader and packaging step are pending.

- `manifest.json` tracks schema version and counts.
- `zones/` contains zone page payloads.
- `instances/` contains instance page payloads.
- `lookup/` contains location cards and glossary references.
- `nav/index.json` contains zone-to-instance edges.

See the [development guide](../../docs/development.md#from-sources-to-bundle) for the authoring flow and validation reports.
