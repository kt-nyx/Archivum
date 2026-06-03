# Pilot fixtures (Western Plaguelands)

Three related fixture layers—do not conflate them.

## 1. Pipeline input — `source_manifest.json`

Ingest manifest: which wiki sources to fetch. Copied into `artifacts/runs/<run-id>/`.
Validated by `test_source_manifest_validates_against_schema`.

## 2. Questline registry — `western_plaguelands_questline_registry.json`

**Runtime copy:** [`pipeline/data/pilot/western_plaguelands_questline_registry.json`](../../pipeline/data/pilot/western_plaguelands_questline_registry.json) (loaded by `pipeline.discovery.pilot_questline_registry`). The copy in this folder remains for fixture discoverability and backward compatibility.

**Schema:** `pilot-questline-registry-v1`

Clustering oracle: wiki storyline parts, which quests belong to each arc, excluded arcs,
`overflow_chain_refs`, `shared_beat_refs`, and optional entry breadcrumbs. Used to evaluate
discovery/clustering and full quest coverage—not emitted by the pipeline.

## 3. Zone page questline gold — `zone_page_western_plaguelands_gold.json`

**Schema:** `pilot-zone-page-questlines-v1`

Target **`ZonePage.major_questlines`** shape (`QuestlineCardV2`):

```json
{
  "id": "ql-andorhal-alliance",
  "title": "...",
  "faction": "alliance",
  "cta_hook": "...",
  "start_anchor": "...",
  "chain_refs": ["quest-..."],
  "include_decision": "include",
  "reason_codes": ["pilot_gold"],
  "wiki_refs": ["/wiki/..."]
}
```

This matches `data/drafts/zone_page/*.json` questline cards (wiki-first pipeline output).

## 4. Instance page gold — `instance_page_scholomance_gold.json`

Target **`InstancePage`** shape for the Scholomance pilot instance. Hand-authored canonical
page that passes release-gate `validate_payload` (0 hard fails), every `instance_lint`
detector, and the manifest alignment for `instance-scholomance`. It is the regression anchor
for instance generation quality (Slice I6).

Companion **`instance_key_character_decisions_scholomance_gold.json`** mirrors the
`data/decisions/instance_key_character_decisions.json` sidecar: the full ranked key-character
roster with an `emitted` flag per candidate. Used by the role-diversity and pool-aware
minimum checks.

Validated by `tests/test_instance_pilot_gold_standard.py`; exercised offline by the pilot
tooling smoke in `tests/test_instance_pilot_tooling.py`. See
[`docs/planning/instance-pilot-rollout.md`](../../../docs/planning/instance-pilot-rollout.md).

## Comparison

| | Registry | Zone page gold | Pipeline draft |
|--|----------|----------------|----------------|
| Purpose | Quest→arc map | Target cards | Actual run output |
| `cta_hook` | Via linked gold file | Yes | Yes |
| `chain_refs` | Yes (+ overflow/shared) | Yes (card cap only) | Yes |
| Faction buckets | Per-arc `faction` | Flat `major_questlines[]` | Flat `major_questlines[]` |
| Excluded arcs | Yes | No | No |

## Tests

`tests/test_pilot_questline_gold_standard.py` covers:

- Manifest schema + URL alignment with registry authority
- Registry ↔ gold ID, chain_ref, wiki_ref, and start_anchor parity
- `chain_ref` slug derivation from wiki titles (matches discovery `node_id` rules)
- Card lint / CTA quality
- Full registry assignment vs optional `zone_quest_graph_v3.json` artifact

Validation-engine tests use inline `_validation_ready_zone_page_payload()` in
`tests/test_validation_engine.py` (not on-disk JSON fixtures).
