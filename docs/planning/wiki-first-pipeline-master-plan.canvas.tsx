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
    status: "pending" as const,
  },
  {
    id: "slice-3",
    content: "Slice 3 — Zone prose workers (at-a-glance, currently, history)",
    status: "pending" as const,
  },
  {
    id: "slice-4",
    content: "Slice 4 — Faction scoring, ranking, zone-role summaries",
    status: "pending" as const,
  },
  {
    id: "slice-5",
    content: "Slice 5 — Location guards, relevance gates, card quality",
    status: "pending" as const,
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

      <CollapsibleSection title="Slice 1 — known deviances (intentional deferrals)" count={4}>
        <Table
          headers={["Topic", "Current behaviour", "Target slice"]}
          rows={[
            [
              "Quest traverse cap",
              "Cap 12 in traverse_wiki; v3 may list more nodes",
              "2",
            ],
            [
              "major_questlines cards",
              "Draft still uses legacy graph projection; cluster cards not synthesized",
              "2",
            ],
            [
              "Prose worker quality",
              "Prompts unchanged; pools fixed only",
              "3",
            ],
            [
              "Full validate_passed on PoC run",
              "Instance hard-fails remain",
              "6 + 8",
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
          ["2", "W4, W5", "Quest traverse; lore extract; cluster questline cards", "Currently, quest section"],
          ["3", "W2", "at-a-glance / currently / history workers + prompts", "Zone prose quality"],
          ["4", "W6", "Faction zone-significance scoring + ranked cards", "Major factions section"],
          ["5", "W7", "Location denylist, relevance, no defer padding", "Landmarks section"],
          ["6", "W8", "Instance LLM workers, boss parse, instance_lore traverse", "Instance pages"],
          ["7", "W9", "Run-scoped glossary terms; linker; wiki_url on refs", "Click-to-wiki UX"],
          ["8", "W10, W11", "Provenance anchors; validation; remove remaining stubs", "Release quality"],
        ]}
      />

      <Divider />
      <H2>Verification commands (Slice 1+)</H2>
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

      <CollapsibleSection title="Slice 2 — Quest traversal + lore extraction + questline cards" count={3}>
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
        </Stack>
      </CollapsibleSection>

      <Divider />
      <H2>Pipeline stage touchpoints</H2>
      <Table
        headers={["Stage", "Changes across slices"]}
        rows={[
          ["ingest / fetch_wiki", "Storyline URLs tagged auxiliary_role + parse_html (Slice 1 ✓)"],
          ["traverse_wiki", "Quest URLs from v3 only; location denylist; instance_lore"],
          ["discovery / storyline_html", "List-item quest parse only (Slice 1 ✓)"],
          ["discovery / entity_typing", "Denylist taxonomy + zone_name self-check (Slice 1 ✓)"],
          ["discovery / enrich", "Scoped evidence field_names (Slice 1 ✓)"],
          ["scripts/check_run_semantics.py", "Zone-agnostic acceptance (Slice 1 ✓)"],
          ["draft / wiki_first", "All section builders; instance parity"],
          ["dictionary/", "Run-scoped terms replace static pilot aliases"],
        ]}
      />

      <Row gap={8}>
        <Pill tone="accent">Next: Slice 2</Pill>
        <Pill tone="neutral">PoC QA: WPL + Scholomance (data only)</Pill>
        <Pill tone="success">Policy: zone-agnostic code</Pill>
      </Row>
    </Stack>
  );
}
