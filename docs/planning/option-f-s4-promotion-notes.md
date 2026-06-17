# Option F S4 — Scholomance pilot verification notes

**Run id:** `test-run-wpl-1`  
**Date:** 2026-06-03  
**Pipeline:** `lore-pipeline run --fact-check-profile off --release-gate`

## Cast emitted (10 / cap)

Darkmaster Gandling, Instructor Chillheart, Jandice Barov, Lilian Voss, Rattlegore, Doctor Theolen Krastinov, Professor Slate, Ravenian, Weldon Barov, Lord Alexei Barov.

## S0 acceptance

| Check | Result |
|-------|--------|
| Must emit (Gandling, Rattlegore, Jandice, Alexei) | Pass |
| Must not emit (places + generic trash) | Pass — denied names only in sidecar pool |
| Registry place in cast | Pass |
| `instance_quality_report --gate` | PASS |

## Sidecar-only / gaps

- **Kirtonos the Herald**, **Ras Frostwhisper** — not present in prefiltered pool for this ingest revision (acceptable per S0).
- **Instructor Malicia** — not in pool (no wiki href in ingest); deferred.

## Gold refresh

Committed fixtures updated from run draft + decision sidecar (`merge_rank`, `selection_reason`; `significance` removed). Professor Slate summary hand-corrected in gold after a bad LLM fragment.

## Follow-up (post-S4)

- `run-western-plaguelands` promotion with `--gate` and archived `diff_instance_runs.py` per `instance-pilot-rollout.md`.
