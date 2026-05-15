# WoW Lore Companion

Data-first repository for building an LLM-first lore pipeline and compiling reviewed pilot content for the WoW addon runtime.

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
2. Optional: copy `.env.example` to `.env` in the repo root and set API keys. On first `load_ai_settings()` (for example via `lore-pipeline health`), variables from `.env` are merged into the process environment; values already set in the shell or container take precedence over the file.
3. Run baseline checks:
   - `uv run ruff check .`
   - `uv run mypy pipeline`
   - `uv run pytest`

## Baseline CLI

- `uv run lore-pipeline --help`
- `uv run lore-pipeline health`
- `uv run lore-pipeline ingest`
- `uv run lore-pipeline run --fact-check-profile warn`

### Manifest prerequisite (MP3)

`ingest` and `run` are manifest-driven and require a run-root `source_manifest.json`.

Minimal local flow:

1. Create a run root and seed manifest:
   - `uv run python -c "from pipeline.common.run_context import ensure_run_context; c=ensure_run_context('run-local-mp3'); print(c.root_dir)"`
   - Copy or author `<run_root>/source_manifest.json` (see `tests/fixtures/pilot/source_manifest.json` for shape).
2. Execute pipeline against that run id:
   - `uv run lore-pipeline ingest --run-id run-local-mp3`
   - `uv run lore-pipeline run --run-id run-local-mp3 --fact-check-profile warn`

## Fact-check providers

Optional external fact-check uses Google Custom Search and OpenAI adjudication.

Global provider defaults for AI-enabled stages (set in the environment or in a repo-root `.env`; see `.env.example`):

- `AI_PROVIDER` (default `openai`)
- `OPENAI_MODEL` (default `gpt-4.1-mini`)
- `OPENAI_BASE_URL` (optional, defaults to OpenAI public API)
- `WOW_LORE_DOTENV` — set to `0` / `false` / `no` / `off` to skip loading `.env` (tests default to skipping `.env` unless you export `WOW_LORE_DOTENV=1`)

- Google:
  - `GOOGLE_API_KEY`
  - `GOOGLE_CSE_ID`
- OpenAI:
  - `OPENAI_API_KEY`

Example:

- `uv run lore-pipeline health --json-output`
- `uv run lore-pipeline run --fact-check-profile warn --fact-check-web-search`
- `uv run lore-pipeline run --fact-check-profile strict --fact-check-web-search`
- `uv run lore-pipeline run --fact-check-profile strict --no-llm-fact-check` (explicit local/dev override only)
