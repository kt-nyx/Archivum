# Plan: Generalization Refactor — Registries, Guarantees & Editorial Selection

**Status: ARCHIVED 2026-07-09 — superseded by `Reference/generalization-quality-recovery-plan.md`.**

## Why this plan exists

The pipeline must produce lore-compendium pages for **every** zone and instance in retail WoW.
A deep review of run `test-run-wpl-24` (2026-07-03) plus a full codebase audit found that many of
its editorial decisions rest on hand-enumerated keyword/regex registries that were reverse-fitted
to the two pilot pages (Western Plaguelands zone, Scholomance instance), and that several of its
correctness *guarantees* silently degrade to no-ops on real data. The recurring
fix-one-run-break-the-next churn traces to these, not to missing tweaks.

Root causes (established in review; letters used throughout):

- **A** — Faction cards are selected by ranking but *vetoed* by surface-form gates. In run-24 the
  zone's own `currently` text opened with "The Argent Crusade and the Cenarion Circle continue to
  heal the land" while **neither faction had a card** (and Alliance was dropped): discovery never
  crawled profiles for the contract's current actors, the finalizer burned all retries on a
  wrong-shaped pool, and the role-framing lint rejected valid summaries (see H).
- **B** — Guarantees assume paragraph-granular evidence identity, but every paragraph of a wiki
  page shares one `source_id`. Coverage units collapse to one-per-page (the setup-bridge
  guarantee is vacuous in production — the "Gandling retreat / Last Holdout" beat vanished from
  Scholomance history while coverage reported `covered: true`), prompt evidence labels are
  indistinguishable, and provenance pointers are backfilled rather than real.
- **C** — LLM temporal adjudication is cost-scoped to claim-eligible fields, leaving 44% of
  canonical paragraphs (all of `location_pool` + `faction_pool`) permanently
  `ambiguous_temporal`. "Ambiguous" is excluded in some code paths and flows unvetted into card
  synthesis in others — location/faction cards bypass the spoiler/temporal layer.
- **D** — Budget/voice constants are duplicated between draft and validate and drift
  independently (`MAX_KEY_CHARACTER_WORDS=110` vs validate `[25,60]`; a 39-word history section
  shipped and hard-failed validate because per-section budgets are not retry triggers).
- **E** — A confident LLM boundary verdict is authoritative (correct in general), but there is no
  deterministic floor for **seed narrative paragraphs from a later expansion than the subject's
  `active_expansion`**. A `battle_for_azeroth_edit` paragraph was classified `entry_state`
  and Fourth-War content framed WPL's `currently` and final history section.
- **F** — The fact-check pass scores token overlap, not assertions ("built **above** Caer Darrow"
  passed at 0.95 against a source saying "beneath").
- **G** — Re-running into an existing run id overwrites all artifacts; regressions between
  generations become unprovable.
- **H** — The umbrella: a **closed-vocabulary world model**. Semantic judgments (is this a
  faction? is this a role statement? is this place sacred or a battlefield?) are made by
  hand-enumerated lists fitted to the pilot: an 11-token faction vocabulary (`dawn`, `circle`…),
  two *drifted* present-tense verb whitelists, phrase-enumerated "historical framing" markers,
  first-match keyword ladders for location typing (Uther's Tomb shipped as `battlefield` because
  `battle|war` is checked before `tomb|shrine`), WPL quest titles inside the "generic" vocab
  file, a literal `if zone_id == WPL: cap = 4` in questline significance, WPL gold headings used
  as prompt exemplars for every zone, and hardcoded instance names in the world registry.

**Design policy for all slices** (this is the contract; reviewers should reject violations):

1. A semantic judgment must come from one of: **wiki structure** (categories, inline links,
   infoboxes, templates), **general grammar** (closed grammatical classes, morphology,
   POS/dependency features exposed through the NLP substrate), or an **LLM call with structured
   output**. Hand-enumerated domain lists are demoted to telemetry/tiebreakers or deleted.
2. **One home per concept.** A threshold, vocabulary, or classification lives in exactly one
   module/data file and everything else imports it.
3. **No pilot facts in shared code, data, or prompts.** Pilot knowledge lives only in
   `tests/fixtures/pilot/` and gold fixtures.
4. Deterministic gates check only what is deterministically checkable (entity anchors, tense
   dominance, budgets, non-answer category). Editorial intent lives in prompts; enforcement is
   the synthesis driver's retry-with-reasons, and every reason string must be actionable by the
   model.
5. Failures must be auditable: every dropped card / floored classification / backfilled pointer
   writes a decision record including the rejected text.

**Registries explicitly kept as-is:** the wiki-category-seeded world registry
(`pipeline/discovery/world_registry.py` category seeds) and the expansion release-order registry
(`expansion_release_order` in `pipeline/data/draft_classification_vocab.v1.json`). Also kept:
genuinely closed grammatical classes (preposition/function-word/stopword lists), the section-label
registry (`pipeline/common/section_registry.py` + `pipeline/data/section_label_registry.v1.json`),
the pinned NLP library/model configuration once Slice 4 lands, and wiki-template conventions
(`non_canon_body_markers`).

**Verification standard for every slice:** `ruff check pipeline tests`, `mypy` on touched modules,
full `pytest` green, plus the slice's own checks. Slices marked **[LIVE]** additionally need an
`OPENAI_API_KEY` pilot run to verify output; slices marked **[RE-CRAWL]** change the ingest schema
and need a fresh crawl before their effects appear. Gold divergences caused by these fixes are
expected in places (noted per slice) — reconcile gold deliberately, per the standing policy that
pilot pages are close to gold promotion.

---

## Slice 1 — Immutable runs (G) — ✅ DONE (2026-07-04)

**Goal:** a run id with existing stage artifacts can never be silently overwritten.

**Implementation notes (as built):**

- `pipeline/common/run_context.py`: new `create_run_context(run_id, *, artifacts_root,
  force_new_suffix)` — the required entry point for **new** pipeline executions. If the run dir
  already holds any stage manifest (`traces/manifests/*.json`) it raises
  `RunArtifactsExistError` (message lists the stages found), or with `force_new_suffix=True`
  allocates the first free `<run_id>-2`, `-3`, … sibling. No overwrite option exists.
  `ensure_run_context` keeps attach-to-existing semantics for in-flow stage tasks and
  single-stage commands (docstring now states the split).
- `pipeline/orchestrator/flow.py`: `run_pipeline_flow` gained `force_new_suffix: bool = False`
  and creates its context via `create_run_context`; `_run_stage_with_retry` still attaches via
  `ensure_run_context` (the flow entry already ran the guard).
- Single-stage re-execution trace: new `record_stage_reexecution(context, stage_name)` appends a
  `status="reexecute"` / `attempt=0` trace event with `replaced_outputs` (+ prior status and
  timestamp) read from the existing stage manifest; no-op on first execution. Every single-stage
  CLI command calls it before running its stage (`link` records both `glossary_terms` and
  `linker`; `traverse` records `traverse_seed`). Detection deliberately does **not** live in
  `write_stage_manifest`: the enrich phases legitimately rewrite the `discovery_enrich` manifest
  five times inside one fresh run and would emit misleading events.
- CLI `run` gained `--force-new-suffix`; a guard rejection is echoed as a clean one-line error
  (exit 1).
- Tests (`tests/test_run_context.py`, `tests/test_cli.py`, `tests/test_orchestrator_flow.py`):
  guard raises on manifest-bearing run dir / proceeds on fresh or artifact-free dir / suffixes to
  the next free id; the flow refuses end-to-end through Prefect before any stage runs; the
  reexecution trace event carries the replaced outputs; CLI flag pass-through and clean error.
  Verified: `ruff check pipeline tests`, `mypy` on the three touched modules, full `pytest`
  (1002 passed, 5 skipped, 1 xfailed).

- In the orchestrator's run setup (`pipeline/orchestrator/`, wherever `RunContext` is created for
  a new pipeline execution): if the run directory already contains any stage manifest, refuse to
  proceed — either hard-fail with a clear message or (behind an explicit `--force-new-suffix`
  style option) auto-suffix the run id (`test-run-wpl-24-2`). Do not add an "overwrite" option.
- Single-stage re-execution against an existing run (a legitimate dev workflow, if the CLI
  supports it) may stay, but must emit a trace event recording which stage outputs were replaced.
- Tests: creating a context over a run dir with a stage manifest raises/suffixes; fresh run dir
  proceeds.

**No dependencies. Do this first — later slices rely on being able to diff runs.**

## Slice 2 — Single-source budgets, wired as retry triggers (D, part of H-3 drift) — ✅ DONE (2026-07-04)

**Goal:** every word budget lives in `pipeline/contracts/models.py` `BudgetRule`s only, and the
synthesis driver retries on budget violations instead of shipping them to validate.

**Implementation notes (as built, 2026-07-04):**

- New page-scope rules in `pipeline/contracts/models.py`: `PAGE_HISTORY_SECTION_BUDGET_RULE`
  ([40,110] HARD_FAIL, shared by zone_page and instance_page — validate previously used inline
  literals, so this home was created) and `ZONE_PAGE_BUDGET_RULES` (at_a_glance [18,48] WARN,
  currently [35,90] HARD_FAIL, major_factions_card_summary [18,48] WARN,
  instance_links_card_summary **= the identity_header rule object** — the instance-link card
  reuses the instance page's at_a_glance caption, so validate now warns on [22,55] instead of
  the old inline [18,48] that contradicted the documented draft coupling).
  `validate/rules/budget.py` `_validate_zone_page` / `_validate_instance_page` read these via
  `_rule_issue_count` instead of inline literals (issue codes unchanged; messages gain the
  target).
- Draft-side derivations (no literal budget homes left): `instance_lint`
  MIN/MAX_KEY_CHARACTER_WORDS ← key_characters_card_summary ([18,110] → [25,60]; the offline
  generic template was lengthened to clear the new floor), MIN/MAX_OVERVIEW_WORDS ←
  story_context (values already equal), MAX_AT_A_GLANCE_WORDS ← identity_header;
  `faction_lint` MIN/MAX_FACTION_SUMMARY_WORDS ← major_factions_card_summary ([12,40] →
  [18,48]) and the duplicate `MAX_FACTION_SUMMARY_WORDS = 40` in `faction_scoring` deleted
  (imports faction_lint); `prose_lint.MAX_AT_A_GLANCE_WORDS` ← zone_page at_a_glance (45 → 48);
  `pages/cards.py` `_HISTORY_SECTION_MIN/MAX_WORDS` ← the shared history rule;
  `prose_synthesis` defaults (at_a_glance 45, currently 120, faction 40, key-character 50),
  `prose_election.fallback_currently` (120), and the zone finalizer's `max_words=120` literals
  ← the same rules (currently synthesis now capped at 90 = validate max; the old 120 cap could
  ship a 91–120-word `currently` straight into a validate hard-fail).
- Retry wiring: new `_history_budget_reasons` (actionable "history section N is X words; each
  section must be 40-110 words — merge/expand/split") joins `_batch_reasons`, the live
  per-section salvage filter, and the coverage-retry acceptance check; zone `currently` gets an
  equivalent budget reason in the driver validator (`_live_reasons`). Key-character summaries
  were already driver-validated via `lint_key_character_summary`, so the registry-derived
  [25,60] window is now their retry trigger (prompt max-words and trim follow the passed cap).
- `_apply_history_section_budget` now absorbs a sub-floor section even below
  `MIN_HISTORY_SECTIONS` (validate's floor is one section; shipping a budget violation is the
  worse outcome). Unabsorbable sub-floor sections are kept and become retry reasons live.
- **Deliberate scoping:** budget retry reasons are live-driver-only. The offline NO_LLM borrow
  ladder has no retry lever, so it keeps the sanctioned thin borrow instead of degrading to a
  null field / empty history on smoke runs (`_batch_reasons(..., enforce_budget=False)`;
  validate still reports the violation on offline artifacts). Documented intentional floors
  kept laxer than the rules, at their definition sites: instance/zone at_a_glance and
  instance-link minimums are degenerate-stub guards for the offline ladder (validate's min is
  WARN-severity there).
- Tests: new `tests/test_budget_single_home.py` pins the registry values and asserts every
  draft constant IS the registry value; history retry-on-budget, absorb-below-MIN, and
  unabsorbable-kept tests in `tests/test_history_finalize.py` / `test_history_section_merge.py`;
  key-character >60 rejection + generic-floor tests in `tests/test_instance_lint.py`. Updated
  fixtures that pinned the old caps (38-word coverage section, 12-word faction snippet,
  20–24-word check_run key-character summaries, sub-40-word zone history paragraphs).
  Verified: `ruff check pipeline tests scripts`, `mypy` on the 11 touched modules, full
  `pytest` (1015 passed, 5 skipped, 1 xfailed).

**Original spec:**

- Add accessor(s) in contracts (or a thin `pipeline/common/budgets.py`) exposing the BudgetRule
  registry to the draft stage.
- Replace draft-side duplicates with derivations from the registry:
  - `instance_lint.MAX_KEY_CHARACTER_WORDS` / `MIN_KEY_CHARACTER_WORDS` → derive from
    `INSTANCE_BUDGET_RULES["key_characters_card_summary"]` ([25,60]); update
    `synthesize_key_character_summary`'s prompt max-words and trim to match.
  - `pages/cards.py` `_HISTORY_SECTION_MIN_WORDS`/`_HISTORY_SECTION_MAX_WORDS` → import the
    validate history budget (40..110) from the same home validate uses.
  - Audit `MAX_OVERVIEW_WORDS`/`MIN_OVERVIEW_WORDS`, at_a_glance and faction caps for the same
    pattern; align or document intentional differences in one place.
- Wire per-section history word budget into `_batch_reasons` in
  `pipeline/generate/draft/pages/cards.py` (`_finalize_history_sections`) so an out-of-budget
  section is a retry reason (phrased actionably: "section N is X words; each section must be
  40–110 words — merge or expand it"). Keep the deterministic trim/absorb pass as post-processing;
  additionally allow absorbing a sub-floor section below `MIN_HISTORY_SECTIONS` when the
  alternative is shipping a budget-violating section (validate's own floor is ≥1 section).
- Same for key-character summaries: word budget becomes part of the driver validator for that
  field, with the registry cap.
- Tests: budget values asserted equal across draft/validate homes (a drift tripwire test);
  history finalizer retries on an out-of-budget section; key-character validator rejects >60
  words. Update tests that pinned the old 110-word cap.

**Expected pilot effect [LIVE]:** the instance page's `budget.history_section` hard-fail and both
`budget.character_card` WARNs disappear; character cards shorten toward gold register (38–46 w).

## Slice 3 — Recency floor for seed paragraphs under boundary authority (E) — ✅ DONE (2026-07-04)

**Goal:** a seed/lore narrative paragraph from an expansion strictly later than the subject's
`active_expansion`, with no linkage to the entry-state contract, cannot be `entry_state` /
`history_setup_bridge`.

**Implementation notes (as built, 2026-07-04):**

- `pipeline/generate/draft/temporal.py`: new `_seed_narrative_recency_override(record)` mirrors
  the character-profile guard and runs in the same post-LLM loop (character guard first — it is
  stricter, having no escape hatch — seed guard only when it declined). Triggers when the
  classification is `entry_state` **or** carries `history_setup_bridge` (it can ride
  `pre_entry_history`), the record appears in a seed/lore narrative field
  (`_SEED_NARRATIVE_FIELD_NAMES` = history_digest, currently_input, at_a_glance_input,
  instance/parent/related_lore_pool — boss/questline anchors and bulk entity pools stay out;
  character_pool keeps its own guard), `_expansion_recency(...) == "later"`, and
  `_paragraph_matches_entry_state_contract(record)` is False. Floors to `post_active_lore`,
  reason exactly `seed_later_expansion_no_contract_linkage`, structural hint
  `seed_narrative_recency_guard:floored_<fallback_mode>_<scope>` (keeps the overridden verdict
  auditable in the canonical decisions sidecar), `history_eligibility=""` so
  `_with_canonical_history_defaults` derives `history_excluded_post_active` for history
  appearances.
- Paragraph-level contract linkage (`_paragraph_matches_entry_state_contract`):
  `_claim_matches_active_conflict_contract`-style exact normalized label/ID matching over
  `_SEED_RECENCY_LINKAGE_CONTRACT_FIELDS` (= `_ACTIVE_CONFLICT_CONTRACT_FIELDS` +
  current_locations + current_objectives, this slice's "active conflicts / current locations /
  objectives"; the pure identity fields — current_factions/inhabitants/controller — deliberately
  don't count, matching the rubric's non-independent-match caution). Matches against (a)
  appearance metadata terms (`_contract_candidate_terms` over refs) and (b) whole-phrase presence
  in the paragraph snippet (`_normalized_prose_match_text`, apostrophes kept). Deliberately NOT
  `_canonical_contract_relation`: its `source_id` match would link every seed paragraph trivially
  (contract anchors come from the seed page itself). The subject's own name/id never counts as
  linkage (`_subject_name_terms`).
- Prompt tempering in `_temporal_adjudication_system_prompt` (single caller = the canonical
  boundary pass; the claim-level pass has its own prompt): the expansion_recency paragraph keeps
  "The key question is not…" and gains "a paragraph marked 'later' with no contract_relation
  linkage to active conflicts / current locations / objectives requires strong textual evidence
  to be classified as current setup; without it prefer post_active_lore".
- Confirmed (no changes needed): `post_active_lore` is excluded from every claim route
  (`claim_routing._claim_allowed_for_route`), from `history_eligibility_allowed` /
  `filter_history_items`, and claims inherit the floored paragraph scope
  (`_classify_claim_temporal_deterministic` POST_ACTIVE_LORE branch) — so the floored BfA
  paragraph leaves both the `currently` and history pools.
- Tests: `tests/test_temporal_evidence_classifier.py` — floor on a confident `llm_boundary`
  entry_state verdict (unit + end-to-end through `enrich_evidence_temporal_metadata` with a
  mocked LLM, asserting items/decisions/canonical sidecar all carry the floor); setup-bridge on
  pre_entry scope floored; contract-linked paragraph spared via prose phrase and via appearance
  metadata; subject's own name is not linkage; same/earlier/unranked-section/unknown-active
  recency untouched; bulk-pool fields and plain background paragraphs out of scope.
  `tests/test_expansion_recency.py` pins the tempered rubric. Verified: `ruff check pipeline
  tests`, `mypy` on temporal.py, full `pytest` (1023 passed, 5 skipped, 1 xfailed). The
  [LIVE] pilot effect (Fourth-War content leaving WPL `currently`/history) is pending the next
  live pilot run.

**Original spec:**

- In `pipeline/generate/draft/temporal.py`, mirror `_character_profile_recency_override` with a
  seed-scope guard: after canonical classification (deterministic or `llm_boundary`), if
  `_expansion_recency(...) == "later"` and the paragraph's claims/entities do **not** match the
  contract's active conflicts / current locations / objectives (reuse
  `_claim_matches_active_conflict_contract`-style matching at paragraph level), floor the
  classification to `POST_ACTIVE_LORE` with a distinct reason
  (`seed_later_expansion_no_contract_linkage`) and record it in the decisions sidecar.
  Contract linkage is the escape hatch that keeps expansion chronology a *soft* signal
  (memory: `expansion-chronology-now-soft-signal`) — a later-expansion paragraph about the zone's
  own active conflict survives.
- Temper `_temporal_adjudication_system_prompt`: keep "the key question is not which expansion is
  later", but add that a paragraph marked `expansion_recency: later` with no contract linkage
  requires strong textual evidence to be classified as current setup.
- Confirm the `currently` pool and history pool filter `post_active_lore` items (they filter by
  scope today; the floor makes the BfA paragraph carry the right scope).
- Tests: a later-expansion seed paragraph with confident `llm_boundary` `entry_state` verdict and
  no contract linkage is floored; the same paragraph with entities matching an active conflict is
  not; deterministic-era paragraphs (`recency in {same, earlier, unknown}`) untouched.

**Expected pilot effect [LIVE]:** Fourth-War content ("War Frontiers", "During the Fourth War…"
in `currently`) leaves the WPL page; zone history ends at the Cataclysm-era state, matching the
gold end-boundary ("After the Lich King" era).

## Slice 4 — NLP substrate for deterministic grammar features (H-2 enabler) — ✅ DONE (2026-07-04)

**Goal:** introduce one pinned, auditable NLP integration for English grammar tasks, without moving
Warcraft/domain semantics into a generic parser.

**Implementation notes (as built, 2026-07-04):**

- `pipeline/common/linguistics.py`: the single NLP home (spike confirmed spaCy — no stanza
  adapter). Pinned `spacy==3.8.13` + `en_core_web_sm` 3.8.0 as a direct-URL GitHub-release-wheel
  dependency in `pyproject.toml` `[project].dependencies` (exact pins, bump together; installed
  into the venv with `python -m pip`). **`uv.lock` reconcile is pending** — `uv` is unavailable
  in this environment; run `uv lock` when it is.
- Model loads lazily (`lru_cache`), NER pipe excluded (entity identity is domain semantics; no
  helper reads it). Load failure raises `LinguisticsModelError` — no regex fallback exists.
- Public helpers, all returning frozen-dataclass/plain values: `sentence_spans` (source char
  offsets), `linguistic_tokens` (text/lemma/POS/tag/dep/morph/whitespace; text+whitespace
  round-trips the source), `tense_profile`, `lemmatized_content_tokens`
  (NOUN/PROPN/VERB/ADJ/ADV lemmas minus spaCy stopwords), `model_info` (pin metadata),
  `describe` (reviewer dump).
- `TenseProfile` carries the planned buckets plus **`past_auxiliaries`** (deliberate addition:
  passives/perfects — "was founded", "had been consumed" — carry past narration on the finite
  auxiliary, which the sm model tags AUX, so the planned `past_count` is unreachable without
  it). Derived: `past_count`/`present_count` (finite verbs + finite auxiliaries),
  `past_dominant` (past > present), `present_framed` (present_count > 0), `imperative_like`.
  Past participles (incl. adjectival "ruined"/"plague-scarred"/"fallen") are reported but never
  counted as finite past. Imperative detection is grammatical shape, not a verb list:
  subjectless clause head (root or conjoined verb) that is base-form VB or has a base-form
  aux/auxpass spine ("Be warned"), excluding infinitival (`to`) and modal-bearing fragments
  ("Can be found in..." — imperatives never take modals).
- Diagnostics: `describe()` + CLI `archivum-pipeline debug-linguistics "<text>"` print model pins,
  sentence spans, per-token features, tense profile, and content lemmas.
- Tests (`tests/test_linguistics.py`, real model, no fixtures/skips): pin-drift smoke test
  (hard failure; also asserts NER absent), offset/round-trip properties, and feature snapshots
  for all plan regression phrases — "heals…", "works to further heal…" (infinitive complement
  not finite), "labors to restore…" (**known sm-model weakness snapshot**: "labors" mis-tagged
  NOUN → zero finite verbs; load-bearing property for Slice 5 gates is *not past-dominant*, so
  gates must reject on positive past evidence, not require positive present evidence),
  "was founded… fought…" (past-dominant via finite aux + finite past), quest imperatives
  (single, conjoined, bare-auxiliary), non-imperatives (infinitival/modal fragments),
  participial caption (no finite spine), present copula framing, empty text, lemmas.
  Monkeypatch policy recorded in the test-module docstring. Verified: `ruff check pipeline
  tests`, `mypy` on linguistics/cli/tests, full `pytest` (1040 passed, 5 skipped, 1 xfailed).

**Original spec:**

- Add a single wrapper module, e.g. `pipeline/common/linguistics.py`, and make it the only place
  that imports the NLP library directly. Preferred implementation: `spacy` with the smallest
  English pipeline that provides sentence boundaries, POS tags, lemmas, morphology, and dependency
  labels. If a spike shows spaCy's tense/morphology is too weak for the gold/regression set,
  record the evidence and use `stanza` instead; do not leave competing adapters.
- Pin the Python package and model version deliberately. Environment facts verified 2026-07-04:
  the project venv runs Python 3.14.3 and `spacy` 3.8.13 resolves cleanly with `cp314`
  `win_amd64` wheels (pip dry-run confirmed), so no interpreter downgrade is needed. The trained
  model (`en_core_web_sm` or chosen equivalent) is **not on PyPI** — pin it as a direct-URL
  dependency in `pyproject.toml` (the GitHub release wheel matching the pinned spaCy minor
  version). Install workflow in this environment: `uv` is not on PATH and `uv.lock` does not
  auto-update — install with `./.venv/Scripts/python.exe -m pip` and reconcile the lock
  deliberately (or document that it is pending).
- The library **and the model** are standard dev/CI dependencies, installed everywhere the test
  suite runs — they are small and fast, and once `split_sentences` delegates to the wrapper
  (Slice 8) a large share of the existing suite exercises it transitively; tests must run real
  segmentation, not a fallback. Failing to load the model is an explicit error in live/dev runs;
  do not silently fall back to the old regex behavior in production.
- Expose project-level data structures rather than raw library objects:
  - `sentence_spans(text)`: start/end/text, preserving source offsets when available.
  - `linguistic_tokens(text)`: text, lemma, POS, tag, dependency label, morph features, whitespace.
  - `tense_profile(text)`: finite past verbs, finite present verbs, present auxiliaries/copulas,
    past participles/adjectival participles, imperative roots, and a small set of derived scores
    (`past_count`, `present_count`, `past_dominant`, `present_framed`, `imperative_like`).
  - `lemmatized_content_tokens(text)`: lowercased lemmas for NOUN/PROPN/VERB/ADJ/ADV, excluding
    stop/function words, for deterministic retrieval/fallback scoring.
- Keep the wrapper conservative:
  - Proper nouns and wiki identifiers must stay as surface text unless the caller explicitly asks
    for lemmas; never lemmatize IDs, titles, or provenance strings.
  - The wrapper reports features only. It must not decide faction identity, location type, temporal
    scope, support/contradiction, or spoiler safety.
  - All public helpers return deterministic plain Python values and include enough feature detail
    to write decision records.
- Add diagnostics: a tiny CLI/script or debug function that prints the wrapper's analysis for a
  text sample. This is for reviewers to inspect tense/parse disagreements without stepping through
  the parser.
- Tests:
  - model-load smoke test (hard failure, not skip, since the model is a standard dev/CI
    dependency — a skip here would let the rest of the suite silently run fallbacks);
  - monkeypatching the wrapper is reserved for *targeted* unit tests that pin a downstream
    module's behavior for a specific feature shape — the default is real analysis;
  - feature snapshots for the current regression phrases ("heals…", "works to further heal…",
    "labors to restore…", "was founded… fought in the Second War…", imperative quest-style prose,
    and a participial caption such as "plague-scarred / ruined / fallen").

**No pilot-run dependency. Do this before replacing the tense/role gates so Slice 5 does not
recreate a hand-maintained grammar table.**

## Slice 5 — Retire the role-framing verb whitelists; one NLP-backed tense home (H-2) — ✅ DONE (2026-07-05)

**Goal:** delete the closed verb/phrase lists that gate faction summaries; recompose the gate from
checks that are legitimately decidable by the NLP grammar substrate; make all retry reasons
actionable.

**Implementation notes (as built, 2026-07-05):**

- All spec'd deletions landed: `_PAST_TENSE_RE`, `_PRESENT_TENSE_RE`, `_PAST_TENSE_MORPH_RE`,
  `_QUEST_IMPERATIVE_OPENER_RE` (prose_lint); `_PRESENT_ROLE_RE`, `has_zone_role_framing`
  (faction_lint); `has_historical_framing` + the `historical_framing_markers` vocab entry and
  loader (every call site re-sourced or retired — see below). `has_present_state_framing`,
  `past_marker_score`, `has_past_tense_signal`, `has_dominant_present_tense` now read
  `linguistics.tense_profile` (which gained an `lru_cache`: lint predicates re-profile the same
  snippet during pool ranking). `tense_marker_counts` was **deleted** rather than rebuilt — after
  the sweep it had zero consumers; the profile's `past_count`/`present_count` are the home.
- **Gate formulation deviation (empirically forced).** The plan's raw "not past-dominant"
  (`past_count > present_count`) rejects three of the seven gold summaries: the sm model erases
  the lone present verb of the gold Forsaken card ("control" tagged NOUN → past=1/pres=0), and
  both gold instance cards legitimately mix an origin spine with a present tail (Scourge
  raised/left vs hold → 2v1; Cult struck/made/doomed vs remains → 3v1). The shipped gate is
  `prose_lint.is_past_dominant_narration`: **finite present == 0 AND finite past >= 2** — reject
  only when the text's sole narration is a repeated past spine. It still fails the org-history
  lede ("was founded… fought…" → 2v0), rejects on positive past evidence only, never requires
  positive present evidence (Slice 4's "labors" constraint), and tolerates one subordinate past
  fact (gold Forsaken shape).
- Two substrate refinements in `linguistics.py` (general dependency grammar, not vocabulary),
  each snapshot-tested: (1) a VERB with `dep=amod` ("maintains **fortified** holdings" — sm
  morphology calls it finite past) counts as an adjectival participle, never finite narration;
  (2) imperative detection inherits subjects/modals through the conjunction chain, so
  "they spy … and **recruit** …" (gold Cult card shape) is finite narration while
  "Aid X and slay Y" stays a two-verb directive.
- `lint_faction_summary` recomposed exactly per spec plus two deliberate keeps: the ADP/BDP
  exact-dating style check (deterministic, shared with every other prose lint, separately
  tested) and the empty-summary check. The `is_generic_faction_summary` phrase-pattern veto and
  the redundant "bare zone-description filler" check (subsumed by the word floor) were deleted.
  All reasons state what to do; none names an internal check.
- `has_historical_framing` call-site resolutions: faction gate → deleted with
  `has_zone_role_framing`; `lint_currently`'s no-present elif → retired (subsumed by the
  present-framing requirement at >=8 words); `prose_election._is_excluded_currently_snippet` and
  `_is_present_state_lore` → re-sourced to `tense_profile(text).past_dominant`;
  `instance_lint.lint_overview` thin-fragment check → re-sourced to `past_dominant` under the
  same word threshold. One consumer-level carve-out: `_tier_latest_era_history` now applies
  content-frame checks only (meta / player-directive / geography-hub) — it deliberately borrows
  a *history* paragraph as the currently seed, which is legitimately past-voiced; the LLM
  worker rewrites voice and the deterministic borrow is still gated by `lint_currently`.
- `lint_history_sections` now checks present-dominance *before* the framing signal (the NLP
  spine makes dominance reliable; the reason names the actual defect), and
  `has_past_tense_signal` counts past/adjectival participles as framing evidence.
- Tests: all six spec'd cases (three previously-rejected summaries; org-history lede fails on
  the tense reason alone; participial caption; non-final present history section; imperatives
  outside any verb list — "Purge…/cleanse…"; all 5 zone + 2 instance gold summaries pass via
  fixture-loading test) plus the two substrate-refinement snapshots and a gold-Forsaken-shape
  tolerance test. Whitelist-pinning tests deleted (canned-template + generic-filler).
  One fixture reword: `test_provenance_page_entities` at_a_glance snippet was shaped to the old
  regex's blind spots ("was ravaged … reclaimed" read as 1 past marker; the NLP spine correctly
  reads was+reclaimed = past-dominant) — replaced with a caption-shaped equivalent.
  Verified: `ruff check pipeline tests`, `mypy` on all touched modules, full `pytest`
  (1045 passed, 5 skipped, 1 xfailed; the one mypy error in `test_classification_vocab.py`
  pre-exists on HEAD).

**Original spec:**

- In `pipeline/generate/draft/prose_lint.py`, replace the local tense regex home with calls to
  `pipeline.common.linguistics.tense_profile`:
  - Delete `_PAST_TENSE_RE`, `_PRESENT_TENSE_RE`, `_PAST_TENSE_MORPH_RE`, and any drifted
    present-tense verb list used only for tense decisions.
  - Rebuild `tense_marker_counts`/`has_dominant_present_tense`/`past_marker_score` on the
    NLP-derived finite-verb counts. Past participles/adjectival participles ("ruined",
    "plague-scarred", "fallen") must not count as finite past narration unless the parser reports a
    finite verb spine.
  - `has_present_state_framing` becomes `present_framed` from the tense profile: finite present
    verbs or present copula/auxiliary constructions count; arbitrary open-ended present role verbs
    do not need a maintained whitelist.
- Replace `has_player_directive`'s quest-imperative opener list with the NLP wrapper's
  `imperative_like` signal, keeping explicit player/meta text regexes (`players can`, "the
  player's arrival", achievements/reputation) as mechanical frame guards.
- In `pipeline/generate/draft/faction_lint.py`:
  - **Delete** `_PRESENT_ROLE_RE` and `has_zone_role_framing`; **delete**
    `historical_framing_markers` usage for this gate (remove the vocab entry if it has no other
    consumers — check `has_historical_framing` call sites and re-source or retire each).
  - `lint_faction_summary` becomes: length budget + terminal punctuation + zone/subregion anchor +
    subject mention + non-answer category + **not past-dominant** (from the tense home) +
    currently-meta. Reason strings must state what to do ("write in present tense: describe what
    the faction does now in <zone>"), never name an internal check.
- Sweep other consumers of the deleted signals and re-point them at the tense home. Known call
  sites as of 2026-07-04 (re-grep before relying on this list):
  - `faction_scoring.fallback_faction_summary` first-pass filter;
  - `prose_election` — `has_present_state_framing` ranking keys (~3 sites) plus
    `has_historical_framing` gates;
  - `prose_synthesis` — imports `past_marker_score` and `has_present_state_framing` as
    evidence-ordering sort keys (top-of-module ranking helpers);
  - `instance_lint` and `draft_vocab` also touch `has_historical_framing`/
    `historical_framing_markers` — resolve each per the faction_lint bullet above (re-source or
    retire; `draft_vocab` is the vocab's home).
- Tests: the three previously-rejected valid summaries ("heals…", "works to further heal…",
  "labors to restore…") pass; a generic org-history lede ("was founded… fought in the Second
  War…") fails on past-dominance; a participial at-a-glance caption stays valid; a present-tense
  non-final history section still fails; imperative quest-objective prose is rejected without
  pinning a verb whitelist; all five WPL gold zone faction summaries and both instance gold
  summaries pass; delete tests pinning the whitelist.

**No pilot-run dependency; unblocks Slice 6.**

## Slice 6 — Faction finalize: one merged pool, full retries, drop audit, coherence check (A draft-side; includes the instance-harvest scope fix) — ✅ DONE (2026-07-05)

**Goal:** the ranked faction election survives finalize; failures are auditable; pages can no
longer name un-carded actors silently; instance faction cards can't be built from character
biographies.

**Implementation notes (as built, 2026-07-05):**

- `pipeline/generate/draft/faction_scoring.py` `finalize_evidence_pools` is now the merge
  function: all zone-role seed mentions stay first, then up to two profile identity lead items
  (`lead`/`introduction`, or the first profile items if no lede role exists), deduped by
  `(source_id, snippet)`. `pages/cards.py` `_finalize_faction_card` consumes that single pool:
  live synthesis runs one `synthesize_with_validation` call at full `SYNTHESIS_MAX_ATTEMPTS`;
  offline `WOW_LORE_WIKI_FIRST_NO_LLM` keeps the sanctioned deterministic borrow on the same
  merged pool.
- Drop auditing landed in two layers. `_record_faction_drop` writes `major_factions.finalize`
  rows keyed by `faction_id` / `faction_name` with `outcome="dropped"`, `rejected_summary`,
  `reasons`, and `attempts`; `prose_synthesis.SynthesisAttemptResult` now preserves
  `last_payload` / `last_reasons` so the drop record shows the final rejected attempt, not just
  the lowest-reason "best" failed attempt. `build_major_factions` also records
  `major_factions.candidates` with the page's candidate names for validation.
- `harvest_instance_faction_targets` now defaults to `_INSTANCE_OWN_EVIDENCE_FIELDS`
  (`history_digest`, `at_a_glance_input`, `boss_pool`, `instance_lore_pool`) for both mention
  counts and the role pool; `character_pool` and other cross-page biography/profile material are
  excluded. Structured-link support remains, but structured-link contexts are likewise restricted
  to the instance's own evidence fields, preserving the Adventure Guide / boss-section path while
  removing the Lilian-Voss-biography-to-Scarlet-Crusade false card.
- `pipeline/validate/context.py` loads `major_factions.candidates` from
  `data/decisions/prose_finalize_decisions.json` into `faction_candidate_names`; the structure
  validator emits WARN-only `structure.uncarded_current_actor` when one of those candidate names is
  present in uncarded page prose. Zone pages scan `at_a_glance` + `currently`; the review cycle
  also extended instance pages to scan `at_a_glance` + `overview`, because instances have no
  `currently` field but can otherwise name un-carded faction actors silently.
- Tests: `tests/test_faction_finalize.py` pins merged-pool ordering, full retry count on the
  single pool, and final rejected-summary/reason trace payloads; `tests/test_instance_faction_harvest.py`
  pins the Scarlet-Crusade-from-Lilian biography exclusion; `tests/test_validation_engine.py` pins
  the zone `currently` WARN and the instance `overview` WARN; `tests/test_questline_promotion_validate.py`
  pins loading candidate names from the finalize decisions sidecar. Verified: `uv run --no-sync
  ruff check pipeline tests`, `uv run --no-sync mypy` on the five touched production modules,
  `uv run --no-sync pytest -q -ra`, and `git diff --check`. Plain `uv run` still attempts an
  editable build and fails before tests on the pre-existing Hatchling direct-reference metadata
  issue, so the verification used the current resolved environment without lockfile churn.
- [LIVE] pilot effect is pending the next OpenAI-backed pilot run: the expected outcome remains
  Argent Crusade / Cenarion Circle surviving with zone-role summaries or explicit audited drops +
  coherence WARNs, and the Scholomance instance faction set excluding Scarlet Crusade.

**Original spec:**

- `pipeline/generate/draft/pages/cards.py` `_finalize_faction_card`: replace the
  pool-ladder (3 attempts on profile pool, 1 on rescue) with **one merged pool** ordered
  zone-role evidence first (seed mentions / quest-lore / currently-input claim views), then 1–2
  profile identity lead items — one `synthesize_with_validation` call at full
  `SYNTHESIS_MAX_ATTEMPTS`. Update `finalize_evidence_pools` accordingly (it becomes the merge
  function).
- On final failure, the decision record (finalize trace) must include the last attempt's
  **rejected summary text** and all reasons, keyed by faction id.
- `harvest_instance_faction_targets` (`pipeline/generate/draft/faction_scoring.py`): restrict
  mention counting and role-pool building to the instance's **own** evidence — exclude
  `character_pool` (and any cross-page biography fields) from both `counts` and `role_pool`.
  Structured-link/Adventure-Guide support stays. This removes the fabricated
  "Scarlet Crusade runs Scholomance" card class.
- New validate rule (WARN), e.g. `structure.uncarded_current_actor` in
  `pipeline/validate/rules/structure.py`: organizations named in `at_a_glance`/`currently`
  (match against the world registry's organization entries once Slice 12 lands; until then match
  against the page's own faction-candidate names recorded in decisions) that have no
  `major_factions` card. WARN only — editorial, but permanently visible.
- Tests: merged-pool ordering; full attempts on the single pool; failure record carries text;
  instance harvest ignores biography-only mentions (Scarlet-Crusade-from-Lilian regression test);
  coherence WARN fires on a page whose `currently` names an un-carded org.

**Expected pilot effect [LIVE]:** Argent Crusade and Cenarion Circle cards return with real
zone-role summaries; Alliance either cards or produces an explicit audited drop + coherence WARN.
Gold instance faction set (Scourge + Cult of the Damned, no Scarlet Crusade) restored.

## Slice 7 — Paragraph-granular evidence identity: prompts, coverage, provenance (B) — ✅ DONE (2026-07-05)

**Goal:** `canonical_evidence_id` is the working evidence identity at draft time, making the
setup-bridge coverage guarantee real and provenance pointers honest.

**Implementation notes (as built):**

- New `pipeline/generate/draft/evidence_identity.py` — the single home for paragraph-level
  identity: `evidence_id_for_item` (canonical id, else `source_id` for synthetic one-per-source
  items) and `translate_used_evidence_ids` (alias→paragraph-id resolution; unknown/hallucinated
  tokens are dropped so they can never become pointers).
- `_format_evidence_block` labels each emitted line `[p1]..[pN]` and returns
  `(block, alias_map)`; the map also carries identity entries for the items' own canonical ids
  and for source ids that name exactly one emitted paragraph (ambiguous shared source ids are
  omitted). All ten live synthesis workers translate `used_evidence_ids` through the map, so
  every `used` list is paragraph-level; offline history paths (`synthesize_history_sections`
  NO_LLM, `fallback_history_sections`) return `evidence_id_for_item` values so offline coverage
  bookkeeping matches live.
- `coverage.py` rekeyed: units keyed by `canonical_evidence_id` (unit rows carry it alongside
  the source id); `covered_coverage_ids` compares used paragraph ids — a sibling paragraph of the
  same source no longer covers a required unit, and a bare source id covers nothing. The
  claim-view-only carve-out is deleted: paragraph-only pools form units on the same single path.
  A history-pool item without a canonical id raises `ValueError` (contract violation — the
  assembling path must be fixed; draft-page tests now stamp ids via
  `tests/factories/wiki_first_pages.stamp_canonical_evidence_ids`). The appended bridge card
  records the unit's canonical id in `used`.
- `_ensure_pointer_count` deleted. `_pointers_for_source_ids`/`_items_for_source_ids` became
  `_pointers_for_evidence_ids`/`_items_for_evidence_ids` (match canonical id or source id, so
  offline source-id citations still resolve). Section pointers come only from the ids the
  synthesis reported: the per-length recommendation is single-homed as
  `contracts.models.required_pointer_count` (validate imports it too), and a shortfall is a
  **soft** retry reason (`assembly.citation_shortfall_reasons`, "cite the evidence ids each
  section draws on…", capped by the pool's own distinct paragraphs so it is always satisfiable)
  wired via a new `validate_soft` hook on `synthesize_with_validation` — soft reasons retry with
  feedback but never fail the field; on exhaustion the hard-clean attempt ships with
  `soft_reasons` recorded (`synth_guard` outcome `ok_soft` decision record). Validate-side,
  a real-but-short pointer list is now `provenance.pointer_count_shortfall` (WARN) while an
  empty pointer set on a non-empty section stays a HARD_FAIL; pointers are never fabricated.
  The two `min_count=1` card fallbacks that used the backfill (key characters, questline CTA)
  now cite the pool the card was actually synthesized from (the sanctioned Slice 6 pattern).
- Tests: `tests/test_history_coverage.py` rewritten to the production shape (every paragraph
  shares ONE `source_id`; distinct canonical ids; used ids are canonical) with the regression
  test — using paragraph A does not cover paragraph B's required setup-bridge unit and the
  coverage retry receives B's claim texts — plus contract-violation and paragraph-only-pool
  tests. New `tests/test_citation_shortfall.py` (shortfall math, driver soft-retry/ship-short,
  validate WARN vs HARD_FAIL). Evidence-block and pointer tests updated for aliases/dual-id
  matching. Verified: `ruff check pipeline tests`, `mypy` on all touched modules, full `pytest`
  (1062 passed, 5 skipped, 1 xfailed).
- The expected pilot effect below still needs the next live (`OPENAI_API_KEY`) pilot run to
  confirm on real output.

- `pipeline/generate/draft/prose_synthesis.py` `_format_evidence_block`: label items with a
  paragraph-unique id (the `canonical_evidence_id`, or a short stable alias `p1..pN` with a
  returned alias→canonical map). `used_evidence_ids` from the model are then paragraph-level;
  callers translate back to `(source_id, locator)` via the canonical records for provenance.
- `pipeline/generate/draft/coverage.py`: key coverage units by `canonical_evidence_id` — no
  `source_id` fallback. Every history-pool item must carry a `canonical_evidence_id`; if any
  assembling path produces items without one, fix that path (it is a contract violation, not a
  case to degrade around). `covered_coverage_ids` compares against used canonical ids.
  `required_event_texts` unchanged. Also delete the claim-view-only carve-out (the module
  docstring's "legacy paragraph path is left unchanged for rollout compatibility"): with
  canonical-id keying, paragraph-only pools form coverage units exactly like claim-level pools —
  there is one coverage path, and it never silently produces zero units.
- `pipeline/generate/draft/pages/cards.py` / `assembly.py`: history `used` bookkeeping, coverage
  retry, and pointer building updated for the id translation. **Delete the `_ensure_pointer_count`
  backfill entirely** — a section with too few citations is a driver retry reason
  ("cite the evidence ids each section draws on"); if still short after retries, ship the real
  (short) pointer list and record the shortfall as a decision + provenance WARN. Pointers are
  never fabricated to satisfy a count.
- **Rewrite coverage/history test fixtures so all paragraphs share one `source_id`** (the
  production shape that masked this bug) with distinct `canonical_evidence_id`s; add a regression
  test: synthesis that uses paragraph A of a page does **not** mark paragraph B's required
  setup-bridge unit covered, and the coverage retry receives B's claim texts.
- Depends on Slice 2 (budget retry) for the full "Last Holdout" outcome but is independently
  implementable.

**Expected pilot effect [LIVE]:** Scholomance history regains the last-holdout/Gandling-retreat
material as its final pre-MoP section (coverage retry now demands it); provenance pointers vary
by section instead of uniform `lead paragraph:1..3` fill.

## Slice 8 — NLP sentence boundaries, claim triggers, and lemmatized fallback scoring (B/F support) — ✅ DONE (2026-07-06)

**Goal:** use the NLP substrate for text-boundary and retrieval-support work where it is stronger
than punctuation/token regexes, while keeping semantic adjudication in the existing claim/LLM
layers.

**Implementation notes (as built):**

- `pipeline/common/linguistics.py` additions (still the only spaCy importer):
  `sentence_spans` is now lru-cached (frozen `SentenceSpan` tuples) since every lint/trim/claim
  path segments through it; `finite_clause_count(text)` counts finite clause predicates
  (verb/aux clause heads that are finite themselves or via a finite aux child; `aux`/`auxpass`/
  `amod` tokens never count) — the grammar replacement for the semicolon/word-count triage
  proxies; `coordinated_finite_clause_split(sentence)` implements the deterministic micro-split
  (single sentence, finite root with subject, exactly one finite verbal conjunct, explicit
  CCONJ junction, positional clause separation, shared-subject copy, PROPN-preservation guard —
  every uncertain shape returns `[]`); `support_tokens(text)` produces the lemmatized support
  token set with proper nouns and adpositions kept as surface text (so "above"≠"beneath").
- `prose_lint.split_sentences` delegates to `linguistics.sentence_spans` (regex and
  `_SENTENCE_SPLIT_RE` deleted; no punctuation fallback — a model failure raises
  `LinguisticsModelError`). The one remaining duplicated sentence-split regex
  (`faction_scoring._faction_focused_excerpt`) now imports `split_sentences` (one-home rule).
  All other consumers (`pages/cards.py`, `card_lint.py`, `instance_lint.py`, `faction_lint.py`,
  CTA finalizer) consume sentence texts only and needed no change.
- `claims.py`: extraction is span-based. `EvidenceClaim` gained `source_char_spans`
  (offsets into `clean_wiki_snippet(paragraph)`, parallel to `source_sentence_indexes`;
  invariant: joining the offset slices reproduces `source_excerpt`). Unambiguous coordinated
  finite clauses micro-split into per-clause claims (`deterministic_clause_split`, same
  sentence index/span/excerpt, no LLM call). `_llm_candidate_reasons` flags
  `sentence_level_claim_may_contain_multiple_events` via `finite_clause_count >= 2` on the
  deterministic claims (micro-split output, so resolved coordinations no longer trigger);
  `_LONG_SENTENCE_WORD_THRESHOLD` deleted, paragraph-level `long_paragraph` telemetry and its
  never-sufficient-alone guard kept. `_extract_claims_llm` prompts with the real sentence list
  (spans), so LLM indexes stay in sentence space regardless of micro-splits, and LLM claims get
  spans derived from their indexes. Each decision row records `segmentation`
  (`linguistics.model_info()` pin + per-sentence offsets), audit-only.
- `temporal._claim_temporal_decision_row` and `claim_routing._claim_view_for_item` pass
  `source_char_spans` through; `pages/cards.py` strips it with the other claim-only keys when
  consolidating history slots. `safe_paragraph_excerpt(views, route, *, paragraph_text)` now
  slices the cleaned paragraph at stored offsets (no re-split/re-find); a view without
  in-bounds offsets makes it return `""` (fragments fallback) since the contaminated set would
  be unknowable. `reconstruct_safe_paragraph_excerpts` supplies each item's `snippet` as the
  paragraph text; the `assembly.py`/`key_characters.py` call sites pass it explicitly.
- Lemmatized fallback scoring, one home in `pipeline/common/text_sim.py`
  (`lemma_support_containment`, `lemma_support_ratio`, both over `support_tokens` filtered to
  >= 3 chars so ubiquitous "of"/"in" cannot inflate support): `coalesce/claim_scoring.
  score_claim_against_source` = max(surface token-set ratio, lemma ratio);
  `validate/rules/fact_check._support_score` = surface containment with the lemma containment
  fallback only when surface is below every support threshold (thresholds now named constants
  `LOCAL_SUPPORT_THRESHOLD`/`WEB_SUPPORT_THRESHOLD`). Support signals only — contradiction
  still comes solely from the LLM adjudicator/markers, and report evidence rows keep raw text.
- Tests: `test_linguistics.py` (abbreviation/ADP-date boundaries, finite-clause counts,
  micro-split accept/refuse shapes, support tokens), `test_claim_extraction.py` (semicolon
  single-event stays one deterministic claim with no candidate reasons; short two-predication
  sentence triggers the LLM reason; own-/shared-subject micro-splits; offsets round-trip with
  the segmentation record; LLM claims carry spans), `test_claim_routing.py` /
  `test_evidence_block_reconstruction.py` / `test_key_character_adventure_guide.py` fixtures
  carry real-segmentation offsets (plus a refuses-without-offsets test),
  `test_text_sim.py` / `test_claim_scoring.py` / `test_validation_engine.py` (inflection
  bridged, inverted spatial relation never a perfect lemma match, already-supported surface
  scores untouched). Known sm-model weakness noted: "War rages…" tags *rages* as a noun, so
  its clause count is 0 — conservative direction (no LLM call), same class as the documented
  "labors" case. Verified: `ruff check pipeline tests`, `mypy` on all twelve touched modules,
  full `pytest` (1085 passed, 5 skipped, 1 xfailed).

- In `pipeline/generate/draft/prose_lint.py`, make `split_sentences` delegate to
  `linguistics.sentence_spans` while preserving the current public return type (`list[str]`).
  There is **no punctuation fallback**: the model is a standard dev/CI dependency (Slice 4), so
  tests run real segmentation, and a model-load failure in production is an explicit error rather
  than silently changed sentence boundaries.
- API choice per call site: `split_sentences` (`list[str]`) stays the convenience API for lint
  checks that only need sentence *texts*. Any path that needs positions — claim extraction,
  claim-view excerpts, provenance sidecars — must call `linguistics.sentence_spans` directly for
  its offsets instead of round-tripping through the string list and re-finding substrings.
- Update all sentence-boundary consumers to tolerate NLP segmentation:
  `pipeline/generate/draft/claims.py`, `claim_routing.py`, `pages/cards.py`, `card_lint.py`,
  `instance_lint.py`, `faction_lint.py`, and questline/CTA trimming paths. Preserve source
  offsets when building claim-view excerpts and provenance sidecars.
- Runs are self-contained (Slice 1 made run ids immutable) and old artifacts are regenerated,
  never migrated or reinterpreted — cross-run sidecar compatibility is a **non-goal**. Record the
  segmentation model pin (`linguistics.model_info`) in the claim-extraction decisions purely for
  audit, and store character offsets for claim views because offsets are the honest provenance
  coordinate within the run — not to interoperate with pre-NLP sidecars.
- In `pipeline/generate/draft/claims.py`:
  - Keep deterministic sentence claims for cheap coverage, but use NLP clause/finite-verb counts
    in `_llm_candidate_reasons` instead of semicolon/word-count proxies alone. A long single-event
    sentence should not spend an LLM call solely because it is long; a sentence with multiple finite
    event/state predicates should.
  - Add an optional deterministic micro-split only for unambiguous coordinated finite clauses when
    each clause has its own subject or shared subject and the split preserves named entities. If
    the parser is uncertain, leave the sentence whole and let the existing LLM semantic splitter
    handle it.
  - Preserve the sentence-backfill guarantee: LLM semantic claims never cause an original source
    sentence to disappear from the sidecar.
- In deterministic fallback scoring (`pipeline/coalesce/claim_scoring.py`,
  `pipeline/validate/rules/fact_check.py`, and `pipeline/common/text_sim.py` where appropriate),
  add lemmatized-content-token variants for retrieval/support heuristics. Use them only as
  fallback ranking/support signals, not as contradiction judges. Proper nouns and exact location
  prepositions ("above", "beneath", "inside", "near") must stay visible in evidence rows so Slice
  15's assertion adjudicator can inspect them.
- Tests:
  - abbreviations and ADP dates do not split incorrectly;
  - semicolon-heavy but single-event sentences remain one deterministic claim unless the NLP
    feature set clearly supports a split;
  - multi-event sentences trigger LLM claim extraction for semantic splitting;
  - lemmatized fallback scoring improves inflection/paraphrase cases without marking an inverted
    spatial relation supported;
  - claim-view provenance offsets/source sentence indexes are internally consistent within a run
    (excerpt reconstruction from offsets round-trips).

**No pilot-run dependency. This is not a replacement for Slice 15's assertion-level fact-check; it
just makes deterministic fallback and LLM-call triage less brittle.**

## Slice 9 — Point-of-use temporal adjudication for card pools; one exclusion policy (C) — ✅ DONE (2026-07-06)

**Goal:** evidence that feeds *rendered cards* is always temporally adjudicated; "ambiguous"
means excluded, everywhere.

**Implementation notes (as built, 2026-07-06):**

- New `pipeline/generate/draft/pool_policy.py` is the single home for the temporal exclusion
  policy: `EXCLUDED_CARD_POOL_SCOPES = {post_active_lore, active_storyline_outcome,
  excluded_noncanon, ambiguous_temporal}` (the plan's exact set) plus `card_pool_scope`
  (item scope with `build_meta` fallback), `is_excluded_from_card_pool`,
  `filter_card_pool` (drops excluded; unscoped kept), and `row_has_admissible_item`. `active_storyline`
  (an active belligerent's ongoing conflict) is deliberately NOT excluded — the Slice 6 reconciliation:
  only the *outcome* (spoiler resolution) is filtered, so a seed-only active combatant keeps the
  current-conflict evidence that justifies its card.
- `faction_scoring` single-homed onto it: `_EXCLUDED_TEMPORAL_SCOPES` (the drifted 3-scope set,
  missing `active_storyline_outcome`), `_item_temporally_excluded`, and
  `_row_has_temporally_allowed_item` were **deleted**; the four call sites now import
  `is_excluded_from_card_pool` / `row_has_admissible_item`. Net effect on discovery/scoring:
  `active_storyline_outcome` is now excluded there too (a correct tightening — an outcome should not
  count as a faction mention or seed the identity summary).
- Point-of-use worker `adjudicate_pool_items_point_of_use(items, records_by_canonical_id)` in
  `temporal.py`: collects the still-`ambiguous_temporal` paragraphs among `items` (deduped by
  `canonical_evidence_id`), runs the **existing** `adjudicate_canonical_temporal_classifications_llm`
  batching over just their canonical records, applies `_with_canonical_history_defaults`, writes the
  resolved scope back onto every matching item, and returns one decision row per adjudicated
  paragraph (carrying the rejected snippet + prior/new scope). No-op when the LLM is disabled
  (offline / no key) or a record is missing, so offline runs keep their ambiguous scope and are then
  dropped by `filter_card_pool` — behaviour-neutral. It does **not** know the exclusion set (that
  concept lives only in `pool_policy`, avoiding a temporal↔pool_policy import cycle).
- `pipeline/generate/draft/point_of_use_temporal.py` wires it in via a contextvar registry
  (`begin`/`clear`/`adjudicate_card_pool`), mirroring `finalize_trace` so the card builders need no
  signature plumbing. `enrich_evidence_temporal_metadata` gained `return_canonical_records=True`;
  `draft_writer` builds the `{canonical_evidence_id: record}` map once after enrich and calls
  `point_of_use_temporal.begin(...)` **inside `_write`** (the per-entity worker thread — a
  `ThreadPoolExecutor` does not copy contextvars, same reason `finalize_trace.begin` lives there).
- Each adjudicated paragraph is recorded to the per-entity finalize trace
  (`data/decisions/prose_finalize_decisions.json`) under stage `temporal.point_of_use` with the
  `point_of_use` marker and an `excluded_from_synthesis` flag (derived in the orchestration layer
  from `pool_policy`). **Deliberate deviation from the spec's "same decisions sidecar":** point-of-use
  is a draft-time, per-page decision, so it uses the existing draft-decision recorder
  (`finalize_trace`) rather than the enrich-time temporal sidecar; the enrich verdict stays in
  `canonical_temporal_decisions.json` and the override is joinable by `canonical_evidence_id`. This
  avoids a new sidecar and heavy return-plumbing while keeping the drop fully auditable (policy 5).
- Assembly (`pages/assembly.py`): the bulk **profile** pools now retain ambiguous paragraphs into
  the card builders — `_FACTION_PROFILE_TEMPORAL_SCOPES = {pre_entry, entry_state, ambiguous}` and
  `_LOCATION_PROFILE_TEMPORAL_SCOPES = {pre_entry, entry_state, active_storyline, ambiguous}` — so
  point-of-use has something to adjudicate. The already-vetted whitelists for the claim-eligible
  page-prose pools (at_a_glance / currently / history / boss / instance-lore) are unchanged: those
  fields were adjudicated at enrich time and are a separate concern from Cause C's faction/location
  cards. This is the plan's "discovery/scoring may keep looser admission, but synthesis input is
  uniformly filtered" split.
- The synthesis-input boundary is one shared seam: `cards._vet_card_pools(queue, label=...)` — called
  in `build_major_factions` and `build_location_cards` **after election, before the finalize loop** —
  runs point-of-use over the elected (bounded) candidates' pools, then applies `filter_card_pool` to
  each candidate's `profile_items` / `seed_mentions` (before `finalize_evidence_pools` merges/leads,
  so a resolved-post-active paragraph never takes a lead slot). Un-elected candidates are never
  vetted (the cost bound). No claim-eligible page-prose whitelist was replaced; only the
  faction/location card path — the exact bypass Cause C names.
- Tests (`tests/test_point_of_use_temporal.py`, 11): `pool_policy` (four-scope floor, drop/keep incl.
  unscoped, `build_meta` fallback, `row_has_admissible_item`); the worker (adjudicate+write-back with
  auditable rejected text, offline no-op, orphan-id skip, non-ambiguous untouched);
  `adjudicate_card_pool` records the `excluded_from_synthesis` flag to the finalize trace;
  `_vet_card_pools` adjudicates-then-filters an elected candidate and leaves an un-elected candidate's
  paragraphs un-adjudicated (cost bound); and a post-active location paragraph never reaches the
  location-summary prompt (captured pool). Verified: `ruff check pipeline tests`, `mypy` on the seven
  touched production modules (tests follow the repo convention of unannotated `monkeypatch`/helpers,
  as the existing temporal tests do), full `pytest` green (exit 0). The [LIVE] pilot effect below is
  pending the next OpenAI-backed pilot run.

- After faction/location candidate election (in `pages/cards.py` build paths, before finalize),
  collect the elected candidates' pool paragraphs that are still `needs_llm`/`ambiguous_temporal`
  and run the existing canonical LLM boundary adjudication over just that set (reuse
  `adjudicate…llm` batching from `temporal.py`; bounded ≈ cards × pool cap ≈ ≤100 paragraphs).
  Write results into the same decisions sidecar with a `point_of_use` marker.
- Add one shared pool-assembly filter (single home, e.g. `wiki_evidence_filters` or a small
  `pool_policy` module): exclude `{post_active_lore, active_storyline_outcome, excluded_noncanon,
  ambiguous_temporal}` from all card synthesis pools. Replace the scattered per-module scope
  checks (`_row_has_temporally_allowed_item`, `_item_temporally_excluded`, ad-hoc filters in
  assembly) with it. Discovery/scoring may keep looser admission, but **synthesis input** is
  uniformly filtered.
- Tests: an elected candidate's ambiguous paragraphs get adjudicated (mock LLM) and the pool is
  filtered by the shared policy; an un-elected candidate's paragraphs are not adjudicated (cost
  bound); a post-active location paragraph never reaches the location-summary prompt.

**Expected pilot effect [LIVE]:** the Hearthglen card loses the unvetted BfA transit sentence;
card pools shrink to vetted evidence (watch for newly-thin pools — that is signal, not noise).

## Slice 10 — Location & boss-role classification via structured outputs (H-3) — ✅ DONE (2026-07-06)

**Goal:** delete the first-match keyword ladders; classification enums ride existing LLM calls,
with wiki categories first.

**Implementation notes (as built, 2026-07-06):**

- **Location typing** is now `location_scoring.location_type_from_signals(categories, *, infobox,
  llm_type)` — one home, structured signals only: `_category_type` (the kept `_CATEGORY_TYPE_RULES`)
  → `_infobox_location_type` (reads an infobox `type`/`location_type` field, inert until the Slice 12
  re-crawl populates `infobox`) → the LLM's own enum → `major_location`. **Deleted:** `_TYPE_NAME_TOKENS`
  (name-token ladder), `_RUINS_TEXT_RE`/`_TOWN_TEXT_RE` (evidence-text overrides), `_CURRENT_SETTLEMENT_TYPES`.
  The old signature `(name, evidence_text, categories)` is gone; the routing *classification* enum stays a
  discovery signal, never the card type.
- **Location significance** is `location_significance_from_signals(*, llm_tag)` — LLM enum → `major_location`.
  No MediaWiki category or infobox field maps onto the significance vocabulary (they describe *what* a place
  is, not *why it matters*), so — unlike type — significance has no structural source; it is purely the LLM's
  classification, else the default. **Deleted:** `location_significance_tag` (the keyword ladder) and its
  helper `_category_text`. `collect_location_candidates` no longer sets `candidate.significance_tag`; the
  selection-time default stands (the `_is_contained_location` quest-hub/instance-anchor exemption that relied
  on the keyword ladder is retired with it — an edge case, no pilot regression expected), and the tag is
  finalized at card-build time.
- **`synthesize_location_summary`** now returns `(summary, used, location_type, significance_tag)`; the two
  enums ride the existing LLM call as required, schema-`enum`-constrained (LocationType values /
  `SIGNIFICANCE_TAGS`) with a prompt line "classify, from the evidence, this place's location_type … and its
  significance_tag …". Offline / no-LLM returns both enums empty — deterministic card typing never depends on
  a keyword guess. `pages/cards.py` `_finalize_location_card` threads the enums through the offline path and
  the live `synthesize_with_validation` payload; `_build_location_card_body` applies the precedence
  (categories → infobox → LLM → default). `_location_evidence_text` deleted (no keyword detection left);
  `LocationCandidate` gained an inert `infobox` field (populated from the candidate-map row, empty pre-Slice-12).
- **Boss/character role**: `instance_bosses.classify_character_role` now always returns
  `("uncertain", "no_signal")` — role (enemy/ally/neutral) is a semantic LLM judgment, so the emit path's
  existing `if role == "uncertain": classify_key_character_role_llm(...)` makes the LLM primary for **every**
  emitted card, and offline the role is honestly `uncertain`. **Deleted:** `_ENEMY_DESCRIPTORS` /
  `_ALLY_DESCRIPTORS` / `_NEUTRAL_DESCRIPTORS`, the `_ENEMY_LEAN_TOKENS` / `_NPC_LEAN_TOKENS` lean-token
  scoring, and `_candidate_profile_text`. Structural signals (boss-section membership, Adventure Guide,
  roster links) are untouched and now drive **presence/eligibility only** (`is_high_confidence_boss_section`,
  `must_include_key_character_names`, `_significance_score`/`_section_weight` ranking). `draft_writer`'s
  sidecar dropped its now-vacuous `classify_character_role` fallback (and the unused `instance_name` param).
- **Offline / [LIVE] split:** offline, the retired ladders mean location cards get category-or-default
  types and `major_location` significance, and bosses get `uncertain` roles — behaviour-neutral against the
  suite (no offline test compares generated type/significance/role to the WPL gold; gold is the live-regen
  target per memory `draft-stage-requires-openai`). Two known offline divergences are now [LIVE]-only: Caer
  Darrow's gold `ruins` (its category is a keep/fortress, so offline yields `fortress`; the LLM reads the
  ruined description) and every non-default significance tag (Uther's Tomb `sacred_landmark`, Andorhal
  `battlefield`, Hearthglen `faction_stronghold`, Caer Darrow `instance_anchor`) — all pending the next
  OpenAI-backed pilot run.
- Tests: `test_location_type_significance.py` rewritten to the structured-signal precedence (category
  authoritative + first-match, category-beats-LLM, infobox-when-no-category, LLM-when-no-category/infobox,
  invalid-enum-ignored, default) + a card-body Uther's-Tomb test (`sacred_landmark`, never `battlefield`)
  and a category-wins-over-LLM card test; keyword-ladder tests deleted. `test_wiki_first_workers.py` updated
  for the 4-tuple + a mocked-LLM test asserting the enums flow out. `test_instance_bosses.py` collapsed the
  three descriptor role tests into one "always uncertain deterministically". `test_instance_page_draft.py`
  faculty-roster assertion flipped from all-`enemy` to all-`uncertain` (offline). Verified: `ruff check
  pipeline tests`, `mypy` on the five touched production modules, full `pytest` (1092 passed, 5 skipped,
  1 xfailed).

- `pipeline/generate/draft/prose_synthesis.py` `synthesize_location_summary`: add `location_type`
  and `significance_tag` (existing enums) to the response JSON schema and prompt ("classify from
  the evidence"). `pipeline/generate/draft/location_scoring.py` /
  `pages/cards.py` `_build_location_card_body`: precedence becomes wiki-category rules
  (`_CATEGORY_TYPE_RULES` — keep) → optional infobox type/affiliation fields when already present
  on the snapshot → LLM enums → `major_location`/`landmark` default. Do not block Slice 10 on new
  ingest fields; before Slice 12, missing infobox data simply means this step is skipped.
  **Delete** `location_type_from_signals`' text-keyword ladder, `_RUINS_TEXT_RE`/`_TOWN_TEXT_RE`
  overrides, and the significance keyword ladder (`_significance…` first-match chain). Offline
  NO_LLM path: categories → optional infobox fields if present → default (never keywords).
- Boss/character narrative roles (`pipeline/discovery/instance_bosses.py` +
  `prose_selection.classify_key_character_role_llm`): the LLM classification becomes primary for
  every emitted card (it already runs for `uncertain`); **delete** `_ENEMY_DESCRIPTORS` /
  `_ALLY_DESCRIPTORS` / `_NEUTRAL_DESCRIPTORS` / lean-token scoring, keeping structural signals
  (boss-section membership, Adventure Guide, roster links) for *presence/eligibility* only.
  Offline: role = `uncertain` honestly, not keyword-guessed.
- Tests: Uther's-Tomb-shaped fixture (tomb evidence mentioning a war) classifies
  `sacred_landmark` via mocked LLM enum, never `battlefield`; category rule still wins over LLM;
  keyword-ladder tests deleted.

**Expected pilot effect [LIVE]:** Uther's Tomb `significance_tag` correct; no other regressions
expected on pilot (categories carry most cases).

## Slice 11 — Pilot eviction from shared code, data, and prompts (H-4) — ✅ DONE (2026-07-06)

**Goal:** zero pilot facts outside `tests/fixtures/pilot/`; a guard that keeps it that way.

**Implementation notes (as built, 2026-07-06):**

- `questline_significance.py`: `_WPL_PILOT_ZONE_ID` / `_WPL_PILOT_MAX_CARDS`, the `if zone_id`
  branch, and the whole `pilot_max_cards` / `pilot_cap` parameter plumbing deleted (production
  never passed it; only a test did). Card count = clusters clearing the threshold (or the
  registry oracle where one exists), capped by `ZONE_MAX_TOTAL_QUESTLINE_CARDS`. **Pilot
  output unchanged** — the WPL registry still yields exactly gold's 4 cards, so no gold
  reconciliation was needed; the cap was dead belt-and-suspenders.
- Vocab: all three WPL tokens removed from `entry_quest_title_keywords` (the plan named two;
  the file held both `'audience with the highlord'` variants) — only `"hero's call"` /
  `"warchief's command"` remain. WPL gold anchors are unaffected: all four gold arcs are
  registry-mapped and `questline_card_polish` overrides their `start_anchor` from the registry.
  `questline_card_polish`'s entry-anchor telemetry now imports `ENTRY_QUEST_TITLE_KEYWORDS`
  (one home) instead of its own drifted copy that still contained `"new era"`/`"audience"`.
- Prompt exemplars replaced with an invented-lore family extending the tests' Archive Vault /
  Archivist Maelor convention (zone *Vellmire*, force *the Hollow Court*, factions *Lantern
  Wardens* / *Emberwake Pact*, town *Maelor's Crossing*, family *House Veldar*, event *Breaking
  of Vellmire*, headings like *Rise of the Curse-Bound*): `compendium_voice.py`
  (`AT_A_GLANCE_VOICE`, `CURRENTLY_VOICE`, `HISTORY_VOICE`, `INSTANCE_AT_A_GLANCE_VOICE`) and
  `prose_synthesis.py` (at-a-glance force reference, currently faction-precision exemplar,
  history heading exemplars, relabel-headings exemplars). Same shapes conveyed. Code *comments*
  that cite pilot lore as documentation of gold/defects were deliberately left (they are not
  prompts and not decision inputs; the vocab files' `_pilot_bias_note` fields set precedent).
- Guard: new `tests/test_pilot_prompt_leak_guard.py` harvests forbidden names from
  `tests/fixtures/pilot/` (zone/instance names, faction/location/key-character card names,
  questline titles *and* start anchors, gold history headings; `Alliance`/`Horde` excluded as
  game-wide) and renders **every** prompt site in the pipeline for an invented subject by
  monkeypatching each module's LLM entry point with a recorder: all 12 `prose_synthesis`
  synth calls, 4 `prose_selection` selectors, 3 `workers`, 2 `planner`, all 6 `legacy`
  generators, `temporal` (claim-temporal + adjudication builders, active-expansion,
  contract-distillation), `claims` extraction, `fact_check` adjudication, `resolve_entities`
  coalesce, and the `compendium_voice` fragments. Every renderer must capture ≥1 prompt
  (coverage can't silently rot); a leak names the renderer and the pilot string.
  Negative-tested by reinjecting `"the Scourge's blight"` — the guard fails, restored it
  passes. `_FORBIDDEN_PILOT_PROMPT_STRINGS` and its single-prompt test deleted.
- `world_registry.py`: `_is_instance_parent` (40+ name markers incl. `'scholomance'`) deleted.
  `build_world_registry` now ingests the article-category seeds (Dungeons/Raids/Instances →
  `instance`) *before* the Subzones sweep, and `_parent_kind_from_entries` classifies a
  subzone parent by looking up its already-ingested entry kinds — the in-build equivalent of
  an `entry_kinds` lookup (the on-disk `entry_kinds()` would be self-referential during a
  rebuild). Unknown parents default to `zone`. Committed `world_registry.json` is untouched;
  the change takes effect on the next registry rebuild.
- Glossary: static `dictionary/glossary_aliases.v1.json` (pure WPL/Scholomance terms) deleted.
  Fallback paths removed from `build_bundle.py` **and** `linker/linker.py` (the plan named
  build_bundle/run_terms, but the linker also consumed the file — required for "remove the
  dictionary if nothing else consumes it"); `run_terms.py` docstring updated. Missing
  run-terms now degrades to metadata-less refs (bundle: `glossary: metadata_less_refs`) or an
  empty alias set (linker: `glossary: empty_run_terms`), each with a `degraded` trace event —
  never to WPL terms.
- `pilot_questline_registry.py` / `questline_arc_map.py` docstrings reclassify the registry as
  gold/QA scaffolding (pilot-only validator/override; the generic `ql-<slug>` path is the
  general path). The runtime copy stays in `pipeline/data/pilot/` because the validate-stage
  promotion gates load it at runtime — it is pilot-only scaffolding by contract, not general
  pipeline data. New `tests/test_questline_general_path.py` builds WPL questlines with all
  three registry loaders disabled and asserts structurally valid cards (non-empty, capped,
  score/borderline inclusion reasons, generic `ql-*` ids, non-empty titles/anchors, zero
  registry-mapped/unmapped counts). Also new: linker/bundle degraded-path tests and a
  `_parent_kind_from_entries` unit test; `test_linker_stage.py`'s first test now injects its
  alias dictionary like its siblings instead of relying on the deleted static fallback.
- Verified: `ruff check pipeline tests`, `mypy` on the twelve touched production modules, full
  `pytest` (1096 passed, 5 skipped, 1 xfailed). Offline pilot output is unchanged (gold
  questline/anchor tests green), matching the expected-effect note below.

- `pipeline/discovery/questline_significance.py`: **delete** `_WPL_PILOT_ZONE_ID` /
  `_WPL_PILOT_MAX_CARDS` and the `if zone_id == …` branch. Card count = clusters clearing the
  significance threshold, capped by `ZONE_MAX_TOTAL_QUESTLINE_CARDS` (Option A, chosen). If the
  WPL pilot then yields a different count than gold's 4, reconcile gold deliberately and update
  `tests/fixtures/pilot/` + the questline gold tests in the same pass.
- `pipeline/data/discovery_classification_vocab.v1.json` `entry_quest_title_keywords`: remove
  `'new era for the plaguelands'` and `'an audience with the highlord'`; keep `"hero's call"` /
  `"warchief's command"` (game-wide conventions).
- Prompt exemplars (`pipeline/generate/draft/prose_synthesis.py`, `compendium_voice.py`): replace
  every WPL/Scholomance-lore example ('Scourging of Lordaeron', 'Coming of the Argent Dawn',
  'Battle for Andorhal', 'Before the Scourge', 'Rise of the Dead', "'Forsaken', not the generic
  'Horde'; 'Scarlet Crusade', not 'humans'", "'the Scourge'") with invented-lore exemplars
  (follow the tests' "Archive Vault / Archivist Maelor" convention) conveying the same shape.
- Generalize the pilot-leak guard: a test that renders **every** system/task prompt builder for a
  fake subject and asserts no name from `tests/fixtures/pilot/` (zone/instance names, faction
  names, location names, questline titles harvested from the gold fixtures) appears. Replace the
  single-prompt `_FORBIDDEN_PILOT_PROMPT_STRINGS` check with this; keep the mechanism.
- `pipeline/discovery/world_registry.py` `_is_instance_parent`: replace the hardcoded name
  markers (`'scholomance'`, `'stratholme'`, `'deadmines'`, suffix list) with an `entry_kinds`
  registry lookup (instance-ness already flows from Category:Dungeons/Raids seeds).
- Glossary: delete the static `dictionary/glossary_aliases.v1.json` fallback path in
  `pipeline/addon/build_bundle.py` / `pipeline/glossary/run_terms.py` — missing run-terms
  degrades to metadata-less refs plus a trace event, never to WPL terms. Remove the dictionary
  file if nothing else consumes it.
- `pipeline/discovery/pilot_questline_registry.py`: reclassify as gold/QA scaffolding — the
  general path must produce questline cards without it. Add a test that builds WPL questlines
  with the registry disabled and gets structurally valid (if not gold-identical) cards; the
  registry remains a *validator/override* for the pilot only, clearly named as such.

**Expected pilot effect [LIVE]:** questline output may diverge from gold (deliberate
reconciliation); everything else should be output-neutral on the pilot — which is exactly the
point: these were invisible on WPL and load-bearing everywhere else.

## Slice 12 — Ingest: inline paragraph links + infobox fields + organization registry (H-1 enablers) **[RE-CRAWL]** — ✅ DONE (2026-07-06, incl. re-crawl)

**Goal:** capture the wiki's own structure so later slices can consume it. Batch *all* ingest
schema additions here so only one re-crawl is needed.

**Implementation notes (as built, 2026-07-06):**

- **Per-block inline links** live in the block-extraction substrate `wiki_html.content_blocks`
  (not per-caller): every emitted block now carries `links: [{anchor_text, href}]` — document
  order, deduped per block by resolved href (first anchor wins), text-less icon/image anchors
  skipped. New single home `wiki_html.wiki_article_href` canonicalizes hrefs to **site-relative
  `/wiki/…` paths** (absolute `warcraft.wiki.gg` origins stripped, fragments stripped) — that is
  the "resolve" the plan asked for, chosen because the registry's `wiki_path` uses the same form,
  so Slice 13 can match link targets to organizations by string. Links ride *all* block types
  (paragraph/list_item/table_cell), matching the "every crawled block" requirement.
- **Threading:** `fetch_wiki._extract_sections_and_links` copies each block's links onto the
  section dict; `run_fetch_wiki` normalizes blocks on write (`_snapshot_section_blocks`) and
  traverse's `_persist_section_block` keeps `links` (both writers guarantee the key even for
  non-extractor `FetchedSource` producers, e.g. test mocks). `quest_lore.extract_quest_lore`
  snippets keep their source block's links, so **both** enrich evidence paths (quest-lore rows
  and the per-block loop) emit `evidence_items[].links` via `enrich._block_evidence_links`.
  `EvidenceItem` gained `links: list[EvidenceLink]` (new contract model; empty default).
  Verified end-to-end on the fresh crawl: all 1332 evidence items carry the key, 1007 non-empty,
  across every pool (faction_pool 216, location_pool 294, quest_lore 319, …).
- **Infobox:** capture already existed since commit `889cf51` (both fetch + traverse paths;
  `parse_infobox` label→value pairs — live-verified `Type` / `Affiliation` / `Location` on the
  pilot pages). This slice added the missing **title**: the leading header-only banner row is
  stored under the reserved `"_title"` key (cannot collide with a character infobox's real
  `Title` label; later header-only rows are in-box section headers and stay skipped). Two
  review-cycle fixes made Slice 10's category → infobox → LLM precedence actually fire after the
  re-crawl: `draft_writer` now threads each location-profile snapshot's `infobox` onto its
  candidate-map row (next to the existing `categories` threading), and
  `location_scoring._infobox_location_type` matches keys case-insensitively (`parse_infobox`
  preserves the wiki's `"Type"` casing; the old exact lookup on `"type"` was a silent no-op).
- **Snapshot loading has one home:** new `pipeline/ingest/snapshots.py` —
  `load_source_snapshots(path, *, missing_ok=False)` + `SnapshotSchemaError` ("re-crawl required",
  names the offending source_id). Requires `infobox` to be a dict and every `section_blocks[]`
  entry to carry a `links` list; empty dict/list are explicitly valid data conditions. All eight
  consumers re-pointed (enrich, discovery workflow, glossary run_terms, draft_writer,
  validate/context, coalesce resolve_entities, normalize_source, traverse state). The one
  deliberate exception: `orchestrator/stages._resolve_instance_roster_identities` keeps its raw
  best-effort read — it re-reads the file `run_fetch_wiki` wrote seconds earlier in the same
  stage inside broad error handling, so it can never see a stale shape.
- **Organization registry:** the plan's category names don't exist on the wiki — the real
  taxonomy is `Category:Organizations` (lore groups) + `Category:Factions` (gameplay factions),
  with umbrella affiliation carried by `Category:Alliance factions` / `Category:Horde factions`
  membership, **no** neutral category (neutrality = absence of umbrella membership), and racial
  org categories swept live from `Category:Organizations by race` subcategories (mirrors the
  Subzones sweep — never hand-listed). `RegistryEntry` gained `affiliations` (union-merged);
  new `entry_affiliations()` accessor beside `entry_kinds()`. Concept/list articles ("Faction",
  "Organization", "Alliance organizations") are meta-filtered (`_META_ARTICLE_TITLES` +
  `\borganizations$` in `_META_TITLE_RE`). Registry version bumped to **3**; committed
  `world_registry.json` rebuilt live: 11297 entries, **1388 organizations**, 51 with
  affiliations (28 alliance / 23 horde); Argent Crusade, Cenarion Circle, Alliance, Horde,
  Forsaken all resolve as organizations. The rebuild also actualized Slice 11's deferred
  subzone-parent semantics (74 instances lost their bogus `zone` kind — Black Temple et al.;
  8 wiki-uncategorized parents like Icecrown Citadel flipped instance→zone), exactly as Slice
  11's notes predicted for "the next registry rebuild". All existing kind consumers enumerate
  explicit kind sets, so the new `organization` kind is inert until Slice 13.
- **Tests:** `test_wiki_html` (block links order/dedupe/icon-skip/normalization,
  `wiki_article_href`, `_title` capture; no-infobox → `{}` already covered); new
  `tests/test_ingest_snapshots.py` (old-shape → "re-crawl required" naming the snapshot,
  empty-infobox/links valid, missing_ok, non-array); `test_world_registry` (committed registry
  has >100 orgs with affiliations; mocked-fetch seed test incl. racial sweep + affiliation
  union + meta filtering); `test_location_type_significance` wiki-cased `"Type"` test. Pinned
  `ingest_parser_cases.json` regenerated (assertion-guarded: only `sections[].links` changed).
  Hand-built snapshot fixtures across 6 test files upgraded via new
  `tests/factories/snapshots.with_required_snapshot_schema` (the fixture builder for the
  post-Slice-12 shape).
- **Re-crawl done:** fresh pilot crawl `test-run-wpl-26` (ingest → discovery → traverse_seed →
  enrich roster → traverse_quests → enrich cluster/significance/card_polish/evidence_merge; the
  LLM stages await the next live pilot, per `draft-stage-requires-openai`). Page population is
  identical to `test-run-wpl-25` (111 snapshots; same per-role counts), 96/111 snapshots carry a
  non-empty infobox, 6771/8646 blocks carry links, and the whole set loads through the schema
  guard while `test-run-wpl-25` is now rejected with the re-crawl error (stale by decree).
  Verified: `ruff check pipeline tests`, `mypy` on all sixteen touched production modules, full
  `pytest` (~1110 passed, 5 skipped, 1 xfailed).

- `pipeline/ingest/fetch_wiki.py` block extraction: record each paragraph block's inline links as
  `links: [{anchor_text, href}]` on the block (resolve relative `/wiki/…` hrefs; keep order;
  dedupe per block). Thread through snapshots → enrich evidence items (`evidence_items[].links`).
- Capture page infobox key fields at ingest (at minimum the location/faction infobox `type`,
  `faction/affiliation`, and title) onto the snapshot (`infobox: {…}`), making Slice 10's optional
  category → infobox → LLM precedence reliable after the re-crawl and enabling Slice 13's faction
  typing.
- `pipeline/discovery/world_registry.py`: add organization category seeds
  (`Category:Organizations`, `Category:Alliance organizations`, `Category:Horde organizations`,
  and the neutral/racial org categories present on the wiki) producing `kind="organization"`
  entries; record each entry's umbrella affiliations from its category memberships (this replaces
  `_BINDING_BY_FACTION_ID` in Slice 13).
- The new fields are **required schema** from this slice on: every crawled block carries `links`
  (empty list when the paragraph has none), every snapshot carries `infobox` (empty dict when the
  page genuinely has no infobox — a data condition, handled), and the registry always includes
  organization kinds. There are no dual-shape loaders: the slice ends with a fresh full crawl,
  and pre-slice snapshots/artifacts are stale — regenerate them, never special-case them. A
  snapshot missing the new keys is rejected at load with a clear "re-crawl required" error.
- Tests: extraction fixtures (HTML → blocks with links; infobox parse; a page with no infobox
  yields an empty `infobox`); registry seeds org kinds; loading an old-shape snapshot raises the
  re-crawl error.

## Slice 13 — Link-based faction recognition; delete the faction vocabulary (H-1 consumers) — ✅ DONE (2026-07-07)

**Goal:** faction mentions and identities come from links + the organization registry; the
name-shape vocabulary dies. **Depends on Slice 12 (+ a re-crawled run for live verification).**

**Implementation notes (as built, 2026-07-07):**

- **Registry is the one home for org identity/umbrella.** `world_registry.py` gained the Slice 13
  lookup surface, all cached: `registry_index` now memoizes per path via `_registry_index_for`
  (the 11k-entry JSON was re-parsed on every link before — link-based recognition looks up per
  inline link); `title_from_wiki_href` (href/bare-path → article title, unquoted, fragment/query
  stripped); `organization_entry` / `organization_entry_for_href` (title/href → registry row iff
  `kind="organization"`); `umbrella_organizations` (display-title → tag) + `umbrella_faction_tags`,
  both **derived** — the tag vocabulary is the set of affiliation values the org-category seeds
  recorded (`Category:Alliance factions` / `Category:Horde factions`), and each umbrella is the
  registry org bearing that title. On the committed registry this yields exactly
  `{"Alliance": "alliance", "Horde": "horde"}` with **no** hand-listed faction names.
- **Links thread into the draft pools.** `assembly._iter_evidence_items` and
  `claim_routing._claim_view_for_item` now copy each evidence item's Slice-12 `links` onto the
  pool item / claim view (empty list when absent), so both the offline paragraph path and the
  live claim-view path carry the block's inline article links to the scorer.
- **`faction_scoring.py` rewrite.** Deleted `_FACTION_NAME_RE`, `_phrase_is_faction`,
  `_faction_token_set`, `_STANDALONE_FACTION_NAMES`, `_canonicalize_faction_phrase`,
  `_is_generic_role_alias_phrase`, `_LEADING_QUALIFIER_RE`/`_ROLE_ALIAS_RE`/
  `_GENERIC_ROLE_ALIAS_HEADS`, the static `_BINDING_BY_FACTION_ID`, `_ALLIANCE_HORDE_IDS`, and the
  static `_UMBRELLA_TAG_BY_ID`. A **mention is now an inline link** whose target resolves to a
  registry organization (`_organization_from_link` prefers the ingest `canonical_path` redirect
  annotation, else the raw href; `_item_organization_links` dedupes per item by normalized title).
  Instance harvest and seed-mention discovery are two-pass: links **establish** an identity (the
  org's canonical registry title, so anchor wording like "Acolytes of the Cult" never mints a
  name), then plain-text name matching counts that established identity across the page's other
  paragraphs (wiki links only the first mention) — **no open-vocabulary phrase matching**.
  `resolve_canonical_faction_name` kept as a thin registry-consulting fallback for stored string
  targets (`"Horde Forsaken"` → `"Forsaken"` via `organization_entry`); `merge_variant_faction_candidates`
  kept and now also unions candidate `affiliations`. `_PROPER_NOUN_PHRASE_RE` (the old
  `_FACTION_NAME_RE` pattern, a general-grammar Title-Case matcher) survives **only** in
  `harvest_instance_anchor_tokens`, which harvests frequent place/figure proper nouns as summary
  anchors — never faction identities.
- **Bindings/umbrella derive from the registry + infobox.** `_bindings_for_faction(faction_id,
  name, affiliations)` replaces the static map: an umbrella faction matches only its own tag; every
  other faction matches its name slug + `shared`/`neutral` + any umbrella side it belongs to.
  Membership (`FactionCandidate.affiliations`) comes from the org registry's category affiliations
  **and** the crawled profile page's infobox `Affiliation` field — the latter is load-bearing
  because `Category:Horde factions` holds gameplay reputation factions ("Undercity (faction)"), not
  the lore org "Forsaken"; the Forsaken page's own infobox (`Affiliation: Horde , …`, captured at
  ingest since Slice 12) is what marks it Horde. `collect_faction_candidates` gained a `snapshots`
  param (threaded from `build_major_factions` ← zone/instance page builders) to read those infoboxes.
  `_suppress_umbrella_factions`, `_discover_candidates_from_v3_bindings`, and the Alliance/Horde
  conflict gate all now key off `umbrella_organizations()`.
- **Discovery targets from seed-page links (Cause A).** `workflow._collect_zone_faction_targets`
  mints faction-profile targets from the seed page's block links that resolve to registry orgs,
  ranked by summed **link frequency × section-class weight** (history/quests = 3.0, lead = 2.0,
  cast = 1.0, gazetteer = 0.5, RPG = 0.0), capped at `_MAX_FACTION_PROFILE_TARGETS = 10`. The
  quests/storyline section weight is the "questline-bound" signal available at discovery time
  (the quest graph does not exist yet). The old per-link `inferred_entity_type == "faction"`
  branch no longer emits a target (it only means "not a location"), and link *typing* itself now
  asks the registry (`"organization" in entry_kinds(title)`) instead of `faction_title_tokens`.
  On the WPL seed page this produces Argent Crusade (7.0), Alliance/Horde (6.0), Scourge/Cenarion
  Circle/Scarlet Crusade (5.0), Argent Dawn/Ashen Verdict/Forsaken (3.0) — the current actors
  Cause A said were missing now get profiles crawled. `traverse_wiki._MAX_FACTION` re-homed onto
  `_MAX_FACTION_PROFILE_TARGETS` so the crawl budget can't silently cut a ranked target.
- **Vocabulary deleted.** `faction_title_tokens` / `lore_faction_tokens` removed from
  `discovery_classification_vocab.v1.json` and their `discovery_vocab` accessors; `lore_sources`
  faction filtering re-pointed at `entry_kinds` (registry organization kind).
- **Offline verification (test-run-wpl-26 artifacts, no re-crawl needed — Slice 12 already
  captured links/infoboxes):** re-running discovery on the run-26 snapshots yields the 9-org
  ranked WPL target list above (was 5, missing the current actors). Instance harvest on the
  run-26 Scholomance evidence reproduces the gold set exactly (Scourge, Cult of the Damned).
  Zone election on run-26 WPL evidence elects Alliance, Scourge, Argent Crusade, Cenarion Circle,
  Forsaken, Scarlet Crusade, Cult of the Damned (Forsaken carries `horde` from its profile
  infobox; generic Horde suppressed). This is the "identical or better, and now generalizes"
  outcome; a full LIVE pilot with re-enrich still awaits `OPENAI_API_KEY`
  (memory: `draft-stage-requires-openai`), verified properly by Slice 16.
- **Tests:** `test_faction_scoring` (link-based seed discovery; unlinked prose discovers nothing;
  an org unknown to the deleted vocab — Kirin Tor — found purely via its link target; adjacent-link
  compound never mints "Horde Forsaken"; Forsaken Horde-suppression driven by profile-infobox
  affiliation), `test_instance_faction_harvest` (link establishes then prose counts; identity from
  link target not anchor text; unlinked prose mints nothing; temporally-excluded evidence never
  counts), `test_discovery_workflow` (`_collect_zone_faction_targets` ranking, identity-from-target,
  cap; seed fixture now carries an org block link), `test_classification_vocab` (deleted loaders
  removed). Verified: `ruff check pipeline tests`, `mypy` on the ten touched modules, full `pytest`
  (1115 passed, 5 skipped, 1 xfailed; the lone failure `test_history_heading_relabel` is
  pre-existing on `157df37` and unrelated to factions).

- `pipeline/generate/draft/faction_scoring.py`:
  - Seed-mention discovery (`_candidates_from_high_weight_seed_mentions`) and
    `harvest_instance_faction_targets`: a mention = an inline link on the evidence block whose
    target is a registry organization (resolve via redirect map where present). Plain-text
    fallback matching may remain **only** for names already established by links/targets on the
    same page (no open-vocabulary phrase matching).
  - **Delete** `_FACTION_NAME_RE`, `_phrase_is_faction`, `_faction_token_set`,
    `_STANDALONE_FACTION_NAMES`, `_canonicalize_faction_phrase`'s token gating; keep
    `resolve_canonical_faction_name` as a thin fallback that now consults the registry, and keep
    `merge_variant_faction_candidates` (dedupe by canonical article via the redirect map —
    links make the "Horde Forsaken" compound-phrase case structurally impossible).
  - `_BINDING_BY_FACTION_ID` / `_UMBRELLA_TAG_BY_ID` → derive from registry org affiliations
    (umbrellas = the faction-capital orgs: Alliance/Horde entries).
  - Remove `faction_title_tokens` / `lore_faction_tokens` from
    `discovery_classification_vocab.v1.json` and all consumers (`discovery_vocab` accessors,
    `lore_sources` link filtering — re-point the latter at registry kinds).
- Discovery profile-target selection (`pipeline/discovery/workflow.py` /
  wherever `faction_profile_targets` is built): targets = organizations linked from the zone's
  seed page + questline-bound orgs, ranked by link frequency × section class; crawl top N. This
  is the "crawl the current actors" half of Cause A (Argent Crusade, Cenarion Circle, Alliance
  get profiles for WPL).
- Tests: link-based mention counting; unknown-vocab factions (a "Defias Brotherhood"-shaped
  fixture) discovered via links; profile targets include questline-bound + top-linked orgs;
  deleted-vocab tests removed.

**Expected pilot effect [LIVE, after re-crawl]:** identical or better faction sets on the pilot;
the mechanism finally *generalizes* (verified properly by Slice 16).

## Slice 14 — Section/heading classification: full registry transition (H-3 residue) — ✅ DONE (2026-07-07)

**Approach changed from the original spec — see below.**

**Verification (2026-07-07):** `ruff check pipeline tests` clean; `mypy` clean on all touched
modules; full `pytest` green (only the pre-existing skips + the known `test_temporal_run_artifacts`
xfail). New `tests/test_section_role_classification_slice14.py` pins the registry-derived
replacements and the two maintainer constraints (no "faculty" theme word in shared code; quest
objectives/description stay page-type lore). Behavior/gold movement is expected and accepted (see
the approach change) — the pilot *page* reconciliation remains the marked **[LIVE]** step, since
draft regeneration needs `OPENAI_API_KEY`; the discovery-stage classification changes are covered by
the offline suite. Notable intentional behavior shifts: `warlords`/`midnight`/`last_titan` are now
recognized as era sections (era tokens derive from `expansion_release_order`); `exploring_azeroth`
(and other adaptation sections) now classify `media` and drop out of history/currently/lore pools;
a bare "Faculty" heading is no longer a boss token (Scholomance's roster reaches `boss_pool` via its
per-dungeon table / adventure guide); a `classic`/`removed` section role no longer forces
`excluded_noncanon` (retail-era exclusion is the category signal's job).

**Goal:** finish the migration the section-label registry started; the scattered role-token
keyword/deny/allow lists become registry-class (and expansion-registry) lookups.

**Approach change (2026-07-07, agreed with maintainer).** The original spec below constrained this
slice to a *behavior-identical, parity-only* sweep ("assert routing decisions unchanged on the pilot
fixtures; improving the classifications themselves is out of scope"). Verifying that against the
code showed the guardrail is in direct tension with the goal: the named lists use **substring**
matching, **mix canonical discovery roles with raw wiki slugs**, and encode purpose-specific
judgments the content-class registry deliberately does not model — so a faithful registry transition
*necessarily* changes behavior (e.g. deriving `era_section_role_tokens` from `expansion_release_order`
makes `warlords_of_draenor`/`midnight` sections count as era history where they didn't, on the pilot
pages themselves). Per maintainer direction, **the parity-only and "don't improve classifications"
guardrails are dropped for this slice.** The whole refactor exists to generalize to every retail
zone; any change that removes a brittle keyword/regex/allow/deny list in favor of the registries is
preferred even when it moves behavior or gold. Pipeline regressions are still avoided; gold *page*
reconciliation that needs the LLM is left as the marked **[LIVE]** step (draft needs
`OPENAI_API_KEY`), with the discovery-stage decision artifacts + test suite verified offline.

**Two maintainer constraints on this slice:**
- **No pilot vocabulary in shared code.** "faculty" is a Scholomance-specific theme word (the school's
  bosses are "faculty"); instance-entity detection must come from the registry `roster` class /
  boss-section detection, never a `faculty` keyword, and shared code/language must use the generic
  terms ("denizens"/"bosses").
- **`objectives`/`description` on quest pages are the lore we extract**, but they are copy-pasted
  in-game quest-journal text and can carry a little meta — keep the quest-page inclusion explicit
  and page-type-scoped rather than assuming those sections are pure prose.

**Plan as implemented (Groups A–C):**

*Registry extensions* (`section_label_registry.v1.json` + `section_registry.py`): add a **`media`**
content-class (RPG/novel/comic/adaptation prose — excluded from lore like `meta`); add labels
`maps_subregions`(geography, canonical alias of `maps_and_subregions`), `resources`(gameplay), and
the media labels (`exploring_azeroth`, `novel`, `novella`, `short_story`, `manga`, `comic`,
`later_appearances`). Add helpers: `is_generic_history_heading(label)` and an `expansion_era`
display-name accessor (single home for the "generic heading" concept and the expansion display
names).

*Group A — content-class exclusion sets → registry queries:*
- `prose_election._HISTORY_EXCLUDED_ROLES` → `section_content_class(role,parent) in {geography, non_canon}`.
- `enrich._HISTORY_DIGEST_EXCLUDED` + `_is_currently_input_role` → registry-narrative / quest-gameplay
  in, geography/non_canon/meta out (drops the `endswith("_edit")` catch-all that leaked `notes_edit`
  etc. into `currently_input`).
- `lore_sources._HISTORY_ROLE_TOKENS` → `is_narrative_section` with `narrative_kind ∈ {history, background}`.
- `wiki_evidence_filters` (`_GENERIC_SECTION_ROLES` / `_EXCLUDED_PROSE_SECTION_ROLES` /
  `_FOOTER_META_SECTION_ROLES`) → `is_named_history_section` re-expressed via parent-inherited
  `content_class` + `is_generic_history_heading` (signature gains `parent`); fixes the current
  `description_edit → named history` false-positive.

*Group B — single-home the duplicated concepts:*
- `era_section_role_tokens()` derived from `expansion_release_order()`; delete the duplicate vocab
  entry (accepts the `warlords`/`midnight`/`last_titan` recognition change).
- `_GENERIC_HISTORY_HEADINGS` → the shared `is_generic_history_heading` helper; its expansion
  display-name portion derives from the registry `expansion_era` labels.
- `retail._NON_RETAIL_PARENTHETICAL_RE` expansion alternatives built from `expansion_release_order()`.

*Group C — markers that aren't pure content-class:*
- `temporal._POST_LORE_ROLE_MARKERS` (novel/manga/comic/exploring-azeroth/later-appearances) →
  the new `media` class + `non_canon`. `temporal._ENTRY_ROLE_MARKERS` → `narrative`(identity) /
  `gameplay`(adventure_guide) / `roster` classes (no `faculty`/`boss` keyword; boss detection is
  the existing `is_boss_section_role`). `temporal._EXCLUDED_ROLE_MARKERS`: the non-canon/gameplay
  parts → registry classes; **the retail-scope part (`classic`/`removed`/`deprecated`) moves to the
  category-based retail signal** (`strict_generation_category_signal`) rather than the content
  registry — `classic` is legitimately `narrative/expansion_era` prose, and retail eligibility is a
  separate, already-homed judgment (memories: `retail-only-no-classic`,
  `classic-era-content-scope-by-section`).
- `workflow._LOCATION_LORE_SECTION_TOKENS` / `_LOCATION_GAMEPLAY_SECTION_TOKENS` and
  `_INSTANCE_ROSTER_SECTION_TOKENS` re-sourced from `content_class` (narrative/geography = lore;
  gameplay/meta/media = gameplay; `roster` + `is_boss_section_role` for instance rosters). The core
  `_SECTION_ROLE_PATTERNS` discovery bucketer is a *different taxonomy* (navigation roles, not
  content classes) and stays, but its lore/gameplay-derived helpers are registry-sourced.
- `quest_lore._EXCLUDED_ROLES` dropped in favor of a `content_class` gameplay/meta exclusion; the
  quest-narrative inclusion (`objectives`/`description`/`quest_text`) stays as an explicit,
  page-type-scoped rule (those sections are `gameplay`/`meta` for zone/faction pages but *are* the
  lore on a quest page).

**Original spec (superseded by the approach change above; kept for reference):**

- Inventory the residual lists: `enrich._HISTORY_DIGEST_EXCLUDED`, `_is_currently_input_role`'s
  role checks, `quest_lore._LORE_ROLES`/`_EXCLUDED_ROLES`, `prose_election._HISTORY_EXCLUDED_ROLES`
  / `_GENERIC_HISTORY_SUBSECTIONS`, `temporal._ENTRY_ROLE_MARKERS` / `_POST_LORE_ROLE_MARKERS` /
  `_EXCLUDED_ROLE_MARKERS`, `lore_sources._HISTORY_ROLE_TOKENS`, workflow section-token lists,
  `wiki_evidence_filters` role sets.
- Extend the section-label registry's class vocabulary where needed (e.g. `meta`, `gameplay`,
  `media`, `official_description`) via the harvest → registry flow already established
  (memory: `section-label-registry`), then re-source each list as a registry-class query and
  delete the local copy. Where a list encodes something genuinely *not* section-classy
  (e.g. `era_section_role_tokens` — expansion names), source it from the expansion registry.
  `_GENERIC_HISTORY_HEADINGS` and `retail._NON_RETAIL_PARENTHETICAL_RE` likewise derive their
  expansion-name portions from `expansion_release_order`.
- This slice is mechanical but wide: keep behavior-identical (assert routing decisions unchanged
  on the pilot fixtures before/after), one module at a time, and stop at parity — improving the
  classifications themselves is out of scope.

## Slice 15 — Assertion-level fact-check (F) — depends on Slice 7 — ✅ DONE (2026-07-07)

**Goal:** fact-check verifies assertions against the cited paragraphs, not token overlap.

**Implementation notes (as built, 2026-07-07):**

- `pipeline/validate/rules/fact_check.py` rewritten around a single verdict source. The
  token-overlap scoring path is **deleted**: `WORD_RE`, `_tokenize`, `_text_overlap_score`,
  `_support_score`, the `LOCAL_SUPPORT_THRESHOLD`/`WEB_SUPPORT_THRESHOLD` constants, and the
  `pipeline.common.text_sim.lemma_support_containment` import are gone. No lexical-overlap score
  ever decides `supported`/`unsupported`/`contradicted` — Slice 8's lemmatized scoring now lives
  only on the synthesis/retrieval side.
- The checked set is built once as `CheckedUnit(path, text, source_ids)` via `_checked_units`:
  the existing section claims (`_section_claims` + `_section_pointer_source_ids`) **plus** card
  summaries (`_card_units`). Card provenance is per-card — zone/instance faction and instance
  key-character pointers hang off `provenance.<group>[card_id]`; location cards carry pointers
  inline on `LocationCard.provenance`. `_pointer_source_ids` now dedupes.
- Per unit (`_check_unit`): deterministic control markers first (`[CONTRADICTED]` →
  contradicted, `[UNSUPPORTED]` → unsupported), evaluated before the pointer check so a marked
  passage always yields its verdict (the pipeline-stage `[CONTRADICTED]` tests still hold). No
  provenance pointers ⇒ `unchecked_missing_pointers` WARN (`fact_check.unchecked_missing_pointers`)
  and move on — never fuzzy-matched. Otherwise the cited **source bodies** are retrieved from the
  ingest snapshots (tags stripped, capped at 2000 chars/source; pointer locators are
  synthesis-relative after Slice 7, so the retrievable unit is the cited source body, which
  carries the paragraph plus its section context) and handed to the LLM adjudicator with
  structured output (`_ADJUDICATION_SCHEMA`, enum `supported|unsupported|contradicted`). When
  adjudication can't run (LLM unavailable, entity not targeted, or no cited-source text), the
  unit is recorded `unchecked` with no issue — no verdict is manufactured.
- Web search is retained as an *evidence gatherer* only (feeds snippets to the adjudicator when
  enabled+targeted+available); its former overlap-scoring-to-`supported` step is deleted.
- Severities: `contradicted` ⇒ HARD_FAIL under STRICT / WARN under WARN
  (`fact_check.contradiction`); `unsupported` ⇒ WARN (`fact_check.unsupported`);
  `unchecked_missing_pointers` ⇒ WARN. The OFF/`llm_unavailable`/`web_unavailable`/targeting
  semantics are unchanged. `_adjudicate_with_openai` keeps its `(settings, claim_text,
  evidence_snippets, model)` signature (the prompt-leak guard renders it); the prompt/status enum
  were rewritten and it now requests structured output.
- Tests (`tests/test_validation_engine.py`): new `_mock_fact_check_llm` helper; inverted spatial
  relation ("above" vs source "beneath") → `contradicted` HARD_FAIL under strict; pointer-less
  field → `unchecked_missing_pointers` WARN and never a supported/unsupported/contradicted
  verdict; faction+location (zone) and key-character (instance) card summaries join the checked
  set and adjudicate. The local-snapshot / history-provenance / instance-bucket tests now supply
  a mocked verdict (the evidence-routing assertions filter to `local_snapshot` rows). The two
  token-overlap scoring tests (`test_fact_check_warn_profile_emits_insufficient_evidence_on_low_overlap`,
  `test_fact_check_support_score_lemma_fallback`) are deleted. Verified: `ruff check pipeline
  tests`, `mypy` on fact_check.py + engine.py, full `pytest` (1129 passed, 5 skipped, 1 xfailed).

**Original spec:**

- `pipeline/validate/rules/fact_check.py`: for each checked sentence, retrieve the **exact
  paragraphs its provenance pointers cite** (paragraph-granular after Slice 7) plus their
  immediate section context; the LLM judges each sentence `supported / unsupported /
  contradicted` against that text (structured output). **Delete the token-overlap scoring path
  entirely** — it is the mechanism that passed "above Caer Darrow" against a source saying
  "beneath". A checked sentence with no provenance pointers is a provenance defect (Slice 7 makes
  pointers honest), not something to fuzzy-match around: fact-check records it as an
  `unchecked_missing_pointers` WARN and moves on. Slice 8's lemmatized scoring stays on the
  synthesis/retrieval side only; it never participates in the fact-check verdict.
  `contradicted` at release gate ⇒ hard-fail; `unsupported` ⇒ WARN (keep the current profile
  semantics otherwise).
- Add card summaries (faction/location/key-character) to the checked set.
- Tests: a fixture with an inverted spatial relation ("above" vs source "beneath") returns
  `contradicted` (mocked LLM); a pointer-less field yields the `unchecked_missing_pointers` WARN
  and never a token-overlap verdict; token-overlap scoring tests deleted.

## Slice 16 — Second pilot: the generalization acceptance gate

**Goal:** the only honest test of Slices 4–15. Add a second, dissimilar pilot subject — a zone
with different factions/tone and **no registry, no gold, no hand-tuning** (recommendation:
a Kalimdor Cataclysm-era zone, e.g. Desolace, or Westfall for an Alliance-flavored Eastern
Kingdoms contrast; pick one and record the choice in the plan doc when implementing).

- Add its source manifest + a pipeline run config; no `pilot_questline_registry` entry, no
  editorial overrides, no new vocab entries (the point is that none should be needed).
- Acceptance checks (scripted, not eyeballed): pipeline completes; validation has no hard-fails
  or every hard-fail is a recorded `field_status`/decision; zero pilot-vocabulary dependencies
  (grep-level guard: the run's decisions never cite deleted registries); faction cards' subjects
  all appear in the zone's evidence; no `structure.uncarded_current_actor` WARN, or each is
  explainable; spot temporal audit — no later-expansion content in `currently`/history absent
  contract linkage.
- Failures here are *findings*, not blockers to merge — file them against the responsible slice.
  This slice defines the bar for promoting WPL/Scholomance to gold: pilot pages get promoted only
  once the second zone runs clean through the same machinery.

## Slice 17 — Remove pilot authority and enforce shared evidence contracts

**Status: IMPLEMENTING (2026-07-09).** The Desolace run established that a WPL-only questline
registry and exact gold gates make WPL an invalid generalization baseline. Remove the runtime
registry, all fixture fallbacks, curated card overrides, and pilot-only gates. Every zone uses
cluster-derived IDs, anchors, chain references, ranking, provenance, and semantic validation.

- Replace all hand-authored WPL/Scholomance output fixtures with raw-input and synthetic edge-case
  fixtures. WPL and Desolace are equal regression inputs; neither prescribes generated prose,
  card counts, IDs, or anchors.
- Replace the Scholomance name denylist with per-candidate wiki-category retail eligibility.
  `retail_confirmed` is required for selection; `non_retail` and `unresolved` candidates never
  enter retail output, and failed category fetches are recorded rather than treated as clean.
- Remove WPL defaults from local launchers, diff tooling, and the addon slash command. Bare
  `/lore` opens neutral usage help.
- Acceptance requires fresh WPL and Desolace runs through identical release/semantic checks;
  output differences are evidence-review findings, never justification for a zone exception.

---

## Standing notes for implementers

- Run everything offline-first (`WOW_LORE_WIKI_FIRST_NO_LLM=1`) for unit verification; live
  checks per slice as marked. The draft stage requires `OPENAI_API_KEY` for page regeneration
  (memory: `draft-stage-requires-openai`).
- Never re-run into an existing run id (Slice 1 enforces this).
- When a fix changes zone output, record the evidence-based reason in its decision artifacts and
  review it under the shared semantic contract. Do not create or update a zone-specific gold
  output fixture.
- Do not add new keyword/regex denylists anywhere in these slices; if a defect seems to need one,
  it belongs to the substance gate / retry loop, or it is a new root cause to record — not patch.
