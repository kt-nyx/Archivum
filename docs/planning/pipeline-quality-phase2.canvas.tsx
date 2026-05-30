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
    id: "slice-9",
    content: "Slice 9 — Evidence hygiene & geography (RPG filter, era selection, parent_continent)",
    status: "complete" as const,
  },
  {
    id: "slice-10",
    content: "Slice 10 — Tense & voice policy (at_a_glance all-past, currently present, history past)",
    status: "pending" as const,
  },
  {
    id: "slice-11",
    content: "Slice 11 — Provenance & citation wiring (revision map, pointer fallbacks, glossary anchors)",
    status: "pending" as const,
  },
  {
    id: "slice-12",
    content: "Slice 12 — Cards & clustering (questlines, locations, faction zone-anchors)",
    status: "pending" as const,
  },
  {
    id: "slice-13",
    content: "Slice 13 — Instance page completeness (key_enemies, boss roles, provenance cap)",
    status: "pending" as const,
  },
  {
    id: "slice-14",
    content: "Slice 14 — Validation & release gate alignment (fact-check off, semantics, pilot green run)",
    status: "pending" as const,
  },
];

const ISSUE_MAP: Array<[string, string, string, string]> = [
  [
    "P0-1",
    "parent_continent = northrend (simile false match)",
    "9",
    "pipeline/discovery/geography.py",
  ],
  [
    "P0-2",
    "RPG / non-canon prose in history_sections",
    "9",
    "enrich.py, prose_election.py, fetch_wiki section tagging",
  ],
  [
    "P0-3",
    "History stops pre-Cata; modern retail eras missing",
    "9",
    "prose_election.select_history_pool, history_section_cap",
  ],
  [
    "P0-4",
    "Expansion boilerplate in history_digest (*This section concerns*)",
    "9",
    "enrich.py, prose_election.py",
  ],
  [
    "P1-1",
    "at_a_glance mixed tense; prompt says present tense",
    "10",
    "wiki_first_workers.py, prose_lint.py",
  ],
  [
    "P1-2",
    "history_sections[2] present tense (maintains)",
    "10",
    "prose_lint.py, wiki_first_workers.py, check_run_semantics.py",
  ],
  [
    "P1-3",
    "at_a_glance / currently thematic overlap",
    "10",
    "wiki_first_workers prompts, prose_election pools",
  ],
  [
    "P0-5",
    "provenance.at_a_glance empty (hard-fail)",
    "11",
    "wiki_first.py _pointers_for_source_ids, _ensure_pointer_count",
  ],
  [
    "P0-6",
    "Questline card provenance empty (quest source_ids not in revision_map)",
    "11",
    "wiki_first._source_revision_map, ingest snapshots index",
  ],
  [
    "P1-4",
    "history_sections[].source_refs always []",
    "11",
    "wiki_first_workers, prose_election fallbacks",
  ],
  [
    "P1-5",
    "Glossary provenance duplicate pointer for all terms",
    "11",
    "pipeline/linker/linker.py glossary backfill",
  ],
  [
    "P1-6",
    "sources[] incomplete vs traversed evidence",
    "11",
    "wiki_first.build_zone_page sources aggregation",
  ],
  [
    "P0-7",
    "Single questline mega-cluster (66 quests, cluster-main)",
    "12",
    "storyline_html.py, draft wiki_first clustering",
  ],
  [
    "P0-8",
    "location_cards empty (scores never reach include_min 0.7)",
    "12",
    "discovery/workflow.py location scoring, build_location_cards",
  ],
  [
    "P1-7",
    "Junk location candidates (ADP, Lore, Ner'zhul, Scourge)",
    "12",
    "entity_typing, workflow location candidates",
  ],
  [
    "P1-8",
    "Faction summaries generic (Alliance lede from faction page)",
    "12",
    "faction_scoring.py, wiki_first _finalize_faction_card",
  ],
  [
    "P1-9",
    "instance key_enemies empty despite boss_pool evidence",
    "13",
    "instance_bosses.py, wiki_first _finalize_key_enemies",
  ],
  [
    "P2-1",
    "fact_check insufficient_evidence warnings with profile=off",
    "14",
    "validate/rules/fact_check.py",
  ],
  [
    "P2-2",
    "validate_passed=false; semantics fails on history tense + empty locations",
    "14",
    "scripts/check_run_semantics.py, validate engine",
  ],
];

export default function PipelineQualityPhase2Plan() {
  return (
    <Stack gap={16}>
      <H1>Pipeline Quality Phase 2 — Slices 9–14</H1>
      <Text tone="secondary">
        Follow-on rewrite after wiki-first Slices 1–8 (complete). Addresses test-run-wpl-1 quality failures:
        polluted evidence, broken provenance, empty cards, tense policy drift, and pilot gate mismatch. Prior plan
        archived to docs/planning/legacy/wiki-first-pipeline-master-plan-slices-1-8.canvas.tsx
      </Text>

      <Row gap={12}>
        <Stat label="Phase" value="Quality rewrite" tone="accent" />
        <Stat label="Slices" value="9 → 14" tone="accent" />
        <Stat label="Dev pilot run" value="test-run-wpl-1" tone="success" />
        <Stat label="CI pilot run" value="run-western-plaguelands" tone="success" />
        <Stat label="Slices 1–8" value="Complete" tone="success" />
        <Stat label="Next" value="Slice 10" tone="accent" />
      </Row>

      <Callout tone="info" title="Locked decisions (2026-05-30)">
        <Stack gap={6}>
          <Text>
            at_a_glance: all past tense — historical identity caption only. currently owns present-state retail
            summary entirely.
          </Text>
          <Text>
            Pilot gates: iterate on test-run-wpl-1; promote to run-western-plaguelands for canonical CI / release
            checklist once green.
          </Text>
          <Text>
            Questline clustering: layered approach — fix storyline heading extraction, then faction / level-band /
            hub-title fallback splits when cluster-main exceeds cap.
          </Text>
          <Text>
            Docs layout: active plan = this file + docs/planning/pipeline-quality-phase2.canvas.tsx. Legacy plans in
            docs/planning/legacy/.
          </Text>
        </Stack>
      </Callout>

      <Callout tone="warning" title="Problem statement (test-run-wpl-1 baseline)">
        <Text>
          Pipeline completes all stages but zone_page fails validation (provenance hard-fails), semantics fails
          (history tense, empty location_cards), history contains RPG non-canon, parent_continent wrong, questlines
          collapse to one 66-quest card, and fact-check warns on every section despite profile=off. Instance page
          passes validate but key_enemies empty and overview overly dense.
        </Text>
      </Callout>

      <TodoListCard todos={SLICES} defaultExpanded />

      <Divider />
      <H2>Product intent — prose & tense (Slice 10 locks this)</H2>
      <Table
        headers={["Field", "Tense", "Scope", "Anti-patterns"]}
        rows={[
          [
            "at_a_glance",
            "Past only",
            "1–2 sentences; zone historical identity from earliest through latest era in evidence — no present-state duties",
            "Present tense; location lists; player meta; duplicating currently",
          ],
          [
            "currently",
            "Present only",
            "Retail in-universe active conflict / recovery state at latest wiki era",
            "Past historical arcs; reputation/achievement; adjacent-zone geography hubs",
          ],
          [
            "history_sections",
            "Past only",
            "Chronological era sections through latest retail block on seed page",
            "RPG non-canon; expansion banner stubs; present tense (maintains, struggles)",
          ],
          [
            "major_questlines.cta_hook",
            "Present or imperative OK",
            "Narrative hook for cluster — not zone geography essay",
            "Truncated mid-sentence; 66-quest dumps",
          ],
        ]}
      />

      <Divider />
      <H2>Issue → slice map</H2>
      <Table
        headers={["ID", "Symptom", "Slice", "Primary files"]}
        rows={ISSUE_MAP}
      />

      <Divider />
      <H2>Dependency order</H2>
      <Table
        headers={["Slice", "Depends on", "Can parallel with"]}
        rows={[
          ["9", "—", "—"],
          ["10", "9 (clean evidence pools)", "11 (partial)"],
          ["11", "9–10 (stable draft text)", "13 (instance revision map)"],
          ["12", "9, 11 (quest provenance helps cards)", "13"],
          ["13", "9, 11", "12"],
          ["14", "9–13", "—"],
        ]}
      />

      <Divider />
      <H2>Golden examples (WPL — illustrative acceptance targets)</H2>
      <Table
        headers={["Section", "Target quality (not verbatim)"]}
        rows={[
          [
            "at_a_glance",
            "Past tense: former Lordaeron breadbasket, fell to the Scourge, began recovering after the Cataclysm.",
          ],
          [
            "currently",
            "Present: Argent Crusade and Cenarion Circle heal the land; Horde and Alliance clash over Andorhal.",
          ],
          [
            "history (must include)",
            "Scourging / cauldrons → Cataclysm recovery → Battle for Andorhal / Fourth War spillover — not RPG Cinderhome only.",
          ],
          [
            "parent_continent",
            "eastern-kingdoms only — never northrend from simile text; never lordaeron as parent.",
          ],
          [
            "major_questlines",
            "Multiple narrative clusters (Andorhal arc, caravan/healing, etc.) — max ~12 quests/card, max 8 cards.",
          ],
          [
            "location_cards",
            "Andorhal, Hearthglen, Caer Darrow — not ADP, Lore, Ner'zhul, Scourge-as-location.",
          ],
          [
            "Scholomance key_enemies",
            "Gandling, Jandice, etc. — not empty array.",
          ],
        ]}
      />

      <Divider />
      <H2>Slice specifications</H2>

      <CollapsibleSection title="Slice 9 — Evidence hygiene & geography" count={7}>
        <Stack gap={12}>
          <H3>Goals</H3>
          <Text>
            Stop polluted snippets entering history_digest and related pools. Fix parent_continent. Ensure modern
            retail era blocks can reach history output.
          </Text>

          <H3>Root causes</H3>
          <Table
            headers={["Issue", "Mechanism"]}
            rows={[
              [
                "RPG in history",
                "Ingest tags RPG body as history_edit; enrich _is_history_digest_role accepts *_edit except in_the_rpg_edit only on disclaimer line",
              ],
              [
                "Northrend continent",
                "resolve_parent_continent substring-matches continent names in any history simile",
              ],
              [
                "Missing Cata/BFA history",
                "select_history_pool sorts history_edit before era sections; cap fills with early/RPG blocks first",
              ],
              [
                "Boilerplate sections",
                "Expansion header stubs (*This section concerns*) pass history_digest role rules",
              ],
            ]}
          />

          <H3>Implementation tasks</H3>
          <Table
            headers={["Task", "Files", "Specification"]}
            rows={[
              [
                "RPG block filter",
                "pipeline/discovery/enrich.py, pipeline/generate/draft/prose_election.py",
                "Exclude snippets after in_the_rpg disclaimer until next major h2; reject *non-canon*, *Warcraft RPG* markers; exclude mis-tagged history_edit duplicates of RPG openings",
              ],
              [
                "Boilerplate filter",
                "prose_election.py",
                "Drop snippets matching /^This section concerns content related to/i and similar wiki template lines from history/at pools",
              ],
              [
                "Era-aware history selection",
                "prose_election.select_history_pool, history_section_cap",
                "Reserve min 2 slots for latest-era sections (cataclysm_*, battle_for_*, exploring_*, fourth war tokens) when present in pool; sort chronologically not only by _role_sort_key early-first",
              ],
              [
                "parent_continent v2",
                "pipeline/discovery/geography.py",
                "Priority: lead/geography seed snippets → coalesce geography claims → history. Ignore continent mentions in simile context (e.g. 'as in Northrend'). Prefer Eastern Kingdoms / Lordaeron over incidental Northrend",
              ],
              [
                "Ingest section tagging (optional hardening)",
                "pipeline/ingest/fetch_wiki.py",
                "After in_the_rpg h2, force section_role prefix in_the_rpg_ until next top-level era heading — prevents history_edit mis-tag",
              ],
              [
                "Tests",
                "tests/test_geography.py, tests/test_evidence_pools.py, new test_rpg_history_filter.py",
                "Fixtures with RPG HTML excerpt; assert excluded from history_digest; WPL parent_continent not northrend",
              ],
            ]}
          />

          <H3>Acceptance gate</H3>
          <Table
            headers={["Check", "Criterion"]}
            rows={[
              ["pytest", "New + updated unit tests green"],
              ["WPL history content", "No non-canon / Warcraft RPG content in history_sections"],
              ["parent_continent", "eastern-kingdoms (not northrend, not lordaeron)"],
              ["Era coverage", "history includes trailing named wiki sections (e.g. Fourth War) for WPL"],
              ["Run command", "uv run lore-pipeline run --run-id test-run-wpl-1 --fact-check-profile off -v"],
            ]}
          />
        </Stack>
      </CollapsibleSection>

      <CollapsibleSection title="Slice 10 — Tense & voice policy" count={6}>
        <Stack gap={12}>
          <H3>Goals</H3>
          <Text>
            Encode locked tense policy in prompts, fallbacks, lint, and semantics. Remove present-tense instruction
            from at_a_glance synthesis.
          </Text>

          <H3>Implementation tasks</H3>
          <Table
            headers={["Task", "Files", "Specification"]}
            rows={[
              [
                "at_a_glance prompt",
                "wiki_first_workers.synthesize_at_a_glance",
                "Past tense only; historical arc through latest era; explicitly defer present state to currently field",
              ],
              [
                "at_a_glance lint",
                "prose_lint.lint_at_a_glance",
                "Reject dominant present-tense verbs (is/are/remains/maintains) unless zero past markers and word_count &lt; 8; require ≥1 past marker or historical framing token",
              ],
              [
                "currently prompt/lint",
                "wiki_first_workers, prose_lint",
                "Keep present tense; strengthen overlap check vs at_a_glance (shared token threshold)",
              ],
              [
                "history prompt/lint",
                "wiki_first_workers.synthesize_history_sections, prose_lint",
                "Strict past tense; fail lint on present-tense dominance without historical framing exception removed for RPG voice",
              ],
              [
                "Fallback trimmers",
                "prose_election.fallback_at_a_glance",
                "When trimming wiki snippets for fallback, prefer sentences with past markers",
              ],
              [
                "Semantics",
                "scripts/check_run_semantics.py",
                "Align at_a_glance checks with new lint; document currently vs at_a_glance division",
              ],
            ]}
          />

          <H3>Acceptance gate</H3>
          <Table
            headers={["Check", "Criterion"]}
            rows={[
              ["WPL at_a_glance", "All past tense; no present-state Andorhal/healing clause (belongs in currently)"],
              ["WPL currently", "Present tense; Battle for Andorhal / faction conflict"],
              ["Semantics", "history_sections[*] past-tense lint passes (incl. index 2 Scarlet)"],
              ["Tests", "tests/test_wiki_first_workers.py, test_prose_lint extensions"],
            ]}
          />
        </Stack>
      </CollapsibleSection>

      <CollapsibleSection title="Slice 11 — Provenance & citation wiring" count={7}>
        <Stack gap={12}>
          <H3>Goals</H3>
          <Text>
            Clear validation hard-fails on at_a_glance and questline provenance. Fix revision map for traversal
            sources. Improve glossary and section-level citation fidelity.
          </Text>

          <H3>Root causes</H3>
          <Table
            headers={["Issue", "Mechanism"]}
            rows={[
              [
                "Empty at_a_glance provenance",
                "LLM used_evidence_ids mismatch → _pointers_for_source_ids returns []; no _ensure_pointer_count on zone at_a_glance",
              ],
              [
                "Empty questline provenance",
                "quest_cluster_lore source_ids (src-*-quest-*) absent from coalesce-only revision_map",
              ],
              [
                "Empty source_refs",
                "Draft always writes source_refs: [] — by design gap",
              ],
              [
                "Glossary dup pointer",
                "linker falls back to _first_valid_pointer for every term",
              ],
            ]}
          />

          <H3>Implementation tasks</H3>
          <Table
            headers={["Task", "Files", "Specification"]}
            rows={[
              [
                "Unified revision index",
                "wiki_first._source_revision_map (or new helper)",
                "Build from ingest source_snapshots.json: all source_id → revision_id; merge with coalesce fact_pack",
              ],
              [
                "Pointer fallback",
                "wiki_first.build_zone_page",
                "Apply _ensure_pointer_count to at_a_glance, currently, questline cards when used IDs fail; min 1 pointer when section text non-empty",
              ],
              [
                "Questline provenance",
                "wiki_first quest card loop",
                "Map quest evidence to storyline parent source when quest snapshot revision unavailable; or include quest rows in revision index",
              ],
              [
                "Section source_refs",
                "wiki_first_workers / prose_election",
                "Populate history_sections[].source_refs from producing evidence item pointer (1 per section)",
              ],
              [
                "Glossary linker",
                "pipeline/linker/linker.py",
                "Match term in section text for pointer; only use _first_valid_pointer when no section match; never duplicate same pointer for all terms on page",
              ],
              [
                "sources[] completeness",
                "wiki_first.build_zone_page",
                "Union all source_ids referenced in any provenance map entry",
              ],
              [
                "Tests",
                "tests/test_provenance_page_entities.py, test_linker_stage.py",
                "Zone draft: at_a_glance provenance ≥1; questline card provenance ≥1; glossary pointers differ per term when sections differ",
              ],
            ]}
          />

          <H3>Acceptance gate</H3>
          <Table
            headers={["Check", "Criterion"]}
            rows={[
              ["validate zone", "No provenance.missing_section_pointers on at_a_glance"],
              ["validate zone", "No provenance.missing_card_pointers on major_questlines_shared.*"],
              ["WPL draft inspect", "provenance.at_a_glance length ≥ 1; quest cluster pointer present"],
            ]}
          />
        </Stack>
      </CollapsibleSection>

      <CollapsibleSection title="Slice 12 — Cards & clustering" count={8}>
        <Stack gap={12}>
          <H3>Goals</H3>
          <Text>
            Actionable questline cards, non-empty location_cards for WPL, zone-specific faction summaries. Layered
            questline clustering (thorough).
          </Text>

          <H3>Questline clustering — layered strategy</H3>
          <Table
            headers={["Layer", "When", "Action"]}
            rows={[
              [
                "L1 Headings",
                "Always",
                "Fix storyline parse_html heading extraction: support wikitables, div.thumb headers, h2/h3 inside mw-parser-output; re-parse WPL storyline snapshot",
              ],
              [
                "L2 Faction split",
                "cluster-main quest count &gt; 15",
                "Split v3 rows into alliance / horde / shared sub-clusters with derived cluster_id suffix",
              ],
              [
                "L3 Level band",
                "Still oversized after L2",
                "Group by level_range bracket ([35-40], etc.) when present on quest rows",
              ],
              [
                "L4 Hub title",
                "Quest list under repeated storyline prefix",
                "Infer cluster_title from nearest bold/questline section label in HTML when headings absent",
              ],
              [
                "L5 Card cap",
                "Always",
                "Enforce max 8 cards, max 12 chain_refs per card; overflow → secondary card or exclude with defer reason in draft_decisions",
              ],
            ]}
          />

          <H3>Location & faction tasks</H3>
          <Table
            headers={["Task", "Files", "Specification"]}
            rows={[
              [
                "Location scoring",
                "discovery/workflow.py (and enrich mirror)",
                "Raise major_location_candidate with history/maps role to include threshold; named place in seed lead bonus; Andorhal/Hearthglen pattern without requiring 'city' keyword",
              ],
              [
                "Junk candidate filter",
                "entity_typing.should_reject_location_title",
                "Hard reject: Lore, ADP, single-token faction names, NPC names, Scourge as location",
              ],
              [
                "Location cards gate",
                "build_location_cards, check_run_semantics",
                "Allow top-N scored defer candidates when zero includes but ≥3 valid candidates (pilot flag) OR lower include_min to 0.45 for major_location_candidate",
              ],
              [
                "Faction zone anchor",
                "faction_scoring.py, faction_lint.py",
                "Score zone-seed mentions above generic faction profile; lint requires zone_name token or subregion anchor in summary",
              ],
              [
                "cta_hook synthesis",
                "wiki_first_workers.synthesize_card_summary",
                "Enforce max words + terminal punctuation; reject truncated hooks in lint",
              ],
            ]}
          />

          <H3>Acceptance gate</H3>
          <Table
            headers={["Check", "Criterion"]}
            rows={[
              ["major_questlines", "≥2 cards for WPL; no card with &gt;12 chain_refs; titles not 'Main storylines' only"],
              ["location_cards", "≥3 include cards (Andorhal, Hearthglen, Caer Darrow or equivalent)"],
              ["major_factions", "Alliance summary mentions Western Plaguelands or Andorhal — not generic Lordaeron lede only"],
              ["Semantics", "location_cards non-empty check passes"],
            ]}
          />
        </Stack>
      </CollapsibleSection>

      <CollapsibleSection title="Slice 13 — Instance page completeness" count={5}>
        <Stack gap={12}>
          <H3>Goals</H3>
          <Text>Scholomance-quality instance output: key_enemies populated, boss evidence wired, provenance not spammy.</Text>

          <H3>Implementation tasks</H3>
          <Table
            headers={["Task", "Files", "Specification"]}
            rows={[
              [
                "Boss section roles",
                "instance_bosses.is_boss_section_role",
                "Add tokens: scholomance_faculty, dungeon_, faculty, denizens, bosses, cataclysm dungeon layout sections on retail pages",
              ],
              [
                "Boss link extract",
                "instance_bosses._extract_wiki_links",
                "Parse faculty/roster tables; map /wiki/Darkmaster_Gandling etc.",
              ],
              [
                "key_enemies finalize",
                "wiki_first._finalize_key_enemies",
                "Allow card emission with pointer fallback from boss_pool when lint passes; min 1 enemy when boss_pool ≥1 valid name",
              ],
              [
                "story_context cap",
                "wiki_first.build_instance_page",
                "Apply _cap_card_pointers to story_context / overview provenance (max 3)",
              ],
              [
                "Tests",
                "tests/test_instance_bosses.py, test_wiki_first_instance",
                "Scholomance fixture: ≥1 key_enemy; Gandling name present",
              ],
            ]}
          />

          <H3>Acceptance gate</H3>
          <Table
            headers={["Check", "Criterion"]}
            rows={[
              ["instance draft", "key_enemies.length ≥ 1 for Scholomance"],
              ["validate", "instance entity still passes; story_context pointer cap warn cleared or ≤3"],
            ]}
          />
        </Stack>
      </CollapsibleSection>

      <CollapsibleSection title="Slice 14 — Validation & release gate" count={6}>
        <Stack gap={12}>
          <H3>Goals</H3>
          <Text>
            Single coherent green-run definition. Align fact-check off behaviour, semantics, and validate. Promote
            test-run-wpl-1 fixes to run-western-plaguelands CI manifest.
          </Text>

          <H3>Implementation tasks</H3>
          <Table
            headers={["Task", "Files", "Specification"]}
            rows={[
              [
                "fact_check off",
                "validate/rules/fact_check.py",
                "When profile=off: skip insufficient_evidence unless provenance pointers exist AND overlap check requested; or raise overlap threshold",
              ],
              [
                "Semantics vs validate",
                "scripts/check_run_semantics.py",
                "Ensure failure messages match validate hard-fails; optional --strict mode for CI",
              ],
              [
                "Pilot manifest",
                "tests/fixtures/pilot/source_manifest.json, artifacts/runs/run-western-plaguelands/",
                "Sync Scholomance lore URL fix; seed CI run directory",
              ],
              [
                "Release checklist",
                "README or docs/planning/",
                "Document dual-run promotion: test-run-wpl-1 dev → run-western-plaguelands CI",
              ],
              [
                "Canvas hygiene",
                "docs/planning/legacy/",
                "Mark slices 9–14 complete in TodoList as each lands; keep this doc updated",
              ],
            ]}
          />

          <H3>Release gate (both runs)</H3>
          <Table
            headers={["Check", "Command / criterion"]}
            rows={[
              ["Full pipeline", "uv run lore-pipeline run --run-id test-run-wpl-1 --fact-check-profile off -v"],
              ["CI pipeline", "uv run lore-pipeline run --run-id run-western-plaguelands --fact-check-profile off -v"],
              ["Semantics", "uv run python scripts/check_run_semantics.py artifacts/runs/<run-id>"],
              ["Unit tests", "uv run pytest"],
              ["Validate", "validate_passed=true for zone + instance"],
              ["Manual read", "Zone + instance drafts match golden examples section above"],
            ]}
          />
        </Stack>
      </CollapsibleSection>

      <Divider />
      <H2>Operating rules (unchanged from Phase 1)</H2>
      <Table
        headers={["Rule", "Requirement"]}
        rows={[
          ["One active slice", "No slice N+1 until slice N acceptance gate passes on test-run-wpl-1"],
          ["Zone-agnostic code", "No WPL proper nouns in pipeline control flow — fixtures/manifests only"],
          ["Tests first", "Failing test reproducing test-run-wpl-1 bug, then fix"],
          ["No stub done", "Empty cards/arrays/provenance forbidden as 'done'"],
          ["Promote to CI run", "After slice gate green on test-run-wpl-1, rerun run-western-plaguelands before marking slice complete"],
        ]}
      />

      <Divider />
      <H2>Workstream index (Phase 2)</H2>
      <Table
        headers={["ID", "Name", "Slice", "Primary files"]}
        rows={[
          ["W12", "Evidence hygiene & geography", "9", "enrich.py, prose_election.py, geography.py, fetch_wiki.py"],
          ["W13", "Tense & voice", "10", "wiki_first_workers.py, prose_lint.py, check_run_semantics.py"],
          ["W14", "Provenance wiring", "11", "wiki_first.py, linker.py"],
          ["W15", "Quest/location/faction cards", "12", "storyline_html.py, workflow.py, wiki_first.py"],
          ["W16", "Instance bosses", "13", "instance_bosses.py, wiki_first.py"],
          ["W17", "Release gate", "14", "fact_check.py, validate engine, pilot manifests"],
        ]}
      />

      <Divider />
      <H2>Pipeline stage touchpoints (Phase 2)</H2>
      <Table
        headers={["Stage", "Slice changes"]}
        rows={[
          ["ingest / fetch_wiki", "RPG section tagging hardening (9)"],
          ["discovery / enrich", "RPG/boilerplate exclusion from history_digest (9)"],
          ["discovery / geography", "parent_continent resolver v2 (9)"],
          ["discovery / storyline_html", "Heading extraction + cluster splits (12)"],
          ["discovery / workflow", "Location scoring + junk filter (12)"],
          ["generate / prose_election", "Era-aware history pool (9); tense-aware fallbacks (10)"],
          ["generate / wiki_first_workers", "Past-tense at_a_glance prompt (10); card hook quality (12)"],
          ["generate / wiki_first", "Revision index, pointer fallbacks, source_refs (11); clustering (12); key_enemies (13)"],
          ["linker", "Term-specific glossary provenance (11)"],
          ["validate / fact_check", "profile=off behaviour (14)"],
          ["scripts/check_run_semantics.py", "Tense + location gates aligned (10, 12, 14)"],
        ]}
      />

      <Divider />
      <H2>Plan session template</H2>
      <Callout tone="info" title="Per-slice workflow">
        <Stack gap={6}>
          <Text>1. Open this canvas → slice CollapsibleSection.</Text>
          <Text>2. Write failing tests from acceptance table.</Text>
          <Text>3. Implement — no TODO stubs.</Text>
          <Text>4. uv run pytest</Text>
          <Text>5. uv run lore-pipeline run --run-id test-run-wpl-1 --fact-check-profile off -v</Text>
          <Text>6. uv run python scripts/check_run_semantics.py artifacts/runs/test-run-wpl-1</Text>
          <Text>7. Promote: rerun run-western-plaguelands if manifest synced</Text>
          <Text>8. Mark slice completed in TodoList; update docs/planning/pipeline-quality-phase2.canvas.tsx copy</Text>
        </Stack>
      </Callout>

      <Row gap={8}>
        <Pill tone="accent">Next: Slice 10</Pill>
        <Pill tone="neutral">Legacy: docs/planning/legacy/</Pill>
        <Pill tone="success">Tense: at_a_glance past / currently present</Pill>
      </Row>
    </Stack>
  );
}
