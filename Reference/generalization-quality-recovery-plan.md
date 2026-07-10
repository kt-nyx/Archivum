# Plan: Generic Quality Recovery — Semantic Cards, Story Arcs, and Release Gates

**Status: PROPOSED — 2026-07-09. Implement in the stated order.**

## Purpose

Recent WPL and Desolace pilot runs exposed regressions after the intentional removal of
WPL/Scholomance-specific scaffolding. This plan restores the *general capabilities* that the
scaffolding previously masked: reliable entity admission, direct evidence ownership, coherent
story-arc selection, intact cross-stage contracts, grammatical final text, and release gates that
make bad output visible.

The target is a generic retail-WoW pipeline. WPL, Scholomance, Desolace, and Maraudon are
evaluation inputs only. They must not become registries, prompt exemplars, title lists, special
caps, or output fixtures that prescribe the answer for other subjects.

## Decisions already made

1. **Clean break.** There is no production data, external consumer, or compatibility obligation.
   When a schema changes, update every in-repo producer and consumer in the same slice, delete the
   obsolete form, and regenerate local artifacts. Do not add dual-read compatibility code.
2. **No title/keyword knowledge bases.** A small output enum such as `place`, `named_actor`, or
   `unknown` is a domain-neutral card-admission contract, not a list of Warcraft facts. Raw page
   titles must not be classified by a curated name/race/species denylist. Source-native evidence
   (categories, infobox structure, parent/containment relations, encounter membership, and direct
   page metadata) determines the enum; unresolved candidates abstain as `unknown`.
3. **Fail closed at rendering boundaries.** Broad discovery may retain uncertain candidates for
   audit, but a card cannot be emitted unless it has the required kind and direct evidence.
4. **LLMs are bounded adjudicators, not untracked fallbacks.** They may resolve genuinely
   ambiguous structured source signals and assess supported prose, but must return an explicit
   decision, confidence, and cited inputs. `unknown`/reject is always an acceptable result.
5. **Tests specify behavior, not WPL prose.** Use synthetic graph/source fixtures and
   machine-checkable artifact invariants. Pilot prose is reviewed as evidence, never frozen as a
   gold answer.
6. **Unknown current state is not publishable as confident current state.** Exploratory runs may
   emit an explicit limited/unknown result with its evidence gap. A strict release cannot publish a
   confident `currently` section when active/current state is unresolved.

## Common implementation rules

- A slice owner reads this document, its dependencies, the touched code, and current Git status
  before changing code. No prior chat context is required.
- Each slice owns its schema, decision-artifact changes, unit/integration tests, and documentation
  updates. Do not leave a producer/consumer mismatch for a later slice.
- Use `uv run --no-sync` for checks in this repository. At minimum run Ruff, MyPy on touched
  modules, the slice tests, and `git diff --check`; run the full suite when the slice says so.
- `[LIVE]` slices require a fresh incremented run id. Never overwrite a historic run.
- Every decision that drops a candidate records a stable reason code and the evidence/signals that
  produced it. A generic reason code is acceptable; a zone-specific exception is not.

## Cross-cutting guardrails

### Bounded abstention and page coverage

Fail-closed card admission is deliberate, but an empty or thin page is not a successful outcome.
Every card family has a documented coverage target and a corresponding insufficiency state:

- Location/character selection must progressively retrieve the next eligible candidates before
  declaring the budget unfilled.
- A page may contain fewer cards only when the decision artifact records `insufficient_viable_*`
  with the attempted candidates, evidence gaps, and retrieval/cap history.
- Strict release fails when a required page section cannot meet its minimum viable coverage or is
  rendered as confident prose from unresolved evidence. Exploratory output may remain visible only
  with an explicit limited/unknown status.

This prevents precision improvements from silently becoming coverage regressions.

### Versioned, fail-fast artifacts

Every cross-stage JSON artifact introduced or changed by this plan carries an explicit schema
version. A reader accepts exactly the current version and rejects a missing or mismatched version
with a diagnostic that names the artifact, producer, and expected version. This is a clean-break
contract, not a compatibility mechanism: producers and consumers change together and historic runs
are regenerated when inspected.

### Run reproducibility record

Each run records a compact immutable manifest containing source snapshot/content hashes, input
manifest identity, code revision, settings, decision-artifact schema versions, and the model/prompt
identifiers used for live structured decisions and synthesis. A quality comparison must surface
these differences before attributing changed output to a code change.

### Adversarial behavioral fixtures

Synthetic tests must include both ordinary and adversarial inputs: ambiguous entity pages, linked
generic terms inside encounter sections, untyped links, containment inversion opportunities,
parallel faction arcs, repeated title decoration, missing metadata refs, and malformed generated
clauses. These fixtures use invented names and structures; they do not encode pilot output.

### Human editorial review rubric

Strict gates establish that output is structurally and evidentially safe, not that it is maximally
useful lore writing. Each live pilot review uses the same short rubric:

1. Are the chosen cards real, relevant entities/arcs and meaningfully diverse?
2. Does each card's defining claim follow from its cited evidence without relation reversal?
3. Is current-state/history framing evidence-backed and spoiler-safe?
4. Are questline titles, faction variants, CTAs, and role labels clear to a player?
5. Does the page have an explained coverage gap or an obviously missing central subject?

Review findings become generic regression cases or explicitly recorded backlog items; they never
become a one-zone exception.

## Slice 0 — Establish the committed main baseline and recovery branch

**Goal:** commit all currently uncommitted generalization work, place that commit on local `main`,
and begin this recovery from a named branch with a recorded baseline SHA.

**Why first:** the current worktree contains the completed pilot-eviction/generalization changes
plus this new plan. Subsequent fixes must be reviewable against that real baseline rather than an
uncommitted mixture.

**Owner actions:**

1. Start on the branch containing the current worktree changes (currently
   `fix/key-character-temporal-spoiler-classification`). Run `git status --short`,
   `git diff --check`, and inspect the staged/untracked set. The expected scope is the existing
   generalization work, its tests/tooling, the archived plan, and this plan; stop if unrelated
   personal work is present.
2. Run the baseline verification surface: `uv run --no-sync ruff check pipeline tests`, MyPy on
   all changed Python modules, the focused questline/location/instance/temporal/validation tests,
   and `uv run --no-sync pytest -q`. A new unexplained failure is a stop condition; do not bury it
   in the baseline commit. A documented existing xfail may remain only if recorded in the commit
   message/body or baseline note.
3. `Reference/` is ignored in this checkout. Stage the reviewed set with `git add -A`, then
   force-add both planning artifacts with
   `git add -f Reference/generalization-quality-recovery-plan.md Reference/legacy/generalization-refactor-plan-2026-07-09.md`.
   Inspect `git diff --cached --name-status` to confirm this records the new plan and archive as a
   rename/addition rather than deleting the old plan. Commit it as one intentional baseline commit,
   for example `feat(generalization): complete pilot-eviction baseline`. Record its SHA in this
   file under the implementation note when done.
4. Switch to `main` and fast-forward it to that baseline (`git merge --ff-only <baseline-branch>`).
   Do not force-update, reset, or silently resolve a divergent main. If it cannot fast-forward,
   stop and reconcile the divergence deliberately before proceeding.
5. Create and switch to `fix/generalization-quality-recovery` from updated `main`. All remaining
   slices commit to this branch. Do not pull, push, or open a PR as part of this plan unless later
   explicitly requested.

**Acceptance:** `main` contains the baseline SHA; the recovery branch points to that SHA; the
working tree is clean; the recorded verification result is reproducible.

**Dependencies:** none.

## Slice 1 — Replace title denylists with an entity-kind evidence and admission contract

**Goal:** make card eligibility depend on evidence about the target page, never on a hardcoded
Warcraft title/race/species vocabulary or an untyped-link default.

**Primary code areas:** `pipeline/discovery/entity_typing.py`,
`pipeline/discovery/workflow.py`, `pipeline/discovery/world_registry.py`, ingest snapshot models,
and `pipeline/contracts/models.py`.

**Implementation:**

1. Define one shared, closed output enum: `place`, `named_actor`, `organization`,
   `group_or_species`, `object_or_concept`, and `unknown`. Define a typed decision record with
   candidate identity, kind, confidence, source signals, source ids, and reason codes.
2. Replace `_infer_entity_type_for_link`-style default-to-`location` behavior with a provisional
   `unknown` decision. Preserve raw links for later probing, but do not infer a render kind from
   title spelling, capitalization, or a manual title list.
3. Build the decision from target-page evidence: canonical page identity, categories, infobox
   keys/values, parent/subzone/map/coordinate relations, and source-page relationship. A bounded
   structured classifier may adjudicate conflicts only after these signals are collected; it must
   receive the signals, return the enum, and be allowed to return `unknown`.
4. Make the world registry an optional positive signal, not an exhaustive truth source. Missing
   registry coverage must never promote a candidate to `place`.
5. Delete `entity_denylist.json`, `entity_denylist.README.md`, race/species title denylists, and
   location-type title-token classification paths once their structural replacements are live.
   Retain only generic URL/namespace/redlink/meta-page validity checks; those are link hygiene,
   not Warcraft knowledge.
6. Emit an entity-kind decision artifact that downstream selection and validation can consume.

**Tests:** synthetic source pages proving that a race/category page, ability/concept page, named
actor page, place page, and structurally ambiguous page respectively resolve to
`group_or_species`, `object_or_concept`, `named_actor`, `place`, and `unknown`. Assert that no
title-specific denylist is consulted and an untyped link is not promoted.

**Acceptance:** no shared classification file contains a curated Warcraft entity-title list; every
candidate reaching a card selector has an entity-kind decision and evidence provenance.

**Dependencies:** Slice 0.

## Slice 2 — Make location cards direct-evidence, typed, and progressively retrieved

**Goal:** select a diverse set of real places with evidence about those places, rather than letting
mentioned concepts consume the crawl budget or borrow another page's description.

**Primary code areas:** `pipeline/discovery/location_discovery.py`,
`pipeline/discovery/workflow.py`, `pipeline/ingest/traverse_wiki.py`,
`pipeline/generate/draft/location_scoring.py`, location models and decision artifacts.

**Implementation:**

1. Split location handling into discovery candidates, lightweight target probes, qualified profile
   targets, and renderable cards. A candidate may be broadly discovered; only `place` candidates
   advance past qualification.
2. Replace the fixed first-eight traversal behavior with progressive retrieval: rank candidates by
   source relationship and preliminary significance, probe a bounded batch, fully fetch qualified
   places, evaluate evidence completeness/diversity, then fetch the next batch only if the desired
   card budget is not filled. Record cap/defer reasons rather than silently skipping targets.
3. Require exact identity ownership for primary card evidence. The selected location id must match
   the profile/evidence subject id. Delete substring/name fallback in `_profile_items_for_location`.
   A mention on a different page may be supporting relational evidence only, with its direction
   preserved.
4. Keep containment and zone-of-record checks, but make “no zone category found” an insufficient
   signal for a place card when no other affirmative place evidence exists. Do not infer that a
   generic concept is on-zone merely because it was linked from the zone page.
5. Select from qualified candidates using coverage/diversity rules: prefer direct, on-zone,
   well-supported places across major current/history/geographic roles; do not switch to an
   all-`lore_significant` pool merely because three names occur in prose.
6. Expose `candidate`, `probe`, `profile`, `selected`, `deferred`, and `rejected` states in the
   decisions so a run explains both omissions and card inclusion.
7. If progressive retrieval exhausts its configured, recorded budget before viable coverage is
   reached, emit `insufficient_viable_locations`; strict release treats it as a coverage failure,
   while exploratory output marks the section limited rather than silently accepting a thin page.

**Tests:** synthetic direct-versus-mentioned containment case; unqualified concepts cannot consume
the profile budget; a lower-ranked but qualified landmark is fetched after contaminated candidates
are rejected; selected cards have direct subject-matched evidence; no substring fallback remains.

**Live acceptance [LIVE]:** fresh WPL and Desolace runs contain no race/species/person/concept
location cards, no Cenarion-Wildlands/Karnum’s-Glade-style relation inversion, and decision
artifacts show why each selected place was fetched.

**Dependencies:** Slices 0–1.

## Slice 3 — Rebuild instance key-character admission around named instance participants

**Goal:** prevent generic creature types, races, concepts, and links from becoming mandatory
Maraudon/instance character cards.

**Primary code areas:** `pipeline/discovery/instance_bosses.py`,
`pipeline/generate/draft/pages/key_characters.py`, `pipeline/ingest/traverse_wiki.py`, and
instance-card models/decisions.

**Implementation:**

1. Extend each roster candidate with the Slice 1 entity-kind decision and separate evidence for
   `instance_presence`, `retail_scope`, and `encounter_relation`. Replace the misleading single
   `retail_confirmed` boolean with those explicit facts.
2. Treat Adventure Guide/encounter/roster links as leads, not automatic characters. A candidate is
   eligible for a key-character card only when it is a `named_actor` and has direct evidence of
   participation in this specific instance. A generic word linked inside a boss section is not
   enough.
3. Restrict the mandatory floor to high-confidence eligible named participants. The floor must
   never fill the budget before type and instance-presence admission.
4. Keep structural presence separate from narrative role. Role generation may use a bounded
   adjudication with evidence, but it must preserve `uncertain` when evidence does not establish
   ally/enemy/neutral; it may not turn an untyped candidate into a confident enemy.
5. Persist final selection reason, entity-kind evidence, presence evidence, retail scope, and
   final role in one sidecar. Final rendering must read that sidecar rather than reconstructing a
   different candidate set.

**Tests:** a boss-section fixture containing named bosses plus `Centaur`, `Earth elemental`,
`Creeping Sludge`, `AoE`, and a deity/concept yields cards only for eligible named participants;
an absent/Classic-only actor is excluded; role evidence cannot contradict final selection data.

**Live acceptance [LIVE]:** a fresh Maraudon page has no generic-type/ability/concept character
cards, and every card has a direct instance-presence record.

**Dependencies:** Slices 0–1. May run in parallel with Slice 2 after Slice 1 is complete.

## Slice 4 — Establish one questline metadata contract and repair entry-state grounding

**Goal:** eliminate the `ordered_chain_refs`/`chain_refs` split and ensure selected questlines
provide real setup evidence to temporal/current-state classification.

**Primary code areas:** `pipeline/contracts/models.py`,
`pipeline/discovery/questline_card_polish.py`, `pipeline/discovery/questline_promotion_gate.py`,
`pipeline/generate/draft/temporal.py`, `pipeline/generate/draft/pages/zone.py`, and
`tests/test_entry_state_contract.py`.

**Implementation:**

1. Define a single typed `QuestlineCardMetadata` artifact. It owns canonical card id, source
   cluster/arc id, display fields, variant fields, start anchor, ordered `chain_refs`, optional
   overflow refs, and source/evidence references. `chain_refs` is the sole canonical field name.
2. Make discovery write this model directly; make temporal classification, promotion validation,
   page generation, and decision reporting consume this same serialized model. Delete
   `ordered_chain_refs` and every compatibility branch rather than translating it downstream.
3. Add a schema/identity check at each handoff: selected metadata refs must exist in the quest
   graph; ordering must be valid; setup refs must resolve to actual quest records; final cards must
   derive from the selected metadata.
4. Rework active-expansion derivation so it records source evidence and confidence and consumes
   real setup anchors. An absent or weak setup signal must be `unknown`/reviewable, not silently
   converted to a confident Classic-era default by a generic synthesis fallback.
5. Produce an entry-state decision artifact that includes metadata id, setup refs/snippets/NPCs,
   active-expansion evidence, and every fallback used.

**Tests:** an end-to-end artifact test writes discovery metadata, reloads it through temporal
classification, and asserts non-empty setup refs/snippets for a selected questline. Cover missing
quest records, bad ordering, missing start anchor, and unknown expansion evidence as explicit
fail/defer cases.

**Acceptance:** no production code reads `ordered_chain_refs`; every selected questline with valid
quest records has setup evidence in the entry-state artifact; strict release rejects a confident
current-state section whose active-state evidence remains unknown.

**Dependencies:** Slice 0. This may run in parallel with Slices 2–3.

## Slice 5 — Replace component scoring with generic story-arc families and structured titles

**Goal:** select coherent player-facing story arcs and justified faction/phase variants without
reintroducing a hand-authored zone registry.

**Primary code areas:** `pipeline/discovery/questline_cluster.py`,
`pipeline/discovery/questline_arc_map.py`, `pipeline/discovery/questline_significance.py`,
`pipeline/discovery/questline_anchor.py`, `pipeline/discovery/questline_card_polish.py`, and
questline tests/report tooling.

**Implementation:**

1. Introduce a generic `ArcCandidate`/`ArcFamily` decision model. Graph components remain input,
   but the model explicitly records campaign signals: shared hub/location, recurring named
   actors/organizations, prerequisite/follow-up structure, conflict/theme evidence, faction, and
   phase/expansion.
2. Resolve split/merge decisions deterministically where graph and structured signals agree. For
   genuine ambiguity, use a bounded structured adjudication that returns merge/split/keep-separate
   with the evidence it used; no free-form title is authoritative.
3. Model a campaign family separately from its variants. Coverage selection first chooses the
   highest-value families, then chooses faction/phase variants where their evidence supports a
   distinct playable path. Record why a parallel variant was included, paired, or rejected.
4. Replace proxy-only significance with a coherent score: setup accessibility, internal
   connectivity, narrative/theme continuity, zone relevance, cast/faction involvement, and
   coverage contribution. Quest count/NPC count/text length are supporting features only.
5. Apply the page budget after family coverage and diversity selection, not as a simple top-N list
   of components. One-quest cards require an explicit high-signal exception and reason code.
6. Store title identity structurally (`base_title`, `faction_variant`, `phase_variant`,
   `segment_index`, canonical id). Render the title once at the page boundary. Delete all
   append-to-rendered-title mutation paths and add a normalized-label uniqueness invariant.
7. Emit a complete arc-selection artifact: candidates, family membership, signal evidence,
   merge/split decisions, ranking, budget selection, and exclusions.

**Tests:** synthetic quest graphs covering coherent multi-node arcs, weak long fragments, paired
faction variants, truly separate campaigns with similar titles, a justified one-quest exception,
and repeated variant processing. Assert no doubled suffixes, no duplicate normalized titles, and
family-level budget behavior. Do not encode WPL quest names.

**Live acceptance [LIVE]:** fresh WPL and Desolace outputs show coherent titles, no duplicate
`(Alliance)`/`(Horde)` suffixes, and decision artifacts explain faction-asymmetric coverage rather
than silently dropping a counterpart.

**Dependencies:** Slices 0 and 4.

## Slice 6 — Generate and validate CTAs as complete final clauses

**Goal:** eliminate sentence damage caused by post-generation zone-name stripping and prevent weak
fallbacks from shipping as CTAs.

**Primary code areas:** `pipeline/generate/draft/card_lint.py`,
`pipeline/generate/draft/prose_synthesis.py`, `pipeline/generate/draft/pages/questlines.py`, and
`tests/test_questline_cta.py`.

**Implementation:**

1. Delete `strip_zone_name_from_cta` as a final string-replacement transform. Generate a
zone-neutral complete clause directly, or perform a full-clause rewrite that preserves a subject;
never delete a subject token from an already-written sentence.
2. Make CTA synthesis consume the Slice 4 setup/early-chain evidence explicitly. The deterministic
fallback must be a complete, neutral, spoiler-safe sentence grounded in the card title/anchor.
3. Run final-text checks *after* every transformation. Use the repository NLP wrapper for clause
features plus deterministic checks for sentence boundary, finite predicate/imperative structure,
dangling function words, malformed joins, length, and spoiler constraints.
4. On failure, perform one bounded rewrite/retry against the same evidence; if it still fails,
emit the validated deterministic fallback and record the reason. Never ship the broken attempt.

**Tests:** zone-leading declarative sentence, imperative sentence, multi-sentence input, malformed
hyphen/join, missing subject, and fallback all prove the final CTA is grammatical and complete.
Remove tests that expect deleting the zone name to leave a verb phrase.

**Acceptance:** no CTA path performs bare zone-name removal; every emitted CTA has a final lint
decision and an auditable fallback/retry record.

**Dependencies:** Slice 4; benefits from Slice 5 but does not require it.

## Slice 7 — Build selected-card evidence packs and claim-level grounding

**Goal:** make synthesized cards draw from direct, selected evidence rather than whole-paragraph
fallback pools that can support a different entity or only part of a compound claim.

**Primary code areas:** `pipeline/generate/draft/claim_routing.py`,
`pipeline/generate/draft/pages/assembly.py`, `pipeline/generate/draft/evidence_identity.py`,
location/character/questline page builders, and claim-routing tests.

**Implementation:**

1. After card selection—not for every crawled paragraph—construct a typed evidence pack per card.
   Each pack contains direct identity evidence, relationship evidence with explicit direction,
   temporal-safe claim views, and paragraph-granular provenance ids.
2. Run claim extraction/routing for the selected packs that currently rely on paragraph fallback:
   locations, factions, selected questlines, and key-character summaries. This confines added cost
   to material that can reach the user.
3. Require direct identity evidence for each card’s defining sentence. Allow supporting related
   evidence only when the generated relation is explicit and directionally valid; it cannot replace
   identity evidence.
4. Remove page-builder fallback from an empty card-specific pack to an arbitrary same-name or
   general pool. Empty/insufficient packs cause a deterministic drop or neutral structural fallback
   according to card type, with a recorded reason.
5. Preserve original source paragraph ids in all shortened claim views and in final provenance.

**Tests:** containment-direction regression; selected location whose only evidence is a mention on
another page is dropped; a card with direct evidence uses its own pointer; a compound assertion is
split/rejected when one clause lacks support; unselected crawl data incurs no claim-extraction work.

**Acceptance:** every rendered card has an evidence pack and provenance resolves to its direct
identity source; paragraph fallback cannot silently establish card identity.

**Dependencies:** Slices 2–5. Slice 3 supplies instance packs; Slice 5 supplies final questline
metadata.

## Slice 8 — Convert semantic and evidence checks into strict release gates

**Goal:** a run cannot report success while emitting invalid card kinds, broken contracts, unsupported
identity claims, or malformed text.

**Primary code areas:** `pipeline/validate/context.py`, `pipeline/validate/engine.py`,
`pipeline/validate/rules/structure.py`, `pipeline/validate/rules/fact_check.py`,
`pipeline/validate/rules/questline_promotion.py`, and `tests/test_validation_engine.py`.

**Implementation:**

1. Add deterministic hard-fail rules for: non-`place` location cards; non-`named_actor`
key-character cards; absent direct identity evidence; invalid instance-presence/retail-scope data;
metadata handoff mismatch; empty required questline setup evidence; duplicate normalized card
labels; and failed final CTA lint.
2. Validate that the final card agrees with its selection sidecar: id, entity kind, selection
reason, role bounds, chain references, and provenance. Final rendering must not create facts that
the selection/evidence artifact does not contain.
3. Expand fact-check targeting to every selected card’s identity/relationship sentence and every
central section claim, not only manual-link/coalescing risk cases. Use the Slice 7 exact evidence
pack and paragraph pointers.
4. In the strict pilot/release profile, make unsupported or contradicted identity, containment,
role, temporal-state, and central storyline assertions hard failures. Keep noncentral stylistic
coverage warnings visible but distinct.
5. Make run success depend on release-gate success. A warning-only profile remains useful for
exploration, but it must never be labelled equivalent to a strict successful run.

**Tests:** each hard gate fails independently; selected-card coverage ensures a run with no manual
link event still fact-checks cards; warning profile versus strict profile behavior is explicit;
final-card/sidecar disagreement fails.

**Acceptance:** the Maraudon-style generic roster and the Cenarion-Wildlands-style identity
inversion are rejected before a strict run can be marked successful.

**Dependencies:** Slices 2–7.

## Slice 9 — Add generic behavioral regression fixtures and pilot acceptance reporting

**Goal:** keep the pipeline general without returning to gold-output fixtures or zone-specific
rules, and provide a repeatable review surface for future regressions.

**Primary code areas:** synthetic test fixtures, `scripts/check_run_semantics.py`,
`scripts/questline_quality_report.py`, run-artifact helpers, and validation reports.

**Implementation:**

1. Create compact synthetic fixtures for each cross-cutting behavior: entity-kind admission,
   direct evidence ownership, containment direction, named instance participation, metadata handoff,
   arc-family/variant selection, title idempotence, and final CTA validity. They must use invented
   names and generic structures, not WPL/Desolace outputs. Include the adversarial cases required
   by the cross-cutting fixture policy.
2. Extend run-semantic reporting with a machine-readable quality summary: selected-card kinds,
   direct-evidence coverage, deferred retrieval reasons, questline setup coverage, arc-family/variant
   coverage, title collisions, final CTA lint, fact-check scope/verdicts, strict release outcome,
   schema versions, source/input hashes, and live model/prompt identifiers.
3. Define the pilot matrix: WPL + Scholomance, Desolace + Maraudon, and Westfall plus its linked
instance if available. Westfall is a hold-out evaluation subject only; if its source manifest is
not available, create a fresh manifest/run config rather than substituting a hand-authored fixture.
4. Run all matrix subjects through identical strict settings. Review the generated quality reports
   and a small human evidence sample per page using the shared editorial-review rubric; record
   findings as generic defects against a slice, never as an exception for that subject.
5. Add a no-pilot-authority guard that searches shared code, configuration, prompts, and tests for
zone/instance-specific behavior sources. It permits pilot names only in run configurations and
evaluation fixtures, never in classification/selection logic.

**Acceptance [LIVE]:** all matrix runs complete with strict release success; no output card lacks
its required semantic/evidence contract; output review finds no WPL-only repair path; all behavior
tests and the full suite pass.

**Dependencies:** Slices 1–8.

## Completion checklist

- [ ] Slice 0 baseline SHA recorded; `main` and recovery branch established.
- [ ] No title/entity/race/species hardcoding remains in shared card-admission logic.
- [ ] Location and character cards are type-gated and have direct identity evidence.
- [ ] Questline metadata has one schema and non-empty setup evidence where required.
- [ ] Questline selection works on generic arc families/variants and renders titles once.
- [ ] CTAs are final-text validated complete clauses.
- [ ] Selected-card evidence packs drive synthesis and fact checking.
- [ ] Strict validation blocks the observed semantic failures.
- [ ] Coverage shortfalls, unresolved current state, and schema mismatches cannot silently pass.
- [ ] Run manifests make source/model/settings changes visible in quality comparisons.
- [ ] Adversarial fixtures and the shared human-review rubric are exercised by every pilot cycle.
- [ ] The multi-subject pilot matrix passes without zone-specific rules.

## Implementation record

Add a short dated entry after each completed slice: commit SHA, tests run, fresh run ids where
applicable, intentional behavior changes, and any deferred generic follow-up. Do not replace the
acceptance criteria with a prose summary.

### 2026-07-09 — Slice 0 complete

- **Baseline SHA:** `a8e1f48` (`feat(generalization): complete pilot-eviction baseline`). Local
  `main` fast-forwarded to this commit; recovery work begins on
  `fix/generalization-quality-recovery` from the same SHA.
- **Verification:** `git diff --check`; `uv run --no-sync ruff check pipeline tests`; `uv run
  --no-sync mypy pipeline`; focused questline/location/instance/temporal/validation tests
  (49 passed); `uv run --no-sync pytest -q` (passed, with the suite's existing skips/xfail).
- **Baseline correction:** the new no-pilot-scaffolding guard no longer scans `.vscode` run
  configurations, because pilot names are permitted in evaluation/run configuration and forbidden
  only in shared runtime logic.

### 2026-07-09 — Slice 1 complete

- **Commit SHA:** `737519c` (`feat(discovery): add evidence-based entity-kind admission`).
- **Behavior:** added the versioned `EntityKindDecision` contract and
  `entity_kind_decisions.json`; a link with no affirmative target-page or positive registry signal
  remains `unknown`, and only `place` decisions enter the location-card path. Removed the entity
  denylist, race/species and faction title lists, location-title type rules, title-shape entity
  fallbacks, and their vocabulary consumers. The draft reader rejects a missing/mismatched entity
  decision artifact or a candidate/decision identity mismatch.
- **Verification:** `uv run --no-sync ruff check pipeline scripts tests`; `uv run --no-sync mypy
  pipeline`; focused entity/discovery/location/registry/vocabulary tests (55 passed); `uv run
  --no-sync pytest -q` (passed, with the suite's existing skips/xfail). `mypy pipeline scripts`
  still reports 14 pre-existing errors in `scripts/harvest_section_labels.py` and
  `scripts/check_run_semantics.py`; the baseline has never type-checked all scripts, and this
  slice introduced no additional pipeline MyPy errors.
- **Deferred:** Slice 2 will progressively probe/fetch unknown location leads and rebuild direct
  evidence ownership; Slice 3 will apply this contract to named instance participants and their
  instance-presence evidence.
