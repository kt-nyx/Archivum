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
    status: "pending" as const,
  },
  {
    id: "slice-i3",
    content: "Slice I3 — Role classification (off the uncertain default), dedupe, and significance ranking",
    status: "pending" as const,
  },
  {
    id: "slice-i4",
    content: "Slice I4 — Instance lore sourcing + cross-page traversal strategy",
    status: "pending" as const,
  },
  {
    id: "slice-i5",
    content: "Slice I5 — Prompting, generation, lint, semantics, and release-gate alignment (instance only)",
    status: "pending" as const,
  },
  {
    id: "slice-i6",
    content: "Slice I6 — Pilot fixtures, evaluation rubric, run playbook, and rollout",
    status: "pending" as const,
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
        </Stack>
      </CollapsibleSection>

      <CollapsibleSection title="Slice I3 — Role classification + significance" count={8}>
        <Stack gap={12}>
          <H3>Intent</H3>
          <Text>
            The role field already exists on the card (added in I1, defaulting to uncertain). I3 supplies the
            intelligence: classify each character's role accurately, dedupe aliases, and rank significance.
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

          <H3>Acceptance gate</H3>
          <Table
            headers={["Check", "Pass condition"]}
            rows={[
              ["No obvious role regressions", "Known allied or neutral figures are no longer forced into enemy-only output"],
              ["Deduping quality", "Boss/NPC duplicate rows collapse into one character entry"],
              ["Summary quality", "Each emitted character has a concise summary covering who they are + their role"],
            ]}
          />
        </Stack>
      </CollapsibleSection>

      <CollapsibleSection title="Slice I4 — Lore source traversal + fusion" count={9}>
        <Stack gap={12}>
          <H3>Intent</H3>
          <Text>
            Ensure instance lore generation draws from the best available evidence even when lore is split across
            instance pages, parent complexes, and related pages.
          </Text>

          <H3>Source ranking strategy</H3>
          <Table
            headers={["Source class", "Use when", "Priority"]}
            rows={[
              ["Instance page", "Has adequate lore sections and clear narrative density", "High"],
              ["Parent/complex page", "Instance page is sparse or mostly gameplay metadata", "High fallback"],
              ["Related linked pages", "Directly relevant and improves narrative completeness", "Selective"],
              ["Low-signal pages", "Mostly loot/achievements/mechanics with weak lore content", "De-prioritize"],
            ]}
          />

          <H3>Implementation tasks</H3>
          <Table
            headers={["Task", "Primary files", "Done when"]}
            rows={[
              ["Cross-page traversal policy", "source traversal logic", "Traversal graph has bounded depth and deterministic tie-breaks"],
              ["Lore density scorer", "evidence selection module", "Selection is based on signal, not hardcoded page type"],
              ["Fusion + provenance", "draft construction path", "Lore excerpts carry clean source_refs and no noisy duplication"],
            ]}
          />

          <H3>Acceptance gate</H3>
          <Table
            headers={["Check", "Pass condition"]}
            rows={[
              ["Sparse-page resilience", "Sparse instance pages still produce coherent lore with justified fallbacks"],
              ["Overreach control", "Traversal does not pull broad unrelated lore that dilutes instance narrative"],
              ["Provenance fidelity", "Merged lore claims remain source-traceable"],
            ]}
          />
        </Stack>
      </CollapsibleSection>

      <CollapsibleSection title="Slice I5 — Generation quality + gates" count={10}>
        <Stack gap={12}>
          <H3>Intent</H3>
          <Text>
            Lock instance-specific quality rules in prompts, lint, and semantics so promotion decisions are objective.
          </Text>

          <H3>Instance quality checks to add or tighten</H3>
          <Table
            headers={["Check", "Rule", "Severity"]}
            rows={[
              ["Character minimum", "If valid candidate pool exists, key_characters must be non-empty", "Fail"],
              ["Role diversity", "Do not emit enemy-only list when clear ally/neutral signal exists", "Warn/Fail"],
              ["Summary quality", "Character summary cannot be empty boilerplate", "Fail"],
              ["Lore density", "Overview/story sections cannot be raw passthrough fragments", "Fail"],
              ["Provenance cap", "Section and card provenance pointer counts stay within configured cap", "Warn/Fail"],
            ]}
          />

          <H3>Acceptance gate</H3>
          <Table
            headers={["Check", "Pass condition"]}
            rows={[
              ["Lint/semantics tests", "All new instance-specific checks are covered and green"],
              ["Pilot run behavior", "Known instance pain points are explicitly improved in output deltas"],
              ["Gate determinism", "Same input run yields same pass/fail state for release gate"],
            ]}
          />
        </Stack>
      </CollapsibleSection>

      <CollapsibleSection title="Slice I6 — Pilot validation + rollout" count={8}>
        <Stack gap={12}>
          <H3>Intent</H3>
          <Text>
            Run the new instance pipeline path in controlled promotion stages and finalize rollout checklist.
          </Text>

          <H3>Promotion flow</H3>
          <Table
            headers={["Stage", "Run target", "Purpose", "Exit criteria"]}
            rows={[
              ["Dev validation", "test-run-wpl-1", "Fast iteration + output inspection", "Instance checks green, manual quality review done"],
              ["Promotion validation", "run-western-plaguelands", "CI parity and release confidence", "Same checks green in promotion run"],
              ["Rollout", "default pipeline path", "Enable canonical behavior", "No unresolved blockers, docs/tests updated"],
            ]}
          />

          <H3>Acceptance gate</H3>
          <Table
            headers={["Check", "Pass condition"]}
            rows={[
              ["Pilot artifacts", "Before/after instance diffs archived with rationale"],
              ["Documentation", "Operational checklist updated for future instance work"],
              ["Final sign-off", "All slices complete with no deferred high-severity instance blockers"],
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
