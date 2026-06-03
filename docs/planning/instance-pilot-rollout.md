# Instance pilot rollout (Slice I6)

Instance-focused run playbook for validating and promoting the instance-page pipeline path.
Pairs with the zone-centric [`pilot-promotion.md`](pilot-promotion.md): run the zone dual-run
gate first, then apply the instance acceptance rubric and archive the before/after diff.

Run artifacts stay local under `artifacts/runs/<run-id>/` (gitignored). The instance gold
fixture (`tests/fixtures/pilot/instance_page_scholomance_gold.json`) is the committed
regression anchor; the tooling below evaluates and compares actual run output against it.

## Instance acceptance rubric

`scripts/instance_quality_report.py` aggregates the deterministic instance signals into a
per-instance PASS / WARN / FAIL scorecard. It is a pure function of the `instance_page`
drafts plus the `instance_key_character_decisions.json` sidecar (no network):

| Dimension | Source | Severity |
|-----------|--------|----------|
| Release-gate validation | `validate_payload(release_gate=True, fact_check off)` | HARD_FAIL -> `FAIL`, WARN -> `WARN` |
| at_a_glance / overview / key-character prose | `instance_lint` detectors | `FAIL` |
| Overview / history passthrough fragment | `lint_passthrough_fragment` | `FAIL` |
| Pool-aware key-character minimum | sidecar roster size vs emitted cast | `FAIL` |
| Role diversity (dropped in-window ally/neutral) | `assess_role_diversity` vs sidecar | `FAIL` / `WARN` |

An instance is `FAIL` if any fail-level signal fires, `WARN` if only warn-level signals
fire, else `PASS`. The script exits non-zero when any instance is `FAIL`; pass `--gate` to
also fail on WARN (strict promotion gate).

```bash
uv run python scripts/instance_quality_report.py artifacts/runs/test-run-wpl-1
# strict promotion gate (WARN also fails):
uv run python scripts/instance_quality_report.py artifacts/runs/run-western-plaguelands --gate
```

Reports are written to `<run_root>/reports/instance_quality_report.{json,md}` by default
(override with `--out`).

## Before/after diff (archived with rationale)

`scripts/diff_instance_runs.py` compares the `instance_page` drafts and decision sidecars of
two run roots, producing an archivable JSON + Markdown report with an auto-generated rationale
line per changed instance. Attach operator rationale with `--notes`.

```bash
uv run python scripts/diff_instance_runs.py \
  --baseline artifacts/runs/run-western-plaguelands-prev \
  --candidate artifacts/runs/run-western-plaguelands \
  --notes promotion-rationale.txt
```

It reports added/removed instances and, per instance, deltas for `at_a_glance`, `overview`
(word delta), `history_sections` count, `key_characters` (added/removed/role changes),
`lore_source`, provenance pointer counts, and the emitted key-character roster. Reports are
written to `<candidate>/reports/instance_run_diff.{json,md}` by default.

## Promotion flow

1. Dev validation (`test-run-wpl-1`): run the pipeline (see `pilot-promotion.md`), then the
   instance rubric. Manually review the rubric Markdown for any WARN/FAIL instance.
2. Promotion validation (`run-western-plaguelands`): re-run on the CI run id with
   `--release-gate`, run the rubric with `--gate`, and archive the before/after diff against
   the previous promotion run with a rationale note.
3. Rollout: once the instance rubric is clean (and `check_run_semantics.py --strict` passes),
   the instance path is promotion-ready. Keep the archived diff + rubric reports with the
   promotion record.

## Tests

```bash
uv run pytest tests/test_instance_pilot_gold_standard.py tests/test_instance_pilot_tooling.py -q
```

- `test_instance_pilot_gold_standard.py` — the committed Scholomance gold passes the release
  gate, the prose detectors, manifest alignment, and role diversity.
- `test_instance_pilot_tooling.py` — offline smoke that builds synthetic baseline/candidate
  run trees from the fixtures and exercises both scripts (PASS/FAIL scoring, reported deltas,
  deterministic output).
