# Archivum

Archivum is a World of Warcraft lore addon and its supporting authoring pipeline.

This public repository contains the in-game addon, deterministic wiki-first discovery and
authoring pipeline, schemas, validation rules, and tests used to compile zone and instance pages.
Personal development orchestration and generated run artifacts are intentionally excluded.

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

## Local bootstrap

1. Install dependencies and create a virtual environment:
   - `uv sync --group dev`
2. Optional: copy `.env.example` to `.env` in the repo root and set API keys. On first `load_ai_settings()` (for example via `archivum-pipeline health`), variables from `.env` are merged into the process environment; values already set in the shell or container take precedence over the file.
3. Run baseline checks:
   - `uv run ruff check .`
   - `uv run mypy pipeline`
   - `uv run pytest`

## Baseline CLI

- `uv run archivum-pipeline --help`
- `uv run archivum-pipeline health`
- `uv run archivum-pipeline ingest`
- `uv run archivum-pipeline run --fact-check-profile warn`

### Manifest prerequisite (MP3)

`ingest` and `run` are manifest-driven and require a run-root `source_manifest.json`.

Run folders default to **`<repository_root>/artifacts/runs/<run_id>/`**, where *repository root* is the directory that contains the `pipeline` package (not the shell’s current working directory). Override with **`WOW_LORE_ARTIFACTS_ROOT`** if your artifact layout should live elsewhere.

Minimal local flow:

1. Create a run root and seed manifest:
   - `uv run python -c "from pipeline.common.run_context import ensure_run_context; c=ensure_run_context('run-local-mp3'); print(c.root_dir)"`
   - Copy or author `<run_root>/source_manifest.json` (see `tests/fixtures/pilot/source_manifest.json` for shape).
2. Execute pipeline against that run id:
   - `uv run archivum-pipeline ingest --run-id run-local-mp3`
   - `uv run archivum-pipeline run --run-id run-local-mp3 --fact-check-profile warn`

### Generalization acceptance

Run each candidate zone through the same release and semantic checks. No zone has a curated
output override or exact-output promotion gate; differences are reviewed from source evidence.
Use `--release-gate` so pipeline `validate_passed` matches `check_run_semantics.py --strict`.

Questline discovery writes `data/discovery/questline_arc_selection.json` as a versioned,
family-first contract. It records component candidates, structured campaign signals, deterministic
merge/split decisions, ranked families, variant selections/exclusions, and bounded coverage.
Selected cards then use `questline_card_metadata.v2`: identity is stored as `base_title`, optional
faction/phase variants, and canonical id; the page renderer formats that title once.

### Wiki ingest (MediaWiki)

`pipeline/ingest/fetch_wiki.py` uses MediaWiki `api.php?action=parse` for canonical article paths (`/wiki/...`) and now captures:

- normalized page text
- section-role blocks
- outbound wiki links

Current policy target is Warcraft Wiki-first ingestion (`warcraft_wiki`). Legacy wowpedia fixtures remain supported for compatibility in tests and migration runs.

## Wiki-first pipeline stages

End-to-end run now includes discovery-first artifacts before writing:

1. `ingest` -> snapshots + normalized source manifest
2. `coalesce` -> coalesced entity claims
3. `discovery` -> deterministic registries, classification, decisions, evidence packs
4. `extract` -> fact packs
5. `draft` -> evidence-pack-fed zone/instance page outputs
6. `linker` -> glossary link QA
7. `validate` -> schema + policy checks
8. `addon_bundle` -> addon-ingestible data pack under run build outputs

Additional stage commands:

- `uv run archivum-pipeline discovery --run-id <run_id>`
- `uv run archivum-pipeline addon-bundle --run-id <run_id>`

Optional external fact-check uses Google Custom Search and OpenAI adjudication.

Global provider defaults for AI-enabled stages (set in the environment or in a repo-root `.env`; see `.env.example`):

- `AI_PROVIDER` (default `openai`)
- `OPENAI_MODEL` (default `gpt-5.5`)
- `OPENAI_BASE_URL` (optional, defaults to OpenAI public API)
- `OPENAI_TEMPERATURE` — optional; **omit for GPT‑5.x** unless the model supports custom sampling (many only accept the API default). For `gpt-4*` style models you can set `0` for more deterministic outputs.
- `OPENAI_REASONING_EFFORT` — optional Chat Completions field for reasoning models (`none`, `minimal`, `low`, `medium`, `high`, `xhigh`). Example: `low` for faster/cheaper coalesce and draft passes when quality is acceptable.
- `OPENAI_VERBOSITY` — optional: `low`, `medium`, or `high` (shorter vs longer answers).
- `OPENAI_TIMEOUT_SECONDS` — optional HTTP timeout for each completion (default **600**; large `json_schema` drafts and reasoning models often need several minutes).
- `OPENAI_DRAFT_REASONING_EFFORT` / `OPENAI_DRAFT_VERBOSITY` — optional overrides for draft substeps (fall back to `OPENAI_REASONING_EFFORT` / `OPENAI_VERBOSITY`).
- `OPENAI_USE_RESPONSES_API` — set to `1` to route draft LLM calls through the Responses API (falls back to Chat Completions on HTTP errors).
- `WOW_LORE_DRAFT_MODE` — `staged` (default) runs plan → parallel workers → stitch for zone/sub-zone; `legacy` uses one monolithic call per entity.
- `WOW_LORE_DRAFT_MAX_QUESTLINES_PER_BUCKET`, `WOW_LORE_DRAFT_MAX_STORY_BEATS`, `WOW_LORE_DRAFT_MAX_LINK_CARDS`, `WOW_LORE_DRAFT_MAX_GLOSSARY_TERMS` — post-LLM output caps.
- `WOW_LORE_DOTENV` — set to `0` / `false` / `no` / `off` to skip loading `.env` (tests default to skipping `.env` unless you export `WOW_LORE_DOTENV=1`)

Use **`uv run archivum-pipeline run ... --verbose`** (or **`-v`**) to print each pipeline stage (and draft substep) start/finish to stderr while Prefect runs.

**Staged draft flow (zone / sub-zone):** fact pack → structure plan (`_plans/`) → parallel prose / questline / links workers → stitch → canonical JSON + `draft_llm_trace.jsonl`.

**GPT‑5.5 vs older defaults:** This repo targets **Chat Completions** with **structured outputs** (`json_schema` / `json_object`). That matches GPT‑5.5, but differs from older `gpt-4.1-mini` assumptions in ways we handle in code: (1) do not send `temperature` unless you opt in via `OPENAI_TEMPERATURE`; (2) strict `json_schema` requires **`additionalProperties: false` on every object** and only [supported schema keywords](https://platform.openai.com/docs/guides/structured-outputs#supported-schemas) (for example, avoid `minItems` / `maxItems` on arrays, and avoid open-ended maps—draft questlines use a `criteria_breakdown` array of `{criterion, score}` rows, then normalize to a dict for contracts). OpenAI recommends the **Responses API** for the richest reasoning-model behavior; migrating the HTTP client would be a larger change.

- Google:
  - `GOOGLE_API_KEY`
  - `GOOGLE_CSE_ID`
- OpenAI:
  - `OPENAI_API_KEY`

Example:

- `uv run archivum-pipeline health --json-output`
- `uv run archivum-pipeline run --fact-check-profile warn --fact-check-web-search`
- `uv run archivum-pipeline run --fact-check-profile strict --fact-check-web-search`
- `uv run archivum-pipeline run --run-id my-run --fact-check-profile off -v`
