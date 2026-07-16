# Build a LangSmith-First, Human-in-the-Loop Lore Development Workflow

You are building a UI-first local orchestration application for the iterative development, evaluation, and repair of the World of Warcraft Lore Companion pipeline. LangSmith Studio is the default primary UI unless a focused architecture spike proves that another existing UI is materially better for this use case and the human approves the change.

Read this entire request before acting. Then inspect the real repository and current machine state. Treat the repository facts below as orientation, not as permission to skip discovery. If the codebase contradicts this prompt, record the discrepancy and use the verified current behavior unless doing so would change the requested product direction; in that case, stop for a human decision.

The goal is not to create another lore-generation pipeline. The target repository already contains one, orchestrated internally with Prefect. The new application must orchestrate the higher-level development cycle around that pipeline: run selection and explicitly approved execution, artifact review, human issue triage, root-cause analysis, conversational solution selection, either plan-driven slices or a bounded small-fix lane, iterative self-review, commits, regression runs, and the next review cycle.

## Target repository and required nested-repository layout

The target project is:

```text
Z:\Development\WoW Addons\Lore Addon
```

The workflow application must live inside that directory, but it must be a separate Git repository and remain untracked by the outer Lore Addon repository.

Use this default layout unless discovery finds a concrete collision:

```text
Z:\Development\WoW Addons\Lore Addon\
  lore-workflow\                 # new nested Git repository
    .git\
    ... workflow source ...
  pipeline\                      # existing target pipeline
  Reference\                     # active and archived implementation plans
  artifacts\runs\               # existing immutable pipeline run roots
```

Before creating the nested repository:

1. Confirm that `lore-workflow\` does not already contain user work.
2. Add `/lore-workflow/` to the outer repository's local `.git/info/exclude`, not its tracked `.gitignore`. Do not duplicate the entry.
3. Verify with `git check-ignore -v lore-workflow` or an equivalent probe that the outer repository will ignore the directory.
4. Initialize a new Git repository inside `lore-workflow\`.
5. Verify that files committed in the nested repository do not appear in the outer repository's status.

Do not create a Git submodule. Do not add the nested repository to the outer index. Do not modify the outer repository merely to make the workflow easier unless a later, explicit human approval authorizes a target-project integration change.

The target path should be configurable, but the exact path above is the safe default for this machine. Normalize and validate Windows paths without lowercasing or string-concatenating them.

## Current machine snapshot to re-check

At the time this prompt was prepared:

- The machine was Windows with PowerShell.
- The target project used Python 3.12, `uv`, Pydantic, Typer, and Prefect 3.
- `codex exec` was available and supported non-interactive execution, JSONL events, a final-output schema, a final-message file, sandbox modes, a working-directory argument, and session resumption.
- `codex login status` reported `Logged in using ChatGPT`, and the common OpenAI/Anthropic/cloud-provider API credential environment variables checked during prompt preparation were absent.
- The `claude` executable was not on `PATH`, even though Claude Code may be available through an IDE extension or may be installed later.
- The `langgraph` CLI was not installed globally.
- The outer target worktree was not clean. Those particular edits may be gone or different when you begin.

Do not hard-code those observations as permanent capabilities. Build and run a doctor/capability probe that records executable paths, versions, subscription-auth/billing readiness where safely queryable, and the exact supported flags. Missing Claude Code or LangGraph tooling must produce an actionable status, not a fake adapter or an unexplained crash.

Discovery and read-only analysis may proceed against a dirty outer worktree, but capture the branch, HEAD, status, and diff summary so the analyzed revision is honest. No target-code implementation or commit may begin against unrelated dirty work. Local-only plan drafting may proceed, but it must not conceal, overwrite, stage, or absorb unrelated user changes. Never stash, reset, discard, overwrite, or absorb user changes automatically.

## Product boundary: outer workflow versus inner pipeline

Keep the two orchestration layers explicit:

```text
Lore development workflow (new; likely LangGraph)
  -> invokes and supervises complete pipeline runs
  -> invokes bounded coding/review agents
  -> pauses for human decisions
  -> persists cycle, issue, root-cause, plan, and slice state

Lore content pipeline (existing; Prefect)
  -> ingest
  -> discovery and traversal
  -> coalesce/extract
  -> discovery enrichment
  -> draft
  -> glossary/linker
  -> validation
  -> addon bundle
```

Do not replace Prefect, wrap every Prefect stage in a second graph node, or reimplement stage retry behavior. At the workflow layer, one pipeline invocation is a supervised external job with captured run identity, process state, output, exit status, and artifact references. The existing stage manifests and trace log remain the source of truth for inner-pipeline progress.

## Existing target-project facts that must shape the implementation

Verify these in the repository before relying on them:

- The package and CLI entrypoint are declared in `pyproject.toml`; the main CLI is `lore-pipeline`.
- `pipeline/orchestrator/flow.py` owns the existing Prefect flow.
- Run contexts live under `artifacts/runs/<run_id>/` unless `WOW_LORE_ARTIFACTS_ROOT` overrides the runs root.
- Complete runs are immutable. Existing run IDs with stage manifests must not be silently reused or overwritten.
- `.vscode/run-incrementing-pipeline.py` creates the next numbered run in a family, copies the latest suitable `source_manifest.json` (or a seed manifest for a new family), and launches the full pipeline.
- The common strict run settings are `--fact-check-profile strict`, `--release-gate`, and usually `--verbose`.
- `scripts/check_run_semantics.py <run-root> --strict --quality-summary` performs the machine-readable semantic gate and writes `reports/run_quality_summary.json` when requested.
- `evaluation/pilot_matrix.json` currently defines Western Plaguelands + Scholomance, Desolace + Maraudon, and a Westfall + Deadmines hold-out. These are evaluation subjects, not allowed sources of runtime special cases.
- Useful review surfaces include:
  - `data/drafts/`
  - `data/decisions/`
  - `data/discovery/`
  - `data/evidence/`
  - `reports/validate/`
  - `reports/run_quality_summary.json`
  - `traces/manifests/`
  - `traces/stage_trace.jsonl`
  - `build/lua/`
- `Reference/` is ignored by the outer repository's `.gitignore`. Development plan documents are intentionally local-only agent context: every new active plan, archived plan, revision, and implementation record created by this workflow must remain untracked and uncommitted. Discovery may find historically force-added tracked plans; treat those as legacy anomalies requiring an explicit migration decision, never as precedent for force-adding another plan.
- The reliable verification form in this checkout has often been `uv run --no-sync ...`, because a plain environment sync/build can fail on the project's intentional direct-reference dependency. Re-probe rather than assuming this has been fixed.

Do not infer success from process exit alone. A reviewable run must have the expected stage manifests, draft artifacts, validation results, and semantic-quality report for the requested profile. Distinguish all of the following:

- pipeline process completed;
- validation passed;
- strict release gate passed;
- semantic quality summary passed;
- intended change is visible in artifacts;
- no unrelated global regression was found;
- human editorial review approved the result.

These are separate facts and must be stored separately.

## Non-negotiable subscription-only billing boundary

There are two different kinds of model usage. Do not conflate them.

1. The existing lore-generation pipeline uses its existing provider configuration, including its current OpenAI-backed synthesis and optional fact checking. Running that pipeline may require `OPENAI_API_KEY` from the target repository's existing local environment. Do not redesign this as part of the workflow project.
2. Every coding, analysis, planning, and review agent launched by the new workflow must use the user's included Codex or Claude Code subscription allowance through an authenticated first-party local CLI. This is a hard invariant, not a default preference.

The orchestration agent layer must never:

- call the OpenAI, Anthropic, Bedrock, Vertex, Foundry, or another model API directly;
- accept an API key as an agent credential;
- fall back from subscription authentication to API-key or cloud-provider authentication;
- consume purchased Codex credits, Claude usage credits/extra usage, or any other pay-as-you-go overflow after included subscription allowance is exhausted;
- enable or recommend auto top-up, usage credits, API billing, or a paid overflow path;
- silently switch providers, credentials, accounts, models, or billing modes to keep a task running;
- expose an "upgrade", "buy credits", "use API", or "continue with paid usage" action in the normal workflow UI.

Codex must be authenticated with the user's ChatGPT subscription identity. Claude Code must be authenticated with the user's Claude subscription identity. Probe the installed tools for their current auth-status facilities and record only a normalized billing mode such as `chatgpt_subscription`, `claude_subscription`, `api_key`, `cloud_provider`, or `unknown`; never store tokens or raw credential material.

Before every agent subprocess, construct a clean environment from an explicit allowlist and remove model-billing variables even if the parent process contains them. At minimum, account for `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, Bedrock/AWS credentials and routing flags, Vertex/Google credentials and routing flags, and Foundry/Azure credentials and routing flags. The exact denylist must be capability-probed and kept current. If subscription auth cannot be positively established, the task enters `billing_mode_unsafe` and does not invoke a model.

Paid overflow can also be enabled at the vendor-account level without appearing as an environment variable. The setup/doctor flow must therefore:

1. Explain how to disable Codex flexible credits/auto top-up and Claude usage credits/extra usage in the current account UI.
2. Verify those settings programmatically if an official read-only mechanism exists.
3. Where no official verification mechanism exists, require a dated human attestation that paid overflow is disabled, display the unverifiable boundary clearly, and require renewal of that attestation after a configurable interval or relevant auth/tool change.
4. Refuse unattended agent execution when the billing mode or paid-overflow state is unknown.

This subscription-only rule applies to the new development agents. The target lore pipeline's existing OpenAI synthesis/fact-check calls are a separate, pre-existing cost boundary and must use a separate supervised environment. Never leak or reuse the pipeline's `OPENAI_API_KEY` in a Codex/Claude agent subprocess. Show pipeline API execution separately in the UI so the user is never misled about which work is covered by coding-agent subscriptions.

The workflow may inherit the minimum environment needed by a supervised target-pipeline command, but it must never copy secret values into workflow state, prompts, reports, traces, snapshots, subprocess metadata, or Git. Store variable names and redacted presence/absence only.

### Subscription quota exhaustion is a resumable wait state

Included subscription allowances may be limited by rolling session windows, weekly windows, model-specific windows, or other provider-defined periods. Do not hard-code one vendor's current limit schedule. Detect current signals and normalize them.

When an agent reports that included usage is approaching exhaustion, exhausted, or unavailable until a reset:

1. Stop launching new tasks for that provider.
2. Do not retry the request, poll by making model calls, or fall back to paid credits/API usage.
3. Persist the rendered prompt, input hashes, captured structured events, partial output, provider session ID, target Git/process reconciliation state, and the last safe workflow checkpoint.
4. Parse and store the reset time/window when the provider supplies one, along with the raw redacted evidence artifact.
5. Transition the task and graph to a non-failure status such as `waiting_for_subscription_quota` with a `resume_not_before` value when known.
6. Surface the pause clearly in the primary UI: affected provider, interrupted task, saved progress, reset time/countdown if known, and the safe resume behavior.
7. Present a durable human decision prompt whose primary choices are `wait_for_same_provider` and `handoff_to_other_provider`, plus cancel/defer. Never choose automatically.
8. If the human chooses `wait_for_same_provider`, checkpoint the decision and enter a quiescent `waiting_for_subscription_quota` state that launches no process and makes no model call. It must be safe to close the browser, stop the workflow server, shut down the machine, and resume the same workflow hours or days later from the local database and artifacts.
9. If the human chooses `handoff_to_other_provider`, show the proposed provider and a compact provider-neutral handoff bundle, require confirmation, independently pass the other provider's subscription-only preflight, and start a new provider session without duplicating completed side effects. Preserve the original provider session for audit/recovery; never silently replace it.
10. On any later resume, first reconcile Git/process/filesystem state and rerun the chosen provider's subscription/billing preflight. Continue the saved provider session when supported, or start a new task with the smallest sufficient recovery context when it is not. An optional local no-model scheduler may make the UI resumable at `resume_not_before`, but it must not invoke a provider or advance a consequential node without the configured human action.

Treat five-hour, weekly, monthly/Agent-SDK, model-specific, and generic plan-cap messages as possible subscription quota classes. Distinguish them from context-window exhaustion, temporary server throttling, network failure, invalid authentication, schema-invalid output, and API-key rate-limit/credit errors. An API-key 429 or low-credit message is evidence of an unsafe billing mode, not a subscription wait to retry.

If output indicates that usage is "continuing with credits", paid overflow is active, an API credit balance is being used, or a dollar/token charge applies, terminate the agent process as safely as possible, enter `billing_safety_violation`, preserve evidence, and require human remediation. Do not make another model call during that recovery.

### Minimize consumption of included allowance

Subscription-included usage is still scarce. Design for useful work per agent invocation:

- use deterministic code for file discovery, hashing, schema validation, Git inspection, artifact indexing, diffs, and test execution;
- cache repository discovery and artifact summaries by Git SHA/config/artifact hashes;
- send minimal context manifests instead of whole run trees or workflow state;
- do not use model calls for status polling, routing, formatting, or tasks a deterministic function can perform;
- avoid speculative parallel agent calls and redundant independent reviews beyond the approved risk policy;
- reuse the same session within the same bounded task, fix, or slice when continuation saves context, while preserving the required fresh context between plan slices;
- apply bounded schema-repair and review loops, then pause for human input rather than burning allowance indefinitely;
- show estimated call count/task fan-out before a phase that will launch multiple agents and require approval for unusually expensive fan-out.

LangSmith is a third, separate concern, but its UI is the default operator experience for this project. Build LangSmith Studio-first: the human should normally start, observe, interrupt, discuss, correct, approve, and resume the workflow from the UI while the graph and supervised processes run locally. A conversational pane is essential, not optional: at review and decision points the human must be able to ask what a finding means, challenge an assumption, compare tradeoffs, add constraints, and request revisions in natural language while seeing the structured artifact under discussion. Detect and explain the LangSmith account/API-key requirement during setup, keep secrets out of state and traces, and make remote tracing explicitly configurable and redacted. A LangSmith key is only an access credential for the UI/tracing integration; it must never be reused for model execution, and no paid LangSmith service may be enabled without explicit approval.

The local CLI remains a supported recovery, automation, and diagnostic fallback; it is not the primary UX. Durable workflow truth must still live in the local checkpoint database and immutable local artifacts so a Studio outage, browser refresh, or tracing failure cannot corrupt or erase a cycle. Never imply that `langgraph dev`'s development server is the durable production state store.

## Architectural direction and required spike

Use Python and strongly prefer LangGraph for the high-level state machine, because durable conditional transitions, human interrupts, and LangSmith Studio graph visualization fit this workflow. LangSmith Studio is the presumed UI choice. However, do not commit the full implementation to that UI before completing a small architecture spike.

The spike must assess Studio against this use case, not merely prove that it can render a graph. The UI must make it easy to understand the current phase, active node, completed and pending phases, selected runs, issue/root-cause/solution counts, active lane and slice/fix, latest agent task, verification state, pending human decision, and links to relevant reports. It must support practical human input for triage, corrections, approvals, and resume actions without requiring the user to decipher raw checkpoint JSON. It must also prove a usable conversational pane or equivalent interaction bound to the current cycle and artifact, with visible conversation history and an explicit way to apply a proposed conversational revision to canonical structured state.

If Studio cannot meet those needs cleanly, especially the conversational pane, evaluate a more suitable existing UI before proposing custom frontend work. Any alternate UI must preserve LangGraph state/interrupt semantics or provide an equally durable integration, run locally on Windows, visualize the workflow and history, combine structured human-decision forms with artifact-scoped conversation, link to local artifacts, and resume safely after restart. Replacing Studio as the primary UI requires an ADR with a concrete comparison and human approval.

The spike must prove, on Windows:

1. A typed graph can pause for a human decision and resume after the process is restarted.
2. State is durably checkpointed outside an in-memory development server.
3. A node can supervise a long-running child process, stream output to files, record the child identity, enforce a timeout, and cancel the Windows process tree safely.
4. A fake structured agent adapter can be invoked without shell-string interpolation.
5. A real read-only Codex probe can return schema-valid structured output without editing the target repository.
6. Re-entering a side-effecting node after a crash does not duplicate a pipeline run, local-only plan publication, Git commit, or agent task.
7. Studio can display the real graph, compact human-readable state, node progress, streamed/custom progress events for long-running work, and a human interrupt that can be edited and resumed.
8. A browser refresh and workflow-process restart preserve the pending decision and run history.
9. The same graph remains recoverable and operable from a CLI if the UI is unavailable.
10. Subscription authentication is positively identified, API credentials are scrubbed from agent subprocesses, and an unsafe/unknown billing mode blocks invocation before any model request.
11. Fake Codex and Claude processes that emit representative five-hour, weekly, monthly/model-specific, paid-credit, API-rate-limit, and context-limit signals transition to the correct durable states without an automatic model retry.
12. A quota-paused task presents wait-versus-handoff choices, survives full UI/workflow-process shutdown in the wait state, and later resumes from its saved session/context after a simulated reset without duplicating edits, commands, or commits.
13. The primary UI can host an artifact-scoped conversation, turn a free-form requested adjustment into a visible proposed structured change, and require explicit apply/approval before canonical state advances.
14. The UI can attach to an already-running pipeline without launching a duplicate, and a launch form can collect and preview the custom run prefix/name and existing helper options but cannot start the process before a separate explicit approval.
15. Sandboxed execution is the default, the effective command/write/network policy is visible, and an unrestricted profile can be selected only through an explicit persisted human approval.

If the spike exposes a material LangGraph or Studio limitation, write an ADR comparing the narrow alternatives and stop for approval before replacing either. Do not quietly substitute a home-grown state machine or custom frontend.

Use a local durable database/checkpointer suitable for one user, such as SQLite, plus immutable human-readable artifacts. Define ownership clearly: the database owns transition/checkpoint state; the filesystem owns reports, prompts, captured agent events, decisions, and references to target artifacts. Provide backup and schema-migration behavior from the start.

## The real human workflow to formalize

Model the following as a repeatable cycle. A cycle may begin by attaching existing run roots, attaching and monitoring an already-running pipeline process, or preparing an explicitly approved new run. Every cycle links to its predecessor and preserves prior evidence.

### Phase A: establish the evidence set

1. Select one or more zone/instance run families or explicit existing run IDs.
2. Record the baseline revision, run roots, source manifests, settings, model/prompt identifiers, and quality summaries.
3. If requested, prepare fresh immutable numbered runs through the existing helper rather than fabricating run directories or overwriting old runs. Preparation is not launch authorization.
4. Run the strict semantic gate/quality-summary command after each complete run.
5. Collect an artifact manifest by reference. Do not duplicate entire crawl trees when stable absolute/relative paths plus hashes are sufficient.

Support at least these target-set modes:

- a user-selected single run family;
- selected zone/instance pairs;
- the repository's current pilot matrix;
- the full pilot matrix including the hold-out;
- attach-only review of existing run roots.

The primary UI must provide both:

- **Attach/monitor**: attach existing completed run roots or discover and attach a currently running pipeline. Attaching must reconcile the run ID, run root, PID/process tree when knowable, manifests, and latest stage trace before monitoring. Do not assume ownership of, cancel, or restart an externally launched process unless the human explicitly adopts that control.
- **Prepare and launch**: a launch form modeled on `.vscode/launch.json` and `.vscode/run-incrementing-pipeline.py`. It must support a custom `run_prefix`/run name like `Pipeline: full run (custom prefix)`, preview the next derived immutable run ID, and expose the verified helper inputs such as `base_run_id`, `seed_manifest`, fact-check profile/options, concurrency, retries, verbosity, and release gate. Prefer safe presets for known pilot configurations while allowing a custom prefix.

Every new LIVE pipeline launch is a consequential, potentially API-billed action. The workflow may prepare and validate a launch specification, but it must interrupt immediately before process creation and show the exact redacted command/argument array, derived run ID, manifest source, environment-key presence, settings, expected evaluation subjects, and cost warning. Only a specific human `approve_launch` action may start it. A plan's `[LIVE]` marker, a regression phase, a scheduled resume, or an agent recommendation is never sufficient authorization by itself. Approval is single-use for the displayed specification; any material change requires reapproval.

Once approved and launched from the UI, stream visible process and stage progress, elapsed time, run ID, logs, and cancellation controls. Cancellation must be explicit and must not declare the run successful. The workflow must not assume that every development slice or bounded fix needs an expensive live run; `[LIVE]` requirements and the human's approval determine when execution occurs.

### Phase B: agent output review plus human observations

Run a read-only artifact-review agent with a bounded prompt and an explicit artifact budget. It must inspect final drafts, selection/decision sidecars, validation reports, semantic-quality summaries, and relevant traces. It should sample source/evidence records when a claim requires verification rather than reviewing prose in isolation.

The agent must look for at least:

- incorrect, irrelevant, missing, or low-value cards;
- unsupported or relation-reversed claims;
- current-state/history/spoiler framing errors;
- questline identity, title, faction/phase, ordering, or CTA defects;
- character/faction/location admission mistakes;
- thin coverage hidden by otherwise valid output;
- schema/decision/provenance inconsistencies;
- generic-writing quality issues and repetitive output;
- differences from a comparable baseline run that are not explained by source, settings, model, prompt, or code changes.

Then interrupt for the human to add observations, examples, and preferred outcomes. Preserve agent findings and human findings separately while also building a normalized combined issue set. Human comments are evidence and requirements, not automatically verified root causes.

### Phase C: issue triage

New issues begin as `untriaged`. Interrupt for the human to classify any issue they are ready to decide as:

- `investigate_now`
- `defer`
- `disregard`
- `duplicate`
- `needs_clarification`

Allow edits, splitting, merging, and cross-links. The human may select only a subset for `investigate_now` and proceed without exhaustively classifying every finding. Unselected findings remain durably `untriaged` in the cycle backlog and can be revisited later; they do not silently enter root-cause work. Nothing marked `defer` or `disregard` enters the active root-cause task unless the human explicitly restores it. Preserve the reason and author for every triage decision.

### Phase D: root-cause investigation

Invoke a fresh read-only agent task for only the `investigate_now` issues. It must inspect artifacts, logs, intermediate decision records, source code, tests, and Git history as needed.

The investigation must:

1. Identify the earliest stage where each defect becomes observable.
2. Distinguish a bad input/source fact, selection/ranking defect, cross-stage contract defect, synthesis defect, validation blind spot, stale artifact, or review misunderstanding.
3. Group multiple symptoms under a shared root cause only when evidence supports a shared mechanism.
4. Separate verified causes from hypotheses.
5. Cite concrete artifact paths, record IDs, code locations, test gaps, and relevant values.
6. State the scope across card families, stages, and zones/instances.
7. Rank causes by severity and breadth, not by the order issues were reported.
8. Describe disconfirming evidence and what additional check would resolve uncertainty.
9. Remain read-only. Root-cause investigation is not authorization to patch code.

Interrupt for human correction and approval of the root-cause grouping before generating solutions. The interrupt must support a conversational explanation/revision loop, not just accept/reject buttons.

### Phase E: solution options and selection

Generate multiple materially different options when they exist. Each option must include:

- the mechanism it changes;
- why it addresses the verified cause;
- affected producers, consumers, artifacts, schemas, tests, validators, and docs;
- benefits and limitations;
- generalization/overfitting risk;
- effect on other card families or pipeline stages;
- clean-break versus compatibility implications;
- test strategy and live-evaluation strategy;
- prerequisites and approximate implementation scope;
- failure modes and rollback considerations.

Reject patches that add zone-, instance-, title-, quest-, character-, race-, species-, or pilot-specific exceptions to shared runtime logic. Pilot names are allowed in evaluation configuration and fixtures, not as behavior authority. If the human intentionally wants a content-specific exception, require a separate explicit approval with the rationale recorded.

Interrupt for the human to select, combine, modify, reject, or defer options. Keep the discussion conversational: the human must be able to ask what terminology means, challenge whether a mechanism is too brittle, add compatibility or clean-break constraints, ask for another option, and request a revised comparison. A model response may propose structured changes, but only an explicit human apply/approval action changes the selected solution state.

### Choose an implementation lane

After root causes and solutions are approved, interrupt for the human to choose one of two first-class lanes:

1. `plan_slices` for changes with multiple dependent steps, broad/cross-cutting scope, public/schema/serialization contract changes, architectural decisions, or work that needs a durable multi-slice handoff.
2. `bounded_fix` for a narrow approved correction that should still receive the workflow's preflight, implementation, review/fix/re-review, verification, commit, audit, and optional LIVE acceptance controls without creating or replacing a full plan document.

Recommend a lane from evidence but let the human decide. The bounded-fix lane may start from a directly reported targeted issue and need not force a full artifact-review cycle first, but it must still capture the issue, verify the root cause, record the approved solution and non-goals, and obtain implementation approval. Generate a concise local fix brief inside the workflow run with scope, affected files/contracts, acceptance criteria, tests, LIVE posture, permissions, and stop conditions.

A bounded fix must automatically stop and offer conversion to `plan_slices` if investigation or implementation reveals dependent slices, broad architectural work, an unapproved public/schema/serialization contract change, significant scope growth, or a need to weaken tests/evaluators. Do not use the fast lane to smuggle a large change through lighter review. A completed bounded fix normally produces one focused target-code commit plus workflow-local records; it never requires a `Reference\` plan or plan-record commit.

### Phase F: plan-driven lane - drafting, review, local archival, and publication

Generate the implementation plan first as a workflow-run draft. Do not immediately replace the active target-project plan.

The plan must be self-contained enough that a fresh coding agent with only the target repository and the plan can implement a slice correctly. Match the useful conventions in the current active recovery plan rather than inventing a generic ticket list.

At minimum, the plan needs:

- purpose and problem statement;
- verified root causes and linked issue IDs;
- approved decisions;
- verified architecture and relevant code/artifact locations;
- explicit non-goals;
- common implementation rules;
- cross-cutting guardrails;
- clean-break/compatibility posture;
- generalization constraints;
- exact verification posture;
- risks and rollback/recovery behavior;
- dependency-ordered implementation slices;
- completion checklist;
- append-only implementation record template.

Every slice must contain:

- stable identifier and title;
- goal and why it is needed;
- dependency IDs and recommended order;
- verified facts versus assumptions to re-check;
- likely code, schema, artifact, test, evaluator, and documentation areas;
- required investigation before editing;
- full implementation requirements;
- producer/consumer and clean-break contract obligations;
- behavioral invariants;
- generic and adversarial tests to add/update;
- targeted checks, full checks, and `[LIVE]` acceptance when applicable;
- artifact-level acceptance criteria;
- forbidden shortcuts;
- review-cycle requirements;
- stop/escalation conditions;
- expected implementation-record fields.

Order slices topologically. Prefer slices that leave the repository coherent and independently reviewable. Do not defer one side of a schema or serialization change to a later slice. Do not include migration/backward-compatibility layers unless an actual consumer requires them and the human approves that requirement.

Interrupt for iterative plan review. The human may ask questions, correct assumptions, or request revisions multiple times through the conversational pane. Keep every draft and comment. A conversational response proposes a revision; publish only an explicitly applied and approved revision.

When publishing the approved local-only plan:

1. Discover the current active Markdown plan directly under `Reference\` rather than guessing from a filename or status line.
2. Show the exact proposed old-path -> legacy-path and draft-path -> active-path changes.
3. Preserve the old local plan under `Reference\legacy\` with a collision-safe descriptive name.
4. Verify with `git check-ignore` and `git ls-files` that every destination plan path is ignored and untracked before writing or moving it.
5. Never run `git add`, `git add -f`, `git mv`, or create a commit for an active plan, legacy plan, plan revision, or implementation record. These files are deliberately local-only development context.
6. If an active or legacy plan path is historically tracked, do not modify, move, remove from the index, or archive it automatically. Stop with a clear migration proposal; proceed only after the human chooses how to establish an untracked local-only active plan without damaging history or unrelated work.
7. Never delete old plans.
8. Record content hashes, paths, ignore/tracking proofs, and target Git state before and after publication in workflow-local state.

Local plan publication/archive is a consequential filesystem action and requires a human gate, but it must never create or alter a target-project commit.

### Phase G: sequential implementation-slice loop

Implement one slice at a time in dependency order. A "fresh agent per slice" is a hard requirement: do not continue the implementation conversation/session from a prior slice. Within one slice, keep the same implementation session for implementation, self-review, and focused repair follow-ups so it can efficiently reason about its own complete change. A bounded fix is one bounded implementation task and may likewise keep one session through its review cycle.

The default should be sequential work on the human-approved active target branch, because later slices depend on earlier commits. Do not introduce Git worktrees as mandatory infrastructure. Worktrees may be an opt-in future strategy for genuinely independent slices after their merge/rebase policy is designed and approved.

Before each slice can edit:

1. Read the complete active plan, target slice, common rules, cross-cutting guardrails, dependency slices, and implementation records for completed prerequisites.
2. Verify the plan's assertions against the current code and artifacts.
3. Capture outer branch, HEAD, status, ignored-plan state, and recent commits.
4. Require a clean target worktree, except for an exact predeclared set already owned by this slice. Default to stopping rather than adopting unexplained changes.
5. Confirm prerequisite implementation commits are ancestors of HEAD and that their local plan implementation records/hashes agree with workflow state.
6. Confirm that no other implementation slice is active.
7. Capture the nested workflow repository's HEAD and status. A target-editing agent is forbidden from changing `lore-workflow\`; any nested-repository change during a slice is a stop condition and must not be silently reverted.

The slice agent must implement the whole slice, not a partial workaround. It must update all in-repo producers, consumers, schemas, artifacts, validators, tests, and documentation owned by the changed contract. Tests should be synthetic and adversarial where possible, not frozen copies of pilot prose or subject-specific exceptions.

#### Required review cycle

"Review cycle" means more than running tests once. The mandatory default is an iterative same-agent self-review cycle:

```text
implement
  -> run targeted deterministic checks
  -> inspect the complete diff and semantic behavior
  -> self-review against the plan/fix brief and prior human decisions
  -> classify self-review findings
  -> repair actionable findings
  -> rerun affected checks
  -> self-review the revised complete diff again
  -> run the final required verification surface
```

Repeat repair and self-review until no actionable findings remain. To keep automation bounded, use a configurable review budget with a conservative default such as three repair rounds. Reaching the budget is not success: interrupt the human with the unresolved findings and allow an explicit extension, plan correction, scope change, or stop. Also interrupt when the same defect recurs, scope expands, the plan/fix brief is wrong, a dependency change is needed, a schema/public contract change was not approved, a test/evaluator would be weakened, or a content-specific rule is proposed.

A separate fresh reviewer is not part of every slice by default. Launch one only when:

- the human explicitly requests independent review;
- the work is explicitly classified and confirmed as high risk, such as a broad public/schema/serialization contract change, security/credential/permission boundary, destructive/recovery behavior, or similarly consequential cross-cutting change; or
- Phase H performs the fresh final regression/editorial review after the complete implementation set.

Because an independent reviewer consumes another subscription call, show the reason, provider, context scope, and estimated call cost/fan-out before launch. The reviewer must use a separate fresh session and remain read-only. Its actionable findings return to the original slice/fix implementation session for repair when resumable, followed by deterministic checks, same-agent re-review, and—if still required—another bounded independent pass. Never spawn independent reviewers speculatively or merely to satisfy a ritual.

Do not use agent confidence as the only acceptance criterion. A slice is acceptable only when:

- plan/fix-brief requirements and acceptance criteria are accounted for;
- required deterministic checks pass;
- diff and semantic review find no remaining actionable issue;
- no unrelated user changes were absorbed;
- required live artifacts demonstrate the intended behavior, if the slice is `[LIVE]`;
- any genuine deferral is generic, explicit, and human-approved.

Use the target plan's commands when specified. Otherwise derive the verification surface from repository conventions. The normal baseline is:

```text
uv run --no-sync ruff check <relevant scopes>
uv run --no-sync mypy pipeline
uv run --no-sync pytest <targeted tests>
git diff --check
uv run --no-sync pytest -q
```

Do not hard-code a pass count. Record exact commands, exit codes, and summarized results from the current run. If an existing failure is claimed, verify it against the pre-slice baseline and record evidence; do not casually relabel new failures as pre-existing.

#### Slice/fix commits and local implementation records

After implementation and review pass:

1. Propose and show the focused target-code commit, create it under the workflow's commit policy, and record its SHA.
2. For a plan slice, append the dated implementation record to the ignored, untracked active plan, including the implementation SHA, exact checks, fresh run IDs where applicable, intentional behavior changes, and genuinely deferred generic follow-up. Record the resulting plan content hash and record location in workflow state. Never stage or commit this plan update.
3. For a bounded fix, write the equivalent closeout data to the workflow-local fix record; no `Reference\` plan update is required.

Do not mark the slice/fix complete until the single focused implementation commit exists, required local metadata and hashes are stored, every plan path remains ignored and untracked, and the target Git worktree is otherwise clean. Never create a plan-record commit. Never amend, rebase, reset, push, merge, or open a pull request unless that operation is separately enabled and approved. Commit messages should be proposed and shown before execution.

### Phase H: regression runs and the next cycle

After all approved slices are complete:

1. Prepare fresh immutable regression runs for the human-selected evaluation set, normally including the relevant pilot pairs and the hold-out when full acceptance is requested, and launch each exact specification only through the Phase A LIVE-run approval gate.
2. Apply identical strict settings across subjects unless an explicit experiment says otherwise.
3. Run semantic quality summaries.
4. Compare candidate runs to the correct baselines while surfacing source hashes, manifest identity, code revision, settings, schema versions, and model/prompt identifiers before attributing differences to code.
5. Invoke a fresh read-only review agent that has no implementation-session carryover.
6. Interrupt for final human editorial review.

The likely result is another issue set. Do not overwrite the completed cycle or mutate its approved decisions. Create a new linked cycle whose baselines point to the just-completed candidate runs and whose issues may reference prior issue/root-cause IDs.

## State and artifact model

Use typed, versioned schemas. Keep large target artifacts out of checkpoint state. State should hold IDs, statuses, hashes, small structured decisions, and artifact references.

At minimum, model these concepts explicitly:

- workflow project/schema version;
- workflow run and cycle IDs;
- created/updated timestamps;
- target repository path;
- target branch, HEAD, dirty-state snapshot, and relevant commit ancestry;
- selected evaluation subjects/run families;
- pipeline invocation specification, custom run prefix/name, derived run ID, launch approval identity/specification hash, ownership/adoption status, and environment-key allowlist;
- baseline and candidate run references;
- pipeline process and completion status;
- stage/validation/release/semantic status;
- artifact manifests and hashes;
- agent task IDs, provider, role, capability snapshot, prompt version, response schema version, session ID, exit status, and artifact paths;
- normalized agent authentication/billing mode, paid-overflow attestation/verification state, provider allowance state, quota-window class, reset time, `resume_not_before`, and billing-safety evidence;
- normalized issues and source observations, including durable `untriaged` backlog membership;
- triage decisions;
- root causes and issue memberships;
- solution options and selections;
- artifact-scoped conversation threads, turns, proposed structured changes, and explicit apply/reject decisions;
- selected implementation lane and lane rationale;
- plan drafts, comments, approval, local-only published target path, ignore/tracking proofs, and hashes;
- bounded-fix briefs and closeout records;
- plan slices and dependency graph;
- active slice lease/status;
- effective execution profile, sandbox/allowlist policy, per-task permission decisions, and unrestricted-approval record;
- verification command records;
- review findings and repair rounds;
- implementation commits and local plan/fix record revisions/hashes;
- regression comparisons;
- human decisions;
- errors, retry counters, quota-wait records, cancellation records, and resumability tokens;
- terminal workflow/cycle status.

Also maintain a compact, typed UI projection designed for Studio (or the approved alternate UI). It should summarize phase progress, active work, the most recent meaningful event, pending decision, available human actions, result counts, warnings, and artifact/report links. Keep this projection small and human-readable; do not force the operator to inspect the full internal state to understand the run.

Every consequential transition should be append-only in an event/audit log even if a current-state projection is also maintained.

Suggested workflow-run layout:

```text
runs/
  <workflow-run-id>/
    run.json
    events.jsonl
    config.snapshot.json
    target-state/
    pipeline-runs/
      references.json
      processes/
      manifests/
    reviews/
    issues/
    root-causes/
    solutions/
    conversations/
    plans/
    fixes/
    slices/
      <slice-id>/
        preflight/
        prompts/
        agent-events/
        verification/
        reviews/
        implementation.json
    decisions/
    comparisons/
    logs/
```

Use immutable or revisioned files for prompts, agent responses, reports, and human decisions. Redact secrets before writing. Never overwrite a prior pipeline run or workflow cycle.

The nested repository's `.gitignore` must exclude workflow run directories, local databases and journals, `.env` files, captured logs/events that may contain local paths, caches, and virtual environments. Commit schemas, migrations, redacted examples, and test fixtures instead of live run state.

## Idempotency, leases, and crash recovery

Durable checkpoints are not enough. Every side-effecting action needs an idempotency key and a reconciliation routine.

Cover at least:

- pipeline launch;
- semantic-gate launch;
- agent task launch;
- subscription quota hold/resume;
- plan archive/publish;
- slice lease acquisition;
- Git commit creation;
- plan-record append;
- cancellation and cleanup.

On resume after a crash, inspect the external system before retrying. Examples:

- If a pipeline process may still be alive, inspect the recorded PID/process tree and run artifacts before launching another run.
- If an agent command exited after writing a valid response artifact, consume it rather than repeating the task.
- If an agent stopped for subscription quota, preserve its session/partial artifacts and wait; do not launch a probe request or replacement task merely to see whether the limit reset.
- If a commit may have succeeded, verify HEAD and commit metadata before issuing another commit.
- If local-only plan publication partially completed, compare hashes, paths, ignore status, and tracking status and interrupt rather than guessing.

Use one active-slice lease so two workflow processes cannot edit the target repository concurrently. Include stale-lease inspection and a human-confirmed recovery command.

## Agent adapter contract

Create a provider-neutral interface, but implement only adapters that can be honestly exercised.

The first usable adapter should be `CodexCliAgent`. Add `ClaudeCodeCliAgent` when the executable and supported non-interactive behavior are available. A missing adapter is `unavailable`, not silently mapped to another provider. Neither adapter may run until the shared subscription-only policy and its provider-specific auth/quota classifier pass.

Each adapter must support or explicitly report lack of support for:

- executable/version/capability probing;
- authenticated-readiness and normalized billing-mode probing without exposing credentials;
- explicit rejection of API-key/cloud-provider auth and unknown billing mode;
- agent-subprocess environment construction that strips model API credentials while leaving the separate pipeline environment untouched;
- subscription quota warning/exhaustion classification, reset-time extraction, durable wait-state creation, and safe continuation;
- paid-credit/extra-usage detection as a billing-safety violation;
- prompt from a versioned file or stdin;
- target working directory;
- read-only, sandboxed-writable, and explicitly approved unrestricted task modes;
- argument-array subprocess execution without `shell=True` or interpolated command strings;
- environment allowlist plus an effective command/write/network policy;
- timeout, cancellation, and Windows process-tree termination;
- streamed stdout/stderr or structured events captured separately;
- schema-constrained final output where supported;
- final response capture;
- exit status and failure classification;
- session ID capture and same-slice continuation where supported;
- model/profile selection where supported;
- log redaction;
- dry-run display of the exact redacted invocation.

Execution permissions are a separate concern from billing authentication. Implement three explicit profiles:

1. `read_only_sandbox` for discovery, artifact review, root-cause work, solution discussion, plan review, and independent review.
2. `workspace_write_sandbox` as the default for implementation, with writes constrained to the target workspace and an enforceable command policy. Seed the allowlist from verified project needs: read-only Git inspection; `rg` and safe file inspection; `uv run --no-sync` invocations for known project CLIs/scripts; targeted/full pytest, Ruff, MyPy, and `git diff --check`; and narrowly defined build/format commands. Keep commit creation, plan publication, pipeline launch, destructive Git, process control, and permission changes in deterministic orchestrator nodes rather than delegating them to an agent shell. Network is off unless the task explicitly needs it and the human enables it.
3. `unrestricted` as an opt-in profile selectable from the primary UI for a specific task or cycle. Before launch, show a prominent warning, the exact adapter flags/permission mode, affected working directory, network posture, and the fact that the agent may gain broad machine access. Require a persisted explicit approval. Reset to a sandboxed profile for each new cycle unless the human deliberately saves a narrower scoped preference; never silently inherit unrestricted mode.

Enforce the sandbox and allowlist outside the model prompt using the strongest verified vendor/OS mechanism available. Treat prompt text as guidance, not a security boundary. Match commands as parsed argument arrays or typed command capabilities, not shell substrings. If the selected sandbox policy cannot be enforced with the installed adapter, stop with an actionable UI decision: install/enable the needed mechanism, further restrict the task, or explicitly opt into unrestricted mode. Never quietly claim sandboxing that is not real.

For Codex, probe the installed `codex exec --help` and auth-status command instead of assuming flags. Require ChatGPT subscription authentication. Prefer structured-output and JSONL facilities when present. Use a read-only sandbox for analysis/review tasks and a workspace-writable sandbox for approved implementation tasks. Dangerous/full-access bypass flags are permitted only when the human selected and approved the visible `unrestricted` profile for that invocation. Treat included-plan exhaustion as a pause and prohibit Codex credits/flexible pay-as-you-go continuation.

For Claude Code, probe `claude --help`, its auth-status command, print mode, structured output, permission modes, hooks/settings policy, session behavior, and current subscription-automation allowance when installed. Require Claude subscription authentication and strip `ANTHROPIC_API_KEY` plus cloud-provider routing credentials. Use permission rules/hooks or another verified enforcement layer for the sandboxed profiles. A bypass-permissions mode is permitted only for a specifically approved `unrestricted` invocation. Do not assume the IDE extension exposes a callable CLI. Do not install or authenticate tools without an explicit human action. Treat plan/Agent-SDK allowance exhaustion as a pause and prohibit usage-credit/extra-usage continuation.

Do not implement direct API-backed agent adapters, even as an inactive fallback. A future request to add one would contradict this product's billing invariant and requires an explicit change to this requirement, not a configuration toggle.

## Prompt and response contracts

Store prompts as versioned template files and responses as versioned JSON Schemas/Pydantic models. Do not bury long prompts in graph-node code.

Provide templates for at least:

- repository discovery;
- artifact review;
- issue normalization;
- root-cause investigation;
- solution generation;
- conversational explanation/revision of the current review or decision artifact;
- plan generation/revision;
- bounded-fix brief generation/revision;
- slice assumption verification and preflight;
- slice implementation;
- same-agent self-review and repair;
- risk-triggered or explicitly requested independent slice/fix review;
- repair follow-up;
- regression comparison review;
- final editorial review.

Each rendered prompt must state:

- role and bounded objective;
- exact permitted and forbidden actions;
- working directory;
- available input artifact paths and why each was selected;
- whether code edits, commands, Git changes, network, or live pipeline runs are allowed;
- selected execution profile and the effective sandbox, command, write, and network policy;
- relevant plan requirements and human decisions;
- expected output schema;
- evidence/citation requirements;
- stop and escalation conditions.

Do not dump the complete workflow state or every pipeline artifact into every prompt. Build small, reproducible context manifests. Record the rendered prompt hash and all input artifact hashes.

## LangSmith-first UI and human interrupts

LangSmith Studio is the primary control and comprehension surface. Design graph names, node names, state fields, interrupt payloads, and progress events for a human following the workflow visually. The UI should answer, at a glance:

- Where am I in the overall development cycle?
- What is running now, and for how long?
- Which pipeline runs, issues, root causes, solutions, plan revision, and slice are in scope?
- Am I in the plan-slices lane or bounded-fix lane, and what remains before implementation/closeout?
- What completed successfully, failed, or is waiting?
- Which subscription provider is available, approaching/exhausted, or waiting for reset, and when is safe resume possible?
- What evidence/report should I inspect next?
- What decision is required from me, what are the available actions, and what will each action do?
- Which execution profile is active, what can the agent run/write/access, and how can I explicitly opt into or back out of unrestricted mode?

Use explicit graph structure and concise state summaries rather than a single opaque node that internally performs most of the workflow. Long-running pipeline and agent nodes must surface progress through supported streaming/custom events and durable log/report links. Do not flood Studio state with raw subprocess output or enormous artifacts.

Quota exhaustion must appear as an intentional paused/waiting state, not a red failure node and not a hung process. The UI must clearly state that no API billing or paid credits will be used, show the provider's reset evidence/time when known, and provide no paid-continuation action. It must prompt the human to choose `wait_for_same_provider` or a confirmed `handoff_to_other_provider`. The wait view must explicitly say that the workflow can now be shut down safely and later reopened, and it must provide a resume action that restores the same pending task from durable local state.

Provide an artifact-scoped conversational pane alongside structured state and decision controls. It must:

- bind each thread to a cycle, phase, current artifact revision, and provider session/task;
- let the human ask follow-up questions, request explanations, add observations/constraints, and ask for adjustments without leaving the workflow UI;
- show the relevant finding/root-cause/solution/plan/fix artifact next to the conversation;
- preserve turns and references durably across browser/server restart;
- distinguish discussion from canonical workflow state;
- turn requested adjustments into a visible structured proposal/diff where applicable; and
- require explicit `apply`, `approve`, or `reject` actions before a conversational suggestion changes triage, root causes, solution selection, plan/fix text, scope, permissions, or execution.

Conversational turns are agent calls and therefore must pass the subscription-only preflight, show provider/quota state, and pause with the same wait/handoff behavior if allowance is exhausted. Do not make background conversational calls merely to summarize UI state.

Provide a pipeline panel that can list/attach completed runs, discover/attach running processes, and prepare new runs. The prepare form must include the custom run prefix/name and verified launch-helper settings, preview the next immutable run ID and manifest source, and keep the launch button disabled until validation succeeds. Clicking launch must first open a separate approval interrupt for the exact specification; it must never directly create the run/process. Once launched, show live logs/stage progress and an explicit cancel control.

Provide a permissions panel before every agent task. Default it to the appropriate sandboxed profile, show the effective allowlisted capabilities and any requested additions, and offer an explicit unrestricted option with a strong warning. Record the human's choice in the task audit trail and make returning to sandboxed mode easy.

Human interrupts should render structured, editable payloads suitable for Studio forms. When a decision involves many issues or options, provide both a compact summary in state and a durable detailed artifact, with stable IDs linking the two. Verify the actual Studio rendering during the architecture spike and each milestone; do not assume a theoretically valid schema produces a usable UI.

The local CLI is the fallback control surface for recovery, scripting, diagnostics, and situations where Studio is unavailable. It must operate on the same checkpoints and decision schemas, never a separate workflow implementation.

Provide fallback CLI commands or equivalent functionality for:

- `doctor` - capability, path, version, subscription-auth/billing safety, paid-overflow attestation, quota state, database, and target-repo checks;
- `start` - create a workflow run/cycle;
- `status` - concise phase, pending decision, active process, and artifact summary;
- `inspect` - open or print the relevant report/decision context;
- `chat` - add a conversational turn to the current artifact-scoped thread and display any proposed structured change without auto-applying it;
- `answer` or `resume` - submit a human decision and continue;
- `pipeline attach` - attach a completed run root or reconcile/monitor an already-running pipeline without launching another;
- `pipeline prepare` - validate and preview a named/prefixed launch specification without starting it;
- `pipeline approve-launch` - approve and launch only the exact prepared specification, with an interactive confirmation unless a separate secure approval token is supplied;
- `permissions` - inspect or choose the effective sandboxed/unrestricted profile through the same decision schema as the UI;
- `cancel` - safely cancel a supervised process without declaring success;
- `recover` - reconcile stale processes/leases after interruption;
- `runs` - list prior workflow cycles and linked target run IDs;
- `export` - create a redacted, portable run summary without copying huge target artifacts.

Every interrupt must display:

- why the workflow stopped;
- the relevant report paths and a concise summary;
- allowed decisions;
- consequences of each decision;
- editable comments/corrections;
- the exact action that resume will perform.

Human input must be validated and durably stored before the graph advances. A process restart must not lose a pending interrupt.

## Safety rules for the target repository

- Preserve user changes.
- Never use destructive Git recovery commands automatically.
- Never clean or delete historic pipeline runs.
- Never overwrite an existing run ID.
- Never launch any LIVE target pipeline run without a single-use explicit approval for the exact displayed specification, even when a plan marks it `[LIVE]` or a regression node expects it.
- Never duplicate a pipeline process when attaching to a run that may still be active, and never assume cancellation ownership over an externally launched process without explicit adoption.
- Never start two target-editing agents concurrently.
- Never let a read-only analysis node silently edit files.
- Never let a target-project agent modify the nested workflow repository; verify both repositories independently after every agent task.
- Never commit secrets, workflow-local state, generated pipeline artifacts, or the nested repository into the outer repository.
- Never stage or commit active plans, archived plans, plan revisions, or plan implementation records under `Reference\`; verify they remain ignored and untracked.
- Never force-push, push, merge, rebase, amend, reset, open a PR, or modify remotes without an explicit separately recorded approval.
- Never weaken/remove a test or evaluator merely to get a pass without a human gate.
- Never introduce subject-specific runtime logic to repair a pilot output.
- Never call a slice complete just because a retry/review budget is exhausted.
- Never claim a live acceptance result unless a fresh run and the relevant artifact inspection actually completed.
- Never launch a Codex/Claude agent unless subscription authentication and the paid-overflow guard pass immediately beforehand.
- Never use API keys, provider cloud credentials, Codex credits, Claude usage credits/extra usage, auto top-up, or pay-as-you-go fallback for orchestration agents.
- Never retry, poll with model calls, or silently switch providers after subscription quota exhaustion.
- Never run an agent unrestricted by default. Unrestricted execution requires a visible, task/cycle-scoped, persisted human approval; billing credential scrubbing and all no-paid-overflow rules still apply in that mode.

## Required tests for the workflow repository

Build deterministic tests around fakes before relying on live agents or expensive pipeline runs.

At minimum, test:

- graph transition and conditional-edge coverage;
- every human interrupt and resume path;
- artifact-scoped conversational turns, structured revision proposals, explicit apply/reject, and conversation recovery after restart;
- Studio-facing input/state schema rendering for every interrupt type;
- compact UI projection updates across success, failure, cancellation, and pending-decision states;
- streamed/custom progress events for supervised long-running jobs;
- Studio reconnect/browser-refresh behavior against a persisted pending interrupt;
- restart/resume from durable checkpoints;
- schema migration or clear refusal on incompatible state;
- event-log consistency;
- idempotent side-effect reconciliation;
- duplicate pipeline-run prevention;
- attach/reconcile of an already-running external pipeline without duplicate launch or implicit process ownership;
- custom run-prefix/name validation, next-ID preview, launch-specification hashing, single-use approval, reapproval after edits, and denial of every unapproved LIVE launch path;
- duplicate agent-task prevention;
- duplicate commit prevention;
- Windows paths containing spaces;
- subprocess argument safety and absence of shell interpolation;
- timeout and Windows process-tree cancellation;
- environment allowlisting and secret redaction;
- API-key/cloud-provider environment scrubbing for agent subprocesses without stripping the separate target-pipeline environment;
- positive recognition of ChatGPT-subscription and Claude-subscription auth plus refusal of API/unknown modes;
- account-level paid-overflow attestation expiry and renewal;
- representative five-hour, weekly, monthly/Agent-SDK, and model-specific subscription-limit messages;
- reset-time parsing, wait-versus-handoff UI decisions, quiescent `waiting_for_subscription_quota`, full process shutdown/restart while waiting, manual resume, provider-neutral handoff, and optional no-model scheduled readiness;
- paid-credit/extra-usage continuation signals causing `billing_safety_violation` with zero automatic retry;
- API-key 429/low-credit signals classified as unsafe billing rather than plan exhaustion;
- context-window, network, auth, server-throttle, schema, and subscription-quota errors remaining distinct;
- fake Codex/Claude structured event parsing;
- invalid/truncated agent output;
- dirty target-worktree handling;
- ignored-and-untracked `Reference` plan enforcement, proof that publication/records are never staged or committed, and safe refusal/migration prompts for historically tracked plans;
- active-plan discovery and collision-safe archival;
- plan-slices versus bounded-fix routing, direct targeted-fix entry, fast-lane closeout, and escalation to plan slices when scope grows;
- slice dependency ordering;
- single-active-slice lease behavior;
- mandatory same-agent self-review/repair loops, independent-review launch only for confirmed high risk/final review/explicit request, review budget exhaustion, and human extension;
- read-only and workspace-write sandbox enforcement, parsed command allowlisting, network controls, visible effective permissions, explicit unrestricted opt-in, and reset to a sandboxed default;
- target process still running during recovery;
- partially completed local-only plan publication;
- target commit succeeded but checkpoint write failed;
- attach-only review of an existing pipeline run;
- pipeline success with missing semantic-quality summary;
- clear separation of process, validation, release-gate, semantic, agent-review, and human-review statuses.

Use temporary fake Git repositories and fake run trees in tests. Do not point unit tests at the real target checkout. Keep live Codex, Claude, and full pipeline smoke tests opt-in. Studio integration is part of the product's primary UX, so include a repeatable local Studio smoke-test procedure in every milestone and automate the underlying graph/API assertions where browser automation is impractical.

## Implementation milestones

Build in vertical, reviewable milestones. Commit each milestone in the nested workflow repository after its own review cycle.

### Milestone 0: discovery and architecture proof

Deliver:

- `discovery.md` grounded in the current target repository;
- capability/doctor report for this machine;
- verified subscription-only policy enforcement, including current Codex auth mode, Claude availability/auth mode, scrubbed agent environments, and the manual/automatic status of paid-overflow guards;
- ADR for the outer-workflow/inner-Prefect boundary;
- ADR for LangGraph persistence and the LangSmith-first UI, including the UI suitability criteria and any evaluated alternatives;
- the architecture spike and tests;
- a working Studio view of the spike with understandable node names, progress state, one structured human interrupt, and resume after restart;
- a usable artifact-scoped conversational pane/equivalent that can propose but not silently apply a structured revision;
- a Studio-visible simulated quota pause with wait/handoff choices, full workflow-process shutdown/restart while waiting, safe resume, no automatic provider retry, and no paid fallback;
- a fake pipeline attach plus named/prefixed launch preview whose process cannot start until the exact launch specification is approved;
- visible default sandbox/allowlist policy plus an audited unrestricted opt-in using only fake agents;
- proposed typed state and artifact schemas;
- a list of any requested target-project integration changes, with none applied.

Stop for human review of the architecture before expanding it.

### Milestone 1: analysis loop

Implement a real end-to-end path for:

```text
create cycle
  -> attach pipeline run(s) or prepare + explicitly approve launch
  -> semantic quality summary
  -> agent artifact review
  -> human issue input
  -> triage
  -> root-cause investigation
  -> human root-cause approval
  -> solution generation
  -> human solution selection
  -> choose plan-slices or bounded-fix lane
  -> plan draft/revision/approval or bounded-fix brief/approval
```

Publishing an ignored, untracked local-only plan into `Reference\` may remain an explicitly gated final step, but it must not be faked or committed. The normal decision points must be usable conversationally, not only through static forms.

### Milestone 2: one complete implementation slice

Implement the complete lifecycle for one human-approved slice:

- preflight and assertion verification;
- fresh implementation agent;
- targeted checks;
- same-agent self-review/repair/re-review;
- independent review only when the fake task is marked high risk or the human explicitly requests it;
- full required checks;
- implementation commit;
- ignored/untracked local plan implementation-record update and hash, with no second commit;
- clean-worktree closeout.

Also exercise the bounded-fix path through the same implementation/review/verification/one-commit closeout without creating a `Reference\` plan. Exercise both first with a harmless fixture/fake target repository. Do not choose a real Lore Addon slice or fix for the first mutation without a separate human approval.

### Milestone 3: full sequential plan and regression cycle

Add dependency-ordered multiple slices, optional live acceptance per slice, regression matrix execution, baseline comparison, fresh final review, and creation of the next linked cycle.

Do not build a custom web frontend in these milestones unless the Studio suitability spike demonstrates a material gap, an ADR compares existing alternatives, and the human explicitly approves that scope. Do not add cloud deployment, multi-user authorization, parallel slice merges, autonomous pushing/PRs, or direct model APIs unless separately approved.

## Initial discovery requirements

Before significant implementation, inspect and document:

- outer repository branch, HEAD, status, ignored/untracked plan intent, any historically tracked plan anomalies, and target-code commit conventions;
- root instructions and agent guidance files, if present;
- `README.md`, `pyproject.toml`, `.gitignore`, and `.git/info/exclude`;
- the complete active `Reference\*.md` plan and relevant legacy plan conventions, without staging or committing them;
- `.vscode\run-incrementing-pipeline.py` and launch configurations, especially `Pipeline: full run (custom prefix)` and every supported helper argument;
- `pipeline/orchestrator/flow.py`, `pipeline/common/run_context.py`, and relevant CLI entrypoints;
- `evaluation/pilot_matrix.json` and `evaluation/README.md`;
- `scripts/check_run_semantics.py` and run-quality-summary generation;
- at least one recent complete run tree and one incomplete/failed run if available;
- actual verification commands and the current `uv --no-sync` behavior;
- installed Codex, Claude Code, LangGraph, Git, and Python capabilities;
- enforceable Codex/Claude sandbox, permission-rule/hook, command-policy, network, and unrestricted-mode capabilities on this Windows machine;
- current Codex/Claude authentication mode, official subscription-automation constraints, included-allowance signals, reset behavior, and paid-overflow controls;
- LangSmith account/key readiness, local Studio connection behavior, and tracing/redaction configuration;
- current official documentation for any CLI flags or LangGraph/Studio behavior you plan to depend on.

The discovery report must clearly label:

- verified current facts;
- design choices made for the workflow;
- assumptions still requiring a spike or human decision;
- discrepancies from this prompt;
- risks caused by the current dirty worktree or missing executables.

Do not make broad target-project changes during discovery.

## Definition of done

The workflow is not done merely because a graph renders in Studio or a happy-path demo runs once. It is done when:

- the nested repository is independently versioned and ignored by the outer repository;
- LangSmith Studio is a usable primary operator surface that clearly shows phase/node progress, current scope, pending work, failures, evidence links, and human decisions;
- the human can perform the normal start/inspect/discuss/adjust/interrupt/correct/approve/resume cycle from the UI without reading raw checkpoint JSON;
- the conversational pane is artifact-scoped, durable, and can propose revisions while requiring explicit application before canonical workflow state changes;
- every orchestration agent invocation is positively verified as subscription-authenticated with API/cloud credentials removed;
- account-level paid overflow is disabled or covered by an explicit current attestation when it cannot be checked programmatically;
- subscription limit exhaustion pauses durably, preserves partial work, prompts for wait versus provider handoff, survives complete UI/workflow shutdown while waiting, and resumes without API/credit fallback or duplicate side effects;
- long-running pipeline and agent work exposes understandable progress rather than appearing as an unexplained frozen node;
- the local CLI can recover, inspect, and resume the same workflow when Studio is unavailable;
- durable state survives process restarts;
- side effects reconcile safely after crashes;
- the UI can attach completed or running pipelines without duplication, and every new LIVE launch uses the existing immutable run mechanism/Prefect flow only after single-use approval of the exact custom-name/prefix specification;
- analysis remains read-only until an approved implementation phase;
- human observations and decisions are first-class durable artifacts;
- root causes group symptoms with concrete evidence and uncertainty;
- the workflow supports both dependency-ordered plan slices and a bounded-fix lane that escalates safely when scope grows;
- plans match the project's active-plan and slice conventions while remaining ignored, untracked, local-only agent context;
- each plan slice uses a fresh agent context and every slice/fix completes a same-agent review/fix/re-review cycle;
- fresh independent reviewers are used only for confirmed high-risk work, final regression review, or explicit human requests;
- each slice/fix has one focused implementation commit, while plan/fix implementation records remain local and uncommitted with recorded hashes;
- sandboxed execution with visible allowlisted capabilities is the default, and unrestricted execution is available only through an explicit audited UI choice;
- strict semantic gates and human editorial review remain distinct;
- a new regression cycle can link to, but never overwrite, the previous one;
- unit/integration tests cover interruption, recovery, Windows subprocesses, Git safety, and ignored plan files;
- documentation explains setup, doctor output, common commands, state/artifact locations, recovery, backups, redaction, and known limitations;
- no secret or unrelated target-project change has been committed.

## How to begin

Start with read-only discovery. Return a concise discovery summary, proposed nested-repository scaffold, architecture diagram, Studio-first operator-flow outline, conversational-pane and structured-interrupt UI outline, named LIVE-run approval flow, execution-permission profiles, state model, milestone plan, and explicit open decisions. Then create the nested repository and Milestone 0 only after confirming that the proposed structure does not collide with existing user work and that the outer ignore rule behaves correctly.

Do not claim later milestones are implemented with placeholders. Mark unavailable transitions clearly and keep the first vertical slice genuinely executable and resumable.
