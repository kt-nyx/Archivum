# Live evaluation

Use each zone and its linked dungeon to check shared authoring behavior. Westfall was held out during the July recovery implementation to check how well those changes worked on a different subject.

| Pair | Input manifest |
| --- | --- |
| Western Plaguelands / Scholomance | [Pilot regression input](../tests/fixtures/pilot/source_manifest.json) |
| Desolace / Maraudon | [Desolace input](desolace/source_manifest.json) |
| Westfall / Deadmines | [Westfall input](westfall/source_manifest.json) |

[The matrix](pilot_matrix.json) records the common settings and run families. Manifests describe source inputs. The pages, cards, and prose are selected from evidence at run time.

## Run and review

From the repository root, configure authoring credentials as described in the [development guide](../docs/development.md#local-setup). Run each command and use the printed run ID in the final step. The helper allocates a new run folder and copies the most recent manifest from that family. It uses the supplied seed for a new family.

```sh
uv run python -m scripts.check_run_semantics --help
uv run python .vscode/run-incrementing-pipeline.py --run-prefix mvp-westfall --seed-manifest evaluation/westfall/source_manifest.json --fact-check-profile strict --release-gate --verbose
uv run python .vscode/run-incrementing-pipeline.py --run-prefix mvp-desolace --seed-manifest evaluation/desolace/source_manifest.json --fact-check-profile strict --release-gate --verbose
uv run python .vscode/run-incrementing-pipeline.py --run-prefix mvp-wpl --seed-manifest tests/fixtures/pilot/source_manifest.json --fact-check-profile strict --release-gate --verbose
```

For a first Westfall run, for example:

```sh
uv run python -m scripts.check_run_semantics artifacts/runs/mvp-westfall-1 --strict --quality-summary
```

Read the printed semantic findings, `reports/run_quality_summary.json`, and `reports/validate/validation_report.json`. Confirm the saved validation report has `release_certified: true`. Use the same short editorial review for each pair.

1. Are the selected places, characters, factions, and story arcs real, relevant, and meaningfully distinct?
2. Do a sample of defining claims follow from the actual cited text, with the right subject and direction of each relationship?
3. Is the entry state supported and the setup free of later spoilers?
4. Do quest titles, faction variants, role labels, and action hooks read clearly to a player?
5. Are any important subjects or sections missing, and do the decision records explain the gaps?

Record findings against shared behavior so corrections can be checked against the other pairs. See [historical results](../docs/status.md#what-the-saved-runs-show) for the last comparison.
