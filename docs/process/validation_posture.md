# Validation Posture

> **Scope note (S10).** This document records the *intended* validation posture so it is not
> accidentally widened later. The deliberate stance is **deterministic-first, LLM-narrow**:
> rules decide structure and selection; the LLM is only ever a *grounded, claim-scoped*
> adjudicator. We do **not** add holistic "is this good writing?" LLM judging. See the
> Guiding Principles in `Reference/refactor-master-plan.md`.

## Where the LLM is (and is not) allowed in validation

The only LLM call in the validation layer is `validate/rules/fact_check.py`
`_adjudicate_with_openai`. It is **bounded by construction**:

- It is invoked **per claim** (a single narrative section's text), never over a whole page or
  the run as a whole.
- It receives the claim text plus a short list of **evidence snippets** drawn from
  provenance-linked ingest snapshot bodies (and, optionally, Google Custom Search hits). It
  is told to return only `supported | contradicted | insufficient_evidence` with a confidence
  and reason — a verdict against supplied evidence, **not** a free-form quality opinion.
- It only runs when **all** of these hold: profile is `warn`/`strict`, the entity is on the
  caller's `fact_check_target_entity_ids` allowlist, `OPENAI_API_KEY` is configured, and the
  claim is still `insufficient_evidence` (or low-confidence) after the deterministic local +
  web passes. Most claims never reach the LLM.

Everything earlier in the pipeline that decides *what* to write, *which* entities to emit, and
*how* cards are ordered is deterministic (discovery typing, coalesce claim-source scoring,
clustering, draft selection). The LLM writes prose grounded to supplied evidence; it does not
choose content.

## The deterministic layers (always on)

`validate/engine.py` `validate_payload` runs these rule modules in order, independent of any
network or API key:

1. **Schema** — Pydantic contract validation (hard-fail on violation).
2. **Structure** — `rules/structure.py` boilerplate/passthrough/shape policies.
3. **Questline promotion** — `rules/questline_promotion.py`.
4. **Budget** — `rules/budget.py` size/length budgets.
5. **Provenance** — `rules/provenance.py` source pointer caps and presence.
6. **Anti-verbatim similarity** — `rules/similarity.py`. Token-set Jaccard
   (`max_similarity_against_sources`) between each narrative section and its
   provenance-linked ingest body; **deterministic**, no LLM. Warn ≥ 0.50, hard-fail ≥ 0.72.
7. **Fact-check** — `rules/fact_check.py`. Deterministic local overlap + optional web search
   first; the bounded LLM adjudication above is the *last* resort and only for targeted
   entities.

Fact-check has three profiles (`validate/profiles.py`): `off` (no claim checking),
`warn` (issues are advisory), `strict` (contradictions and missing LLM/ingest become
hard-fails). The default is conservative.

## Instance quality gate — false-PASS risk (re-checked at S10)

`scripts/instance_quality_report.py` is the deterministic instance-page scorecard. A prior
review (memory: *gold fixtures are canonical*) flagged that the gate could **false-PASS**
because it did not assert page-vs-sidecar agreement or emit-order vs `merge_rank`.

Re-checked once S3/S5 landed — the gate now closes that risk via
`_sidecar_coherence_findings`, which hard-fails on:

- `semantics.sidecar_emitted_without_rank` — an emitted candidate with no `merge_rank`.
- `semantics.sidecar_rank_without_emit` — a ranked candidate not marked emitted.
- `semantics.page_sidecar_cast_mismatch` — the page `key_characters` set differs from the
  sidecar's emitted set.
- `semantics.page_sidecar_order_mismatch` — the page cast emit-order disagrees with the
  sidecar `merge_rank` order (added at S10; the set-only check used to pass this through).

These are deterministic structural-coherence assertions, **not** quality judgements, and are
covered by regression tests in `tests/test_instance_pilot_tooling.py`. The rubric remains a
pure function of the committed drafts + decision sidecar and never touches the network.

## What we will not do

- No holistic "rate the overall quality / tone / engagingness" LLM pass.
- No LLM that selects which entities, bosses, or questlines to emit (deterministic).
- No widening of the fact-check LLM beyond per-claim, evidence-grounded adjudication.
