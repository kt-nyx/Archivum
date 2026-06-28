# Temporal Accuracy Refactor Tracker

Created: 2026-06-27

Purpose: replace brittle paragraph-level temporal routing with a general, boundary-relative,
claim-aware system that can work across all retail WoW zones and instances without pilot-specific
keywords, expansion alias lists, or hardcoded lore cases.

This is a live implementation tracker. Update the status fields as slices land.

## Status Legend

- Not started
- In progress
- Blocked
- Landed
- Verified

## Current Baseline

Latest reviewed run: `artifacts/runs/test-run-wpl-3`

Important artifacts:

- `data/decisions/content_boundary_decisions.json`
- `data/decisions/canonical_temporal_evidence_decisions.json`
- `data/decisions/temporal_evidence_decisions.json`
- `data/drafts/zone_page/zone-western-plaguelands.json`
- `data/drafts/instance_page/instance-scholomance.json`

What is already improved:

- Canonical evidence IDs are created and reused across routed evidence rows.
- Shared paragraphs are classified once instead of separately per field.
- Scholomance history mostly behaves correctly:
  - Shadow Council / Legion material is `post_active_lore`.
  - Lilian Voss completion paragraph is `active_storyline_outcome`.
  - Fourth War report is `post_active_lore`.
  - Final history stops at the playable instance setup.
- WPL Andorhal outcome is excluded from history/current summary.
- Final prose has no ADP/smart-punctuation regressions in run 3.

Remaining temporal failures:

- WPL Argent Dawn cauldron campaign was labeled `post_active_lore`, but should be
  `pre_entry_history`.
- WPL Hearthglen / Argent Crusade setup bridge was correctly labeled `entry_state` +
  `history_setup_bridge`, but final history omitted it.
- WPL Cenarion Circle healing setup is trapped inside a mixed paragraph that also contains the
  Andorhal outcome. Paragraph-level labeling safely excludes the paragraph, but drops the safe
  setup clause.
- Boundary packets are still built from raw snippets and can include noisy at-a-glance/history
  snippets as "current" anchors before temporal classification exists.
- Profile/context evidence is still too often treated as deterministic `entry_state`, even when it
  is historical or generic profile-page material.
- Instance key-character prose can still leak encounter-state spoilers from roster/mechanics rows
  such as `Lilian Voss defeated` or `Course: Reeducation`.
- History synthesis can silently skip eligible setup-bridge evidence.

## Non-Negotiables

- No WPL-specific, Scholomance-specific, expansion-specific, or keyword-list fixes.
- No maintained era alias registry for temporal classification.
- Deterministic logic can use structure, source roles, graph position, category policy, roster
  membership, and persisted metadata.
- LLMs may classify semantic relationships, but must not invent evidence.
- Public addon-facing JSON should remain stable by default, but schema/contract changes are allowed
  if they are explicitly proposed, reviewed, versioned, and justified by downstream addon/editorial
  needs.
- Provenance must remain paragraph/source based even if routing becomes claim-level.
- Offline tests must use deterministic fixtures and mocked LLMs. Release-quality pilot runs may
  require OpenAI-backed classification.

## Clarifying Questions

These are non-blocking. Confirmed decisions should be reflected in the relevant implementation
slices. If one of these decisions needs to change later, update the affected slice before
implementation continues.

1. Should encounter/mechanics labels like `Lilian Voss defeated`, `Course: Reeducation`, or boss
   defeat criteria be spoiler-unsafe for character prose by default?
   - Decision: yes. Treat encounter/mechanics labels as spoiler-unsafe for character prose by
     default unless they are separately classified as safe setup/context.
   - Explanation: this refers to structured dungeon/encounter evidence that is useful for knowing
     who appears in the instance, but is not necessarily safe to repeat in lore prose for a player
     just entering. Examples:
     - `Lilian Voss defeated` proves Lilian is in the encounter/roster, but the word `defeated`
       is a gameplay outcome/state, not pre-entry lore context.
     - `Course: Reeducation` may identify Lilian's encounter theme, but it implies her captured or
       corrupted state and can spoil the in-instance reveal.
     - `Headmaster's Study Darkmaster Gandling` is safer because it locates a character without
       narrating an outcome.
   - Implementation consequence: use encounter/mechanics rows for inclusion and structural role,
     but do not let them write character-summary prose unless they are separately labeled
     `safe_entry_context` or `encounter_setup`.

2. Should a safe setup clause inside a mixed paragraph be usable even when the same paragraph also
   contains an active-storyline outcome?
   - Decision: yes.
   - Implementation consequence: claim-level routing must be able to use the safe setup claim while
     excluding the unsafe outcome claim. Provenance still points back to the source paragraph.

3. Should final history be required to cover at least one eligible `history_setup_bridge` claim
   when one exists?
   - Decision: yes, as proposed.
   - Implementation consequence: history synthesis must track coverage and cannot silently omit all
     eligible setup-bridge claims. Exceptions must be explicit in `section_coverage_decisions.json`
     and should be limited to weak, duplicate, or prose-unsafe claims.

4. Should profile-page evidence be treated as identity context only unless it is independently tied
   to the page entry state?
   - Decision: yes. Treat profile-page evidence as identity context only unless independent local
     evidence ties it to the page entry state.
   - Explanation: profile pages are global pages for factions, characters, locations, and concepts.
     Their lead/history text often spans many eras and many places. "Identity context only" means
     profile evidence can explain what an entity is once the entity is already relevant, but it
     should not by itself prove that entity is currently important to this zone/instance.
   - Example: a Forsaken profile lead can explain that the Forsaken are free-willed undead, but WPL
     evidence or the entry-state contract should prove the Forsaken are relevant to Western
     Plaguelands. A profile-page paragraph about a different war or city should not become
     `entry_state` for WPL merely because the profile was fetched.
   - Implementation consequence: profile evidence supports wording/identity after candidate
     inclusion, while inclusion and temporal relation come from subject-local evidence, quest
     setup, roster, category/source structure, or explicit entry-state contract matches.

5. Should the new sidecars be considered internal/debug artifacts only?
   - Decision: yes for the initial refactor. Keep new sidecars internal/debug-only by default,
     while allowing later public schema/contract changes when explicitly justified.
   - Explanation: "internal/debug artifacts only" means the new entry-state contracts, claim
     extraction records, temporal decisions, and coverage records live under `data/decisions/` and
     guide generation/review, but are not copied into the addon-facing zone/instance JSON.
   - Why keep them internal by default: the addon likely needs concise display content, not every
     claim/rationale/debug label; internal sidecars can change faster without breaking the addon.
   - Why schemas/contracts might still change: if the addon or future editorial workflow needs
     claim IDs, coverage status, spoiler flags, or review metadata, we may want to expose a
     versioned subset publicly.
   - Implementation consequence: implement the refactor with internal sidecars first, but keep
     Slice 11 as an explicit schema/contract decision point. Public draft schema changes are
     allowed if a later slice defines exactly which fields are needed and why.

## Target Architecture

Current rough flow:

```text
raw evidence rows
  -> canonical paragraph grouping
  -> paragraph-level temporal classification
  -> routed drafting pools
  -> final section drafting
```

Target flow:

```text
raw evidence rows
  -> canonical paragraph grouping
  -> entry-state contract per subject
  -> atomic claim/event extraction per canonical paragraph
  -> claim-level temporal + spoiler classification
  -> routed section evidence views
  -> coverage-aware drafting
```

Core idea:

- A paragraph remains the provenance unit.
- A claim becomes the routing unit.
- The entry-state contract becomes the semantic boundary.
- Temporal scope answers "when does this claim sit relative to the player entering?"
- Spoiler safety answers "can this claim be shown to a player before engaging the content?"

## New Internal Concepts

### Entry-State Contract

One per generated subject. It summarizes what the player is walking into.

Suggested internal fields:

```json
{
  "subject_id": "zone-western-plaguelands",
  "subject_type": "zone",
  "boundary_id": "boundary-...",
  "entry_state": {
    "current_locations": [],
    "current_factions": [],
    "current_threats": [],
    "active_conflicts": [],
    "current_objectives": [],
    "current_inhabitants": [],
    "current_controller": "",
    "setup_summary": ""
  },
  "active_storylines": [
    {
      "id": "",
      "title": "",
      "faction": "",
      "start_anchor": "",
      "setup_claims": [],
      "late_or_outcome_hints": []
    }
  ],
  "excluded_outcome_hints": [],
  "source_anchor_refs": [],
  "confidence": 0.0,
  "reason": ""
}
```

Zones should prefer:

- included questline cards
- quest graph order
- first 1-2 quest descriptions
- start NPCs
- start locations
- reputation/faction orgs from quest records
- current field rows already labeled as structurally current
- location/faction profile leads only after source/category checks

Instances should prefer:

- current infobox
- boss/encounter roster
- adventure guide/current dungeon description
- current occupants/factions from lead/overview
- current instance objective/antagonist
- lore source mapping

### Atomic Claim

One canonical paragraph can produce many claims.

Suggested internal fields:

```json
{
  "claim_id": "claim-...",
  "canonical_evidence_id": "canonical-...",
  "subject_id": "",
  "source_id": "",
  "source_title": "",
  "claim_text": "",
  "claim_type": "event|state|identity|relationship|objective|location_status|faction_presence|encounter_state|other",
  "entities": [],
  "source_sentence_indexes": [],
  "source_excerpt": "",
  "extraction_confidence": 0.0,
  "extraction_reason": ""
}
```

### Claim Temporal Classification

Suggested labels:

- `pre_entry_history`
- `history_setup_bridge`
- `entry_state`
- `active_storyline`
- `active_storyline_outcome`
- `post_active_lore`
- `excluded_noncanon`
- `ambiguous_temporal`

Important note: `history_setup_bridge` can be either a separate temporal scope or a history
eligibility value. The implementation can keep the current `temporal_scope=entry_state` +
`history_eligibility=history_setup_bridge` shape for compatibility. The claim-level sidecar should
still make setup bridge explicit.

### Spoiler Safety

Suggested labels:

- `safe_background`
- `safe_entry_context`
- `safe_setup_hook`
- `encounter_setup`
- `active_mechanics_state`
- `active_outcome`
- `post_active_reference`
- `unsafe_completion_detail`
- `unknown_spoiler_safety`

Examples:

- "Darkmaster Gandling controls Scholomance" -> `safe_entry_context`
- "Lilian Voss entered Scholomance to stop the necromancers" -> likely `safe_setup_hook`
- "Gandling subdued Lilian Voss" -> `active_storyline_outcome` or `unsafe_completion_detail`
- "Lilian Voss defeated" -> `active_mechanics_state`
- "Course: Reeducation" -> likely `active_mechanics_state` or `encounter_setup`, not general
  character-summary prose by default

## Sidecars To Add Or Replace

New sidecars:

- `data/decisions/entry_state_contract_decisions.json`
- `data/decisions/canonical_claim_extraction_decisions.json`
- `data/decisions/claim_temporal_decisions.json`
- `data/decisions/section_coverage_decisions.json`

Existing sidecars to keep during migration:

- `content_boundary_decisions.json`
- `canonical_temporal_evidence_decisions.json`
- `temporal_evidence_decisions.json`

Schema note:

- These artifacts should start as internal decision sidecars.
- Public draft schema exposure is allowed later if there is a clear addon/editorial consumer need.
- Any public schema change must be explicit, versioned, tested, and recorded in Slice 11.

Eventually:

- `content_boundary_decisions.json` can become a compatibility projection of
  `entry_state_contract_decisions.json`.
- `canonical_temporal_evidence_decisions.json` can summarize paragraph-level aggregate labels
  derived from claim labels.
- `temporal_evidence_decisions.json` can remain a routed-view audit artifact.

## Slice 0 - Baseline Audit And Instrumentation

Status: Verified

Goal: make the current failure modes mechanically visible before changing behavior.

Why first:

- We need to know whether future changes fix classification, routing, synthesis, or all three.
- Run 3 has enough artifacts to define concrete regression checks.

Files likely touched:

- `tests/test_temporal_evidence_classifier.py`
- `tests/test_draft_baseline.py`
- `tests/test_instance_pilot_gold_standard.py`
- `tests/test_pilot_questline_gold_standard.py`
- `scripts/check_run_semantics.py` only if new checks belong in release gate
- possibly new `tests/test_temporal_run_artifacts.py`

Implementation tasks:

1. Add a helper that loads run artifacts from a fixture-like directory and summarizes:
   - boundary anchors by subject
   - canonical paragraph labels by subject and field appearances
   - history-eligible labels that do not appear in final history text
   - post/outcome labels that do appear in final history/current/faction/character text

2. Add targeted assertions for current known failures using small fixtures, not the full live run:
   - WPL-like Argent Dawn cauldron claim is before current Cataclysm entry state.
   - WPL-like Hearthglen setup bridge is labeled eligible and is required in history coverage.
   - Mixed Cenarion/Andorhal paragraph splits safe setup from unsafe outcome once claim extraction
     exists. This is a confirmed requirement from clarification question 2. Before claim
     extraction, mark expected xfail or pending in tracker.
   - Scholomance Shadow Council remains `post_active_lore`.
   - Scholomance Lilian completion paragraph remains outcome/unsafe.

3. Add sidecar existence checks for future sidecars but skip until implemented.

4. Add documentation comments explaining which failures are classifier-level vs downstream
   synthesis-level.

Acceptance:

- Full suite still passes.
- New tests fail or xfail only where they intentionally describe not-yet-implemented behavior.
- There is a reusable helper for comparing labels to final draft omissions.

Implementation notes:

- Added `tests/temporal_run_artifact_helpers.py` with `summarize_temporal_run_artifacts(...)`.
- The helper reads fixture-like run directories and summarizes:
  - boundary anchors by subject;
  - canonical paragraph labels by subject and appearance fields;
  - history-eligible canonical snippets absent from final history text;
  - restricted outcome/post-active/noncanon snippets appearing in final history/current/faction/
    character text;
  - present/missing temporal decision sidecars.
- Review-cycle refinement: presence/leak checks now match exact normalized sentence/clause
  fragments as well as whole snippets, so copied subparts of a source paragraph are mechanically
  visible without adding semantic matching.
- Added `tests/test_temporal_run_artifacts.py` with distilled artifact fixtures instead of live
  `artifacts/runs/test-run-wpl-3` dependencies.
- Tests now distinguish:
  - classifier-level labels, such as Shadow Council `post_active_lore` and Lilian completion
    `active_storyline_outcome`;
  - downstream synthesis/coverage omissions, such as an eligible Hearthglen setup bridge missing
    from final history;
  - restricted-label leaks into spoiler-sensitive final fields.
- Added an intentional `xfail` for mixed setup/outcome paragraphs until claim extraction lands.
- Added a skipped future-sidecar existence check for claim and coverage sidecars.

Validation:

- `uv run pytest tests/test_temporal_run_artifacts.py tests/test_temporal_evidence_classifier.py tests/test_entry_state_contract.py -q`
- `uv run pytest -q`

Risks:

- Avoid tests that depend directly on live `artifacts/runs/test-run-wpl-3`, unless skipped when
  missing. Prefer distilled fixtures.

## Slice 1 - Entry-State Contract V1

Status: Completed

Goal: replace raw boundary snippets as the classifier's primary context with a structured,
run-specific entry-state contract.

Files likely touched:

- `pipeline/generate/draft/temporal.py`
- possibly new `pipeline/generate/draft/entry_state.py`
- `pipeline/generate/draft_writer.py`
- tests in `tests/test_temporal_evidence_classifier.py`
- new tests in `tests/test_entry_state_contract.py`

Implementation tasks:

1. Introduce `EntryStateContract` dataclass or typed dict.

2. Implement deterministic contract builder:
   - `build_entry_state_contracts(...)`
   - called before temporal/claim classification
   - one contract per generated entity

3. Zone contract fields:
   - `current_locations`
   - `current_factions`
   - `current_threats`
   - `active_conflicts`
   - `current_objectives`
   - `active_storylines`
   - `excluded_outcome_hints`
   - `source_anchor_refs`

4. Instance contract fields:
   - `current_locations`
   - `current_factions`
   - `current_inhabitants`
   - `current_controller`
   - `current_objectives`
   - `active_encounters`
   - `excluded_outcome_hints`
   - `source_anchor_refs`

5. Use only structural signals:
   - quest graph order
   - first quest descriptions
   - start/end NPCs for early quest records
   - questline card metadata
   - roster/infobox/adventure-guide links
   - source roles and category registry
   - existing included cluster decisions

6. Do not use expansion names, year numbers, or era keyword rules to determine order.

7. Add optional LLM contract distillation only after deterministic anchors:
   - input: structural anchors and snippets
   - output: concise contract fields
   - no invented entities allowed
   - if LLM unavailable, deterministic contract remains usable

8. Persist `entry_state_contract_decisions.json`.

9. Keep `content_boundary_decisions.json` as a compatibility projection for existing code.

Test plan:

- WPL contract includes:
  - Andorhal conflict as active
  - Hearthglen / Argent Crusade setup
  - Gahrron's Withering plague setup
  - outcome hints for late Andorhal victory
- WPL contract does not put Fourth War report in entry state.
- Scholomance contract includes:
  - Darkmaster Gandling
  - Scourge / Cult current occupancy
  - boss roster
  - current school of necromancy setup
- Scholomance contract does not include Shadow Council as current roster.
- Missing questline data still produces a lower-confidence contract from lead/roster/source roles.

Acceptance:

- Existing temporal tests pass or are updated to read contract sidecars.
- Contract sidecar is available in new runs.
- Boundary prompt uses structured contract payload, not raw digest as the main context.

Implementation notes:

- Added `EntryStateContract` and `build_entry_state_contracts(...)` in
  `pipeline/generate/draft/temporal.py`.
- Added deterministic zone contracts from questline setup records, early quest records, questline
  card metadata, and current structural anchors.
- Added deterministic instance contracts from infobox fields, current roster/encounter links, and
  current structural anchors.
- Added conservative profile metadata extraction for entry-like `location_pool` and `faction_pool`
  rows so contract location/faction fields are populated without treating generic profile history as
  current state.
- Added an opt-in LLM distillation hook behind `WOW_LORE_ENTRY_STATE_CONTRACT_LLM`; it is disabled
  by default and can only add meaningful labels already present in the deterministic contract.
- `content_boundary_decisions.json` is now a compatibility projection from the entry-state contract.
- `entry_state_contract_decisions.json` is written by the draft writer.
- Removed unreachable pre-contract zone/instance boundary builders; the defensive fallback boundary
  now also projects from a fallback entry-state contract.
- Added `tests/test_entry_state_contract.py`.

Validation:

- `uv run pytest tests/test_entry_state_contract.py tests/test_temporal_evidence_classifier.py -q`
- `python -m py_compile pipeline/generate/draft/temporal.py pipeline/generate/draft_writer.py`
- `uv run pytest -q`

Risks:

- Overly broad supplemental anchors can reintroduce noisy history/post-active snippets. The contract
  builder must distinguish `anchor_kind` and confidence, and avoid treating all at-a-glance rows as
  current facts.

## Slice 2 - Contract-Aware Paragraph Classification

Status: Verified

Goal: improve current paragraph-level classification before claim extraction lands.

Why this slice exists:

- Claim extraction is a bigger change.
- We can get immediate quality gains by using the contract and reducing overconfident structural
  defaults.

Files likely touched:

- `pipeline/generate/draft/temporal.py`
- `pipeline/generate/draft/entry_state.py` if created
- `tests/test_temporal_evidence_classifier.py`

Implementation tasks:

1. Replace boundary prompt payload with entry-state contract:
   - include `entry_state`
   - include `active_storylines`
   - include `excluded_outcome_hints`
   - include source roles and appearances

2. Revise LLM rubric:
   - `post_active_lore` means after or outside the playable entry boundary.
   - "Later than the origin/fall" does not imply post-active.
   - If a claim/event helps explain why the contract's current state exists, use
     setup bridge or pre-entry history as appropriate.
   - Classic-era, pre-Cataclysm, pre-current-page events can still be history even if they mention
     heroes/adventurers.

3. Lower deterministic confidence for profile/context fields:
   - profile page lead/history becomes `ambiguous_temporal` or `identity_context_needs_contract`
     unless tied to entry-state contract.
   - profile evidence can still support identity summaries after filtering, but should not force
     temporal scope.
   - This follows the confirmed decision from clarification question 4.

4. Keep deterministic hard labels for:
   - noncanon/removed/RPG-only
   - early quest setup
   - late quest outcomes
   - roster membership as structural current, but not necessarily spoiler-safe

5. Add classification confidence/rationale fields that show:
   - contract match
   - source role
   - appearance roles
   - reason for exclusion

6. Preserve canonical paragraph grouping and routed label copying.

Test plan:

- WPL Argent Dawn cauldron campaign classifies as `pre_entry_history`.
- WPL Hearthglen setup remains `entry_state` + `history_setup_bridge`.
- WPL Andorhal outcome remains `active_storyline_outcome`.
- WPL Fourth War report remains `post_active_lore`.
- Generic profile-page historical paragraph is not automatically `entry_state`.
- Scholomance Shadow Council remains `post_active_lore`.

Acceptance:

- `test-run-wpl` equivalent run should show improved WPL history eligibility before changing
  claim extraction.
- Existing Scholomance pass should not regress.

Implementation notes:

- Moved profile/context field handling ahead of generic entry-role handling in
  `pipeline/generate/draft/temporal.py`.
- Profile/context evidence now becomes deterministic `entry_state` only when it has an independent
  match against the entry-state contract. Self-generated `entry_profile_context` contract entries
  and same-source profile snippets do not count as independent ties.
- Profile/context evidence without an independent contract tie becomes `ambiguous_temporal` with
  `needs_llm`, preserving it for boundary adjudication without forcing it into current summaries.
- Later report/book/source-role evidence still receives deterministic `post_active_lore`.
- Added exact-label/ID contract relation metadata to canonical decision rows and LLM prompt items:
  `contract_relation`, `source_roles`, and richer deterministic hints.
- Revised the LLM rubric to classify relative to the entry-state contract rather than named eras,
  explicitly noting that events later than an origin/fall can still be `pre_entry_history`.
- Added tests for:
  - contract-aware LLM classification of an earlier cauldron-style campaign as
    `pre_entry_history`;
  - profile evidence not self-promoting into `entry_state`;
  - independently contract-tied profile evidence remaining usable as `entry_state`.

Validation:

- `uv run pytest tests/test_temporal_evidence_classifier.py tests/test_entry_state_contract.py -q`
- `uv run pytest -q`

Risks:

- Prompt-only changes may still misclassify mixed paragraphs. That is acceptable for this slice;
  Slice 4 is the durable fix.

## Slice 3 - Atomic Claim Model And Sidecar

Status: Verified

Goal: introduce claim records without changing routing behavior yet.

Files likely touched:

- new `pipeline/generate/draft/claims.py`
- `pipeline/generate/draft/temporal.py`
- `pipeline/generate/draft_writer.py`
- `pipeline/contracts/models.py` only if internal model objects are centralized there
- tests in new `tests/test_claim_extraction.py`

Implementation tasks:

1. Define claim model:
   - `claim_id`
   - `canonical_evidence_id`
   - `subject_id`
   - `source_id`
   - `source_title`
   - `claim_text`
   - `claim_type`
   - `entities`
   - `source_sentence_indexes`
   - `source_excerpt`
   - `extraction_confidence`
   - `extraction_reason`

2. Add deterministic sentence splitting:
   - use existing text cleaning utilities
   - preserve offsets or sentence indexes
   - avoid changing source text

3. Add claim ID generation:
   - hash `canonical_evidence_id + normalized claim_text + sentence indexes`
   - stable across reruns unless text changes

4. Add sidecar writer:
   - `canonical_claim_extraction_decisions.json`

5. Initial extraction can be conservative:
   - one claim per sentence
   - no semantic splitting inside semicolon-heavy sentences yet
   - no routing changes

6. Add appearance mapping:
   - each claim knows all paragraph appearances through `canonical_evidence_id`

7. Keep provenance at canonical paragraph/source pointer level.

Test plan:

- Same paragraph across `history_digest`, `currently_input`, and `at_a_glance_input` produces one
  claim set.
- Different paragraphs from same source produce different claim sets.
- Claim IDs are stable.
- Mixed paragraph produces multiple sentence-level claims.

Acceptance:

- Sidecar exists and is deterministic.
- Public draft JSON unchanged.
- No section routing changes yet.

Risks:

- Sentence splitting is not enough for all mixed paragraphs, but it creates the model and sidecar
  needed for LLM claim extraction.

Implementation notes:

- Added `pipeline/generate/draft/claims.py` with a source-side `EvidenceClaim` model. This is
  deliberately separate from coalesce/entity fact claims and post-draft validation claims.
- Extraction is deterministic sentence-level only:
  - one claim per sentence;
  - stable `claim_id` from `canonical_evidence_id`, normalized claim text, and sentence indexes;
  - no semantic clause splitting or routing changes yet.
- `enrich_evidence_temporal_metadata(..., return_claim_decisions=True)` now returns
  `canonical_claim_extraction_decisions` for callers that opt in.
- `run_draft_writer` writes `data/decisions/canonical_claim_extraction_decisions.json`.
- Public draft JSON remains unchanged.

Review notes:

- First review pass fixed claim extraction so it is runtime opt-in unless a caller requests
  `return_claim_decisions=True`; this keeps ordinary temporal enrichment from doing unnecessary
  sidecar work.
- Second review pass made `claim_type` conservative when one canonical paragraph has conflicting
  routed appearances, returning `other` instead of biasing toward one downstream field.
- Added tests that pin no semantic splitting inside semicolon-heavy sentences, no claim metadata in
  public draft JSON, and no extraction call when claim decisions are not requested.

## Slice 4 - LLM Claim Extraction For Mixed Paragraphs

Status: Verified

Goal: split canonical paragraphs into semantic claims/events when sentence-level splitting is too
coarse.

Files likely touched:

- `pipeline/generate/draft/claims.py`
- `pipeline/generate/draft/llm.py`
- tests in `tests/test_claim_extraction.py`

Implementation tasks:

1. Add LLM extraction path for candidate paragraphs:
   - paragraphs with multiple temporal signals from structural appearances
   - history paragraphs that also appear in current fields
   - paragraphs with outcome hints and setup phrases in same paragraph
   - long paragraphs above a word threshold
   - paragraphs where sentence-level claims still contain multiple independent events

2. Prompt output schema:
   - `claims[]`
   - each claim has `claim_text`, `claim_type`, `source_sentence_indexes`, `entities`,
     `extraction_reason`

3. Prompt rules:
   - split into smallest useful factual claims
   - do not summarize away entities
   - do not invent facts
   - keep exact meaning but not necessarily exact wording
   - preserve relation to source sentence indexes

4. Fallback:
   - if LLM unavailable or fails, use sentence-level claims
   - mark `extraction_mode=sentence_fallback`

5. Persist extraction mode in sidecar.

6. Add a claim-level passthrough/copyright check:
   - claims should be concise paraphrases where possible
   - retain source excerpt for audit, not final prose

Test plan:

- WPL mixed Cataclysm paragraph yields separate claims:
  - Cenarion Circle helps dispel plague
  - life starts emerging
  - war rages at Andorhal/Gahrron's Withering
  - Forsaken gain control of Andorhal
  - Alliance cast out
  - Scourge presence ends
- Claims preserve source pointer back to one paragraph.
- No invented claim appears when source lacks it.

Acceptance:

- Claim sidecar clearly exposes safe vs unsafe components of mixed paragraphs.
- Safe setup claims inside mixed paragraphs are usable even when sibling claims in the same source
  paragraph are excluded outcomes, per confirmed clarification question 2.
- No public draft behavior changes required yet.

Risks:

- LLM extraction may over-split. Prefer too many small claims over one mixed claim because routing
  can cluster later.

Implementation notes:

- Extended `pipeline/generate/draft/claims.py` with an LLM semantic extraction path for likely
  mixed canonical paragraphs.
- Candidate detection stays structural/general:
  - paragraph appears in both history and current drafting views;
  - canonical record has multiple structural temporal signals;
  - paragraph is long;
  - sentence-level fallback has semicolon-heavy or very long sentences;
  - paragraph overlaps both entry-state setup context and outcome-hint context.
- LLM output remains sidecar-only and does not change section routing or public draft JSON.
- Unsupported LLM claims are filtered by source-overlap checks; provider failures or disabled LLM
  produce `extraction_mode=sentence_fallback`.
- Claim rows now include `source_passthrough_risk` and `source_passthrough_reason` for the
  claim-level copyright/passthrough audit.

Review notes:

- First review pass tightened source-support filtering so short invented claims with only one
  shared token are rejected, and fixed overlong LLM claims so `claim_id` is derived from the
  emitted/truncated claim text.
- Second review pass added sentence-level backfill for source sentences not covered by valid LLM
  claims, preventing semantic extraction from silently dropping evidence.
- Added regression tests for invalid sentence indexes, partial-overlap inventions, passthrough risk,
  setup/outcome candidate detection, overlong claim ID stability, and LLM sentence backfill.

## Slice 5 - Claim-Level Temporal And Spoiler Classification

Status: Not started

Goal: classify claims, not paragraphs, against the entry-state contract.

Files likely touched:

- `pipeline/generate/draft/temporal.py`
- `pipeline/generate/draft/claims.py`
- `pipeline/generate/draft/entry_state.py`
- tests in `tests/test_temporal_evidence_classifier.py`
- new `tests/test_claim_temporal_classifier.py`

Implementation tasks:

1. Implement `classify_claims_temporal(...)`.

2. Deterministic claim hints:
   - source role
   - canonical paragraph appearances
   - active quest graph position
   - late/outcome hint relation
   - roster/encounter membership
   - category exclusion signal
   - contract entity matches

3. LLM input:
   - entry-state contract
   - claim text
   - claim type/entities
   - source role
   - paragraph appearances
   - deterministic hints
   - outcome hints

4. LLM output per claim:
   - temporal scope
   - history eligibility
   - spoiler safety
   - confidence
   - rationale
   - event label

5. Spoiler-safety rules:
   - active outcome is unsafe for pre-entry player context
   - mechanics-state snippets are unsafe for general character summaries
   - roster membership is safe entry context only when it identifies presence/role without defeat,
     room-state, or encounter resolution

6. Persist `claim_temporal_decisions.json`.

7. Aggregate paragraph labels from claim labels for compatibility:
   - if any claim is `active_storyline_outcome`, paragraph aggregate may remain restrictive for
     paragraph-level consumers
   - claim-level routed views can still use safe claims from mixed paragraphs

Test plan:

- WPL Argent Dawn cauldron claim is `pre_entry_history`.
- WPL Cenarion Circle healing claim is setup/history eligible.
- WPL Andorhal victory claim is outcome/unsafe.
- WPL Fourth War claim is post-active.
- Scholomance Shadow Council claim is post-active.
- Scholomance Lilian capture/escape claim is outcome/unsafe.
- Scholomance `Course: Reeducation` is not safe for character summary prose by default.

Acceptance:

- Sidecar has claim-level labels and paragraph aggregate labels.
- Paragraph-level tests still pass through compatibility layer.

Risks:

- Need to avoid creating two competing classification truths. Claim labels should become source of
  truth; paragraph labels should be derived compatibility summaries.

## Slice 6 - Claim-Level Routed Evidence Views

Status: Not started

Goal: make drafting pools consume safe claims while preserving paragraph provenance.

Files likely touched:

- `pipeline/generate/draft/pages/assembly.py`
- `pipeline/generate/draft/pages/cards.py`
- `pipeline/generate/draft/pages/zone.py`
- `pipeline/generate/draft/pages/instance.py`
- possibly new `pipeline/generate/draft/claim_routing.py`
- tests in `tests/test_draft_baseline.py`

Implementation tasks:

1. Add a claim-view object for drafting:
   - `claim_text`
   - `source_url`
   - `source_title`
   - `source_id`
   - `canonical_evidence_id`
   - `claim_id`
   - `temporal_scope`
   - `history_eligibility`
   - `spoiler_safety`
   - `source_refs`
   - original paragraph snippet for audit only

2. Build field-specific claim pools:
   - history pool
   - currently pool
   - at-a-glance pool
   - faction context pool
   - location context pool
   - instance overview pool
   - key-character pool

3. Filtering rules:
   - history accepts `history_background` and `history_setup_bridge`
   - currently accepts `entry_state`, safe setup, and non-outcome active setup
   - at-a-glance accepts background + entry-state identity, not outcomes/post-active
   - faction summaries accept identity + entry-state relevance, not profile lore unrelated to
     subject contract
   - key-character summaries accept safe identity/context, not active mechanics/outcomes
   - safe claims from mixed paragraphs are routeable independently of excluded sibling claims from
     the same source paragraph

4. Keep paragraph-level fallback when no claim sidecar exists:
   - important for incremental rollout and old artifacts

5. Update provenance pointer generation:
   - source refs still point to paragraph/source locator
   - optional `claim_id` can appear in internal sidecars, not public source refs

Test plan:

- Mixed paragraph safe claim can enter WPL history while outcome claim is excluded.
- No outcome claim appears in WPL currently/history/faction text.
- Scholomance key-character pool excludes unsafe Lilian outcome/mechanics claims.
- Public draft JSON remains schema-valid.

Acceptance:

- Claim pools are visible in debug output or sidecars.
- Existing paragraph-only tests pass via fallback.

Risks:

- Some prose synthesis code assumes `snippet`. Claim views may need to expose `snippet=claim_text`
  while retaining `source_excerpt` separately.

## Slice 7 - Coverage-Aware History Synthesis

Status: Not started

Goal: prevent eligible background/setup evidence from silently disappearing from final history.

Files likely touched:

- `pipeline/generate/draft/pages/cards.py`
- `pipeline/generate/draft/prose_synthesis.py`
- `pipeline/generate/draft/prose_election.py`
- new `pipeline/generate/draft/coverage.py`
- tests in `tests/test_history_coverage.py`

Implementation tasks:

1. Add history coverage planner:
   - input: history claim pool
   - output: `coverage_units`
   - group by chronology/source order and semantic relation
   - mark setup bridge units as required if present, per confirmed clarification question 3

2. Define coverage unit fields:
   - `coverage_id`
   - `claim_ids`
   - `required`
   - `reason`
   - `suggested_heading`
   - `temporal_bucket`
   - `source_order`

3. LLM history prompt changes:
   - include required coverage units
   - require every required unit to be represented
   - allow combining adjacent units into one card
   - require `covered_coverage_ids` in response

4. Add deterministic coverage validator:
   - response must cover all required units
   - response must not cover excluded outcome/post-active claims
   - if missing required units, retry once with explicit missing IDs
   - if still missing, deterministic fallback can append a concise setup bridge card from safe
     claim text

5. Persist `section_coverage_decisions.json`.

6. Keep max section cap:
   - coverage planner can merge adjacent related units
   - cap should not justify dropping required setup bridge

Test plan:

- WPL five eligible history units include Hearthglen setup bridge.
- Final history includes the setup bridge, either as its own card or combined.
- If LLM returns only first three sections, retry occurs.
- If retry fails, deterministic fallback includes missing setup bridge.
- Scholomance four-card history remains stable.

Acceptance:

- No eligible `history_setup_bridge` claim is omitted without a sidecar reason.
- WPL run includes post-Lich-King Hearthglen/Argent Crusade setup.

Risks:

- Overforcing coverage can produce bloated history. Mitigate by allowing merged coverage units and
  concise bridge cards.

## Slice 8 - Current, At-A-Glance, And Faction Routing From Claims

Status: Not started

Goal: use claim labels and entry-state contract to improve current summaries and faction cards.

Files likely touched:

- `pipeline/generate/draft/pages/assembly.py`
- `pipeline/generate/draft/pages/zone.py`
- `pipeline/generate/draft/pages/instance.py`
- `pipeline/generate/draft/faction_scoring.py`
- `pipeline/generate/draft/prose_synthesis.py`
- tests in `tests/test_faction_scoring.py`
- tests in `tests/test_instance_faction_harvest.py`

Implementation tasks:

1. Current summary:
   - prefer claim pool matching `entry_state` and `safe_entry_context`
   - allow setup hooks for active conflicts
   - exclude outcome/post-active

2. At-a-glance:
   - prefer identity/background + entry-state claims
   - avoid using history claims that are only old origin if they obscure current identity

3. Faction candidates:
   - candidates from entry-state contract get a support boost
   - candidates from claim entities get support when claim is entry-state or setup
   - profile-page identity evidence can support summary wording but not inclusion by itself unless
     tied to subject contract
   - this profile-page rule follows the confirmed decision from clarification question 4

4. Faction prose:
   - use claim-level subject relevance
   - separate faction identity context from role in this page
   - avoid past-tense active outcomes

5. Instance factions:
   - use contract current factions/inhabitants
   - avoid later off-screen factions even if source page mentions them

Test plan:

- WPL faction set includes current/restoration/active conflict actors expected by policy once
  selection goals are clarified.
- WPL faction summaries do not spoil Andorhal outcome.
- Generic profile-page faction history does not dominate a zone summary.
- Scholomance keeps Scourge and Cult of the Damned, excludes Shadow Council.

Acceptance:

- Faction prose becomes less profile-generic and more page-specific.
- No temporal regressions in current or at-a-glance fields.

Risks:

- Faction selection policy still has editorial ambiguity. This slice should focus on temporal
  routing and evidence quality; final inclusion policy may need separate review.

## Slice 9 - Key Character Spoiler-Safe Evidence

Status: Not started

Goal: stop key-character summaries from using unsafe encounter outcomes or mechanics-state snippets
as general pre-entry lore.

Files likely touched:

- `pipeline/generate/draft/pages/key_characters.py`
- `pipeline/discovery/instance_bosses.py`
- `pipeline/generate/draft/pages/instance.py`
- tests in `tests/test_build_instance_key_character_selection.py`
- tests in `tests/test_instance_pilot_gold_standard.py`

Implementation tasks:

1. Split key-character input pools:
   - identity/background claims
   - safe entry role claims
   - encounter/mechanics claims
   - unsafe outcome claims

2. Summary prompt inputs:
   - pass structural role separately
   - pass safe claims only for prose
   - pass unsafe claims only as exclusion/risk hints, not usable content

3. Add deterministic filters:
   - `spoiler_safety in {active_mechanics_state, active_outcome, unsafe_completion_detail}` is not
     allowed in summary evidence
   - roster membership alone can justify inclusion, but not spoil wording
   - this follows the confirmed decision from clarification question 1

4. Add fallback summary behavior:
   - if only unsafe evidence exists, generate a restrained identity/role summary from structural
     role and page context, or omit summary detail rather than using spoiler text

5. Update character decision sidecar:
   - include counts of safe vs unsafe evidence
   - include reason if summary used structural fallback

Test plan:

- Lilian Voss summary does not say she is captured, subdued, corrupted, defeated, or escaped.
- Rattlegore summary explains guardian/experiment role without "stands as" repetition.
- Instructor Chillheart summary is not generic if safe claim evidence exists.
- Darkmaster Gandling remains strong and in-universe.

Acceptance:

- Scholomance key characters remain five cards.
- Character summaries are entry-perspective safe.

Risks:

- Some characters only have encounter/mechanics evidence. Structural fallback must be acceptable
  and conservative.

## Slice 10 - Claim-Aware Location And Glossary Filtering

Status: Not started

Goal: prevent post-active or unsafe claims from supporting location/glossary inclusion, while also
using safe setup claims more accurately.

Files likely touched:

- `pipeline/generate/draft/location_scoring.py`
- `pipeline/generate/draft/pages/assembly.py`
- `pipeline/glossary/run_terms.py`
- tests in `tests/test_faction_scoring.py` if shared utilities
- tests in `tests/test_glossary_run_terms.py`

Implementation tasks:

1. Location scoring:
   - use claim-level temporal labels for seed mentions
   - suppress locations whose only support is post-active/off-page lore
   - support locations from safe active setup and instance anchors

2. Significance tag assignment:
   - infer from structured signals and claim types
   - avoid assigning tags from unrelated profile snippets
   - keep controlled vocabulary

3. Glossary filtering:
   - term must appear in final normalized display text
   - term provenance must not be only excluded/post-active/noncanon claims
   - terms from unsafe spoiler claims should not be linked in pre-entry prose

4. Sidecar updates:
   - location decision rationale can include claim IDs
   - glossary sidecar can include claim provenance

Test plan:

- Strahnbrad is not supported as WPL major location from post-active/Fourth War claims.
- Uther's Tomb tag is not derived from wrong context.
- Scholomance Shadow Council does not appear as glossary/faction/current term if absent from final
  display text.

Acceptance:

- No accidental public schema changes.
- Location/glossary decisions are explainable through claim labels.

Risks:

- Location inclusion has non-temporal quality issues too. This slice should only handle temporal
  evidence support and spoiler drift.

## Slice 11 - Backward Compatibility And Migration

Status: Not started

Goal: keep existing pipeline functions usable while claim-level classification rolls out, and make
an explicit schema/contract decision before exposing claim metadata publicly.

Files likely touched:

- `pipeline/generate/draft/temporal.py`
- `pipeline/generate/draft/pages/assembly.py`
- `pipeline/generate/draft_writer.py`
- `pipeline/contracts/models.py`
- schemas only if internal schema exports require optional fields

Implementation tasks:

1. Add feature flag or capability detection:
   - if claim sidecar exists, use claim views
   - else use canonical paragraph labels

2. Keep `EvidenceItem` optional metadata stable:
   - `canonical_evidence_id`
   - `temporal_scope`
   - `history_eligibility`
   - `temporal_reason`
   - `temporal_event_label`

3. Add optional claim metadata only if needed:
   - `claim_ids`
   - avoid making draft JSON depend on it until the schema decision below is made

4. Maintain old sidecars during transition.

5. Add explicit version fields:
   - `temporal_classifier_version`
   - `claim_extractor_version`
   - `entry_state_contract_version`

6. Add a schema/contract decision record:
   - document whether claim IDs, spoiler safety, coverage status, or review metadata should remain
     internal sidecar-only or become part of public draft JSON
   - if public fields are added, version the affected schema and update fixtures in the same slice
   - preserve addon compatibility or add a migration note for addon consumers

Test plan:

- Old test fixtures without claim sidecars still pass.
- New claim-enabled fixtures route through claim views.
- Draft writer can write both old and new sidecars.
- Schema export/tests cover either internal-only metadata or approved public fields.

Acceptance:

- No accidental public addon-facing draft JSON changes. Any public schema changes are explicit,
  versioned, tested, and tied to a documented consumer/editorial need.
- Existing full suite passes throughout migration.

Risks:

- Dual paths can hide bugs. Keep fallback path small and plan to delete it after enough runs.

## Slice 12 - End-To-End Pilot Rebaseline

Status: Not started

Goal: verify WPL and Scholomance with real pipeline artifacts after the refactor.

Files likely touched:

- tests/fixtures/pilot only after review
- maybe Reference tracker updates

Implementation tasks:

1. Run a fresh pilot:
   - new incremented run ID
   - OpenAI ready
   - no `WOW_LORE_WIKI_FIRST_NO_LLM`

2. Inspect sidecars:
   - entry-state contract
   - claim extraction
   - claim temporal
   - coverage decisions
   - routed temporal decisions

3. Compare final drafts:
   - WPL history includes Argent Dawn/Argent Crusade setup and excludes Andorhal outcome.
   - WPL current summary is entry-perspective.
   - WPL questline CTAs stay spoiler-free.
   - WPL location cards do not include Strahnbrad from later/off-zone support.
   - Scholomance history excludes Shadow Council/Fourth War.
   - Scholomance character summaries avoid active/outcome spoilers.

4. Run:
   - `uv run pytest -q`
   - `uv run python -m scripts.check_run_semantics artifacts/runs/<run-id>`

5. Update gold fixtures only after manual review.

Acceptance:

- Full test suite passes.
- Semantic checker has no new temporal/content-boundary failures.
- Any remaining failures are documented separately and not caused by temporal routing.

Risks:

- Existing quest graph provenance checker may still fail independently. Do not conflate that with
  temporal accuracy unless the failure affects evidence routing.

## Suggested Implementation Order

1. Slice 0 - Baseline Audit And Instrumentation
2. Slice 1 - Entry-State Contract V1
3. Slice 2 - Contract-Aware Paragraph Classification
4. Slice 7 - Coverage-Aware History Synthesis
5. Slice 3 - Atomic Claim Model And Sidecar
6. Slice 4 - LLM Claim Extraction For Mixed Paragraphs
7. Slice 5 - Claim-Level Temporal And Spoiler Classification
8. Slice 6 - Claim-Level Routed Evidence Views
9. Slice 9 - Key Character Spoiler-Safe Evidence
10. Slice 8 - Current, At-A-Glance, And Faction Routing From Claims
11. Slice 10 - Claim-Aware Location And Glossary Filtering
12. Slice 11 - Backward Compatibility And Migration
13. Slice 12 - End-To-End Pilot Rebaseline

Reasoning:

- Slices 1, 2, and 7 likely fix the largest visible WPL history regression quickly.
- Slices 3 through 6 are the durable mixed-paragraph solution.
- Slice 9 should happen before final pilot review because Scholomance character spoilers are user
  visible and not solved by paragraph temporal labels.
- Slices 8 and 10 improve consumers once claim labels are reliable.

## Acceptance Checklist

Global:

- [ ] No era keyword/alias registry is introduced.
- [ ] No pilot-specific lore allowlists or denylists are introduced.
- [ ] Entry-state contract sidecar exists.
- [ ] Claim extraction sidecar exists.
- [ ] Claim temporal sidecar exists.
- [ ] Section coverage sidecar exists.
- [ ] Paragraph-level compatibility sidecars still exist during rollout.
- [ ] Full suite passes with `uv run pytest -q`.

WPL:

- [ ] Argent Dawn cauldron campaign is history-eligible.
- [ ] Hearthglen / Argent Crusade post-Lich-King setup bridge appears in final history.
- [ ] Cenarion Circle healing setup can be used without Andorhal outcome leakage.
- [ ] Andorhal outcome is excluded from history/current/faction prose.
- [ ] Fourth War report is post-active and excluded from current playable context.
- [ ] Questline CTA hooks remain spoiler-free.
- [ ] Location selection is not supported by post-active/off-zone claims only.

Scholomance:

- [ ] Shadow Council / Legion material remains post-active.
- [ ] Fourth War report remains post-active.
- [ ] Current Scholomance setup remains available for history bridge/overview.
- [ ] Lilian Voss outcome paragraph is unsafe/outcome.
- [ ] Roster/mechanics snippets do not spoil character summaries.
- [ ] Scourge and Cult of the Damned remain major factions.

## Known Non-Temporal Issues To Keep Separate

- `check_run_semantics.py` currently reports quest graph provenance failures for several WPL
  quests not parsed from storyline list items. This should not be treated as solved by the temporal
  refactor unless claim extraction/routing directly touches quest graph provenance.
- Faction inclusion policy still has editorial questions independent of temporal classification.
- Location significance quality has non-temporal scoring issues independent of temporal routing.

## Progress Log

Add dated entries here as slices move.

- 2026-06-27: Tracker created after review of `test-run-wpl-3` temporal artifacts.
