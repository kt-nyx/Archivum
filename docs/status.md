# Project status — 2026-11-15

Archivum can generate zone and instance drafts from Warcraft Wiki and export them as JSON. The effort to remove pilot-specific assumptions fixed clear selection errors in Desolace and Maraudon. Saved live runs still failed the strict release checks for all three test pairs, and the WoW addon still displays placeholder text. The project has an authoring pipeline and a UI scaffold, with a playable package and reliable content still ahead.

## Where the generation work went

1. **June — make the original pilot read like a lore guide.** Western Plaguelands and Scholomance drove work on source fidelity, the difference between history and the start of the playable story, spoiler-safe character biographies, and relevant factions and locations. The authoring stages learned to use individual claims and paragraphs, rather than treating a whole modern wiki article as the state the player encounters.
2. **Early July — remove the pilot's influence on shared behavior.** Commit `6c1a830` removed explicit pilot names and output rules from shared code and prompts. The surrounding work added wiki-derived categories and section roles, source-linked evidence, and claim-level checks. The resulting baseline `a8e1f48` exposed weaknesses the old assumptions had masked. The first Desolace/Maraudon run passed in warning mode while putting Naga, Satyr, and Felsteed into location cards and Area of Effect and Centaur into the character cast.
3. **July 9–16 — recover quality with evidence rules.** The merged recovery (`9254bba`) introduced affirmative evidence for entity types, direct evidence for places and named instance participants, shared questline metadata, story-arc grouping, and complete quest hook clauses. Selected cards got their own evidence packs. Strict validation gained coverage and evidence checks, and the evaluation matrix added Westfall/Deadmines as an unseen pair. Desolace's later drafts showed six plausible named places, including Karnum’s Glade and Furien’s Post, and Maraudon's cast shrank to Celebras, Lord Vyletongue, and Tinkerer Gizlock.
4. **July 11–27 — live failures exposed the remaining work.** The committed recovery plan records live evaluation as deferred. The local reports show all three pairs subsequently ran with strict settings. Review continued in the local Archivum Workflow companion. The only later content fix visible in the shared Git history is `4b14ac6`, a narrow quest-hook repair for clauses ending in a dangling “before.” Follow-ups for grounding and page coverage were planned. The July 27 rename `5c6c24d` is the last pre-revival product commit.

## What the saved runs show

These are historical outputs, with validation issues tallied from the saved `reports/validate/validation_report.json` files. The counts measure what the validator flagged. Diagnosing a flag requires comparing the actual sentence to its cited text.

| Saved run | Pair | Strict result |
| --- | --- | --- |
| `test-run-wpl-42` | Western Plaguelands / Scholomance | Failed. 19 unsupported passages and 4 contradictions. |
| `test-run-desolace-12` | Desolace / Maraudon | Failed. 21 unsupported passages and 2 contradictions. |
| `test-run-westfall-1` | Westfall / Deadmines | Failed. 30 unsupported passages, 2 contradictions, and zero viable location cards emitted for Westfall. |
| `test-run-desolace-13` | Desolace / Maraudon, latest saved run | Failed. 24 unsupported passages and 3 contradictions. |

- **Grounding is still the largest visible release blocker.** In the Westfall pair, saved draft decisions accepted sections that the later validator flagged, including Deadmines's overview and Westfall's current-state and history prose. The old follow-up plan proposed checking source support before finalizing text. Audit a few claims end to end to establish how much is missed evidence, misrouted citations, prose adding facts, or checker error.
- **Coverage is the other half of selection quality.** Westfall's selection log deferred candidates after the retrieval limit. The strict gate caught the empty location list. The 25 selected Westfall/Deadmines cards in the summary all had direct identity evidence, but the count covered characters, factions, and questlines. It said nothing about the missing category or whether each description was supported.
- **Titles and quest hooks had visible defects.** The saved Desolace and Westfall pages include repeated faction labels and literal `(None)` suffixes. The current title renderer still converts nullable variants to strings, which gives a concrete lead. The separate strict semantic check also rejected saved quest hooks for truncation or reading like zone-description filler, including in the final Desolace run. The narrow “before” fix covered one truncation shape. The saved runs still warrant a replay.

Local evidence remains under `artifacts/runs/`. The companion's two follow-up plans cover Westfall grounding and location retrieval, and shared grounding, zone-page coherence, and quest hook completeness. The committed recovery and fidelity history is indexed in the [archive](archive/README.md).

## What works now

| Area | State |
| --- | --- |
| Pipeline | Working authoring stages, versioned schemas and decision files, drafts, fact-check reports, and JSON bundle export. Strict generation quality remains open. |
| Local checks | 1,168 tests passed on the revival baseline, with 4 skipped and 1 expected failure. Ruff and mypy passed. These checks use fixtures and do not establish live content quality. |
| In-game addon | The [Lua scaffold](../addon/Core.lua) registers `/archivum` and `/lore`, opens a frame with placeholder text, and has a URL copy dialog. The [TOC](../addon/Archivum.toc) loads only `Core.lua`. Generated-page loading, real navigation, and an in-game smoke test are still pending. |
| Release | GitHub had no release or candidate tags for the baseline. Saved bundle files exist for failed runs because bundle assembly still runs after validation. A playable release needs both approved content and the addon data integration. |
| Archivum Workflow | A separate local repository for reviewing outputs, writing implementation plans, and coordinating changes. It has its own history and local run state. The product can be developed with the pipeline CLI and Git directly. |

This review used saved live runs and read-only inspection of the current runtime. A fresh live generation run and a Retail client test remain the next verification steps. See [the MVP plan](product.md#recommended-path-to-the-first-playable-build).
