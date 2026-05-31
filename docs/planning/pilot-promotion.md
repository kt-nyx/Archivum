# Pilot promotion checklist (Western Plaguelands)

Dual-run flow for dev iteration and CI promotion. Pilot input manifest lives at
`tests/fixtures/pilot/source_manifest.json`; run artifacts stay local under
`artifacts/runs/<run-id>/` (gitignored).

## Bootstrap (once per machine)

```bash
uv run python -c "from pipeline.common.run_context import ensure_run_context; ensure_run_context('test-run-wpl-1')"
uv run python -c "from pipeline.common.run_context import ensure_run_context; ensure_run_context('run-western-plaguelands')"

cp tests/fixtures/pilot/source_manifest.json artifacts/runs/test-run-wpl-1/source_manifest.json
cp tests/fixtures/pilot/source_manifest.json artifacts/runs/run-western-plaguelands/source_manifest.json
```

## Dev gate — `test-run-wpl-1`

Iterate without release gate (WARN pointer caps allowed):

```bash
uv run lore-pipeline run --run-id test-run-wpl-1 --fact-check-profile off -v
uv run python scripts/check_run_semantics.py artifacts/runs/test-run-wpl-1
uv run python scripts/check_run_semantics.py artifacts/runs/test-run-wpl-1 --strict
```

Fast validate-only loop (skip LLM draft re-run):

```bash
uv run lore-pipeline validate --run-id test-run-wpl-1 --fact-check-profile off --release-gate
uv run python scripts/check_run_semantics.py artifacts/runs/test-run-wpl-1 --strict
```

Final dev sign-off (pipeline validate must match `--strict`):

```bash
uv run lore-pipeline run --run-id test-run-wpl-1 --fact-check-profile off --release-gate -v
```

**Green criteria**

- `validation_report.json` → `"passed": true` for all entity reports
- `check_run_semantics.py` PASS (zone + instance + glossary)
- `check_run_semantics.py --strict` PASS (release gate + fact-check off parity)
- Qualitative spot-check vs canvas golden examples (parent_continent, questlines, locations, Scholomance key_enemies)

## CI promotion — `run-western-plaguelands`

After dev gate is green:

```bash
uv run lore-pipeline run --run-id run-western-plaguelands --fact-check-profile off --release-gate -v
uv run python scripts/check_run_semantics.py artifacts/runs/run-western-plaguelands
uv run python scripts/check_run_semantics.py artifacts/runs/run-western-plaguelands --strict
LORE_PILOT_RUN_ROOT=artifacts/runs/run-western-plaguelands uv run pytest tests/test_run_storyline_artifacts.py -q
```

## Flags and tools

| Flag / tool | Role |
|-------------|------|
| `--fact-check-profile off` | No `fact_check.*` validation issues; similarity anti-verbatim skipped |
| `--release-gate` | Pointer caps and unresolved provenance overrides hard-fail; empty instance `key_enemies` hard-fail |
| Default validate (no gate) | Pointer cap overages are WARN; use for iteration |
| `check_run_semantics.py` | Zone-agnostic semantic acceptance (preferred over deprecated `check_pilot_semantics.py`) |
| `--strict` | Re-validates all `drafts/*/*.json` with shared validation context (`release_gate=True`, `fact_check_profile=off`) |
| `LORE_PILOT_RUN_ROOT` | Points artifact regression tests at the promoted CI run tree |

## Unit tests

```bash
uv run pytest
```
