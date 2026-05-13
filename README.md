# WoW Lore Companion

Data-first repository for building a deterministic lore pipeline and compiling reviewed pilot content for the WoW addon runtime.

## Branch and release model

- `dev`: active integration branch for day-to-day development.
- `main`: stabilized integration branch after passing full checks.
- `release`: promoted release branch after candidate validation and sign-off.

Tag conventions:

- Candidate promotion tags: `candidate/vX.Y.Z`
- Release promotion tags: `release/vX.Y.Z`

Detailed policy lives in `docs/process/release_model.md`.

## Project map

- `addon/` - in-game runtime addon code.
- `schemas/v1/` - canonical JSON schema artifacts.
- `pipeline/` - authoring and validation pipeline code.
- `review/` - editorial review packs/redlines/decisions.
- `build/lua/` - compiler and generated Lua output.
- `tests/` - test suites and fixtures.
- `docs/legal/` - legal and attribution documentation.
- `artifacts/` - run/build evidence bundles and manifests.
- `.github/workflows/` - CI workflow definitions.

## Local bootstrap

1. Install dependencies and create a virtual environment:
   - `uv sync --group dev`
2. Run baseline checks:
   - `uv run ruff check .`
   - `uv run mypy pipeline`
   - `uv run pytest`

## Baseline CLI

- `uv run lore-pipeline --help`
- `uv run lore-pipeline health`
