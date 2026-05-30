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
    content: "Slice 2 — Quest traversal, lore extraction, questline cluster cards",
    status: "pending" as const,
  },
  {
    id: "slice-3",
    content: "Slice 3 — Zone prose workers (at-a-glance, currently, history)",
    status: "pending" as const,
  },
  {
    id: "slice-4",
    content: "Slice 4 — Faction zone-significance scoring + ranked cards",
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
    content: "Slice 7 — Dynamic glossary generation + linker + wiki URLs",
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
        Single reference for gated slice implementation. Pilot run: run-western-plaguelands (Western Plaguelands +
        Scholomance). All behaviour must generalize to any zone. Previous canvases backed up to
        docs/planning/archive/*.canvas.tsx.bak
      </Text>

      <Row gap={12}>
        <Stat label="Execution" value="1 slice at a time" tone="accent" />
        <Stat label="Pilot run" value="run-western-plaguelands" tone="success" />
        <Stat label="Slices" value="8 gated" tone="success" />
        <Stat label="Next" value="Slice 2" tone="accent" />
      </Row>

      <Callout tone="warning" title="Problem statement">
        <Text>
          Pipeline runs end-to-end but output quality is poor because features were partially wired: quest graph treats
          geography as quests, evidence pools merge 992 auxiliary snippets into at-a-glance, instance drafting skips LLM
          synthesis, glossary depends on a static dictionary, semantic checks pass broken drafts, and validation only
          hard-fails on missing instance provenance. This plan replaces mega-implementation with acceptance-gated slices.
        </Text>
      </Callout>

      <Callout tone="info" title="Product intent (zone page sections)">
        <Stack gap={6}>
          <Text>
            at_a_glance: 1–2 sentence historical identity caption (card/subtitle). Not geography, not location lists.
          </Text>
          <Text>
            currently: In-universe present-tense summary of what is happening in this zone now — like a summary of major
            quest activity, not player guides or reputation.
          </Text>
          <Text>
            history: Chronological past-tense era/event sections from earliest lore through latest wiki era on the zone
            page.
          </Text>
          <Text>
            major_questlines: Narrative cluster cards from real quest evidence — not zone or continent descriptions.
          </Text>
        </Stack>
      </Callout>

      <Divider />
      <H2>Operating rules</H2>
      <Table
        headers={["Rule", "Requirement"]}
        rows={[
          ["One active slice", "No next slice until current acceptance tests pass on WPL rerun."],
          ["Tests before merge", "Add failing tests for old broken behaviour, then fix until green."],
          ["No placeholder done", "Forbidden: empty arrays, regex boss dumps, raw wiki passthrough, generic filler."],
          ["Seed vs auxiliary", "Zone seed (no auxiliary_role) owns identity/history; auxiliary scoped by role."],
          ["Generalize", "Rules work for late-expansion-only zones, classic zones, sparse wikis — not WPL hacks."],
          ["Plan session", "30–45 min per slice only when a design fork exists; else implement from this doc."],
        ]}
      />

      <TodoListCard todos={SLICES} defaultExpanded />

      <Divider />
      <H2>WPL golden examples (manual acceptance targets)</H2>
      <Table
        headers={["Section", "Target (illustrative, not verbatim)"]}
        rows={[
          [
            "at_a_glance",
            "Former breadbasket of Lordaeron, ravaged in the Third War; Western Plaguelands have begun to recover since the Cataclysm.",
          ],
          [
            "currently",
            "Argent Crusade paladins hold Scourge remnants at bay while Cenarion druids heal the land; Horde and Alliance clash over Andorhal where the plague began.",
          ],
          [
            "history (last era)",
            "Must reach Cataclysm recovery and/or Fourth War Andorhal — not stop at Tirion/Cinderhome only.",
          ],
          [
            "major_questlines",
            "Battle for Andorhal cluster, Fiona's Caravan / Into the Woods, etc. — not Lordaeron or Eastern Kingdoms.",
          ],
          [
            "locations",
            "Andorhal, Hearthglen, Cinderhome — not Undercity, Ironforge, ADP.",
          ],
          [
            "Scholomance",
            "Prose hook about the School of Necromancy — not a boss name list.",
          ],
        ]}
      />

      <Divider />
      <H2>Investigation findings (run-western-plaguelands)</H2>
      <Table
        headers={["Finding", "Detail"]}
        rows={[
          [
            "Storyline HTML is rich",
            "Warcraft Wiki storyline page has questlink list items with Alliance_15 / Horde_15 / Neutral_15 / Both_15 icons (~67 rows). Text extractor kept only 2 lead blurbs.",
          ],
          [
            "Zone seed history is structured",
            "Section roles: history_edit, world_of_warcraft_edit, cataclysm_edit, battle_for_azeroth_edit, exploring_azeroth_edit, quests_edit, geography_edit.",
          ],
          [
            "Evidence contamination",
            "at_a_glance pool had 992 items because all auxiliary other snippets merged.",
          ],
          [
            "Quest graph v2 broken",
            "Chain: Western Plaguelands → Lordaeron → Eastern Kingdoms → Stranglethorn → … → Western Plaguelands Quests (achievement).",
          ],
          [
            "Glossary static",
            "Linker reads dictionary/glossary_aliases.v1.json only (~20 pilot terms). Draft refs are term_id-only until bundle.",
          ],
          [
            "Validation gap",
            "check_pilot_semantics.py passes broken quest output; zone validate hard-fails only on instance provenance.",
          ],
        ]}
      />

      <Divider />
      <H2>Stub / partial inventory (must clear by slice 8)</H2>
      <Table
        headers={["Component", "Current state", "Target slice"]}
        rows={[
          ["Evidence pools", "Cross-contaminated all auxiliary snippets", "1"],
          ["storyline_parser._is_quest_link", "Accepts any wiki link", "1"],
          ["zone_quest_graph_v2", "Geography chain", "1 → v3"],
          ["Quest traverse", "Fetches Lordaeron, continents, achievements", "2"],
          ["major_questlines cards", "Zone descriptions not narrative hooks", "2"],
          ["synthesize_at_a_glance prompt", "80 words, present tense, wrong pool", "3"],
          ["synthesize_currently", "No zone filter, no meta exclusion", "3"],
          ["synthesize_history_sections", "max_sections=4, no past tense rule", "3"],
          ["_extract_factions", "Keyword grep, fixed order, truncated summaries", "4"],
          ["Location defer padding", "Admits ADP, Ironforge, Undercity", "5"],
          ["build_instance_page", "No LLM; regex key_enemies; _sized_summary pad", "6"],
          ["glossary_refs in draft", "[] then static linker dictionary", "7"],
          ["Provenance", "Paragraph spam; empty instances", "8"],
          ["parent_continent", "Hardcoded unknown", "8"],
          ["related_quest_chains", "Always [] on instances", "8"],
        ]}
      />

      <Divider />
      <H2>Evidence architecture (target state)</H2>
      <Table
        headers={["Pool name", "Source", "Used for"]}
        rows={[
          ["history_digest", "Zone seed: history_* + *_edit expansion blocks, ordered", "at_a_glance input, history input"],
          ["at_a_glance_input", "history_digest + optional seed lead (1–2 paras max)", "Caption LLM only"],
          ["currently_input", "Seed retail sections + quest cluster lore + scoped faction profiles", "Currently LLM"],
          ["history_input", "Same as history_digest", "History LLM"],
          ["quest_cluster_pool", "Per-cluster merged quest page lore snippets", "Questline card LLM"],
          ["faction_zone_pool", "faction_profile aux where score passes", "Faction card LLM"],
          ["location_zone_pool", "Seed geography/maps + passed location_profile", "Location card LLM"],
          ["instance_pool", "Instance seed + zone seed instance mentions + instance_lore", "Instance workers"],
        ]}
      />
      <Callout tone="info" title="Metadata on every evidence item">
        <Text>
          source_kind: seed | auxiliary · auxiliary_role: storyline | quest | faction_profile | location_profile |
          instance_lore · subject_zone_id · section_role · source_id
        </Text>
      </Callout>

      <Divider />
      <H2>Slice roadmap</H2>
      <Table
        headers={["Slice", "Workstreams", "Deliverables", "Unblocks"]}
        rows={[
          ["1", "W1, W3", "Scoped pools; storyline HTML parser; zone_quest_graph_v3; quest denylist", "All downstream"],
          ["2", "W4, W5", "Quest traverse; lore extract; hub resolver; cluster cards + faction buckets", "Currently, questlines"],
          ["3", "W2", "Caption / currently / history workers + prompts + dynamic history cap", "Zone prose quality"],
          ["4", "W6", "Faction significance scoring + dynamic rank + zone-role prompts", "Major factions"],
          ["5", "W7", "Location denylist; relevance; no defer padding; traverse guard", "Landmarks"],
          ["6", "W8", "Instance LLM workers; boss HTML parse; instance_lore traverse", "Scholomance"],
          ["7", "W9", "run_terms.jsonl; dynamic linker; wiki_url on glossary_refs", "Glossary UX"],
          ["8", "W10, W11", "Provenance anchors; validation; semantic script; stub removal", "Release quality"],
        ]}
      />

      <Divider />
      <H2>Slice specifications</H2>

      <CollapsibleSection title="Slice 1 — Evidence scoping + storyline parser + quest graph v3" count={6}>
        <Stack gap={12}>
          <H3>Goals</H3>
          <Text>
            Stop evidence cross-contamination. Parse storyline HTML for real quest rows with faction icons. Emit
            zone_quest_graph_v3 with narrative clusters. Old geography-as-quest behaviour must fail tests.
          </Text>

          <H3>Implementation tasks</H3>
          <Table
            headers={["Task", "Files", "Specification"]}
            rows={[
              [
                "Evidence metadata",
                "pipeline/discovery/enrich.py",
                "Add source_kind, auxiliary_role, subject_zone_id on evidence_items. Split field_names: history_digest, at_a_glance_input, currently_input — never dump all other.",
              ],
              [
                "Pool builder",
                "pipeline/generate/draft/wiki_first.py",
                "_build_evidence_pools reads scoped field_names only. Remove fallback to all_items for prose pools.",
              ],
              [
                "Storyline HTML parser (new)",
                "pipeline/discovery/storyline_html.py",
                "Input: parse-API HTML for {Zone}_storyline. Walk h2/h3 → cluster_id/title. Parse li.questlink rows: href, level range text, faction from img src (Alliance_15, Horde_15, Neutral_15, Both_15).",
              ],
              [
                "Quest denylist",
                "pipeline/discovery/entity_typing.py, entity_denylist.json",
                "Reject: continents, zones, *_Quests achievements, Category:/File:, Faction meta, adjacent zones, capitals.",
              ],
              [
                "Graph v3 artifact",
                "data/discovery/zone_quest_graph_v3.json",
                "Rows: zone_id, cluster_id, cluster_title, cluster_order, node_id, title, node_type=quest, faction_binding, level_range, source_link, order_in_cluster.",
              ],
              [
                "Storyline target fix",
                "pipeline/discovery/workflow.py",
                "Do not emit /wiki/Faction as storyline. Require _storyline suffix or explicit see-line. Prefer zone fallback URL.",
              ],
              [
                "Enrich uses v3",
                "pipeline/discovery/enrich.py",
                "Rebuild v2 from v3 or replace v2 consumption in draft_writer with v3 clusters.",
              ],
            ]}
          />

          <H3>Generalization notes</H3>
          <Table
            headers={["Zone type", "Behaviour"]}
            rows={[
              ["Classic zone with rich history", "history_digest uses all *_edit sections on seed page."],
              ["Cataclysm-era zone", "cataclysm_edit + quests_edit drive currently if present."],
              ["Expansion-new zone (no pre-history)", "history_digest short; at_a_glance uses introduction era only."],
              ["Missing storyline page", "Fallback: seed quests_edit links + Western_Plaguelands_Quests hub parse if exists."],
            ]}
          />

          <H3>Acceptance tests (must fail before slice, pass after)</H3>
          <Table
            headers={["Test", "Criterion"]}
            rows={[
              ["test_at_a_glance_pool_scoped", "WPL pool ≤ 50 items; zero auxiliary_role≠empty in at_a_glance_input"],
              ["test_graph_v3_no_geography", "No node title in {Lordaeron, Eastern Kingdoms, Hinterlands, Cape of Stranglethorn}"],
              ["test_graph_v3_no_achievements", "No *Quests achievement nodes"],
              ["test_graph_v3_quest_count", "WPL ≥ 5 quest nodes with valid faction_binding"],
              ["test_storyline_icon_parse", "Parsed faction counts match HTML icon counts ±0"],
              ["test_storyline_target_clean", "storyline_traversal_targets has no /wiki/Faction"],
            ]}
          />

          <H3>Verification</H3>
          <Text tone="secondary">
            pytest tests/test_storyline_html.py tests/test_evidence_pools.py (new) · uv run lore-pipeline run --run-id
            run-western-plaguelands --fact-check-profile off -v · inspect zone_quest_graph_v3.json
          </Text>
        </Stack>
      </CollapsibleSection>

      <CollapsibleSection title="Slice 1 — Completed / Deviances" count={6}>
        <Stack gap={12}>
          <Text tone="secondary">
            Slice 1 acceptance passed on run-western-plaguelands (pytest + check_pilot_semantics.py). Intentional
            differences from original canvas spec:
          </Text>
          <Table
            headers={["Topic", "Canvas intent", "Actual implementation"]}
            rows={[
              ["Quest graph v2", "Dual-write v3 + v2", "v3-only (user choice); enrich writes v1 projection from v3"],
              [
                "HTML retention",
                "Optional on ingest",
                "parse_html on storyline snapshots only (512KB cap)",
              ],
              [
                "Storyline headings",
                "h2/h3 clusters",
                "Fallback cluster-main when headings absent; quest rows parsed from questlong-prefix + anchor (not li-only)",
              ],
              ["Quest traverse cap", "~25 in Slice 2", "Keep 12 in Slice 1; priority-ordered from v3"],
              [
                "Prose LLM prompts",
                "Slice 1 pools",
                "Pools created; prompt changes deferred to Slice 3",
              ],
              [
                "major_questlines cards",
                "Cluster cards",
                "Per-quest v3 nodes until Slice 2",
              ],
            ]}
          />
        </Stack>
      </CollapsibleSection>

      <CollapsibleSection title="Slice 2 — Quest traversal + lore extraction + cluster cards" count={5}>
        <Stack gap={12}>
          <H3>Goals</H3>
          <Text>
            Traverse only v3 quest URLs. Extract lore from quest pages (not storyline page prose). One card per narrative
            cluster. Resolve hub pages (The Battle for Andorhal → sub-quests). Bucket alliance/horde/shared correctly.
          </Text>

          <H3>Implementation tasks</H3>
          <Table
            headers={["Task", "Files", "Specification"]}
            rows={[
              [
                "Quest traverse",
                "pipeline/ingest/traverse_wiki.py",
                "Fetch quest URLs from v3 only. Cap ~25/zone. Skip denylist. Do not use parse_storyline_snapshot link dump.",
              ],
              [
                "Quest lore extractor (new)",
                "pipeline/ingest/quest_lore.py",
                "From quest page HTML/blocks: keep lead + lore/description; strip rewards, objectives tables, external DB links, breadcrumb meta.",
              ],
              [
                "Hub resolver",
                "pipeline/ingest/quest_lore.py",
                "Detect hub/disambiguation (multiple quest links, title matches zone event). Follow 1–2 sub-quest links max.",
              ],
              [
                "Cluster evidence packs",
                "pipeline/discovery/enrich.py",
                "quest_cluster_pool per cluster_id merging member quest snippets.",
              ],
              [
                "Cluster card synthesis",
                "pipeline/generate/draft/wiki_first.py, wiki_first_workers.py",
                "New synthesize_questline_cluster_hook(cluster_title, evidence, faction). Not per-quest cards.",
              ],
              [
                "Draft writer wiring",
                "pipeline/generate/draft_writer.py",
                "Read v3 clusters + group for major_questlines_* buckets.",
              ],
            ]}
          />

          <H3>Quest page content expectations</H3>
          <Text tone="secondary">
            Many quest pages are thin (dialogue, quest-giver lists). Fallback: cluster card from zone seed quests_edit +
            quest titles + section heading on storyline page. Flag low_confidence in draft_decisions when lore word count
            below threshold.
          </Text>

          <H3>Acceptance tests</H3>
          <Table
            headers={["Test", "Criterion"]}
            rows={[
              ["traversal_report", "No role=quest for /wiki/Lordaeron, /wiki/Eastern_Kingdoms"],
              ["major_questlines titles", "Denylist geography + achievement titles"],
              ["WPL narrative", "At least one card mentions Andorhal conflict or caravan/healing arc"],
              ["faction buckets", "Alliance/horde cards only when cluster faction_binding matches"],
              ["cta_hook quality", "No zone-level description sentences (level range, contested zone, etc.)"],
            ]}
          />
        </Stack>
      </CollapsibleSection>

      <CollapsibleSection title="Slice 3 — Zone prose workers" count={4}>
        <Stack gap={12}>
          <H3>At-a-glance — read wide, write narrow</H3>
          <Table
            headers={["Step", "Spec"]}
            rows={[
              ["Input", "history_digest: ALL zone seed history/expansion blocks chronologically — not first-N-only skew"],
              ["Precompress (optional)", "Timeline bullets ~150 words max from full digest"],
              ["LLM output", "1–2 sentences, 35–45 words; must span earliest + latest era present in digest"],
              ["Prompt bans", "No locations, characters, geography, factions, player meta"],
              ["Validator", "Word cap; regex deny notable places list; require latest-era keyword if digest contains cataclysm/bfa/etc."],
            ]}
          />

          <H3>Currently — generalizable fallback ladder</H3>
          <Table
            headers={["Priority", "Source"]}
            rows={[
              ["1", "Seed expansion-tagged sections: cataclysm_*, battle_for_*, dragonflight_*, exploring_*, etc."],
              ["2", "Seed quests_edit prose (in-universe faction activity)"],
              ["3", "Quest cluster synthesized summaries (slice 2)"],
              ["4", "If zone is expansion-new: that expansion intro section"],
              ["5", "If only classic-era text: LLM reframes historical 'current at time' carefully — or shortest honest summary"],
              ["Exclude", "Adjacent zone names, reputation, achievement, players, level ranges, breadcrumb"],
            ]}
          />

          <H3>History — dynamic cap</H3>
          <Table
            headers={["Rule", "Spec"]}
            rows={[
              ["Pool", "history_digest (zone seed only)"],
              ["Cap formula", "clamp(3, count(eligible_blocks with ≥25 words), 8); if total words > 800 allow up to 8"],
              ["Prompt", "Strict past tense; chronological; event/era headings not character-centric; through latest wiki era"],
              ["Anti-pattern", "No present tense for Scourge/Scarlet historical arcs; no stopping mid-arc without latest era"],
            ]}
          />

          <H3>Files</H3>
          <Text tone="secondary">
            pipeline/generate/draft/wiki_first_workers.py — rewrite system prompts · pipeline/validate/rules/structure.py —
            word caps, token denylist · scripts/check_pilot_semantics.py — expand assertions
          </Text>

          <H3>Acceptance (WPL + generic tests)</H3>
          <Table
            headers={["Check", "Criterion"]}
            rows={[
              ["at_a_glance", "≤45 words; no location list; mentions recovery/Cataclysm"],
              ["currently", "No Eastern Plaguelands; no reputation; in-universe present tense"],
              ["history", "≥4 sections; past tense; includes post-Cata or BfA era for WPL"],
              ["generic: empty digest", "Zone with no history blocks → validation warn, honest minimal caption"],
            ]}
          />
        </Stack>
      </CollapsibleSection>

      <CollapsibleSection title="Slice 4 — Factions" count={3}>
        <Stack gap={12}>
          <H3>Scoring model</H3>
          <Table
            headers={["Signal", "Weight"]}
            rows={[
              ["Mention in seed quests_edit or retail history sections", "High (+3)"],
              ["Quest cluster faction_binding in this zone", "High (+3)"],
              ["faction_profile auxiliary fetched for zone", "Medium (+2)"],
              ["Generic faction wiki lede only", "Low (0–1, likely exclude)"],
              ["Alliance/Horde base presence", "Low (+1); +3 if conflict_score ≥ threshold (shared PvP cluster, battle for)"],
            ]}
          />
          <H3>Ranking</H3>
          <Text>
            Sort by score descending. Include while score ≥ min_threshold AND (within top N OR score ≥ 50% of previous).
            Dynamic N: 2–6. Card prompt: role in this zone (retail); past tense for defunct leadership (Scarlet/Taelan).
            Complete sentences within word cap — no mid-clause truncation.
          </Text>
          <H3>Acceptance (WPL)</H3>
          <Text tone="secondary">
            Argent Crusade + Cenarion Circle rank high · Scarlet not implied current WPL leadership · Horde present if
            Andorhal cluster exists · summaries not truncated
          </Text>
        </Stack>
      </CollapsibleSection>

      <CollapsibleSection title="Slice 5 — Locations" count={3}>
        <Stack gap={12}>
          <Table
            headers={["Guard", "Action"]}
            rows={[
              ["Denylist expand", "ADP, BDP, dating conventions, meta (Lore, Faction), factions, NPC names, capitals outside zone"],
              ["Adjacent zones", "Reuse entity_typing adjacent list + parent continent links"],
              ["Defer padding", "Remove or max 1 defer; include-only default"],
              ["Zone relevance", "location_profile body must mention zone name OR seed subregion from geography_edit"],
              ["Source preference", "Seed links from maps_subregions, geography_edit, history_edit only for candidates"],
              ["Traverse guard", "Skip denylisted location_profile targets in traverse_wiki"],
              ["Classification", "Reject city keyword false positives (Undercity mentioned in passing ≠ WPL city)"],
            ]}
          />
          <H3>Acceptance (WPL)</H3>
          <Text tone="secondary">Include Andorhal, Hearthglen, Cinderhome · Exclude Undercity, Ironforge, ADP, Scourge-as-location</Text>
        </Stack>
      </CollapsibleSection>

      <CollapsibleSection title="Slice 6 — Instance parity" count={3}>
        <Stack gap={12}>
          <Table
            headers={["Task", "Spec"]}
            rows={[
              ["LLM workers", "build_instance_page → synthesize_at_a_glance, synthesize_overview, synthesize_history_sections"],
              ["Boss parse", "HTML parse encounter section / infobox — replace _extract_key_enemy_names regex"],
              ["instance_lore traverse", "If discovery instance_lore_source_map emits targets, fetch in traverse stage"],
              ["Evidence", "instance_pool from seed + zone geography mention + aux instance_lore"],
              ["Remove", "_sized_summary padding; boss-list at_a_glance; generic enemy summaries"],
            ]}
          />
          <H3>Acceptance (Scholomance)</H3>
          <Text tone="secondary">
            at_a_glance prose about necromancy academy · overview significance not MoP redesign notes · key_enemies:
            Gandling, etc. · validate passes instance entity
          </Text>
        </Stack>
      </CollapsibleSection>

      <CollapsibleSection title="Slice 7 — Dynamic glossary" count={3}>
        <Stack gap={12}>
          <Text>
            Pipeline must NOT depend on pre-generated dictionary/glossary_aliases.v1.json for production runs. Static file
            remains for unit tests / fixtures only.
          </Text>
          <Table
            headers={["Step", "Spec"]}
            rows={[
              ["Generate run terms", "New stage or enrich pass → data/glossary/run_terms.jsonl from entities: zone, factions, locations, quest clusters, prominent proper nouns in evidence"],
              ["Term shape", "{ term_id, label, wiki_url, category, aliases[] } — wiki_url required"],
              ["Linker", "Load run_terms first; match aliases in draft text; emit glossary_refs with term_id + label + wiki_url"],
              ["Bundle", "build/lua/lookup/glossary_refs.json from run terms not static dict"],
              ["Density", "Tune cap per page type; prefer high-confidence entity matches"],
            ]}
          />
          <H3>Acceptance</H3>
          <Text tone="secondary">
            WPL: &gt;7 terms · each ref has wiki_url · covers zone name + major factions/locations · new run works with empty
            static dictionary (test with env flag)
          </Text>
        </Stack>
      </CollapsibleSection>

      <CollapsibleSection title="Slice 8 — Provenance, validation, stub removal" count={4}>
        <Stack gap={12}>
          <H3>Provenance anchor model (recommended)</H3>
          <Text>
            One pointer per synthesized field/card: source_id + section_role + excerpt_hash of snippet actually used in LLM
            output. Not enumeration of every paragraph on traversed pages.
          </Text>
          <Table
            headers={["Fix", "Detail"]}
            rows={[
              ["instances provenance", "Populate when instance link/card summary synthesized"],
              ["glossary provenance", "Section + excerpt where alias matched"],
              ["Pollution cap", "Hard-fail or warn if pointers per card &gt; 3"],
              ["sources[]", "Union of used source_ids with optional auxiliary_role metadata"],
            ]}
          />
          <H3>Validation hardening</H3>
          <Table
            headers={["Rule", "Severity"]}
            rows={[
              ["Wrong-zone tokens in currently", "hard-fail"],
              ["Location card fails zone relevance", "hard-fail"],
              ["Questline title in geography denylist", "hard-fail"],
              ["at_a_glance word count &gt; 45", "hard-fail"],
              ["Empty instance provenance on zone", "hard-fail (existing)"],
              ["Provenance pointer spam", "warn → hard-fail in slice 8"],
            ]}
          />
          <H3>Stub removal checklist</H3>
          <Table
            headers={["Stub", "Action"]}
            rows={[
              ["glossary_refs: [] in wiki_first draft", "Post-linker contract with full refs or draft-time placeholder rejected by validate"],
              ["parent_continent: unknown", "Infer from seed geography or explicit nullable + warn"],
              ["related_quest_chains: []", "Populate from quest clusters or remove from export schema"],
              ["Generic fallback sentences", "Remove; empty synthesis → hard-fail with actionable message"],
              ["check_pilot_semantics.py", "Full slice acceptance matrix"],
            ]}
          />
          <H3>Release gate</H3>
          <Text tone="secondary">
            validate_passed=true zone + instance · check_pilot_semantics.py pass · manual read matches golden examples ·
            no stub inventory rows remain open
          </Text>
        </Stack>
      </CollapsibleSection>

      <Divider />
      <H2>Workstream index (W1–W11)</H2>
      <Table
        headers={["ID", "Name", "Slice", "Primary files"]}
        rows={[
          ["W1", "Evidence scoping", "1", "enrich.py, wiki_first.py"],
          ["W2", "Section LLM workers", "3", "wiki_first_workers.py"],
          ["W3", "Storyline HTML + graph v3", "1", "storyline_html.py, storyline_parser.py"],
          ["W4", "Quest traverse + lore extract", "2", "traverse_wiki.py, quest_lore.py"],
          ["W5", "Questline cluster cards", "2", "wiki_first.py, wiki_first_workers.py"],
          ["W6", "Faction scoring", "4", "wiki_first.py, enrich.py"],
          ["W7", "Location guards", "5", "workflow.py, entity_typing.py, wiki_first.py"],
          ["W8", "Instance parity", "6", "wiki_first.py, wiki_first_workers.py"],
          ["W9", "Dynamic glossary", "7", "linker.py, build_bundle.py, new glossary stage"],
          ["W10", "Provenance + validation", "8", "validate/rules, linker.py"],
          ["W11", "Stub removal", "8", "Across draft + contracts"],
        ]}
      />

      <Divider />
      <H2>Pipeline stage map</H2>
      <Table
        headers={["Stage", "Slice changes"]}
        rows={[
          ["ingest / fetch_wiki", "Optional retain HTML snippet for storyline/quest parse; section role normalization"],
          ["traverse_wiki", "Quest URLs from v3; location denylist; instance_lore"],
          ["discovery / workflow", "Storyline targets; location candidate typing"],
          ["discovery / storyline_html + parser", "v3 graph; cluster model"],
          ["discovery / enrich", "Scoped evidence pools; quest_cluster_pool; glossary candidates"],
          ["draft / wiki_first + workers", "All section builders; instance parity; cluster cards"],
          ["linker", "Run-scoped terms; wiki_url on refs"],
          ["validate", "Content sanity + provenance caps"],
          ["addon / build_bundle", "Dynamic glossary lookup"],
          ["scripts/check_pilot_semantics.py", "Per-slice growing acceptance suite"],
        ]}
      />

      <Divider />
      <H2>Plan session template (copy per slice)</H2>
      <Callout tone="info" title="Before coding">
        <Stack gap={6}>
          <Text>1. Open this canvas → slice CollapsibleSection.</Text>
          <Text>2. List design forks only (max 3). If none, skip Plan mode.</Text>
          <Text>3. Write failing acceptance tests from slice table.</Text>
          <Text>4. Implement completely — no TODO stubs.</Text>
          <Text>5. uv run lore-pipeline run --run-id run-western-plaguelands --fact-check-profile off -v</Text>
          <Text>6. pytest + check_pilot_semantics.py</Text>
          <Text>7. Manual read against golden examples section.</Text>
          <Text>8. Mark slice completed in TodoList only when all checks pass.</Text>
        </Stack>
      </Callout>

      <Row gap={8}>
        <Pill tone="accent">Next action: Slice 2</Pill>
        <Pill tone="neutral">Pilot: run-western-plaguelands</Pill>
        <Pill tone="success">Backups: docs/planning/archive/</Pill>
      </Row>
    </Stack>
  );
}
