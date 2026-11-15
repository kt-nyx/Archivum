# Pipeline and development

The pipeline runs outside the game. It turns wiki pages into structured lore drafts and exports a JSON data bundle. The addon still needs a build step or loader to make that data available to its Lua code.

## Local setup

Use Python 3.12 or later and `uv`. Install the locked dependencies with `uv sync --group dev --frozen`. The language analysis library and its English model are pinned together in [pyproject.toml](../pyproject.toml).

```sh
uv run ruff check pipeline scripts tests .vscode/run-incrementing-pipeline.py
uv run mypy pipeline
uv run python -m pytest
uv run archivum-pipeline --help
```

For a live run, copy [the environment template](../.env.example) to `.env` and configure the authoring provider. Shell variables take precedence. `uv run archivum-pipeline health` reports configuration readiness without printing credentials. The command checks local settings. Use a live run to verify service access.

- `OPENAI_MODEL` controls the authoring model. The fact-check model has its own CLI option, `--fact-check-llm-model`.
- `OPENAI_REASONING_EFFORT`, `OPENAI_VERBOSITY`, and their draft overrides adjust the calls. Leave `OPENAI_TEMPERATURE` unset unless the model supports it. `OPENAI_TIMEOUT_SECONDS` controls the request read timeout.
- `OPENAI_USE_RESPONSES_API=1` enables the draft client's Responses API path with a Chat Completions fallback. The current defaults and supported options are in [the template](../.env.example) and [provider configuration](../pipeline/ai/config.py).
- Google Custom Search is optional external evidence for fact-checking. It needs `GOOGLE_API_KEY`, `GOOGLE_CSE_ID`, and `--fact-check-web-search`. Tests normally skip dotenv loading.

## From sources to bundle

1. **Ingest and identify.** Start with `source_manifest.json` in the run folder. Ingest captures article snapshots with page text, section roles, links, and classification signals. Discovery resolves identities and follows relevant links under the retail scope. Coalesce combines source claims and writes fact packs.
2. **Enrich and select.** Discover quests and their relationships, locations, instance cast, and factions. Shared rules use evidence such as categories, infoboxes, section roles, containment, and encounter membership. The model may adjudicate ambiguous evidence within those rules. The questline selector groups related candidates into story arcs and stores structured title and variant metadata. Selected cards get evidence packs with direct evidence of their identity.
3. **Write and link.** Draft writers turn field-specific evidence into original, time-aware page prose. Trace records explain accepted, retried, or skipped fields. When live synthesis runs out of supported material, it can leave the field absent with a recorded explanation. Glossary references come from the run and the linker checks their targets.
4. **Check and export.** Validation checks the page schema, structure, budget, source pointers, similarity to source wording, and fact-check results. Release-gated validation also checks selection evidence and required coverage. The bundle stage exports page JSON, lookup tables, and navigation under `build/lua` in the run directory. The flow can write this diagnostic bundle even when validation fails.

The [orchestrator](../pipeline/orchestrator/flow.py) defines stage order. [Python models](../pipeline/contracts/models.py) and [exported schemas](../schemas/v1) describe the generated records. [Decision files](../pipeline/generate/draft/card_evidence_pack.py) record the evidence and reasons behind selections. When changing these contracts, update the producers and readers together. Keep internal traces outside the player-facing page format.

## Inspect a run

See [evaluation](../evaluation/README.md) for the manifest-driven commands. The default run root is `artifacts/runs/<run-id>` at the repository root. `WOW_LORE_ARTIFACTS_ROOT` changes the parent directory. Keep historical runs intact and use fresh IDs for comparisons.

| Path inside a run | What it explains |
| --- | --- |
| `source_manifest.json`, `data/ingest/` | Starting sources and fetched evidence |
| `data/discovery/`, `data/decisions/` | Candidates, related quest arcs, selection reasons, rejected candidates, and drafting decisions |
| `data/drafts/` | Final structured pages and source pointers |
| `reports/validate/` | Validation outcomes and per-claim judgments |
| `reports/run_quality_summary.json` | Shared comparison of coverage, lint, release status, input hashes, and recorded model or schema identifiers |
| `build/lua/` | JSON bundle and navigation index, plus the validation report |

`off` skips fact-checking, `warn` reports issues for exploration, and `strict` blocks contradictions and unsupported central claims. In warn or strict mode, validation can adjudicate unresolved claims across drafted pages against the available source snippets. The separate semantic checker inspects saved outputs for cross-file consistency and player-facing issues. Treat `release_certified: true`, the strict semantic report, and a short editorial review as distinct evidence. An automated pass cannot tell whether the page is useful and complete from a player's point of view.

## Branches and release

Develop from `dev` and open pull requests back into it. The fast GitHub workflow runs the lint, typing, and test commands above. The repository uses protected `dev`, `main`, and `release` branches with review required.

The intended release flow promotes reviewed integration to `main`, marks a tested candidate with `candidate/vX.Y.Z`, and marks the signed-off production build on `release` with `release/vX.Y.Z`. Before promotion, use comparable strict runs, editorial sign-off, an actual Retail client smoke test, and finished [attribution and publishing notices](legal/SOURCES.md).
