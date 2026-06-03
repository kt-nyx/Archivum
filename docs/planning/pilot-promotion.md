# Pilot promotion checklist (Western Plaguelands)

Dual-run flow for dev iteration and CI promotion. Pilot input manifest lives at
`tests/fixtures/pilot/source_manifest.json`; run artifacts stay local under
`artifacts/runs/<run-id>/` (gitignored).

## Questline gold standard (Western Plaguelands)

Pilot questline fixtures (see `tests/fixtures/pilot/README.md`):

- **`western_plaguelands_questline_registry.json`** — quest→arc clustering oracle (wiki parts, overflow, excluded arcs)
- **`zone_page_western_plaguelands_gold.json`** — target `ZonePage.major_questlines` (`QuestlineCardV2`) shape

Fact-checked against
[Warcraft Wiki](https://warcraft.wiki.gg/wiki/Western_Plaguelands_storyline).

| Card | Faction | Start anchor |
|------|---------|--------------|
| Andorhal Campaign (Horde) | horde | Warchief's Command: Western Plaguelands! |
| Andorhal Campaign (Alliance) | alliance | Hero's Call: Western Plaguelands! |
| The Mender's Stead / Healing the Plaguelands | shared | A New Era for the Plaguelands |
| Hearthglen / Tirion Fordring's Legacy | shared | An Audience with the Highlord |

Each included row has a gold `cta_hook` that passes `lint_cta_hook` and semantic
filler checks. Excluded arcs (Northridge/Redpine, Gahrron's Withering cleanup)
are documented with `exclude_reason`. Scholomancer/Araj beats belong to Andorhal
Part 1 shared beats—not the Gahrron's excluded arc. The fixture also records known pipeline
gaps (flat storyline HTML → single v3 cluster → shared junk drawer).

Validate the fixture:

```bash
uv run pytest tests/test_pilot_questline_gold_standard.py -q
```

Compare a run draft qualitatively: `major_questlines` should surface all four
included arcs—not only Andorhal—and CTAs should read like the gold hooks, not
wiki snippet dumps.

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
uv run python scripts/check_run_semantics.py artifacts/runs/test-run-wpl-1 --strict --pilot-questline-gate
uv run python scripts/questline_quality_report.py artifacts/runs/test-run-wpl-1
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
- `instance_quality_report.py` clean (no FAIL instances; see instance gate below)
- `questline_quality_report.py` PASS (pilot strict questline structural gate; see questline gate below)
- Qualitative spot-check vs canvas golden examples (parent_continent, questlines, locations, Scholomance key_characters)

## Questline gate (Slice E)

Score and archive questline-card quality with the WPL pilot registry (structural parity with
[`pipeline/data/pilot/western_plaguelands_questline_registry.json`](../pipeline/data/pilot/western_plaguelands_questline_registry.json);
no verbatim CTA match required):

```bash
uv run python scripts/questline_quality_report.py artifacts/runs/test-run-wpl-1
# promotion (WARN also fails) + before/after diff archived with rationale:
uv run python scripts/questline_quality_report.py artifacts/runs/run-western-plaguelands --gate
uv run python scripts/diff_zone_questline_runs.py \
  --baseline artifacts/runs/run-western-plaguelands-prev \
  --candidate artifacts/runs/run-western-plaguelands --notes promotion-rationale.txt
```

Pilot registry structural checks run automatically for `zone-western-plaguelands` in
`check_run_semantics.py` (override with `--pilot-questline-gate` / `--no-pilot-questline-gate`).

## Instance gate

Score and archive instance quality with the Slice I6 tooling (full instance run playbook in
[`instance-pilot-rollout.md`](instance-pilot-rollout.md)):

```bash
uv run python scripts/instance_quality_report.py artifacts/runs/test-run-wpl-1
# promotion (WARN also fails) + before/after diff archived with rationale:
uv run python scripts/instance_quality_report.py artifacts/runs/run-western-plaguelands --gate
uv run python scripts/diff_instance_runs.py \
  --baseline artifacts/runs/run-western-plaguelands-prev \
  --candidate artifacts/runs/run-western-plaguelands --notes promotion-rationale.txt
```

## CI promotion — `run-western-plaguelands`

After dev gate is green:

```bash
uv run lore-pipeline run --run-id run-western-plaguelands --fact-check-profile off --release-gate -v
uv run python scripts/check_run_semantics.py artifacts/runs/run-western-plaguelands
uv run python scripts/check_run_semantics.py artifacts/runs/run-western-plaguelands --strict
LORE_PILOT_RUN_ROOT=artifacts/runs/run-western-plaguelands uv run pytest tests/test_run_storyline_artifacts.py tests/test_run_pilot_questline_draft.py -q
```

## Flags and tools

| Flag / tool | Role |
|-------------|------|
| `--fact-check-profile off` | No `fact_check.*` validation issues; similarity anti-verbatim skipped |
| `--release-gate` | Pointer caps and unresolved provenance overrides hard-fail; empty instance `key_characters` hard-fail |
| Default validate (no gate) | Pointer cap overages are WARN; use for iteration |
| `check_run_semantics.py` | Zone-agnostic semantic acceptance (preferred over deprecated `check_pilot_semantics.py`) |
| `--strict` | Re-validates all `drafts/*/*.json` with shared validation context (`release_gate=True`, `fact_check_profile=off`) |
| `LORE_PILOT_RUN_ROOT` | Points artifact regression tests at the promoted CI run tree |
| `--pilot-questline-gate` | WPL registry structural checks in `check_run_semantics` (default on for Western Plaguelands) |
| `questline_quality_report.py` | Aggregates release-gate validate + questline promotion gate into a per-zone scorecard |
| `diff_zone_questline_runs.py` | Archives before/after questline card field diffs between two run roots |

## Unit tests

```bash
uv run pytest
```
