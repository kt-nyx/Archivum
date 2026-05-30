import {
  Callout,
  CollapsibleSection,
  Divider,
  H1,
  H2,
  H3,
  Pill,
  Row,
  Stack,
  Stat,
  Table,
  Text,
  TodoListCard,
} from "cursor/canvas";

const SLICES = [
  {
    id: "slice-1",
    content: "Slice 1 — Evidence scoping + storyline HTML parser + quest graph v3",
    status: "completed" as const,
  },
  {
    id: "slice-2",
    content: "Slice 2 — Quest traversal, lore extraction, questline card synthesis",
    status: "completed" as const,
  },
  {
    id: "slice-3",
    content: "Slice 3 — Zone prose workers (at-a-glance, currently, history)",
    status: "completed" as const,
  },
  {
    id: "slice-4",
    content: "Slice 4 — Faction scoring, ranking, zone-role summaries",
    status: "completed" as const,
  },
  {
    id: "slice-5",
    content: "Slice 5 — Location guards, relevance gates, card quality",
    status: "completed" as const,
  },
  {
    id: "slice-6",
    content: "Slice 6 — Instance parity (LLM workers, bosses, traverse)",
    status: "pending" as const,
  },
  {
    id: "slice-7",
    content: "Slice 7 — Dynamic glossary generation + linker + wiki URLs on refs",
    status: "pending" as const,
  },
  {
    id: "slice-8",
    content: "Slice 8 — Provenance anchors, validation hardening, stub removal",
    status: "pending" as const,
  },
];

export default function WikiFirstPipelineMasterPlan() {
  return (
    <Stack gap={16}>
      <H1>Wiki-First Pipeline — Master Implementation Plan</H1>
      <Text tone="secondary">
        Reference blueprint for slice-by-slice implementation. A proof-of-concept run (currently WPL +
        Scholomance) validates acceptance, but production code, classifiers, and tests must stay zone-agnostic.
        Archive backup: docs/planning/archive/wiki-first-pipeline-master-plan.canvas.tsx.bak
      </Text>

      <Row gap={12}>
        <Stat label="Execution model" value="One slice at a time" tone="accent" />
        <Stat label="PoC run (manual QA)" value="run-western-plaguelands" tone="success" />
        <Stat label="Active slices" value="8 gated" tone="success" />
        <Stat label="Slice 1" value="Completed" tone="success" />
        <Stat label="Slice 2" value="Completed" tone="success" />
        <Stat label="Slice 3" value="Completed" tone="success" />
        <Stat label="Slice 4" value="Completed" tone="success" />
        <Stat label="Slice 5" value="Completed" tone="success" />
      </Row>

      <Callout tone="info" title="Zone-agnostic engineering policy">
        <Stack gap={8}>
          <Text>
            Never encode pilot zone names, adjacent-zone handoffs, or location proper nouns in Python control flow.
            Use structural wiki patterns, run-scoped entity ids from manifests, and curated taxonomy files instead.
          </Text>
          <Table
            headers={["Need", "Allowed", "Not allowed"]}
            rows={[
              [
                "Reject geography hub links",
                "entity_denylist.json (world taxonomy) + self-zone check via zone_name arg",
                "_ADJACENT_ZONE_TITLES-style frozensets in code; pilot zone regexes",
              ],
              [
                "Skip cross-zone handoff quests",
                "Parse quest rows only inside &lt;li&gt; list items on storyline HTML",
                "Hardcoded quest titles or neighbor zone names in parser",
              ],
              [
                "Semantic acceptance",
                "scripts/check_run_semantics.py with --zone-id or auto-detect from run",
                "Hardcoded zone draft paths or zone names in scripts",
              ],
              [
                "Regression against a real run",
                "Optional artifact tests via LORE_PILOT_RUN_ROOT env var",
                "WPL-specific logic in pipeline modules",
              ],
              [
                "Pilot manifests / HTML fixtures",
                "tests/fixtures/** and artifacts/runs/** as data only",
                "Importing fixture zone names into pipeline/discovery or pipeline/generate",
              ],
            ]}
          />
        </Stack>
      </Callout>

      <TodoListCard todos={SLICES} defaultExpanded />

      <Divider />
      <H2>Slice 1 — completed summary</H2>
      <Table
        headers={["Deliverable", "Status", "Notes"]}
        rows={[
          ["Scoped evidence pools (seed vs auxiliary)", "Done", "history_digest, at_a_glance_input, currently_input"],
          ["Storyline HTML parser", "Done", "List-item quest rows + faction icons; prose handoffs ignored structurally"],
          ["zone_quest_graph_v3", "Done", "Enrich owns graph + questline decisions"],
          ["entity_denylist taxonomy", "Done", "Geography hubs in JSON; entity_denylist.README.md documents policy"],
          ["check_run_semantics.py", "Done", "Zone-agnostic; check_pilot_semantics.py is deprecated wrapper"],
          ["Ingest storyline tagging", "Done", "Manifest _storyline URLs get auxiliary_role + parse_html at ingest"],
        ]}
      />

      <CollapsibleSection title="Slice 1 — known deviances (intentional deferrals)" count={1}>
        <Table
          headers={["Topic", "Current behaviour", "Target slice"]}
          rows={[
            [
              "Full validate_passed on PoC run",
              "Instance hard-fails remain",
              "6 + 8",
            ],
          ]}
        />
      </CollapsibleSection>

      <Divider />
      <H2>Slice 2 — completed summary</H2>
      <Table
        headers={["Deliverable", "Status", "Notes"]}
        rows={[
          ["Split traverse (seed vs quests)", "Done", "traverse_seed → coalesce → graph enrich → traverse_quests → evidence merge"],
          ["V3-driven quest fetch", "Done", "Cap 25/zone; traversal_origin=v3_graph; denylist/registry guards"],
          ["Quest lore extractor", "Done", "pipeline/discovery/quest_lore.py — narrative roles only (no non-narrative fallback)"],
          ["Hub page resolver", "Done", "Structure-based, 1 hop max; uses parse_html, wiki_links, or structured_links"],
          ["Cluster evidence fields", "Done", "quest_lore + quest_cluster_lore in evidence_packs.jsonl"],
          ["Cluster questline cards", "Done", "One card per cluster_id; faction provenance buckets; neutral → shared"],
          ["Semantic checks", "Done", "wiki_refs, cluster evidence, cap-8, hub_resolved_from, traversal denylist"],
        ]}
      />

      <CollapsibleSection title="Slice 2 — intentional deviations (documented)" count={10}>
        <Table
          headers={["Topic", "Plan / canvas wording", "Actual behaviour", "Rationale"]}
          rows={[
            [
              "Hub child cap",
              "Follow top 1–2 sub-quest links",
              "Hard cap of 2 children per hub (`quest_hub._MAX_HUB_CHILDREN`)",
              "Limits burst fetches; still 1 hop depth only",
            ],
            [
              "Hub link sources",
              "Structure-based resolver",
              "Prefers parse_html list-item questlinks; falls back to structured_links, then wiki_links, then href in section_blocks",
              "Quest snapshots omit parse_html for size; wiki_links from fetch_wiki carry hub candidates",
            ],
            [
              "CLI stepwise runs",
              "Verification commands imply staged pipeline",
              "`traverse` = seed only; no `traverse-quests` subcommand; `discovery-enrich` defaults to `phase=full`",
              "Backward-compatible CLI; full Slice 2 order only via `lore-pipeline run` or stage APIs",
            ],
            [
              "evidence_merge naming",
              "Second enrich pass merges quest evidence",
              "Rebuilds entire `evidence_packs.jsonl` from all snapshots + v3 on disk",
              "Deterministic idempotency; cheaper than partial patch logic",
            ],
            [
              "graph_only evidence",
              "First enrich after seed traverse",
              "Writes seed/storyline pools immediately; quest/cluster lore absent until `evidence_merge`",
              "Consumers must not assume complete quest evidence mid-pipeline",
            ],
            [
              "Coalesce placement",
              "Coalesce before graph enrich",
              "Quest pages fetched after coalesce; quest bodies live in evidence/draft, not `entities.jsonl`",
              "Entity resolution uses manifest rows only; quest lore is evidence-path",
            ],
            [
              "Duplicate guard scope",
              "Key on subject_id + field_name + source_id + cluster_id",
              "Dedup only when rolling up `quest_cluster_lore`; key adds quest_node_id + snippet prefix; `quest_lore` rows not deduped",
              "Rebuild is deterministic; per-snippet quest_lore packs are intentional for provenance granularity",
            ],
            [
              "Trace stage names",
              "Two enrich passes",
              "Both passes log as `discovery_enrich` in flow retries/manifests",
              "Phase is in stage function args, not trace event name (Slice 8 hardening candidate)",
            ],
            [
              "Cluster card cap",
              "Dynamic cap vs v3 cluster count",
              "`min(len(clusters), 8)` in wiki_first; clusters without quest lore evidence are skipped; subset check in check_run_semantics",
              "UI budget; draft omits evidence-empty clusters",
            ],
            [
              "Neutral faction binding",
              "Faction buckets alliance / horde / shared",
              "v3 `neutral` majority maps to `shared` card faction before emit",
              "Keeps QuestlineCardV2 within Faction enum without Slice 8 contract change",
            ],
          ]}
        />
      </CollapsibleSection>

      <CollapsibleSection title="Slice 2 — post-review fixes (completed)" count={9}>
        <Table
          headers={["Fix", "Status", "Notes"]}
          rows={[
            ["Hub resolver uses wiki_links / structured_links", "Done", "traverse_quests passes snapshot links into quest_hub"],
            ["neutral → shared faction mapping", "Done", "wiki_first._majority_faction"],
            ["ZonePage provenance by faction bucket", "Done", "validate/rules/provenance.py _validate_zone_page"],
            ["Quest lore: narrative roles only", "Done", "Removed non-narrative fallback in extract_quest_lore"],
            ["Semantic checks tightened + unit tests", "Done", "Cap-8, hub_resolved_from, quest-only cluster ids; tests/test_check_run_semantics.py"],
            ["Hub traverse integration test", "Done", "tests/test_traverse_wiki.py hub_resolved_from + wiki_links path"],
            ["Cluster alignment without snapshots", "Done", "check_run_semantics validates v3/card subset when only v3 + draft exist"],
            ["Orchestrator enrich phase order test", "Done", "tests/test_orchestrator_flow.py graph_only → quests → evidence_merge"],
            ["Skip evidence-empty cluster cards", "Done", "wiki_first uses cluster-scoped lore only; omits clusters with no lore pool"],
          ]}
        />
      </CollapsibleSection>

      <Divider />
      <H2>Slice 3 — completed summary</H2>
      <Table
        headers={["Deliverable", "Status", "Notes"]}
        rows={[
          ["prose_election.py", "Done", "At-a-glance ordering; currently 4-tier ladder; history pool + dynamic cap"],
          ["prose_lint.py", "Done", "Shared heuristics for draft fallback + check_run_semantics (45-word at-a-glance)"],
          ["wiki_first_workers upgrades", "Done", "Dedicated prompts; 45/120/dynamic history; precompress at-a-glance"],
          ["build_zone_page wiring", "Done", "Election → workers → lint/fallback; elected pools for provenance"],
          ["enrich build_meta.section_role", "Done", "Seed prose packs tagged for election heuristics"],
          ["Semantic prose checks", "Done", "at_a_glance/currently/history quality + non-seed provenance WARN in check_run_semantics.py"],
          ["Prose finalize helpers", "Done", "_finalize_* in wiki_first: synthesize → lint → fallback → re-lint → rescue pool"],
        ]}
      />

      <CollapsibleSection title="Slice 3 — intentional deviations (documented)" count={4}>
        <Table
          headers={["Topic", "Plan / canvas wording", "Actual behaviour", "Rationale"]}
          rows={[
            [
              "at_a_glance validate budget",
              "Some plans mention tightening budget.py to 45",
              "validate budget.py still warns up to 70; 45 enforced in prose_lint + semantics only",
              "User preference: semantics-only enforcement for word cap",
            ],
            [
              "History minimum sections",
              "Count within [3, 8] when seed blocks ≥ 3",
              "Draft uses dynamic cap; semantics fails if eligible seed blocks ≥ 3 but draft has fewer than 3 sections",
              "Avoid forcing padding when evidence is thin",
            ],
            [
              "Currently tier 1",
              "Expansion-tagged *_edit sections",
              "Requires era token in section_role (cataclysm, dragonflight, etc.); generic *_edit roles fall to tier 2",
              "Prevents quests_edit from outranking expansion-era prose",
            ],
            [
              "History pool eligibility",
              "Seed history_digest blocks only",
              "select_history_pool drops snippets under 25 words and excluded geography roles",
              "Filters stub/location-list sections that would produce low-quality history bodies",
            ],
          ]}
        />
      </CollapsibleSection>

      <CollapsibleSection title="Slice 3 — verification (completed)" count={5}>
        <Table
          headers={["Check", "Criterion"]}
          rows={[
            ["at_a_glance words", "≤ 45 via prose_lint; no location-list dump heuristic"],
            ["currently", "Present tense; no geography hub names; no reputation/achievement/player meta"],
            ["history", "Past-tense framing; section count within dynamic cap; seed history_digest only"],
            ["Unit tests", "tests/test_prose_election.py, test_zone_prose_draft.py, test_wiki_first_workers.py"],
            [
              "Run semantics",
              "uv run python scripts/check_run_semantics.py artifacts/runs/<run-id> [--zone-id zone-...]",
            ],
          ]}
        />
      </CollapsibleSection>

      <Divider />
      <H2>Slice 5 — completed summary</H2>
      <Table
        headers={["Deliverable", "Status", "Notes"]}
        rows={[
          ["enrich build_meta.location_id", "Done", "location_profile packs tagged with location_id + location_name"],
          ["location_pool scoping", "Done", "Separate location_pool and location_seed_pool (no history_digest fallback)"],
          ["entity_typing guards", "Done", "Dating-convention titles; geography roles exempt from likely_npc heuristic"],
          ["traverse include-only", "Done", "location_profile fetches include decisions only; defer skipped"],
          ["location_scoring.py", "Done", "Candidate collection, zone relevance, ranked election (3–8 include-only)"],
          ["location_lint.py", "Done", "Shared heuristics for draft finalize + check_run_semantics"],
          ["synthesize_location_summary", "Done", "In-zone landmark worker; deterministic trim fallback"],
          ["build_location_cards", "Done", "Replaces defer-padded _build_location_cards in build_zone_page"],
          ["draft_writer wiring", "Done", "Loads location_profile_targets.json per zone"],
          ["Semantic location checks", "Done", "Card count, lint, denylist, provenance, defer leakage in check_run_semantics.py"],
        ]}
      />

      <CollapsibleSection title="Slice 5 — intentional deviations (documented)" count={9}>
        <Table
          headers={["Topic", "Plan / canvas wording", "Actual behaviour", "Rationale"]}
          rows={[
            [
              "location_cards validate budget",
              "major_landmarks_card_summary in validate budget",
              "Card quality enforced in check_run_semantics + location_lint (20–50 words)",
              "Schema still uses location_cards on draft; major_landmarks naming unification deferred to Slice 8",
            ],
            [
              "Defer in draft",
              "Defer remains in decision artifacts only",
              "Draft election uses include-only; no defer padding",
              "Matches plan: defer for audit, not card emission",
            ],
            [
              "Card count floor",
              "3–8 when enough include-scored candidates",
              "Semantics fails below MIN when ≥3 candidates; draft may emit fewer when evidence thin",
              "Distinguishes thin vs broken runs per plan risk note",
            ],
            [
              "likely_npc guard",
              "Denylist at discovery, traverse, and draft",
              "Geography source roles (maps_subregions, etc.) exempt from two-word Title Case NPC heuristic",
              "Prevents false rejects for legitimate subregion place names",
            ],
            [
              "Card id pattern",
              "loc-* or location-*",
              "Semantics accepts location-* and loc-* prefixes",
              "Legacy test fixtures use loc-* ids",
            ],
            [
              "Lede-only + seed",
              "Exclude lede-only profiles without seed",
              "Lede-only profiles remain electable when seed geography mentions exist",
              "Matches plan scoring table; enables profile→seed finalize rescue",
            ],
            [
              "Semantics eligible set",
              "≥3 include-scored candidates",
              "Eligible location ids filtered to include decisions when decision artifact exists",
              "Defer/exclude targets no longer inflate minimum card-count checks",
            ],
            [
              "Finalize pool order",
              "Profile then seed rescue pools",
              "Per-pool synthesize + fallback_location_summary(pool) before next pool (mirrors faction)",
              "Ensures seed geography rescues failed profile ledes",
            ],
            [
              "PoC artifact regression",
              "Optional LORE_PILOT_RUN_ROOT location spot-check",
              "Not added — unit/integration tests use neutral fixtures only",
              "Optional per plan; manual QA + semantics on pilot runs instead",
            ],
          ]}
        />
      </CollapsibleSection>

      <CollapsibleSection title="Slice 5 — verification (completed)" count={5}>
        <Table
          headers={["Check", "Criterion"]}
          rows={[
            ["location_cards count", "3–8 when ≥3 include-scored candidates in evidence/targets"],
            ["Card summaries", "In-zone landmark prose; no generic filler; 20–50 words; zone/landmark anchor"],
            ["Include-only election", "No defer-only cards; traverse fetches include targets only"],
            ["Unit tests", "tests/test_location_scoring.py, test_zone_location_draft.py, test_location_lint.py"],
            [
              "Run semantics",
              "uv run python scripts/check_run_semantics.py artifacts/runs/<run-id> [--zone-id zone-...]",
            ],
          ]}
        />
      </CollapsibleSection>

      <Divider />
      <H2>Slice 4 — completed summary</H2>
      <Table
        headers={["Deliverable", "Status", "Notes"]}
        rows={[
          ["enrich build_meta.faction_id", "Done", "faction_profile packs tagged with faction_id + faction_name"],
          ["faction_scoring.py", "Done", "Candidate collection, significance scoring, ranked election (2–6)"],
          ["faction_lint.py", "Done", "Shared heuristics for draft finalize + check_run_semantics"],
          ["synthesize_faction_summary", "Done", "Zone-role worker; deterministic trim fallback; no generic filler"],
          ["build_major_factions", "Done", "Replaces _FACTION_HINTS / _extract_factions in build_zone_page"],
          ["draft_writer wiring", "Done", "Loads faction_profile_targets.json per zone"],
          ["Semantic faction checks", "Done", "Card count, lint, provenance, Alliance/Horde WARN in check_run_semantics.py"],
          ["Instance major_factions", "Deferred", "build_instance_page returns [] until Slice 6"],
        ]}
      />

      <CollapsibleSection title="Slice 4 — intentional deviations (documented)" count={8}>
        <Table
          headers={["Topic", "Plan / canvas wording", "Actual behaviour", "Rationale"]}
          rows={[
            [
              "major_factions validate budget",
              "Optional warn-level 2–6 in budget.py",
              "Card count enforced in check_run_semantics only (when ≥2 candidates)",
              "Matches Slice 3 semantics-only enforcement pattern",
            ],
            [
              "Instance faction parity",
              "Shared build_major_factions on instance pages",
              "build_instance_page emits major_factions: [] until Slice 6",
              "Avoid stale _FACTION_HINTS substring matching on instance drafts",
            ],
            [
              "Alliance/Horde semantics",
              "WARN if present without quest-binding or high-weight seed",
              "WARN via shared alliance_horde_conflict_met helper (bindings or high-weight seed roles)",
              "Warn-only (not fail) so thin runs pass while flagging suspicious cards",
            ],
            [
              "Finalize backfill",
              "Election picks N candidates; finalize may skip failing cards",
              "Backfill queue uses score ≥ MIN_SCORE when eligible candidates exist; thin runs use score > 0",
              "Recovers card count when top picks fail lint without promoting sub-threshold factions",
            ],
            [
              "Seed candidate discovery",
              "Seed mentions may infer candidates beyond targets",
              "Candidates limited to discovery targets, faction_pool evidence, and v3 Alliance/Horde bindings",
              "Avoids global registry substring false positives in seed prose",
            ],
            [
              "Zone-role soft lint",
              "Optional has_zone_role_framing heuristic in faction_lint",
              "Enforced in lint_faction_summary (present-tense role verbs or historical framing)",
              "Implemented in Slice 4 follow-up — rejects bare factual stubs",
            ],
            [
              "Duplicate faction summaries",
              "Optionally duplicate structure.py check in semantics",
              "Enforced only in validate/rules/structure.py during validate stage",
              "Early fail not needed; validate stage already covers duplicates",
            ],
            [
              "PoC artifact regression",
              "Optional LORE_PILOT_RUN_ROOT WPL faction rank spot-check",
              "Not added — unit/integration tests use neutral fixtures only",
              "Optional per plan; manual QA + semantics on pilot runs instead",
            ],
          ]}
        />
      </CollapsibleSection>

      <CollapsibleSection title="Slice 4 — verification (completed)" count={5}>
        <Table
          headers={["Check", "Criterion"]}
          rows={[
            ["major_factions count", "2–6 when ≥2 faction candidates in evidence/targets"],
            ["Card summaries", "Zone-role prose; no generic filler; ≥12 words; ends with sentence punctuation"],
            ["Alliance/Horde gate", "Scoring + semantics use alliance_horde_conflict_met (bindings or high-weight seed)"],
            ["Unit tests", "tests/test_faction_scoring.py, test_zone_faction_draft.py, test_wiki_first_workers.py"],
            [
              "Run semantics",
              "uv run python scripts/check_run_semantics.py artifacts/runs/<run-id> [--zone-id zone-...]",
            ],
          ]}
        />
      </CollapsibleSection>

      <Divider />
      <H2>Deferred hardcoded cleanup (outside Slice 1 scope)</H2>
      <Text tone="secondary">
        The following still contain pilot-specific names as test data, static glossary seeds, or validation fixtures.
        They are acceptable for PoC runs but must be generalized before multi-zone release.
      </Text>
      <Table
        headers={["Area", "Examples today", "Planned action", "Slice"]}
        rows={[
          [
            "tests/fixtures/happy|edge|failure/*.json",
            "zone-western-plaguelands ids, Andorhal prose",
            "Introduce neutral happy-path fixtures; keep WPL copies under tests/fixtures/pilot/",
            "8",
          ],
          [
            "tests/test_draft_baseline.py, test_validation_engine.py, test_linker_stage.py",
            "Inline WPL/Scholomance draft payloads",
            "Extract shared factory helpers; parameterize entity ids",
            "3–8",
          ],
          [
            "dictionary/glossary_aliases.v1.json",
            "Western Plaguelands, Andorhal, Scholomance terms",
            "Tests-only fallback after run-scoped glossary (Slice 7)",
            "7",
          ],
          [
            "tests/fixtures/pilot/source_manifest.json",
            "WPL + Scholomance manifest rows",
            "Keep as pilot data; CLI docs reference shape not content",
            "—",
          ],
          [
            "tests/fixtures/storyline/western_plaguelands_storyline.html",
            "Real wiki excerpt for regression",
            "Keep; pair with cross_zone_handoff.html for generic cases",
            "—",
          ],
          [
            "Canvas acceptance rows mentioning WPL",
            "PoC spot-check criteria in slices 2–6",
            "Reword to parameterized checks + optional LORE_PILOT_RUN_ROOT spot-check",
            "Per slice",
          ],
          [
            "PoC manual QA checklist",
            "Andorhal, Scholomance, EPL mentions",
            "Replace with manifest-driven entity list from run",
            "8",
          ],
        ]}
      />

      <Divider />
      <H2>Slice roadmap (summary)</H2>
      <Table
        headers={["Slice", "Workstreams", "Primary deliverables", "Blocks"]}
        rows={[
          [
            "1 ✓",
            "W1, W3",
            "Scoped evidence pools; storyline HTML parser; zone_quest_graph_v3; denylist taxonomy",
            "—",
          ],
          ["2 ✓", "W4, W5", "Quest traverse; lore extract; cluster questline cards", "—"],
          ["3 ✓", "W2", "at-a-glance / currently / history workers + election + lint", "—"],
          ["4 ✓", "W6", "Faction zone-significance scoring + ranked cards", "—"],
          ["5", "W7", "Location denylist, relevance, no defer padding", "Landmarks section"],
          ["6", "W8", "Instance LLM workers, boss parse, instance_lore traverse", "Instance pages"],
          ["7", "W9", "Run-scoped glossary terms; linker; wiki_url on refs", "Click-to-wiki UX"],
          ["8", "W10, W11", "Provenance anchors; validation; remove remaining stubs", "Release quality"],
        ]}
      />

      <Divider />
      <H2>Verification commands (Slice 1–4)</H2>
      <Table
        headers={["Check", "Command"]}
        rows={[
          ["Unit + integration tests", "uv run pytest"],
          [
            "Optional PoC artifact regression",
            "LORE_PILOT_RUN_ROOT=artifacts/runs/run-western-plaguelands uv run pytest tests/test_run_storyline_artifacts.py",
          ],
          [
            "Run semantic acceptance",
            "uv run python scripts/check_run_semantics.py artifacts/runs/<run-id> [--zone-id zone-...]",
          ],
          [
            "Full pipeline (manual QA)",
            "uv run lore-pipeline run --run-id <run-id> --fact-check-profile off -v",
          ],
        ]}
      />

      <CollapsibleSection title="Slice 2 — verification (completed)" count={5}>
        <Table
          headers={["Check", "Criterion"]}
          rows={[
            ["Cluster card wiki_refs", "Each ref passes is_valid_quest_graph_link; titles are cluster headings"],
            ["Card count", "Card cluster ids ⊆ v3 quest cluster_ids; max 8 enforced in draft and check_run_semantics"],
            ["Traversal report", "No denylisted geography hrefs as role=quest; hub rows have hub_resolved_from"],
            ["Quest evidence", "Each included cluster has ≥1 quest_cluster_lore snippet in evidence_packs.jsonl"],
            [
              "PoC spot-check (optional)",
              "LORE_PILOT_RUN_ROOT run: narrative cta_hook; no zone-description filler heuristics",
            ],
          ]}
        />
      </CollapsibleSection>

      <CollapsibleSection title="Slice 2 — goals (reference)" count={3}>
        <Stack gap={12}>
          <H3>Goals</H3>
          <Text>
            Traverse only graph v3 quest URLs. Extract lore-bearing text from quest pages. Synthesize one card per
            narrative cluster (not per quest). Hub-page resolver must stay zone-agnostic (structure-based, not title
            lists).
          </Text>
          <H3>Acceptance</H3>
          <Table
            headers={["Check", "Criterion"]}
            rows={[
              ["major_questlines titles", "No geography hub titles from entity_denylist; no *Quests achievement"],
              ["traversal report", "No denylisted geography hrefs as role=quest"],
              ["quest evidence", "Each cluster has at least 1 quest page snippet in evidence"],
              [
                "PoC spot-check (optional)",
                "LORE_PILOT_RUN_ROOT run includes narrative cluster hooks, not zone-description filler",
              ],
            ]}
          />
        </Stack>
      </CollapsibleSection>

      <CollapsibleSection title="Slice 3 — Zone prose workers" count={2}>
        <Stack gap={12}>
          <H3>Acceptance (generalized)</H3>
          <Table
            headers={["Check", "Criterion"]}
            rows={[
              ["at_a_glance words", "≤ 45; no location list dump pattern"],
              ["currently", "No adjacent-zone geography hubs; no reputation/achievement meta; present tense"],
              ["history", "Past tense; section count within dynamic cap; uses seed history blocks only"],
            ]}
          />
          <Text tone="success">Slice 3 completed — see summary and verification tables above.</Text>
        </Stack>
      </CollapsibleSection>

      <CollapsibleSection title="Slice 4 — Faction scoring and zone-role summaries" count={2}>
        <Stack gap={12}>
          <H3>Acceptance (generalized)</H3>
          <Table
            headers={["Check", "Criterion"]}
            rows={[
              ["major_factions count", "2–6 when ≥2 scored candidates; discovery-driven ids (no _FACTION_HINTS)"],
              ["Card summaries", "Zone-role only; present tense for active role; no reputation/achievement meta"],
              ["Alliance/Horde", "Included only when conflict_score ≥ threshold (quest bindings or high-weight seed)"],
            ]}
          />
          <Text tone="success">Slice 4 completed — see summary and verification tables above.</Text>
        </Stack>
      </CollapsibleSection>

      <CollapsibleSection title="Slice 5 — Location guards and landmark summaries" count={2}>
        <Stack gap={12}>
          <H3>Acceptance (generalized)</H3>
          <Table
            headers={["Check", "Criterion"]}
            rows={[
              ["location_cards count", "3–8 include-only when enough scored candidates; no defer padding"],
              ["Card summaries", "In-zone landmark; zone/subregion anchor; no dating-convention or faction lede"],
              ["Traverse", "location_profile include-only; dating-convention and denylist defense-in-depth"],
            ]}
          />
          <Text tone="success">Slice 5 completed — see summary and verification tables above.</Text>
        </Stack>
      </CollapsibleSection>

      <Divider />
      <H2>Pipeline stage touchpoints</H2>
      <Table
        headers={["Stage", "Changes across slices"]}
        rows={[
          ["ingest / fetch_wiki", "Storyline URLs tagged auxiliary_role + parse_html (Slice 1 ✓)"],
          ["traverse_seed", "Storyline + faction + location (include-only) (Slice 2–5 ✓)"],
          ["traverse_quests", "Quest URLs from v3 only; cap 25; hub resolver (Slice 2 ✓)"],
          ["discovery / storyline_html", "List-item quest parse only (Slice 1 ✓)"],
          ["discovery / entity_typing", "Denylist taxonomy + zone_name self-check (Slice 1 ✓)"],
          ["discovery / enrich", "Scoped evidence + quest_lore / quest_cluster_lore (Slice 1–2 ✓)"],
          ["scripts/check_run_semantics.py", "Cluster cards + traversal denylist + prose + faction + location quality (Slice 1–5 ✓)"],
          ["draft / wiki_first", "Cluster questline cards + zone prose + major_factions + location_cards election/lint (Slice 2–5 ✓)"],
          ["dictionary/", "Run-scoped terms replace static pilot aliases"],
        ]}
      />

      <Row gap={8}>
        <Pill tone="accent">Next: Slice 6</Pill>
        <Pill tone="neutral">PoC QA: WPL + Scholomance (data only)</Pill>
        <Pill tone="success">Policy: zone-agnostic code</Pill>
      </Row>
    </Stack>
  );
}
