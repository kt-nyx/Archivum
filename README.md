# Archivum

Archivum is a work-in-progress lore companion for retail World of Warcraft. It aims to give players quick, spoiler-light context for a zone or dungeon while they play. The authoring tools gather evidence from Warcraft Wiki, write and check lore pages, and export data for the addon.

- [Project status](docs/status.md) covers what shipped to Git, what the saved runs showed, and where development stopped.
- [Product and MVP](docs/product.md) records the experience, design decisions, and recommended next steps.
- [Pipeline and development](docs/development.md) explains how to run, inspect, and promote changes.
- [Evaluation](evaluation/README.md) has the three test subjects and commands for a comparable live run.
- [Sources and attribution](docs/legal/SOURCES.md) and [content policy](docs/legal/CONTENT_POLICY.md) record the publishing rules.
- [Planning archive](docs/archive/README.md) points to the original technical and product decisions.

## Start locally

```sh
uv sync --group dev --frozen
uv run archivum-pipeline --help
uv run python -m pytest
```

The tests run without live credentials. See the [development guide](docs/development.md) for local configuration and the live-run steps.
