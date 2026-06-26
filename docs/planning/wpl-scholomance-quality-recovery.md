# WPL / Scholomance Quality Recovery Plan

This is the Codex-owned successor to the Claude Code plan for the branch
`fix/wpl-run-review-rootcauses`.

The goal is to finish the Western Plaguelands / Scholomance pilot recovery without
hardcoding WPL-specific lore. The pilot remains the regression harness, but fixes
must use wiki-wide structure, run-local evidence, provenance, and domain-general
text rules.

## Current Status

Branch state when this plan was checkpointed:

- Branch: `fix/wpl-run-review-rootcauses`
- Latest committed work includes PR1 prose safety, dangling-clause prevention, cast
  sidecar refresh, instance/location/faction fixes, and release-gate LLM hardening.
- Branch contains a verified PR3 slice:
  - `pipeline/common/text_ids.py`: apostrophes are removed in slugs.
  - `pipeline/glossary/run_terms.py`: abbreviation-shape filter and leading-article
    dedup are implemented.
  - WPL questline/gold fixtures and tests have been updated for the apostrophe slug
    change.
- Targeted tests for the touched dirty files were green:
  - `62 passed, 2 skipped`
  - command used:
    `python -m pytest tests/test_common_utils.py tests/test_glossary_run_terms.py tests/test_linker_stage.py tests/test_questline_arc_map.py tests/test_questline_cluster.py tests/test_questline_cta.py`

The latest known live run in `artifacts/runs/test-run-wpl-1` passes validation with
zero hard failures, but still has warning-class issues:

- fact-check evidence lookup warns for history/overview claims because claim paths
  do not resolve to the correct provenance buckets.
- glossary linking still includes junk terms and misses some editorially significant
  terms.

## Non-Negotiables

- No per-zone allowlists, WPL keyword lists, or magic fixes for Scholomance only.
- Retail-only. Classic/removed/wiki-legacy material must be excluded from draft
  outputs and pilot gold unless explicitly preserved as historical context.
- Offline determinism matters. Network category lookups belong in ingest/enrichment
  stages that persist cached signals for later offline stages.
- Provenance remains mandatory. Any generated or selected page content must retain
  traceable source pointers.
- Glossary/category logic must be explainable as wiki-wide structure:
  - MediaWiki categories.
  - Parent category roots.
  - source section roles.
  - page/link prominence.
  - domain-general text shape rules.

## PR1 - Prose Safety And Release Gate Blockers

Status: mostly done and committed.

Already landed:

- near-verbatim detection now uses contiguous shingle containment in addition to
  set-style similarity.
- history sections and instance overview run through non-passthrough enforcement.
- finalize-level gates pass source snippets so deterministic fallbacks cannot ship
  large copied wiki prose in live LLM runs.
- source-attribution preambles are stripped in the central wiki snippet cleaner.
- history synthesis reliability was fixed by replacing brittle past-tense lint and
  adding per-section salvage/backstops.
- instance major-faction provenance now survives deterministic fallback paths.
- stale Scholomance key-character sidecar gold was refreshed to the structural boss
  roster behavior.
- dangling clause prevention was added to generation voice guidance.
- release-gate draft runs now fail before draft generation when OpenAI is not ready
  or `WOW_LORE_WIKI_FIRST_NO_LLM` is forced, preventing release runs from silently
  shipping deterministic verbatim fallback prose.

Remaining optional cleanup:

- consider catching hard synthesis errors in `draft_writer` and reporting a
  per-entity draft failure instead of a blunt stage abort.

Acceptance:

- WPL/Scholomance run has zero hard failures.
- no long-form field contains source-attribution preambles.
- overlap scan shows no large near-verbatim history/overview bodies.
- targeted prose/lint/gate tests stay green.

## PR2 - Election Quality: Factions And Locations

Status: partially landed; verify before doing more.

Already landed in recent commits:

- deterministic instance faction fallback so Scourge / Cult do not drop to `[]`.
- generic umbrella faction suppression when a specific sub-faction is elected.
- location cards prefer lore significance over maps-gazetteer naming.
- traversal prioritizes marquee landmarks and type cards from wiki categories.

Need verify:

- whether zone major factions now include current/restoration actors surfaced from
  prose, such as Argent Crusade and Cenarion Circle, without forcing WPL names.
- whether weak structural hits still crowd out prominent prose-mentioned factions.
- whether location sub-location containment is sufficient beyond WPL.

If still needed:

- harvest faction-typed entity mentions from zone narrative evidence as candidate
  seeds, using existing category/entity typing where available.
- score candidates by prominence:
  - lead/currently presence.
  - cross-section mention spread.
  - current-era section role.
  - page-level commitments already selected elsewhere.
- keep location selection relative rather than fixed-top-N where possible.

Acceptance:

- WPL zone faction cards are narrative-prominent rather than hyperlink-accidental.
- WPL location cards do not include sub-locations of already selected parents.
- at least one structurally different zone gives sensible results without tuning.

## PR3 - Slug Hygiene And Low-Risk Glossary Cleanup

Status: implemented, verified, and checkpointed before PR4.

Purpose:

Fix deterministic identifier mismatches and trivial glossary junk without building
the full category registry yet.

Tasks:

- Finish and commit the apostrophe slug rule:
  - `Kel'Thuzad` -> `kelthuzad`
  - `Ner'zhul` -> `nerzhul`
  - `Uther's Tomb` -> `uthers-tomb`
- Keep the rule global and mechanical:
  - delete straight/curly/modifier apostrophes before collapsing other
    non-alphanumerics.
  - do not add per-name exceptions.
- Finish leading-article dedup in run terms:
  - `The Battle for Andorhal` and `Battle for Andorhal` collapse to one term key.
  - preserve both surface forms as aliases.
- Keep abbreviation/date-shape filtering:
  - short all-caps single tokens like `ADP` are not glossary terms.
  - this is a shape rule, not a content denylist.
- Confirmed article-stripped slugs use the stripped form everywhere:
  - term key.
  - `term_id`.
  - wiki URL when no explicit URL exists.
  - aliases.

Known caution:

- Do not add a blunt "drop single-word concept terms" rule. The user correctly
  rejected that direction because significant proper nouns can be single words.

Acceptance:

- targeted dirty-tree tests remain green.
- affected fixtures are consistently migrated to the new slug convention.
- no duplicate Andorhal term from leading article variance.
- `term-adp` no longer enters run terms through seed-page links.

## PR4 - Wiki Category Registry For Glossary Significance

Status: new slice added by Codex from the interrupted category-list work.

Why this is its own PR:

The junk glossary problem is not just a local `run_terms.py` filter. Terms such as
`Human`, `Lich`, `Academy`, and `Necromancer` enter through seed-page outbound
links as generic `concept` rows. In the current WPL run they are not fetched
snapshots, so their page categories are not available to offline glossary/linker
logic.

Therefore the fix needs two parts:

1. an online category enrichment/cache step for linked pages.
2. offline glossary/linker use of the persisted category signals.

### Research Baseline

Claude enumerated the Warcraft Wiki category list and cached it locally.

Observed counts:

- total categories: `16,497`
- broad parent-category rows cached before rate limiting: `2,629`
- current parent+token filter sketch:
  - strong include via parent: `491`
  - strong drop: `10,787`
  - soft drop: `29`
  - positive-token review queue: `1,279`
  - unmatched / later review: `3,911`

Strong include roots currently worth keeping:

- person:
  - `Characters`
  - `Characters by organization`
  - `NPCs`
  - `NPCs by zone`
  - `Bosses`
- place:
  - `Subzones`
  - `Zones`
  - `Settlements`
  - `Cities`
  - `Locations`
  - `Territories`
  - `Regions`
  - `Kingdoms`
  - `Continents`
  - `Geography`
  - `Instances`
  - `World of Warcraft instances`
  - `Dungeons`
  - `Raids`
- faction:
  - `Factions`
  - `Organizations`
  - `Alliance`
  - `Horde`
- event:
  - `Events`
  - `Battles`
  - `Wars`
- artifact:
  - `Artifacts`

Important correction:

- `Lore` is not a strong include root. It catches real lore categories but also
  broad/meta categories such as `Magic`, `Bandages`, and `Items`. Treat `Lore` as a
  boost/review signal, not an automatic keep.

Strong drop roots currently worth using:

- `Images`
- `User created content`
- `Hidden categories`
- `World of Warcraft items`
- `World of Warcraft items by quality`
- `Quests`
- `World of Warcraft quests`
- `API`
- `Achievements`
- `Templates`
- `Disambiguations`
- `Image requests`
- `Concept art`
- `Developer showcases`
- `Maps`
- `Item sets`
- `Objects`

Soft drop roots:

- `Mobs`
- `Named mobs`
- `World of Warcraft creatures`
- `Roleplaying`
- `Glossary`
- `World of Warcraft`
- `Potentially out-of-date content`
- `Reputation`
- `Warcraft RPG`
- `Warcraft: The Roleplaying Game`

Soft roots must not override strong includes. Example:

- `Factions` has parents `Organizations` and `Reputation`.
- `Organizations` should keep it as a faction category.
- `Reputation` should lower confidence or mark review, not hard-drop it.

### Proposed Implementation

Add a small category registry module, for example:

- `pipeline/common/wiki_category_registry.py`
- data/config file under `pipeline/data/` or `rules/`, for example:
  - `rules/wiki_category_registry.v1.yaml`

The registry should expose:

- `classify_category(name, parents) -> CategorySignal`
- `classify_page_categories(categories, parent_map=None) -> PageCategorySignal`

The signal should include:

- inferred entity bucket:
  - `person`
  - `place`
  - `faction`
  - `event`
  - `artifact`
  - `concept`
  - `noise`
- confidence / disposition:
  - `strong_include`
  - `weak_include`
  - `review`
  - `soft_drop`
  - `strong_drop`
- matched roots and reasons.

The rules should be ordered:

1. strong-drop parent roots win.
2. strong-include parent roots win unless contradicted by a strong-drop parent.
3. soft-drop roots reduce confidence or force review.
4. wiki-wide token rules fill gaps only when parent data is absent.
5. no WPL-specific category names.

### Online Enrichment

Add a stage in ingest/traversal that batch-fetches categories for seed-page
outbound links:

- reuse `pipeline.ingest.fetch_wiki.fetch_categories_for_titles`.
- batch and cache results.
- do not call the network from offline glossary generation.
- persist the result under the run, for example:
  - `data/ingest/link_category_cache.json`
  - or enrich seed snapshots with `structured_links[*].target_categories`.

Prefer a separate run artifact over mutating raw fetched snapshots unless the
mutation fits the existing ingest contract cleanly.

The artifact should map normalized wiki titles or URLs to:

- canonical title.
- categories.
- parent categories when available.
- registry classification.
- fetch timestamp / source class.

### Offline Glossary Use

Update `pipeline/glossary/run_terms.py`:

- when harvesting seed-page outbound links, look up the target page's category
  signal from the persisted category cache.
- do not add links classified as `strong_drop`.
- for `soft_drop`, either skip or add only if other strong run-local significance
  exists.
- upgrade `concept` category to `person` / `place` / `faction` / `event` /
  `artifact` when the category signal is strong.
- keep multi-word named concepts such as `Third War` and `Plague of Undeath`.
- do not drop significant single-word proper nouns merely because they are
  single-token labels.

Update linker behavior if needed:

- avoid linking a shorter generic term inside a longer already-linked term.
  Example: avoid `Lich` when the actual prose hit is `Lich King`.
- continue sorting `glossary_refs` deterministically by term id after linker
  writeback.

Acceptance:

- `Human`, `Academy`, `ADP`, `Lich`, and `Necromancer` no longer appear as junk
  glossary refs in WPL/Scholomance unless supported by stronger context.
- `Third War`, `Plague of Undeath`, named factions, places, and key lore entities
  remain eligible.
- category decisions are captured in a reviewable artifact.
- no live network calls occur during offline `build_run_terms` or linker stages.
- tests cover:
  - strong include parent beats soft drop.
  - strong drop parent beats broad lore/category tokens.
  - `Lore` alone is not a strong include.
  - outbound-link category cache filters a disambiguation/user-content/item/quest
    term.
  - category cache upgrades a concept link to event/faction/place/person.

## PR5 - Fact-Check Provenance Path Resolver

Status: diagnosed, not implemented.

Problem:

The validation fact-check rule looks up provenance by the exact claim path, but
some claim paths are represented by aggregate provenance buckets:

- `history_sections[N].body` should use `provenance.history`.
- instance `at_a_glance` / `overview` should use the appropriate story-context or
  identity provenance buckets.

Current effect:

- local evidence scoring sees no source pointers.
- validation emits many `fact_check.insufficient_evidence` warnings even when the
  content is grounded.
- strict or LLM-enabled profiles may send unnecessary claims to paid adjudication.

Tasks:

- add a claim-path to provenance-key resolver in
  `pipeline/validate/rules/fact_check.py`.
- keep the resolver generic and page-type aware.
- add targeted tests in `tests/test_validation_engine.py`.

Acceptance:

- history/overview fact-check warnings disappear when supporting provenance exists.
- unsupported claims still warn/fail normally.
- no live run required for the unit-level fix.

## Verification Checklist

Use focused tests after each PR, then a live pilot run when a PR affects generated
draft content.

Fast local checks:

- `python -m pytest tests/test_common_utils.py tests/test_glossary_run_terms.py tests/test_linker_stage.py`
- add module-specific tests for each touched area.

Broader checks before handoff:

- `python -m pytest`
- `python -m ruff check .`
- `python -m mypy pipeline`

Live pilot run when needed:

- rerun `test-run-wpl-1` or a new run id with OpenAI configured.
- inspect:
  - `data/drafts/zone_page/zone-western-plaguelands.json`
  - `data/drafts/instance_page/instance-scholomance.json`
  - `data/glossary/run_terms.jsonl`
  - `reports/validate/validation_report.json`
  - category decision/cache artifact from PR4.

Cross-zone check:

- run one structurally different zone before treating category/election heuristics
  as generally safe.
- good candidates:
  - a faction-capital zone.
  - a low-lore leveling zone.
  - a dense expansion hub.

## Immediate Next Steps

1. Build `wiki_category_registry` with a small YAML-backed rule set and unit tests.
2. Add the online outbound-link category cache artifact.
3. Wire `run_terms.py` to use the cache for seed-page outbound links.
4. Rerun glossary/linker on the WPL pilot and compare junk kept/dropped terms.
