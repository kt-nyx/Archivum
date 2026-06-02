# RFC: Instance `key_characters` Migration (Slice I0 — Scope Lock)

Status: Decisions locked (2026-06-01). No code changes in this slice.
Program: Instance Pipeline Master Plan — Character + Lore Rewrite.
Scope: Instance entities only. Non-instance issues remain deferred (see
[deferred-non-instance-issues-2026-06-01.md](../../Reference/deferred-non-instance-issues-2026-06-01.md)).

This RFC freezes the contract and scope for the `key_enemies` -> `key_characters`
migration so downstream slices (I1-I6) build on stable assumptions. It is the
single source of truth for the I0 acceptance gate: decision lock, migration path,
and downstream impact sign-off.

---

## 1. Locked decisions (D1-D5)

### D1 — Compatibility: NONE. Clean rewrite.

Fully replace `key_enemies` with `key_characters` across the codebase. No
read-shim, no dual-field write, no derived back-compat view.

- Rationale: the app is pre-production and explicitly rewritable. The only bar is
  that a brand-new end-to-end run is functional and green. Legacy run artifacts
  and any external consumer expectations are not preserved.
- Consequence: pre-migration draft JSON under old run roots will no longer parse
  against the new contract. This is accepted; the migration is validated by a
  fresh run, not by re-reading old artifacts.

### D2 — `CharacterCard` shape: structured role + inclusion justification.

(Revised after the initial draft: `role` is a structured, filterable enum, not
prose.) The card adds a filterable `role` label, an optional wiki link, and an
internal inclusion-justification list.

- Final card fields: `id`, `name`, `summary`, `role` (enum
  `enemy | ally | neutral | uncertain`, default `uncertain`), `wiki_ref`
  (optional), `decision_reason_codes` (list, internal), and the existing optional
  `thumbnail_asset_id`.
- `summary` is the user-facing descriptive text: who the character is and why
  they matter in the instance (opposing, aiding, or neutral). It is what the
  addon shows.
- `role` is a structured label for filtering/UI; it is NOT derived from prose.
  It defaults to `uncertain`; accurate classification is the I3 slice's job.
- `decision_reason_codes: list[str]` records why a character was included
  (mirrors `LocationCard.decision_reason_codes`). It replaces the earlier
  `importance` / `narrative_reason` ideas and is internal, not user-facing.
- Rationale: a structured `role` makes hostile/allied/neutral actors filterable
  (e.g. Tirion Fordring as an ally in ICC, Lilian Voss as a part-time enemy in
  Scholomance) instead of burying that signal in prose.

### D3 — Validator naming unification: in I1.

Align validator JSON paths and messages (`$.key_enemies` -> `$.key_characters`)
with the already-`key_characters` error codes, as part of the I1 rename.

- Rationale: the error codes already read `instance_key_characters_*`; finishing
  the path/message rename in the same slice avoids a lingering internal mismatch.

### D4 — Schema regeneration: via the existing generator.

Regenerate `schemas/v1/instance_page.schema.json` from the Pydantic models using
the existing exporter rather than hand-editing JSON. The legacy `Instance` schema
stays untouched.

- Generator: [pipeline/contracts/export_schema.py](../../pipeline/contracts/export_schema.py),
  run as `python -m pipeline.contracts.export_schema`. It calls
  `model.model_json_schema()` for every entity in `ENTITY_MODEL_MAP` and
  `WIKI_FIRST_ENTITY_MODEL_MAP` and writes deterministic (sorted-key) JSON for the
  whole `schemas/v1/` set plus `manifest.json`.
- Consequence: regenerating will rewrite all `schemas/v1/*.schema.json` files
  deterministically. The only intended content delta is `instance_page` losing
  `key_enemies`/gaining `key_characters`, plus `CharacterCard` gaining `role`,
  `wiki_ref`, and `decision_reason_codes` wherever that `$def` appears.

### D5 — Provenance key: confirmed no-op.

`InstanceProvenance.key_characters` already has the correct name. No rename
needed; documented here for completeness.

---

## 2. Migration contract (implemented in I1)

### 2.1 `CharacterCard` (target)

```python
class CharacterCard(BaseModel):
    id: str = Field(pattern=ID_PATTERN)
    name: str = Field(min_length=1)
    summary: str = Field(min_length=1)   # user-facing: who they are + why they matter
    role: Literal["enemy", "ally", "neutral", "uncertain"] = "uncertain"  # filterable label
    wiki_ref: str | None = None          # canonical wiki link when available
    decision_reason_codes: list[str] = Field(default_factory=list)  # internal inclusion justification
    thumbnail_asset_id: str | None = None
```

Note: `CharacterCard` is a shared model. Adding an optional `wiki_ref` is additive
and non-breaking for other consumers (it defaults to `None`). The field is
optional because some extracted characters will not have a resolvable wiki page.

### 2.2 `InstancePage` (target)

- Rename `key_enemies: list[CharacterCard]` -> `key_characters: list[CharacterCard]`.
- `provenance.key_characters` is unchanged (D5).
- `model_config = ConfigDict(extra="forbid")` stays; under a clean rewrite there
  is no transitional acceptance of the old `key_enemies` key.

### 2.3 Count + budget constants (already aligned)

`INSTANCE_MIN_KEY_CHARACTERS` / `INSTANCE_MAX_KEY_CHARACTERS` (2-10) and
`INSTANCE_BUDGET_RULES["key_characters_card_summary"]` are already named for
`key_characters`; only the field/path references need updating.

### 2.4 Canvas alignment

The master-plan canvas has been rewritten to the final model:

- Slice I1 "Model design" reflects the final `CharacterCard` shape (`id`, `name`,
  `summary`, `role` enum, `wiki_ref` optional, `decision_reason_codes`,
  `thumbnail_asset_id`).
- Slice I3 is "Role classification + significance": the `role` field exists and
  defaults to `uncertain`; I3 supplies the intelligence to assign the correct
  value, dedupe, and order — it no longer adds the field.

---

## 3. Grounding facts (verified in code, 2026-06-01)

| Fact | Location |
| --- | --- |
| `InstancePage.key_enemies: list[CharacterCard]`; model uses `extra="forbid"` | [pipeline/contracts/models.py](../../pipeline/contracts/models.py) ~L376-396 (field L388) |
| `CharacterCard` = `id, name, summary, role, wiki_ref, decision_reason_codes, thumbnail_asset_id` | models.py L220-227 |
| Provenance already uses `key_characters` | `InstanceProvenance` models.py L368-373 |
| Draft writes `provenance.key_characters` | [wiki_first.py](../../pipeline/generate/draft/wiki_first.py) L1565-1576 |
| Legacy `Instance` entity already uses `key_characters: list[CharacterCard]` | models.py ~L399-413 (schema untouched per D4) |
| Validator codes say `instance_key_characters_*`, paths say `$.key_enemies` | [budget.py](../../pipeline/validate/rules/budget.py) L350-398; [provenance.py](../../pipeline/validate/rules/provenance.py) L571-572 |
| Schema artifact defines `key_enemies` | [schemas/v1/instance_page.schema.json](../../schemas/v1/instance_page.schema.json) L356-361 |
| Schema generator | [pipeline/contracts/export_schema.py](../../pipeline/contracts/export_schema.py) |
| Linker maps section `key_enemies` -> provenance `key_characters` | [linker.py](../../pipeline/linker/linker.py) L284, L370, L401 |

---

## 4. Acceptance matrix (expected behavior per stage after I1)

| Stage | Entry point | Expected post-migration behavior |
| --- | --- | --- |
| Ingest | [pipeline/ingest/fetch_wiki.py](../../pipeline/ingest/fetch_wiki.py) | Unchanged. Section roles and structured links unaffected by the field rename. |
| Discovery / enrich | [pipeline/discovery/enrich.py](../../pipeline/discovery/enrich.py) | Unchanged. `boss_pool` / evidence packs are not renamed. |
| Draft writer | [wiki_first.py](../../pipeline/generate/draft/wiki_first.py), [draft_writer.py](../../pipeline/generate/draft_writer.py) | Emits `key_characters` (not `key_enemies`); each card may carry `wiki_ref`; `summary` describes character + dungeon role. `provenance.key_characters` unchanged. |
| Validate | [budget.py](../../pipeline/validate/rules/budget.py), [provenance.py](../../pipeline/validate/rules/provenance.py) | Count/release-gate/summary-budget checks read `key_characters`; JSON paths/messages say `$.key_characters` (D3). No false failures on a fresh run. |
| Semantics (`--strict`) | [scripts/check_run_semantics.py](../../scripts/check_run_semantics.py) ~L1009-1097 | Reads `key_characters`; boss/min/max/quality/provenance checks pass on a fresh run. |
| Linker | [linker.py](../../pipeline/linker/linker.py) L284/L370/L401 | Scans `key_characters` cards; section->provenance map becomes `key_characters` -> `key_characters`. |
| Glossary terms | [run_terms.py](../../pipeline/glossary/run_terms.py) L219 | Reads `key_characters` cards into run terms. |
| Addon bundle | [pipeline/addon/build_bundle.py](../../pipeline/addon/build_bundle.py) | Consumes drafts generically; does not reference the field by name today, so no change expected unless card-aware logic is added later. |

Program-level gate: a fresh end-to-end run (target `test-run-wpl-1`, promotion
`run-western-plaguelands`) produces instance drafts with non-empty
`key_characters` when candidates exist, and passes `validate` + `check_run_semantics --strict`.

---

## 5. Risk table

| Risk | Likelihood | Impact | Mitigation |
| --- | --- | --- | --- |
| Residual `key_enemies` references left behind after rename | Medium | Runtime/`extra="forbid"` failures or silent dead code | Exhaustive grep checklist (Section 6 list) + a full run as the gate |
| Schema/model drift if schema hand-edited instead of regenerated | Low | Schema disagrees with model | Use the generator (D4); add/keep a schema-vs-model regen check |
| Pre-migration run artifacts no longer parse | High | Old drafts unreadable | Accepted (D1); fresh run is the bar, not backward reads |
| `wiki_ref` added to shared `CharacterCard` affects other entities | Low | Unexpected field on zone/other cards | Field is optional/defaulted `None`; additive and non-breaking |
| Test/fixture churn across many files | Medium | Red test suite mid-migration | Update factories + tests in the same I1 slice; list enumerated below |
| Semantics script vs validate engine drift on naming | Low | Inconsistent failures | D3 aligns both in I1; helper names noted below |

---

## 6. Downstream impact (affected modules — sign-off list)

Production / pipeline:

- [pipeline/contracts/models.py](../../pipeline/contracts/models.py) — `CharacterCard.role` + `CharacterCard.wiki_ref` + `CharacterCard.decision_reason_codes`; `InstancePage.key_enemies` -> `key_characters`.
- [pipeline/contracts/export_schema.py](../../pipeline/contracts/export_schema.py) — run to regenerate schemas (no code change expected).
- [schemas/v1/instance_page.schema.json](../../schemas/v1/instance_page.schema.json) — regenerated; `CharacterCard` `$def` gains `role`, `wiki_ref`, `decision_reason_codes`.
- [pipeline/generate/draft/wiki_first.py](../../pipeline/generate/draft/wiki_first.py) — `_finalize_key_enemies`, draft dict keys (L1532, L1565, L1575).
- [pipeline/generate/draft/instance_lint.py](../../pipeline/generate/draft/instance_lint.py) — `*_key_enemy_summary` helpers (`trim`/`is_generic`/`lint`/`fallback`).
- [pipeline/generate/draft/wiki_first_workers.py](../../pipeline/generate/draft/wiki_first_workers.py) — `synthesize_key_enemy_summary`.
- [pipeline/generate/draft_writer.py](../../pipeline/generate/draft_writer.py) — instance draft assembly references.
- [pipeline/validate/rules/budget.py](../../pipeline/validate/rules/budget.py) — paths/messages (L350-398).
- [pipeline/validate/rules/provenance.py](../../pipeline/validate/rules/provenance.py) — card pointer map (L571-572).
- [pipeline/linker/linker.py](../../pipeline/linker/linker.py) — L284, L370, L401.
- [pipeline/glossary/run_terms.py](../../pipeline/glossary/run_terms.py) — L219.

Scripts:

- [scripts/check_run_semantics.py](../../scripts/check_run_semantics.py) — L916-919 imports + L1030-1083 instance checks.

Tests / fixtures:

- [tests/factories/wiki_first_pages.py](../../tests/factories/wiki_first_pages.py) — L104.
- [tests/test_validation_engine.py](../../tests/test_validation_engine.py) — L383, L1260-1268, L1317-1319.
- [tests/test_instance_page_draft.py](../../tests/test_instance_page_draft.py) — L8, L100-114, L192-238.
- [tests/test_draft_baseline.py](../../tests/test_draft_baseline.py) — L428, L431.
- [tests/test_linker_stage.py](../../tests/test_linker_stage.py) — L608.
- [tests/test_glossary_run_terms.py](../../tests/test_glossary_run_terms.py) — L41.
- [tests/test_check_run_semantics.py](../../tests/test_check_run_semantics.py) — L516, L681, L693-792.
- [tests/test_wiki_first_workers.py](../../tests/test_wiki_first_workers.py) — L13, L150-152.

Docs / canvas (revise during I1/I3 re-plan, not in I0):

- [docs/planning/pipeline-quality-phase2.canvas.tsx](pipeline-quality-phase2.canvas.tsx) — I1 model table + I3 role-model slice (per Section 2.4).
- [docs/planning/pilot-promotion.md](pilot-promotion.md) — L78, L96 references to `key_enemies`.

---

## 7. I0 acceptance gate

- Decision lock: D1-D5 resolved and recorded (Section 1). PASS.
- Migration path: one explicit mechanism documented — clean rename, no compat
  (D1, Section 2). PASS.
- Downstream impact: affected-module list enumerated for sign-off (Section 6). PASS.

## 8. Out of scope for I0

No schema/model/writer/validator edits, no fixture changes, no runs, no canvas
edits. Implementation begins in I1.
