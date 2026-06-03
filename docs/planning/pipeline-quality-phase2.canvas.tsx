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

const INSTANCE_SLICES = [
  {
    id: "slice-i0",
    content: "Slice I0 — Scope lock, contract strategy, compatibility guarantees",
    status: "completed" as const,
  },
  {
    id: "slice-i1",
    content: "Slice I1 — key_enemies -> key_characters clean rename (+ role, wiki_ref, decision_reason_codes)",
    status: "completed" as const,
  },
  {
    id: "slice-i2",
    content: "Slice I2 — Robust character extraction across wiki structure variants",
    status: "completed" as const,
  },
  {
    id: "slice-i2_5",
    content: "Slice I2.5 — Ingestion structure fidelity (list/table capture + structured-link accuracy)",
    status: "completed" as const,
  },
  {
    id: "slice-i3",
    content: "Slice I3 — Role classification (hybrid), redirect alias dedupe, and significance ranking",
    status: "completed" as const,
  },
  {
    id: "slice-i4",
    content: "Slice I4 — Instance lore sourcing + cross-page traversal strategy",
    status: "completed" as const,
  },
  {
    id: "slice-i5",
    content: "Slice I5 — Prompting, generation, lint, semantics, and release-gate alignment (instance only)",
    status: "completed" as const,
  },
  {
    id: "slice-i6",
    content: "Slice I6 — Pilot fixtures, evaluation rubric, run playbook, and rollout",
    status: "completed" as const,
  },
];

const MAJOR_WORK_ITEMS: Array<[string, string, string, string]> = [
  [
    "W-I1",
    "Data model migration",
    "key_enemies -> key_characters clean rename (no compatibility); add role, wiki_ref, decision_reason_codes",
    "schemas, contracts/models, validators, writers",
  ],
  [
    "W-I2",
    "Discovery normalization",
    "Handle Dungeon denizens, Denizens, Inhabitants, Encounters, Encounters by location, mixed tables/lists",
    "discovery extractors + section role mapping",
  ],
  [
    "W-I3",
    "Character intelligence",
    "Classify enemy/ally/neutral/uncertain; dedupe aliases; select high-signal cast",
    "instance extraction + ranking + linker touchpoints",
  ],
  [
    "W-I4",
    "Lore sourcing strategy",
    "Rank instance page vs parent/related page by lore signal and narrative relevance",
    "source traversal + evidence selection",
  ],
  [
    "W-I5",
    "Quality and gating",
    "Instance-specific lint, semantics checks, release gate criteria, deterministic acceptance table",
    "prose_lint, check_run_semantics, validate rules",
  ],
];

export default function InstanceMasterPlanCanvas() {
  return (
    <Stack gap={16}>
      <H1>Instance Pipeline Master Plan — Character + Lore Rewrite</H1>
      <Text tone="secondary">
        Active master plan for instance-specific work only. This plan replaces the previous mixed-quality canvas and
        is structured for one focused plan-mode session per major slice.
      </Text>

      <Row gap={12}>
        <Stat label="Program" value="Instance pipeline rewrite" tone="accent" />
        <Stat label="Scope" value="Instance entities only" tone="accent" />
        <Stat label="Primary migration" value="key_characters model" tone="warning" />
        <Stat label="Primary run target" value="test-run-wpl-1" tone="warning" />
        <Stat label="Promotion target" value="run-western-plaguelands" tone="warning" />
      </Row>

      <Callout tone="warning" title="Scope guardrails">
        <Stack gap={6}>
          <Text>In scope: instance character extraction, role modeling, instance lore sourcing, instance generation quality.</Text>
          <Text>
            Out of scope: zone storyline clustering, zone location coverage, zone history passthrough cleanup, and
            other deferred non-instance items (tracked separately in Reference notes).
          </Text>
          <Text>
            Rule: no bundling with unrelated fixes. Every slice must produce isolated, explainable output deltas.
          </Text>
        </Stack>
      </Callout>

      <Callout tone="info" title="Locked architecture decisions">
        <Stack gap={6}>
          <Text>
            Canonical output shifts to <Text weight="medium">key_characters</Text>, not key_enemies, to support
            hostile + allied + neutral narrative actors.
          </Text>
          <Text>
            Character harvest is multi-source and structure-tolerant: headings, encounter blocks, NPC/monster tables,
            and narrative sections.
          </Text>
          <Text>
            Lore selection is graph-based and score-driven; no fixed assumption that an instance page or parent page
            is always best.
          </Text>
        </Stack>
      </Callout>

      <TodoListCard todos={INSTANCE_SLICES} defaultExpanded />

      <Divider />
      <H2>Major Work Items</H2>
      <Table headers={["ID", "Work item", "Primary objective", "Main touchpoints"]} rows={MAJOR_WORK_ITEMS} />

      <Divider />
      <H2>Execution Order</H2>
      <Table
        headers={["Slice", "Depends on", "Can run in parallel", "Why order matters"]}
        rows={[
          ["I0", "—", "—", "Prevents rework by locking compatibility, naming, and acceptance criteria first"],
          ["I1", "I0", "—", "Schema and compatibility are prerequisite for downstream extraction/generation changes"],
          ["I2", "I1", "—", "Raw extraction must stabilize before role/ranking logic is meaningful"],
          ["I3", "I2", "—", "Role/significance model depends on normalized candidate pool"],
          ["I4", "I2", "I3 (partial)", "Lore traversal can start after normalization; final weighting needs role signals"],
          ["I5", "I1–I4", "—", "Quality gates must evaluate final behavior, not partial behavior"],
          ["I6", "I1–I5", "—", "Pilot reruns and promotion should only happen after full instance path is coherent"],
        ]}
      />

      <Divider />
      <H2>Plan-Mode Session Template</H2>
      <Callout tone="info" title="Use this template for each slice session">
        <Stack gap={6}>
          <Text>1. Confirm scope boundary for this slice (what is explicitly not changing).</Text>
          <Text>2. Define acceptance tests first (unit + run-level checks).</Text>
          <Text>3. List touched modules and contract changes.</Text>
          <Text>4. Define rollback strategy and compatibility behavior.</Text>
          <Text>5. Implement in smallest coherent commit-sized chunk.</Text>
          <Text>6. Run acceptance table and record pass/fail outcomes.</Text>
          <Text>7. Only then mark the slice complete and start next slice planning.</Text>
        </Stack>
      </Callout>

      <Divider />
      <H2>Slice Detail Blocks</H2>

      <CollapsibleSection title="Slice I0 — Scope lock + compatibility contract" count={7}>
        <Stack gap={12}>
          <H3>Intent</H3>
          <Text>
            Freeze the migration contract so all follow-up slices build on stable assumptions, especially around field
            names, validation behavior, and transitional read/write compatibility.
          </Text>

          <H3>Session outputs</H3>
          <Table
            headers={["Output", "Description"]}
            rows={[
              ["Migration RFC note", "Internal note defining key_characters canonical shape and transition timeline"],
              ["Compatibility policy", "Read old + new, write both or write canonical+derived (final decision locked)"],
              ["Acceptance matrix", "Clear expected behavior per stage: ingest, draft, validate, semantics"],
              ["Risk table", "Breaking risks and mitigations for schemas, fixtures, downstream consumers"],
            ]}
          />

          <H3>Acceptance gate</H3>
          <Table
            headers={["Check", "Pass condition"]}
            rows={[
              ["Decision lock", "No unresolved schema strategy questions"],
              ["Compatibility path", "One explicit transition mechanism documented"],
              ["Downstream impact", "List of all affected modules reviewed and signed off"],
            ]}
          />
        </Stack>
      </CollapsibleSection>

      <CollapsibleSection title="Slice I1 — key_characters migration" count={8}>
        <Stack gap={12}>
          <H3>Intent</H3>
          <Text>
            Replace enemy-only framing with character-centric modeling while preserving compatibility during
            transition.
          </Text>

          <H3>Model design (final)</H3>
          <Table
            headers={["Field", "Purpose", "Required"]}
            rows={[
              ["id", "Stable character id", "Yes"],
              ["name", "Character display name", "Yes"],
              ["summary", "User-facing: who they are + why they matter in the instance", "Yes"],
              ["role", "Filterable enum: enemy | ally | neutral | uncertain (default uncertain)", "Yes"],
              ["wiki_ref", "Canonical wiki link when available", "Optional"],
              ["decision_reason_codes", "Internal inclusion justification (mirrors LocationCard)", "Optional"],
              ["thumbnail_asset_id", "Asset reference", "Optional"],
            ]}
          />

          <H3>Implementation tasks</H3>
          <Table
            headers={["Task", "Primary files", "Done when"]}
            rows={[
              ["Schema update", "contracts/models + schema artifacts", "Instance contract validates key_characters"],
              ["Writer migration", "instance page builder", "Drafts emit key_characters with role + wiki_ref + decision_reason_codes"],
              ["Clean rename", "writer/validators/linker/glossary/semantics", "No key_enemies references remain (no compat layer)"],
              ["Validator updates", "validate payload rules", "Paths/messages say key_characters; enum enforced"],
              ["Fixture updates", "pilot + tests fixtures", "Fixtures represent canonical new shape"],
            ]}
          />

          <H3>Acceptance gate</H3>
          <Table
            headers={["Check", "Pass condition"]}
            rows={[
              ["Unit tests", "Model parsing/writing tests pass for the canonical key_characters form"],
              ["Draft output", "Instance drafts include non-empty key_characters (role defaults to uncertain, wiki_ref populated when available)"],
              ["Clean rewrite", "Zero key_enemies references remain across pipeline/scripts/tests/schemas"],
            ]}
          />
        </Stack>
      </CollapsibleSection>

      <CollapsibleSection title="Slice I2 — Structure-tolerant extraction" count={9}>
        <Stack gap={12}>
          <H3>Intent</H3>
          <Text>
            Normalize extraction across all observed Warcraft Wiki instance patterns so character harvesting no longer
            depends on one brittle heading format.
          </Text>

          <H3>Observed structure families to support</H3>
          <Table
            headers={["Family", "Examples", "Required extraction behavior"]}
            rows={[
              [
                "Dungeon denizens variants",
                "Dungeon denizens / Denizens / Inhabitants",
                "Capture bosses, NPCs, monsters even when nested by subregion",
              ],
              [
                "Encounter-first pages",
                "Encounters or Encounters by location",
                "Extract names from encounter blocks and location subheaders",
              ],
              [
                "Mixed tables and bullets",
                "Bosses|Monsters|NPCs table + bullet lists",
                "Union and dedupe names from both formats",
              ],
              [
                "Narrative-heavy pages",
                "Sparse denizens, rich story sections",
                "Fallback to narrative NER-like extraction path",
              ],
            ]}
          />

          <H3>Implementation tasks</H3>
          <Table
            headers={["Task", "Primary files", "Done when"]}
            rows={[
              ["Section canonicalizer", "discovery section-role mapper", "Variant headings map to stable internal roles"],
              ["List/table parser hardening", "instance extraction helpers", "Bullet + table content parsed together"],
              ["Location-subsection parser", "encounter block parser", "Subregion blocks no longer lose entries"],
              ["Narrative fallback", "text extraction path", "Pages with weak denizen blocks still yield candidates"],
            ]}
          />

          <H3>Acceptance gate</H3>
          <Table
            headers={["Check", "Pass condition"]}
            rows={[
              ["Fixture matrix", "Cross-structure fixtures pass (ICC, Ulduar, Scholomance-like, encounter-only pages)"],
              ["Coverage", "Candidate extraction rate no longer collapses to zero on known edge pages"],
              ["Determinism", "Repeated runs produce stable candidate sets for same inputs"],
            ]}
          />

          <H3>Outcome (shipped)</H3>
          <Text>
            Extraction is now structure-tolerant. Roster vocabulary expanded (inhabitants / notable / character / npc /
            monster); ingest records an additive parent_section_role so rosters nested under subregion subheadings are no
            longer lost; structured_links are scoped to roster-relevant roles (leaf or parent) for precision. A grounded
            narrative fallback fires only when roster sources yield nothing: a deterministic miner pulls person-like
            /wiki/ links from narrative sections (ranked by prose mention frequency, location/faction-filtered, capped),
            then an LLM selector picks the genuine key characters constrained to those links — with the deterministic
            ranking as the NO_LLM fallback so offline runs stay reproducible. Locked by a real-fetched cross-structure
            fixture matrix (ICC + Ulduar narrative fallback; Blackrock Depths roster + subregion-nested parent awareness)
            and an end-to-end build_instance_page wiring test. Role still defaults to uncertain (classification is I3).
          </Text>

          <H3>Review hardening (103-page survey)</H3>
          <Text>
            Surveyed 103 real instance pages across every expansion. Two structural gaps were found and fixed: the
            roster vocabulary missed an Inhabitants sub-role (added an `inhabit` token), and ~12% of pages produced zero
            candidates because their roster/lore lives in the page's eponymous lead bucket — the MediaWiki h1 title is
            slugified into a section role equal to the instance name (e.g. razorfen_kraul, halls_of_lightning,
            trial_of_the_crusader), which is neither roster nor narrative. The narrative fallback now recognizes that
            eponymous bucket (article/apostrophe/comma-insensitive slug match), taking the survey from 12 zero-candidate
            pages to 0 (final: 49 roster, 54 narrative-fallback, 0 zero) with the full suite still green.
          </Text>
        </Stack>
      </CollapsibleSection>

      <CollapsibleSection title="Slice I2.5 — Ingestion structure fidelity (shipped)" count={5}>
        <Stack gap={12}>
          <H3>Intent</H3>
          <Text>
            Fix the real ingest-layer root cause that starved instance rosters, so every downstream consumer (instances,
            zones, characters, factions) benefits and the instance narrative-fallback eponymous patch can be retired.
            Goal: section blocks faithfully represent the page's lead prose, lists, and tables. Fetch strategy is
            unchanged — ingest still uses the MediaWiki action=parse API; only the parser of the returned fragment changed.
          </Text>

          <Callout tone="warning">
            Premise correction: production ingest for warcraft_wiki uses the action=parse API, which returns a content
            fragment with no &lt;h1&gt; page title and no site chrome. The I2 "eponymous lead bucket" (h1 slugified into a
            section role) was an artifact of the review survey fetching full pages out-of-band; it does not occur in
            production. Verified across 52 parse-API instance pages: 0 had a section role equal to the instance slug. The
            genuine, reproducible gap is that rosters live in &lt;ul&gt;/&lt;li&gt; and &lt;table&gt; elements that the old
            BLOCK_RE (&lt;p&gt;/&lt;h*&gt; only) never captured.
          </Callout>

          <H3>Root cause (actual)</H3>
          <Table
            headers={["Cause", "Effect", "Where"]}
            rows={[
              [
                "Section walk captured only <p>/<h*>",
                "Boss rosters in <ul>/<li> and <table> (e.g. a 'Bosses' list + 'Encounters' table under 'Dungeon denizens', or the infobox boss collapsible) never became section blocks, so their links were scoped out and enrich boss_pool stayed empty",
                "fetch_wiki._extract_sections_and_links (BLOCK_RE loop)",
              ],
              [
                "First-match link role assignment",
                "A boss named in lead prose first (e.g. Loken) bound to 'lead' and was shadowed out of the roster path even though it also appeared under a 'Bosses' heading",
                "fetch_wiki.build_structured_links_from_sections",
              ],
            ]}
          />

          <H3>Implementation (shipped)</H3>
          <Table
            headers={["Change", "Primary files", "Result"]}
            rows={[
              [
                "Document-order section walk over <p>/<h*>/<li>/<td>/<th>",
                "fetch_wiki (SECTION_BLOCK_RE + _extract_sections_and_links)",
                "<ul>/<li> and content-table cells become section blocks with the correct section_role + parent_section_role",
              ],
              [
                "Chrome-table exclusion",
                "fetch_wiki (_strip_excluded_tables, nesting-aware)",
                "infobox/navbox/toc/metadata tables are removed before the walk, so they never pollute lead / at_a_glance",
              ],
              [
                "Multi-homed structured links",
                "fetch_wiki.build_structured_links_from_sections",
                "One entry per distinct (href, section_role); the roster collector keeps roster-roled entries even when a narrative section mentions the link earlier",
              ],
              [
                "Lead guard + retire eponymous patch",
                "fetch_wiki (h1 ignored as a section setter); instance_bosses.mine_narrative_character_candidates",
                "Stray h1 never overrides lead; eponymous-slug special-case and its test removed. Added a 'force' roster token (recovers scenario 'Forces' rosters, e.g. Culling of Stratholme)",
              ],
            ]}
          />

          <H3>Acceptance gate (met)</H3>
          <Table
            headers={["Check", "Result"]}
            rows={[
              ["Roster capture", "Halls of Lightning (Bjarngrim/Volkhan/Ionar/Loken) and Razorfen Kraul rosters now flow through the roster path from their real list/table blocks"],
              ["Parse-API sweep", "52 instance pages: 41 roster, 4 narrative-fallback; remaining zeros were redirect-title artifacts or a location-vs-dungeon article, not parsing gaps"],
              ["Eponymous retired", "0 production pages relied on the eponymous bucket; patch + test removed, full suite green"],
              ["No regression", "Live zone (Western Plaguelands) at_a_glance/history evidence still draws clean lead/history prose; infobox/navbox excluded"],
            ]}
          />
        </Stack>
      </CollapsibleSection>

      <CollapsibleSection title="Slice I3 — Role classification + significance (shipped)" count={8}>
        <Stack gap={12}>
          <H3>Intent</H3>
          <Text>
            The role field already exists on the card (added in I1, defaulting to uncertain). I3 supplies the
            intelligence: classify each character's role accurately, collapse redirect/title aliases, and rank
            significance instead of emitting an alphabetical cast.
          </Text>

          <H3>Decision framework</H3>
          <Table
            headers={["Dimension", "Signals", "Output"]}
            rows={[
              ["Role", "Section context + nearby descriptors + encounter framing", "role enum value (off the uncertain default)"],
              ["Significance", "Frequency + section weight + narrative centrality", "Ranking used to order/trim the cast"],
              ["Deduping", "Name normalization + wiki_ref + alias handling", "Single canonical entry per character"],
              ["Ordering", "Significance then narrative relevance", "Stable prioritized list"],
            ]}
          />

          <H3>Implementation (shipped)</H3>
          <Table
            headers={["Area", "What shipped"]}
            rows={[
              ["Hybrid role classifier", "Deterministic classify_character_role (section lean + per-character descriptor markers) in instance_bosses.py; LLM tiebreaker classify_key_character_role_llm (enum-constrained, openai-gated, deterministic fallback) in wiki_first_workers.py, called only when the heuristic is uncertain. Wired into _finalize_key_characters off the hardcoded uncertain."],
              ["Conservative by design", "force/faction rosters are not treated as hostile (Alliance + Scourge share one heading), and broad scourge/corruption words are excluded so ambiguous figures stay uncertain for the LLM rather than being mislabeled enemy."],
              ["Redirect alias dedupe", "New ingest network step (pipeline/ingest/wiki_redirects.py) resolves roster-link identity via action=query&redirects=1, annotating snapshot structured_links with canonical_path + page_id and writing data/ingest/wiki_redirect_map.json. collect_boss_candidates keys candidates by canonical identity (canonical_path -> href path -> title), collapsing redirect aliases (e.g. Caldoran -> Baelin_Caldoran)."],
              ["Significance ranking", "BossCandidate.significance = section weight + evidence depth + name mentions; replaces the alphabetical sort so marquee bosses (Loken, Sapphiron) lead the cast and the cap keeps the top-N."],
            ]}
          />

          <H3>Acceptance gate (met)</H3>
          <Table
            headers={["Check", "Result"]}
            rows={[
              ["No obvious role regressions", "Culling of Stratholme allies (Uther, Eris, townsfolk) fall to uncertain instead of enemy; pure-enemy dungeons (Halls of Lightning, Naxxramas) classify enemy"],
              ["Deduping quality", "Redirect/title aliases collapse to one canonical entry via ingest-resolved page identity; unit + live spot checks confirm"],
              ["Summary quality", "Each emitted character keeps the I1/I2 who+role summary path; classification adds a role:<value>:<reason> decision code for provenance"],
            ]}
          />
        </Stack>
      </CollapsibleSection>

      <CollapsibleSection title="Slice I4 — Lore source traversal + fusion (shipped)" count={9}>
        <Stack gap={12}>
          <H3>Intent</H3>
          <Text>
            Ensure instance lore generation draws from the best available evidence even when lore is split across
            instance pages, parent complexes, and related pages — without fusing tangential or Classic-version content.
          </Text>

          <H3>Locked decisions (this session)</H3>
          <Text>
            Hybrid B/C: one-hop parent-complex + related candidates, always-score (candidates fetched every run),
            strict attribution (cross-page prose must name the instance), and explicit exclusion of
            Classic/expansion-version pages.
          </Text>

          <H3>Implementation (shipped)</H3>
          <Table
            headers={["Area", "What shipped"]}
            rows={[
              ["Candidate enumeration", "New pipeline/discovery/lore_sources.py derives a bounded, deterministic candidate set from each instance's OWN page: parent-complex = a lead link corroborated by the infobox (wiki_links), capped to 1; related = history/lore prose links, capped to 3. Self, Classic-suffixed variants, noise, and character/faction links are filtered. Emits discovery/lore_traversal_targets.json and records the instance page's own lore density."],
              ["Always-score traversal", "run_traverse_seed fetches each candidate as parent_lore / related_lore auxiliary snapshots via the existing fetch path, with per-instance caps (parent<=1, related<=3), URL dedupe, a post-fetch retail-eligibility skip (drops Classic-only/other-game pages), and new _TRAVERSE_BLOCK_BY_ROLE entries so parent complexes (instance/zone-classified) are not blocked. Manifest aux enum extended."],
              ["Signal scorer", "pipeline/generate/draft/lore_selection.py scores instance vs cross-page lore by word volume + instance-name mention; replaces the zone-seed has_history proxy. Optional LLM relevance gate (classify_lore_relevance_llm, enum-constrained, openai-gated) rescues borderline parent context for sparse instances; deterministic NO_LLM fallback keeps related pages out."],
              ["Attribution-disciplined fusion", "enrich routes parent_lore/related_lore narrative blocks into parent_lore_pool/related_lore_pool with a lore_scope tag. build_instance_page fuses cross-page snippets into the overview ONLY when the instance is sparse and ONLY snippets that name the instance (mention gate); rich instances keep their exact prior pool (no regression). Dedup by normalized text; provenance pointers cite each source page+revision; lore_source flips to linked_lore_page (reason cross_page_fusion) only when a pointer actually cites a cross-page source."],
            ]}
          />

          <H3>Acceptance gate (met)</H3>
          <Table
            headers={["Check", "Result"]}
            rows={[
              ["Sparse-page resilience", "Sparse instance whose own page is a stub fuses parent-complex prose that names it; end-to-end test asserts a coherent overview + parent citation"],
              ["Overreach control", "Rich-instance test asserts a non-naming parent snippet is never fused and lore_source stays instance_page; mention-gating + Classic exclusion + caps bound the candidate set"],
              ["Provenance fidelity", "Every fused claim keeps source_id -> revision via existing pointer machinery; story_context provenance cites the originating page"],
            ]}
          />
        </Stack>
      </CollapsibleSection>

      <CollapsibleSection title="Slice I5 — Generation quality + gates (shipped)" count={10}>
        <Stack gap={12}>
          <H3>Intent</H3>
          <Text>
            Lock instance-specific quality rules across prompts, deterministic lint, semantics, and the release gate
            so promotion decisions are objective and reproducible.
          </Text>

          <H3>Locked decisions (this session)</H3>
          <Text>
            Full prompt work: unify Compendium Voice across all instance prompts and add a shared
            anti-passthrough / anti-meta clause. Role diversity FAILs only when an ally/neutral candidate inside the
            top-N ranked window is dropped from the emitted cast; WARN when the only ally/neutral signal is ranked
            outside the window.
          </Text>

          <H3>Implementation (shipped)</H3>
          <Table
            headers={["Area", "What shipped"]}
            rows={[
              ["Centralized config + shared roster", "INSTANCE_PROVENANCE_POINTER_CAP in contracts/models.py is the single source of truth for the provenance cap (validate + check_run_semantics). build_instance_key_character_roster() in wiki_first.py is the one deterministic roster builder shared by page assembly and the decision sidecar."],
              ["Compendium Voice unification + anti-passthrough", "compendium_voice.py adds INSTANCE_AT_A_GLANCE_VOICE / INSTANCE_OVERVIEW_VOICE / KEY_CHARACTER_VOICE / INSTANCE_FACTION_VOICE, a shared NO_META_NO_PASSTHROUGH clause, and an instance_system_prompt() builder. Instance overview, key-character, instance at-a-glance, and instance-scoped faction prompts route through it; zone prompts and classifier prompts unchanged; NO_LLM fallbacks unaffected."],
              ["Deterministic detectors", "instance_lint.py adds lint_passthrough_fragment (mid-sentence lowercase start, missing terminal punctuation, list-bullet residue) and assess_role_diversity (fail-on-dropped-in-window / warn-on-signal-only-outside). Passthrough lint wired into the overview + key-character finalize retry loops so drafts self-correct before the gate."],
              ["Release gate parity", "validate/rules/structure.py HARD_FAILs instance overview/history passthrough fragments and generic overview/key-character boilerplate; provenance.py reads the centralized cap (WARN default / HARD_FAIL at release gate)."],
              ["Semantics + decision sidecar", "draft_writer emits data/decisions/instance_key_character_decisions.json (full ranked roster + emitted flag). check_run_semantics consumes it for role-diversity (fail/warn), a pool-aware character minimum, and overview/history passthrough parity, all using the centralized cap."],
            ]}
          />

          <H3>Acceptance gate (met)</H3>
          <Table
            headers={["Check", "Result"]}
            rows={[
              ["Lint/semantics tests", "All five instance checks (character minimum, role diversity, summary boilerplate, passthrough, provenance cap) covered and green across instance_lint, validation engine, and check_run_semantics suites"],
              ["Flagged behaviors", "Enemy-only-with-dropped-ally FAILs; ally-only-outside-window WARNs; overview/history passthrough fragments and generic boilerplate HARD_FAIL at the gate and in semantics"],
              ["Gate determinism", "All new checks are pure functions of payload + sidecar; identical input yields identical pass/fail. Full pytest suite green; no new ruff violations in production source"],
            ]}
          />
        </Stack>
      </CollapsibleSection>

      <CollapsibleSection title="Slice I6 — Pilot validation + rollout (shipped)" count={9}>
        <Stack gap={12}>
          <H3>Intent</H3>
          <Text>
            Make instance pilot validation and promotion objective and repeatable: a deterministic
            evaluation rubric, a before/after run-diff archiver, a committed instance gold anchor, and
            a run playbook — all exercisable offline so the tooling is testable without OpenAI.
          </Text>

          <H3>Locked decisions (this session)</H3>
          <Text>
            Ship all four deliverables (run-diff tool, quality rubric, instance gold fixture + tests,
            refreshed playbook/docs) plus an offline/deterministic smoke path. The live pipeline run
            stays operator-driven (coalesce requires OpenAI); the slice ships no production pipeline
            code changes — only additive tooling, fixtures, tests, and docs.
          </Text>

          <H3>Promotion flow</H3>
          <Table
            headers={["Stage", "Run target", "Purpose", "Exit criteria"]}
            rows={[
              ["Dev validation", "test-run-wpl-1", "Fast iteration + output inspection", "Instance rubric clean, semantics + manual review done"],
              ["Promotion validation", "run-western-plaguelands", "CI parity and release confidence", "Rubric --gate clean, before/after diff archived"],
              ["Rollout", "default pipeline path", "Enable canonical behavior", "No unresolved blockers, docs/tests updated"],
            ]}
          />

          <H3>Implementation (shipped)</H3>
          <Table
            headers={["Area", "What shipped"]}
            rows={[
              ["Evaluation rubric", "scripts/instance_quality_report.py scores each instance_page draft PASS/WARN/FAIL by aggregating release-gate validate_payload + instance_lint detectors + pool-aware key-character minimum + assess_role_diversity (sidecar). Emits reports/instance_quality_report.{json,md}; exits non-zero on FAIL, and on WARN with --gate. Pure function of payload + sidecar."],
              ["Before/after diff", "scripts/diff_instance_runs.py compares two run roots' instance_page drafts + decision sidecars (at_a_glance, overview word delta, history count, key_characters added/removed/role changes, lore_source, provenance counts, emitted roster) and writes reports/instance_run_diff.{json,md} with an auto rationale per changed instance plus an optional --notes operator rationale."],
              ["Instance gold anchor", "tests/fixtures/pilot/instance_page_scholomance_gold.json (canonical InstancePage that passes the release gate + every detector) and instance_key_character_decisions_scholomance_gold.json (ranked roster sidecar). tests/test_instance_pilot_gold_standard.py asserts contract, release-gate pass, detectors, manifest alignment, and role diversity."],
              ["Offline smoke", "tests/test_instance_pilot_tooling.py builds synthetic baseline/candidate run trees from the fixtures and exercises both scripts (candidate PASS, degraded baseline FAIL, WARN-only --gate escalation, reported deltas, deterministic JSON) without network or OpenAI."],
              ["Docs + rollout", "New docs/planning/instance-pilot-rollout.md run playbook; pilot-promotion.md gains an instance gate step and fixes the stale key_enemies wording; tests/fixtures/pilot/README.md documents the instance gold layer."],
            ]}
          />

          <H3>Acceptance gate (met)</H3>
          <Table
            headers={["Check", "Result"]}
            rows={[
              ["Pilot artifacts", "Before/after instance diffs are archivable with rationale via diff_instance_runs.py (json + md, optional --notes); smoke test asserts overview/cast/roster deltas"],
              ["Evaluation rubric", "instance_quality_report.py scores PASS/WARN/FAIL deterministically; gold candidate PASSes and a degraded baseline FAILs in the offline smoke"],
              ["Documentation", "Instance run playbook added; pilot-promotion.md + pilot README refreshed for the instance path; canvas slice updated"],
              ["Final sign-off", "Full pytest suite green; no new ruff violations; no production pipeline code touched (additive tooling/fixtures/tests/docs only)"],
            ]}
          />
        </Stack>
      </CollapsibleSection>

      <Divider />
      <H2>Definition of Done (Program Level)</H2>
      <Table
        headers={["Area", "Done condition"]}
        rows={[
          ["Model", "key_characters is canonical and stable with migration compatibility"],
          ["Extraction", "Cross-structure pages produce robust candidate sets"],
          ["Quality", "Roles and significance are credible and narrative-focused"],
          ["Lore", "Source traversal yields complete, non-noisy instance lore"],
          ["Validation", "Instance-specific lint + semantics + release-gate checks are green"],
          ["Operations", "Pilot promotion path is repeatable and documented"],
        ]}
      />

      <Row gap={8}>
        <Pill tone="warning">Instance-only focus</Pill>
        <Pill tone="warning">One slice at a time</Pill>
        <Pill tone="neutral">Deferred non-instance issues tracked in Reference</Pill>
      </Row>
    </Stack>
  );
}
