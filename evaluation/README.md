# Pilot evaluation matrix (Slice 9)

`pilot_matrix.json` defines the multi-subject acceptance matrix for the generic pipeline:

| Pair | Zone | Linked instance | Hold-out |
| --- | --- | --- | --- |
| `wpl-scholomance` | Western Plaguelands | Scholomance | no |
| `desolace-maraudon` | Desolace | Maraudon | no |
| `westfall-deadmines` | Westfall | Deadmines | **yes** |

These are **evaluation subjects only**. Pilot names are permitted in this directory because it is a
run configuration, and are forbidden in shared classification/selection logic (enforced by
`tests/test_no_pilot_authority_guard.py`). Nothing here prescribes emitted card ids, counts, titles,
anchors, or prose — the manifests list only the source pages to crawl.

Westfall is a **hold-out** evaluation subject: it was not used while building the generalization
recovery. Its source manifest was not previously available, so `westfall/source_manifest.json` is a
fresh run configuration (not a hand-authored output fixture).

## Running a subject

Each pair runs through identical strict settings (`strict_settings` in `pilot_matrix.json`):

```
# From repo root, with OPENAI_API_KEY set for the draft/synthesis stages.
python .vscode/run-incrementing-pipeline.py \
  --run-prefix test-run-westfall \
  --fact-check-profile strict \
  --release-gate

# Then the machine-readable quality summary + strict semantic gate:
python scripts/check_run_semantics.py artifacts/runs/test-run-westfall-1 \
  --strict --quality-summary
```

`--run-prefix` copies the newest existing manifest for that prefix; seed a new family by first
copying the matching `evaluation/<subject>/source_manifest.json` (or the committed WPL fixture) into
`artifacts/runs/<prefix>-1/source_manifest.json`.

## Review

Review each subject's `reports/run_quality_summary.json` plus a small human evidence sample with the
shared editorial-review rubric in `Reference/generalization-quality-recovery-plan.md`. Record
findings as generic regression cases against a slice, never as a per-subject exception.
