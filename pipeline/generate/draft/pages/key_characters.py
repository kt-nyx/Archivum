"""Instance key-character pool selection and card finalization."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from pipeline.common.draft_vocab import expansion_release_order
from pipeline.common.linguistics import action_relations
from pipeline.common.text_normalize import clean_wiki_snippet
from pipeline.contracts.models import (
    INSTANCE_MAX_KEY_CHARACTERS,
    CardEvidencePackDecision,
    EntityKind,
)
from pipeline.discovery.adventure_guide import (
    AdventureGuideInstance,
    default_provider,
)
from pipeline.discovery.entity_typing import normalize_title
from pipeline.discovery.instance_bosses import (
    BossCandidate,
    cap_pool_for_llm_prompt,
    collect_character_pool,
    deterministic_pool_order,
    is_boss_section_role,
    merge_key_character_cast,
    merged_cast_candidates,
    must_include_key_character_names,
    prefilter_character_pool,
)
from pipeline.generate.draft.card_evidence_pack import build_card_evidence_pack
from pipeline.generate.draft.claim_routing import (
    CLAIM_VIEW_KEY,
    KEY_CHARACTER_ROUTE,
    SAFE_SETUP_HOOK,
    item_has_claim_views,
    key_character_setup_hook_claim_views,
    key_character_unsafe_claim_views,
    reconstruct_safe_paragraph_excerpts,
    route_claim_views_for_pool,
    safe_intent_excerpt,
    safe_paragraph_excerpt,
)
from pipeline.generate.draft.evidence_identity import evidence_id_for_item
from pipeline.generate.draft.instance_lint import (
    MAX_KEY_CHARACTER_WORDS,
    MIN_KEY_CHARACTER_WORDS,
    TARGET_KEY_CHARACTER_WORDS,
    fallback_key_character_summary,
    lint_key_character_spoilers,
    lint_key_character_summary,
    lint_passthrough_fragment,
)
from pipeline.generate.draft.pages.assembly import (
    _build_instance_evidence_pools,
    _cap_card_pointers,
    _extract_instance_infobox,
    _extract_instance_structured_links,
    _instance_participant_records,
    _pointers_for_evidence_ids,
)
from pipeline.generate.draft.prose_gate import prose_gate_violations
from pipeline.generate.draft.prose_lint import word_count
from pipeline.generate.draft.prose_selection import (
    classify_key_character_role_llm,
    select_key_characters_from_pool,
)
from pipeline.generate.draft.prose_synthesis import (
    KEY_CHARACTER_EVIDENCE_ITEM_LIMIT,
    KEY_CHARACTER_RANKER_INPUT_LIMIT,
    llm_synthesis_active,
    select_salient_key_character_beats_llm,
    synthesize_key_character_summary,
    synthesize_with_validation,
)

_POOL_SELECTION_CONTEXT_MAX_CHARS = 800

# Fix 6: below this many words of real biographical evidence (claim-view path only), a character
# card uses the restrained structural-presence blurb instead of letting the synthesizer extrapolate
# a backstory from one or two thin sentences (the Instructor Chillheart case).
_MIN_BIOGRAPHY_EVIDENCE_WORDS = 22

# A card that lands this far below target reads as an under-developed origin stub — a single "who
# they are" sentence that never reaches the through-line explaining why the figure holds this place
# (the Gandling/Jandice case: ~25-28 words from evidence rich enough for a full arc). The synthesis
# prompt bounds only the ceiling, so sampling variance alone decided whether a card grew or stopped
# short; this floor drives one retry toward the target. It is enforced as a *soft* reason: it
# re-prompts a thin card but never fails the field, so a genuinely sparse figure still ships its best
# attempt. Sits midway between the hard minimum and the target so it fires only near the floor.
_KEY_CHARACTER_THROUGH_LINE_MIN_WORDS = (MIN_KEY_CHARACTER_WORDS + TARGET_KEY_CHARACTER_WORDS) // 2


def _through_line_soft_reasons(
    summary: str, *, instance_name: str, target_words: int | None = None
) -> list[str]:
    """Soft retry trigger for a short origin-stub card (drives richness, never fails the field).

    Fires when the synthesized card lands near the hard word floor: a full origin -> presence
    through-line cannot fit in so few words, so the card almost certainly stopped at "who they
    are" and dropped the "why they are here" beat that makes it useful. Returns a plain-language
    reason the retry feeds back to the model; ``synthesize_with_validation`` treats it as soft, so
    an unavoidably thin figure still ships its best attempt.

    ``target_words`` is the evidence-proportional target for this card (the caller caps it at what
    the source supports). When it is near the hard floor — a genuinely thin figure — the card is not
    pushed at all: there is nothing to develop the through-line from, so retrying would only invite
    filler. With no target given, the fixed midpoint floor is used (offline / direct callers).
    """
    if not summary.strip():
        return []
    if target_words is None:
        threshold = _KEY_CHARACTER_THROUGH_LINE_MIN_WORDS
        aim = TARGET_KEY_CHARACTER_WORDS
    else:
        # Thin evidence: do not push a card the source cannot support beyond the floor.
        if target_words <= MIN_KEY_CHARACTER_WORDS + 5:
            return []
        threshold = (MIN_KEY_CHARACTER_WORDS + target_words) // 2
        aim = target_words
    if word_count(summary) >= threshold:
        return []
    place = instance_name or "this place"
    return [
        "the summary is short and reads as an origin stub — develop the through-line that explains "
        f"why this figure is present in {place} now (the history, motivations, or allegiances that "
        f"brought them here), aiming for about {aim} words"
    ]


def _summary_pool_word_count(summary_pool: list[dict[str, Any]]) -> int:
    return sum(len(str(view.get("snippet", "")).split()) for view in summary_pool)


@dataclass
class InstanceKeyCharacterSelection:
    """Option F cast selection: merged emit list + full prefiltered pool for sidecar."""

    cast: list[BossCandidate] = field(default_factory=list)
    pool: list[BossCandidate] = field(default_factory=list)
    selection_reasons: dict[str, str] = field(default_factory=dict)
    context_text: str = ""


def _admit_named_instance_participants(
    candidates: list[BossCandidate],
    participant_records: list[dict[str, Any]] | None,
) -> list[BossCandidate]:
    """Apply Slice 3's complete card-admission contract.

    ``None`` means this is a small direct unit call without an ingest seed.  A real
    instance seed always supplies records (and the assembly helper rejects a stale
    seed that does not), so production rendering cannot bypass this boundary.
    """
    if participant_records is None:
        return candidates
    by_id = {
        str(row.get("candidate_id", "")).strip(): row
        for row in participant_records
        if str(row.get("candidate_id", "")).strip()
    }
    admitted: list[BossCandidate] = []
    for candidate in candidates:
        row = by_id.get(candidate.boss_id)
        if row is None:
            candidate.admission_reason_codes.append("missing_participant_decision")
            continue
        try:
            candidate.entity_kind = EntityKind(str(row.get("entity_kind", "unknown")))
        except ValueError:
            candidate.entity_kind = EntityKind.UNKNOWN
        candidate.entity_kind_decision_id = str(row.get("entity_kind_decision_id", "")).strip()
        candidate.instance_presence_evidence = [
            str(value) for value in row.get("instance_presence_evidence", []) if str(value).strip()
        ]
        candidate.retail_scope = str(row.get("retail_scope", "unknown")).strip() or "unknown"
        candidate.retail_scope_evidence = [
            str(value) for value in row.get("retail_scope_evidence", []) if str(value).strip()
        ]
        candidate.encounter_relation_evidence = [
            str(value) for value in row.get("encounter_relation_evidence", []) if str(value).strip()
        ]
        candidate.admission_reason_codes = [
            str(value) for value in row.get("reason_codes", []) if str(value).strip()
        ]
        if not candidate.entity_kind_decision_id:
            candidate.admission_reason_codes.append("missing_entity_kind_decision")
            continue
        if candidate.entity_kind is not EntityKind.NAMED_ACTOR:
            candidate.admission_reason_codes.append("entity_kind_not_named_actor")
            continue
        if not candidate.instance_presence_evidence:
            candidate.admission_reason_codes.append("missing_direct_instance_presence")
            continue
        if candidate.retail_scope != "retail_confirmed":
            candidate.admission_reason_codes.append("retail_scope_not_confirmed")
            continue
        admitted.append(candidate)
    return admitted


def _instance_key_character_context_text(pools: dict[str, list[dict[str, Any]]]) -> str:
    parts: list[str] = []
    for item in pools.get("overview_pool", []) + pools.get("at_a_glance_pool", []):
        snippet = clean_wiki_snippet(str(item.get("snippet", "")))
        if snippet:
            parts.append(snippet)
    combined = " ".join(parts).strip()
    return combined[:_POOL_SELECTION_CONTEXT_MAX_CHARS]


def _order_sidecar_pool_candidates(
    pool: list[BossCandidate],
    *,
    cast_names: list[str],
    context_text: str,
) -> list[BossCandidate]:
    """Emitted cast first (merge order), then non-emitted by offline rank (diversity window)."""
    pool_by_name = {candidate.name: candidate for candidate in pool}
    cast_keys = {normalize_title(name) for name in cast_names}
    ordered: list[BossCandidate] = []
    seen: set[str] = set()
    for name in cast_names:
        candidate = pool_by_name.get(name)
        if candidate is None:
            continue
        key = normalize_title(candidate.name)
        if key in seen:
            continue
        ordered.append(candidate)
        seen.add(key)
    remaining = [
        candidate for candidate in pool if normalize_title(candidate.name) not in cast_keys
    ]
    for name in deterministic_pool_order(remaining, narrative_text=context_text):
        candidate = pool_by_name.get(name)
        if candidate is None:
            continue
        key = normalize_title(candidate.name)
        if key in seen:
            continue
        ordered.append(candidate)
        seen.add(key)
    return ordered


def _merge_character_profile_evidence(
    cast: list[BossCandidate], character_pool: list[dict[str, Any]]
) -> None:
    """Slice D: attach crawled character-page biography to each cast member's profile_pool.

    The biography is prepended so identity ("who this figure is") leads the synthesis evidence ahead
    of the instance's structural-presence mentions. Spoiler bounding is unchanged — the finalizer
    still routes the merged pool through KEY_CHARACTER_ROUTE, dropping unsafe claim views.
    """
    if not cast or not character_pool:
        return
    by_name: dict[str, list[dict[str, Any]]] = {}
    for item in character_pool:
        name = str(item.get("character_name") or item.get("source_title") or "").strip()
        if not name:
            continue
        by_name.setdefault(normalize_title(name), []).append(item)
    if not by_name:
        return
    for candidate in cast:
        cand_key = normalize_title(candidate.name)
        matched = by_name.get(cand_key)
        if matched is None:
            # Tolerate page-title vs roster-name drift (page "Gandling" vs cast "Darkmaster
            # Gandling"): accept the first character whose name contains or is contained by the cast
            # name, so a one-word page still binds to a titled roster entry.
            for name_key, items in by_name.items():
                if name_key and (name_key in cand_key or cand_key in name_key):
                    matched = items
                    break
        if matched:
            candidate.profile_pool = list(matched) + list(candidate.profile_pool or [])


def build_instance_key_character_selection(
    *,
    instance_id: str,
    instance_name: str,
    evidence_rows: list[dict[str, Any]],
    section_blocks: list[dict[str, Any]] | None = None,
    snapshots: list[dict[str, Any]] | None = None,
    pools: dict[str, list[dict[str, Any]]] | None = None,
    parent_zone_evidence_rows: list[dict[str, Any]] | None = None,
) -> InstanceKeyCharacterSelection:
    """Option F: pool → prefilter → floor → LLM → merge."""
    if pools is None:
        pools = _build_instance_evidence_pools(
            evidence_rows,
            instance_name=instance_name,
            parent_zone_evidence_rows=parent_zone_evidence_rows,
        )
    blocks = section_blocks if isinstance(section_blocks, list) else []
    structured_links = _extract_instance_structured_links(snapshots, instance_id)
    narrative_pool = pools["overview_pool"] + pools["at_a_glance_pool"]
    history_pool = pools.get("history_pool", [])
    context_text = _instance_key_character_context_text(pools)

    all_candidates = collect_character_pool(
        section_blocks=blocks,
        instance_name=instance_name,
        boss_pool_items=pools["boss_pool"],
        structured_links=structured_links,
        narrative_pool=narrative_pool,
        history_pool=history_pool,
    )
    raw_pool = _admit_named_instance_participants(
        all_candidates,
        _instance_participant_records(snapshots, instance_id),
    )
    pool = prefilter_character_pool(
        raw_pool,
        instance_name=instance_name,
    )
    if not pool:
        return InstanceKeyCharacterSelection(pool=all_candidates, context_text=context_text)

    floor = must_include_key_character_names(
        boss_pool_items=pools["boss_pool"],
        pool=pool,
        instance_name=instance_name,
        infobox=_extract_instance_infobox(snapshots, instance_id),
    )
    if len(floor) > INSTANCE_MAX_KEY_CHARACTERS:
        floor = floor[:INSTANCE_MAX_KEY_CHARACTERS]

    # When the page yields a structural boss roster (adventure guide / dungeon journal / faculty /
    # boss table), that roster *is* the cast: don't pad it with the LLM, which otherwise pulls in
    # denizen trash (random skeletons) and narrative-only figures the gold cast excludes. The LLM
    # discovers the cast only for instances whose page exposes no structural roster.
    llm_names: list[str] = []
    remaining = INSTANCE_MAX_KEY_CHARACTERS - len(floor)
    if not floor and remaining > 0:
        prompt_pool = cap_pool_for_llm_prompt(
            pool,
            must_include_names=floor,
            limit=40,
        )
        llm_names = select_key_characters_from_pool(
            prompt_pool,
            instance_name=instance_name,
            context_text=context_text,
            max_count=remaining,
            exclude_names=floor,
        )

    merged_names, selection_reasons = merge_key_character_cast(
        pool,
        must_include_names=floor,
        llm_ordered_names=llm_names,
        max_count=INSTANCE_MAX_KEY_CHARACTERS,
    )
    cast = merged_cast_candidates(pool, merged_names, instance_name=instance_name)
    _merge_character_profile_evidence(cast, pools.get("character_pool", []))
    sidecar_pool = _order_sidecar_pool_candidates(
        all_candidates,
        cast_names=merged_names,
        context_text=context_text,
    )
    return InstanceKeyCharacterSelection(
        cast=cast,
        pool=sidecar_pool,
        selection_reasons=selection_reasons,
        context_text=context_text,
    )


def build_instance_key_character_roster(
    *,
    instance_id: str,
    instance_name: str,
    evidence_rows: list[dict[str, Any]],
    section_blocks: list[dict[str, Any]] | None = None,
    snapshots: list[dict[str, Any]] | None = None,
    pools: dict[str, list[dict[str, Any]]] | None = None,
    parent_zone_evidence_rows: list[dict[str, Any]] | None = None,
) -> list[BossCandidate]:
    """Merged cast order for page assembly (Option F)."""
    return build_instance_key_character_selection(
        instance_id=instance_id,
        instance_name=instance_name,
        evidence_rows=evidence_rows,
        section_blocks=section_blocks,
        snapshots=snapshots,
        pools=pools,
        parent_zone_evidence_rows=parent_zone_evidence_rows,
    ).cast


# Section labels that hold a character's earliest life/origin material — they precede any
# expansion-tagged biography section chronologically (Fix 3).
_ORIGIN_SECTION_TOKENS = ("life", "origin", "childhood", "early", "background", "biography")


def _view_chronological_rank(view: dict[str, Any]) -> int:
    """Chronological rank of a claim view from its source section (Fix 3).

    Origin/life sections sort first, then expansion-tagged sections in release order, then
    undated background. This gives the summary pool a chronological spine so a character's story
    is told in order (origin -> ... -> the arrival that explains why they are on this page).
    """
    role = f"{view.get('raw_section_role', '')} {view.get('section_role', '')}".lower()
    for token in _ORIGIN_SECTION_TOKENS:
        if token in role:
            return -1
    order = expansion_release_order()
    for index, token in enumerate(order):
        if token and token in role:
            return index
    return len(order)


def _view_is_lead(view: dict[str, Any]) -> bool:
    if str(view.get("content_role", "")).strip().lower() == "lead":
        return True
    return str(view.get("section_role", "")).strip().lower() in {"lead", "introduction"}


def _view_mentions_instance(view: dict[str, Any], *, instance_key: str, instance_lower: str) -> bool:
    if not instance_key:
        return False
    text = f"{view.get('claim_text', '')} {view.get('snippet', '')}".lower()
    if instance_lower and instance_lower in text:
        return True
    entities = view.get("entities")
    if isinstance(entities, list):
        for entity in entities:
            if isinstance(entity, dict) and normalize_title(str(entity.get("name", ""))) == instance_key:
                return True
    return False


def _order_key_character_summary_views(
    views: list[dict[str, Any]], *, instance_name: str
) -> list[dict[str, Any]]:
    """Present routed claim views chronologically (Fix 3), demoting the modern lead (Fix 2).

    Ordering: (1) once real non-lead biography exists, the whole-page lead — a modern whole-life
    summary — sinks to the back so it does not crowd out the dated biography (a lead-only figure like
    Rattlegore keeps it); (2) chronological rank, origin first through the arrival that explains the
    figure's presence; (3) original document order within an era (the natural narrative order — no
    longer re-ranked by claim type, which used to sink the pivotal ``event`` beats).

    Offline paragraph-fallback pools carry no claim views, so this returns them unchanged and their
    gold output stays byte-identical.
    """
    if not any(isinstance(view, dict) and view.get("is_claim_view") for view in views):
        return views

    has_non_lead = any(
        isinstance(view, dict) and view.get("is_claim_view") and not _view_is_lead(view)
        for view in views
    )

    def rank_key(indexed: tuple[int, dict[str, Any]]) -> tuple[int, int, int]:
        index, view = indexed
        lead_penalty = 1 if has_non_lead and _view_is_lead(view) else 0
        return (lead_penalty, _view_chronological_rank(view), index)

    return [view for _, view in sorted(enumerate(views), key=rank_key)]


def _select_salient_key_character_views(
    views: list[dict[str, Any]], *, instance_name: str, limit: int
) -> list[dict[str, Any]]:
    """Choose which claim views survive the evidence cap, prioritizing story beats over volume.

    Wiki biographies atomize into many micro-claims, so a naive chronological cut fills the window
    with one era's granular trivia and starves the instance-relevant era (Lilian's whole-page window
    was 12 ``life`` micro-facts + 2 low-salience ``cataclysm`` claims, dropping her death, undeath,
    vendetta, and the Scholomance hook entirely). This selects for coverage instead:

      1. Always keep views that name this instance — the beat that explains why the figure is here.
      2. Fill the rest by round-robin across chronological eras, so no single era's micro-claims
         dominate; within an era, document order (natural narrative order) is preserved.

    Paragraph-fallback pools (no claim views) and pools already within the cap are returned as-is.
    """
    if limit <= 0 or len(views) <= limit:
        return views
    if not any(isinstance(view, dict) and view.get("is_claim_view") for view in views):
        return views

    instance_key = normalize_title(instance_name) if instance_name else ""
    instance_lower = instance_name.lower() if instance_name else ""
    indexed = list(enumerate(views))

    selected_idx: set[int] = set()
    # (1) Guarantee the instance-relevant beats (cap so they cannot swamp the window either).
    instance_budget = max(1, limit // 3)
    for index, view in indexed:
        if len(selected_idx) >= instance_budget:
            break
        if _view_mentions_instance(view, instance_key=instance_key, instance_lower=instance_lower):
            selected_idx.add(index)

    # (2) Round-robin across eras for the remaining budget, preserving document order within each era.
    by_era: dict[int, list[int]] = {}
    for index, view in indexed:
        if index in selected_idx:
            continue
        by_era.setdefault(_view_chronological_rank(view), []).append(index)
    era_order = sorted(by_era)
    while len(selected_idx) < limit and any(by_era[era] for era in era_order):
        for era in era_order:
            if not by_era[era]:
                continue
            selected_idx.add(by_era[era].pop(0))
            if len(selected_idx) >= limit:
                break

    return [view for index, view in indexed if index in selected_idx]


def _beat_text(view: dict[str, Any]) -> str:
    return str(view.get("claim_text") or view.get("snippet", "")).strip()


def _name_tokens(value: str) -> set[str]:
    # Strip edge punctuation so a name at a clause/sentence boundary ("Gandling.") still matches its
    # bare token ("gandling") — otherwise a trailing period would hide a cast member from the check.
    tokens: set[str] = set()
    for raw in str(value).lower().split():
        token = raw.strip(".,;:!?'\"()[]{}—–-")
        if token:
            tokens.add(token)
    return tokens


def _beat_is_self_motivation(
    text: str, *, self_name: str, other_cast_names: list[str]
) -> bool:
    """True when a setup-hook beat is the card character's OWN aim, not encounter play-by-play.

    The classifier labels a genuine motivation beat ("Lilian turned her wrath on the necromancers of
    this place") and an in-encounter mechanic ("Gandling forced Lilian to fight the adventurers")
    identically, so this separates them by structure alone — grammar and cast identity, never
    wording. A beat qualifies only when:

      * no other cast member is named anywhere in it (drops interaction beats the dependency parse
        misses via prepositions, e.g. "caught up with Gandling"); and
      * the card character is a grammatical AGENT of the beat and is NOT the PATIENT of any action
        (drops "Gandling forced her to fight …", where she is acted upon).
    """
    self_tokens = _name_tokens(self_name)
    if not self_tokens:
        return False
    text_tokens = _name_tokens(text)
    for other in other_cast_names:
        other_tokens = _name_tokens(other)
        if other_tokens and other_tokens != self_tokens and other_tokens <= text_tokens:
            return False
    relations = action_relations(text)
    if not relations:
        return False
    self_is_agent = any(
        self_tokens & _name_tokens(agent) for rel in relations for agent in rel.agents
    )
    if not self_is_agent:
        return False
    self_is_patient = any(
        self_tokens & _name_tokens(patient) for rel in relations for patient in rel.patients
    )
    return not self_is_patient


def _recover_instance_setup_hooks(
    source_pool: list[dict[str, Any]],
    *,
    instance_name: str,
    boss_name: str,
    other_cast_names: list[str],
    selected: list[dict[str, Any]],
    limit: int = 2,
) -> list[dict[str, Any]]:
    """Recover the card character's spoiler-safe 'why they're here' motivation hook.

    ``safe_setup_hook`` beats are barred from the key-character route because they share their labels
    with in-encounter mechanics (and the route also feeds paragraph reconstruction). This re-admits
    only the ones that are the character's own aim toward this place, gated by
    :func:`_beat_is_self_motivation` — so the motivation lead-in reaches synthesis while the mechanics
    and outcomes stay filtered. No-op when a safe instance beat is already selected, or for
    paragraph-fallback pools (no claim views).
    """
    if not instance_name or not boss_name:
        return []
    instance_key = normalize_title(instance_name)
    instance_lower = instance_name.lower()
    if any(
        _view_mentions_instance(view, instance_key=instance_key, instance_lower=instance_lower)
        for view in selected
    ):
        return []
    recovered: list[dict[str, Any]] = []
    seen: set[str] = set()
    for view in key_character_setup_hook_claim_views(source_pool):
        if not _view_mentions_instance(
            view, instance_key=instance_key, instance_lower=instance_lower
        ):
            continue
        text = _beat_text(view)
        if not text:
            continue
        if not _beat_is_self_motivation(
            text, self_name=boss_name, other_cast_names=other_cast_names
        ):
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        synthetic = dict(view)
        # Detach from the source paragraph so the hook text survives synthesis-item collapse
        # (a shared canonical id would let a same-paragraph background excerpt overwrite it).
        synthetic["canonical_evidence_id"] = ""
        synthetic["spoiler_safety"] = SAFE_SETUP_HOOK
        synthetic["is_claim_view"] = True
        recovered.append(synthetic)
        if len(recovered) >= limit:
            break
    return recovered


def _recover_instance_hook_intent(
    source_pool: list[dict[str, Any]],
    *,
    instance_name: str,
    selected: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Recover the spoiler-safe intent of an instance-hook beat routing dropped (Cause 3).

    When no selected safe beat names this instance, the character's whole 'why they're here'
    arc is a spoiler-shaped sentence (Lilian Voss: "intended to kill Gandling, though it
    failed") that the safety route drops before selection. Keep only its intent clause (up to
    the first adversative connective) as a synthetic safe view, so the connective arc reaches
    synthesis while the outcome tail stays filtered. No-op for paragraph-fallback pools (no
    claim views) and when a safe instance beat is already selected.
    """
    if not instance_name:
        return []
    instance_key = normalize_title(instance_name)
    instance_lower = instance_name.lower()
    if any(
        _view_mentions_instance(view, instance_key=instance_key, instance_lower=instance_lower)
        for view in selected
    ):
        return []
    recovered: list[dict[str, Any]] = []
    seen: set[str] = set()
    for view in key_character_unsafe_claim_views(source_pool):
        if not _view_mentions_instance(
            view, instance_key=instance_key, instance_lower=instance_lower
        ):
            continue
        intent = safe_intent_excerpt(view)
        if not intent:
            continue
        key = intent.lower()
        if key in seen:
            continue
        seen.add(key)
        synthetic = dict(view)
        synthetic["snippet"] = intent
        synthetic["claim_text"] = intent
        synthetic["spoiler_safety"] = "safe_setup_hook"
        synthetic["is_claim_view"] = True
        recovered.append(synthetic)
    return recovered


def _key_character_summary_pool(
    pool: list[dict[str, Any]],
    *,
    instance_name: str = "",
    boss_name: str = "",
    other_cast_names: list[str] | None = None,
    reference_arc: str = "",
    decisions_out: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Route, select the most significant beats within budget, then present chronologically.

    Selection is a two-step funnel: a deterministic era-balanced trim bounds the candidate set (and
    is the offline/no-LLM fallback), then an LLM salience pass (option B) keeps the beats that most
    define the character and their presence here. Both steps only *select* from the route-filtered
    pool; neither reintroduces filtered content. ``reference_arc`` (the Adventure Guide blurb) is
    passed to the salience pass as a hint toward the arc points the game itself treats as defining.
    When ``decisions_out`` is provided it is populated with a beat-selection audit (available/kept
    counts, method, kept/dropped beat texts).
    """
    routed = route_claim_views_for_pool(pool, KEY_CHARACTER_ROUTE)
    if not routed:
        return routed
    candidates = _select_salient_key_character_views(
        routed, instance_name=instance_name, limit=KEY_CHARACTER_RANKER_INPUT_LIMIT
    )
    selected = select_salient_key_character_beats_llm(
        candidates,
        boss_name=boss_name,
        instance_name=instance_name,
        limit=KEY_CHARACTER_EVIDENCE_ITEM_LIMIT,
        reference_arc=reference_arc,
    )
    method = "llm_ranked"
    if selected is None:
        method = "deterministic" if len(routed) > KEY_CHARACTER_EVIDENCE_ITEM_LIMIT else "within_budget"
        selected = _select_salient_key_character_views(
            candidates, instance_name=instance_name, limit=KEY_CHARACTER_EVIDENCE_ITEM_LIMIT
        )
    ordered = _order_key_character_summary_views(selected, instance_name=instance_name)
    # Recover the character's spoiler-safe "why they're here" motivation hook — a safe_setup_hook
    # beat the route drops — when it is the character's own aim (grammar/cast gated). Appended last:
    # it is their latest, current aim leading into this place.
    recovered_hooks: list[dict[str, Any]] = []
    setup_hooks = _recover_instance_setup_hooks(
        pool,
        instance_name=instance_name,
        boss_name=boss_name,
        other_cast_names=other_cast_names or [],
        selected=ordered,
    )
    for view in setup_hooks:
        if view not in ordered:
            ordered = ordered + [view]
            recovered_hooks.append(view)
    # Cause 3 fallback: if no safe instance hook survived, splice the spoiler-safe intent clause of
    # an otherwise-unsafe instance-hook beat (up to the first adversative connective).
    hook_views = _recover_instance_hook_intent(
        pool, instance_name=instance_name, selected=ordered
    )
    for view in hook_views:
        if view not in ordered:
            ordered = ordered + [view]
            recovered_hooks.append(view)
    # Pin the recovered hook within the synthesis evidence window. It is appended last (the current
    # aim), so on a figure with a full selection it could fall outside the ``max_items`` cap the
    # synthesizer shows. Drop the lowest-priority background beats instead — never the lead-in.
    if recovered_hooks and len(ordered) > KEY_CHARACTER_EVIDENCE_ITEM_LIMIT:
        others = [view for view in ordered if view not in recovered_hooks]
        keep = max(0, KEY_CHARACTER_EVIDENCE_ITEM_LIMIT - len(recovered_hooks))
        ordered = others[:keep] + recovered_hooks
    if decisions_out is not None:
        kept_texts = {_beat_text(view) for view in ordered}
        decisions_out["method"] = method
        decisions_out["available_beats"] = len(routed)
        decisions_out["kept_beats"] = len(ordered)
        decisions_out["kept"] = [
            {"text": _beat_text(view)[:160], "section": _view_chronological_rank(view)}
            for view in ordered
        ]
        decisions_out["dropped"] = [
            _beat_text(view)[:160]
            for view in routed
            if _beat_text(view) not in kept_texts
        ][:24]
    return ordered


def _structural_presence_item(
    *,
    candidate: BossCandidate,
    instance_name: str,
    source_pool: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """The restrained, spoiler-free structural-presence seed item (ungated by section role).

    Used both as the pre-synthesis fallback for thin/unsafe evidence and as the guaranteed
    last resort for a must-include boss whose evidence-rich summary cannot pass validation.
    """
    if not source_pool:
        return []
    base = dict(source_pool[0])
    base["snippet"] = (
        f"{candidate.name} is present in {instance_name} as one of the setting's notable "
        f"figures, helping define the threats and power structure encountered there."
    )
    base["source_excerpt"] = str(source_pool[0].get("source_excerpt") or source_pool[0].get("snippet", ""))
    base["is_claim_view"] = True
    base["claim_id"] = ""
    base["spoiler_safety"] = "encounter_setup"
    return [base]


def _structural_presence_summary_pool(
    *,
    candidate: BossCandidate,
    instance_name: str,
    source_pool: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not is_boss_section_role(candidate.source_section_role):
        return []
    return _structural_presence_item(
        candidate=candidate, instance_name=instance_name, source_pool=source_pool
    )


_ADVENTURE_GUIDE_TOKENS = ("adventure_guide", "adventurers_guide", "dungeon_journal")
_MAX_ADVENTURE_GUIDE_FRAMING_WORDS = 90


def _is_adventure_guide_role(role: str) -> bool:
    lowered = str(role).lower()
    return any(token in lowered for token in _ADVENTURE_GUIDE_TOKENS)


def _build_adventure_guide_framing(
    candidate: BossCandidate, boss_pool: list[dict[str, Any]]
) -> str:
    """The game's Adventure Guide / dungeon-journal blurb for this character, spoiler-filtered.

    These are Blizzard-authored character summaries — high-value context for identity, role, and
    tone. Returned as *reference framing* (used but never copied — the call site's passthrough gate
    enforces that), spoiler-filtered through the same safe-sentence reconstruction as the beats.
    Empty when the character has no Adventure Guide entry, so the beats carry the card unchanged.
    """
    if not boss_pool:
        return ""
    name_lower = candidate.name.strip().lower()
    if not name_lower:
        return ""
    parts: list[str] = []
    for item in boss_pool:
        if not isinstance(item, dict):
            continue
        role = str(item.get("raw_section_role") or item.get("section_role") or "")
        if not _is_adventure_guide_role(role):
            continue
        if name_lower not in str(item.get("snippet", "")).lower():
            continue
        views = item.get(CLAIM_VIEW_KEY)
        if isinstance(views, list) and views:
            excerpt = safe_paragraph_excerpt(
                views, KEY_CHARACTER_ROUTE, paragraph_text=str(item.get("snippet", ""))
            )
        else:
            excerpt = clean_wiki_snippet(str(item.get("snippet", "")))
        if excerpt:
            parts.append(excerpt)
    framing = " ".join(parts).strip()
    if not framing:
        return ""
    words = framing.split()
    if len(words) > _MAX_ADVENTURE_GUIDE_FRAMING_WORDS:
        framing = " ".join(words[:_MAX_ADVENTURE_GUIDE_FRAMING_WORDS])
    return framing


def resolve_adventure_guide_instance(instance_name: str) -> AdventureGuideInstance | None:
    """Fetch the dedicated Adventure Guide page content for this instance, or ``None``.

    Gated to live LLM runs (the framing is only consumed by the LLM synthesis / role / salience
    passes; offline paths ignore it) and behind the ``WOW_LORE_NO_ADVENTURE_GUIDE`` kill-switch, so
    deterministic and offline runs never touch the network. Any crawl failure degrades to ``None``,
    leaving the character cards to synthesize from beats exactly as before.
    """
    if not instance_name.strip():
        return None
    if os.environ.get("WOW_LORE_NO_ADVENTURE_GUIDE", "").lower() in {"1", "true", "yes"}:
        return None
    if not llm_synthesis_active():
        return None
    try:
        return default_provider().instance_content(instance_name)
    except Exception:  # pragma: no cover - network/parse failures degrade to no framing
        return None


def _adventure_guide_entry_framing(instance: AdventureGuideInstance | None, name: str) -> str:
    """Reference-framing text for a cast member from the dedicated Adventure Guide page.

    Only the character's own journal description is used (never the encounter ``Course:`` mechanics),
    capped for prompt size. The cap bounds the reference block, not the synthesized card. Returns
    ``""`` when there is no Adventure Guide page, no matching entry, or an entry with no description
    — so a character with only structural evidence, or an instance whose page carries only an
    overview and no per-boss entries, falls back to beats exactly as before.
    """
    if instance is None:
        return ""
    entry = instance.entry_for(name)
    if entry is None:
        return ""
    text = clean_wiki_snippet(entry.description).strip()
    if not text:
        return ""
    words = text.split()
    if len(words) > _MAX_ADVENTURE_GUIDE_FRAMING_WORDS:
        text = " ".join(words[:_MAX_ADVENTURE_GUIDE_FRAMING_WORDS])
    return text


_MAX_ADVENTURE_GUIDE_OVERVIEW_WORDS = 120


def adventure_guide_overview_framing(instance: AdventureGuideInstance | None) -> str:
    """The instance's own Adventure Guide intro blurb, as reference framing for the overview.

    Blizzard's per-instance intro is exactly the in-universe story-context blurb the overview field
    aims for, so it anchors framing (never copied). Returns ``""`` when there is no Adventure Guide
    page or the page carries only per-boss entries with no intro — so instances with partial or no
    Adventure Guide content synthesize the overview from evidence unchanged.
    """
    if instance is None:
        return ""
    text = clean_wiki_snippet(instance.overview).strip()
    if not text:
        return ""
    words = text.split()
    if len(words) > _MAX_ADVENTURE_GUIDE_OVERVIEW_WORDS:
        text = " ".join(words[:_MAX_ADVENTURE_GUIDE_OVERVIEW_WORDS])
    return text


def _synthesis_items_from_pool(
    summary_pool: list[dict[str, Any]], para_excerpts: dict[str, str]
) -> list[dict[str, Any]]:
    """Collapse selected claim views to one item per source paragraph for synthesis (Fix 1).

    Each item's snippet becomes the reconstructed contiguous safe excerpt (coherent prose) instead
    of the atomized claim fragment; same-paragraph claims merge, and a paragraph with no
    reconstruction falls back to the claim fragment. Provenance fields (source_id, source_refs) are
    preserved from the representative view.
    """
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for view in summary_pool:
        canonical_id = str(view.get("canonical_evidence_id", "")).strip()
        key = canonical_id or f"_view-{id(view)}"
        if key in seen:
            continue
        seen.add(key)
        item = dict(view)
        excerpt = para_excerpts.get(canonical_id, "") if canonical_id else ""
        if excerpt:
            item["snippet"] = excerpt
        items.append(item)
    return items


def _finalize_key_characters(
    *,
    instance_name: str,
    boss_candidates: list[BossCandidate],
    boss_pool: list[dict[str, Any]],
    revision_map: dict[str, str],
    selection_reasons: dict[str, str] | None = None,
    adventure_guide: AdventureGuideInstance | None = None,
    pack_sink: list[CardEvidencePackDecision] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, str]]], set[str]]:
    cards: list[dict[str, Any]] = []
    provenance_map: dict[str, list[dict[str, str]]] = {}
    used_source_ids: set[str] = set()
    if not boss_candidates:
        return cards, provenance_map, used_source_ids

    all_cast_names = [str(c.name).strip() for c in boss_candidates if str(c.name).strip()]
    for candidate in boss_candidates[:INSTANCE_MAX_KEY_CHARACTERS]:
        other_cast_names = [name for name in all_cast_names if name != candidate.name]
        # The game's Adventure Guide framing for this figure (reference context, never copied).
        # Prefer the dedicated Adventure Guide page's per-boss journal blurb; fall back to the
        # instance page's own dungeon-journal scrape when the figure has no dedicated entry.
        ag_page_framing = _adventure_guide_entry_framing(adventure_guide, candidate.name)
        ag_framing = ag_page_framing or _build_adventure_guide_framing(candidate, boss_pool)
        ag_source = "adventure_guide_page" if ag_page_framing else "instance_page"
        pools_to_try: list[list[dict[str, Any]]] = []
        if candidate.profile_pool:
            pools_to_try.append(candidate.profile_pool)
        if boss_pool and boss_pool not in pools_to_try:
            pools_to_try.append(boss_pool)
        if not pools_to_try:
            continue

        card: dict[str, Any] | None = None
        card_pointers: list[dict[str, str]] = []
        card_pack: CardEvidencePackDecision | None = None
        structural_role = candidate.role or "uncertain"
        # A must-include boss is a confirmed encounter: it must always ship (Cause 2a). On
        # validation failure it falls back to the spoiler-free structural-presence seed rather
        # than being dropped like a speculative narrative candidate.
        is_floor_candidate = (selection_reasons or {}).get(candidate.name) == "must_include_floor"
        for pool in pools_to_try:
            source_pool = pool
            # Slice 9: encounter-mechanics / outcome claims (e.g. "Lilian Voss defeated",
            # "Course: Reeducation") are barred from character prose (clarification question 1).
            # The route already drops them from the safe summary pool; collect them here only to
            # tell the synthesizer what to avoid, and to record safe/unsafe counts in the sidecar.
            has_claim_views = any(item_has_claim_views(item) for item in source_pool)
            unsafe_views = key_character_unsafe_claim_views(source_pool)
            avoid_hints = [
                text
                for view in unsafe_views
                if (text := str(view.get("claim_text", "")).strip())
            ]
            beat_decision: dict[str, Any] = {}
            summary_pool = _key_character_summary_pool(
                source_pool,
                instance_name=instance_name,
                boss_name=candidate.name,
                other_cast_names=other_cast_names,
                reference_arc=ag_framing,
                decisions_out=beat_decision,
            )
            safe_evidence_count = len(summary_pool)
            used_structural_fallback = False
            if not summary_pool:
                # Only unsafe / unlabeled encounter evidence remains: fall back to a restrained
                # structural-presence summary rather than letting spoiler text write the card.
                summary_pool = _structural_presence_summary_pool(
                    candidate=candidate,
                    instance_name=instance_name,
                    source_pool=source_pool,
                )
                used_structural_fallback = bool(summary_pool)
            elif (
                has_claim_views
                and all(_view_is_lead(view) for view in summary_pool)
                and _summary_pool_word_count(summary_pool) < _MIN_BIOGRAPHY_EVIDENCE_WORDS
            ):
                # Fix 6: the figure has no real biography — only a thin page lead — so summarizing it
                # would extrapolate a backstory (the Instructor Chillheart case). Prefer the
                # restrained structural-presence blurb. A rich lead (e.g. Rattlegore) clears the word
                # floor and a figure with real biography sections is not lead-only, so neither is
                # downgraded. Only applies when a structural blurb is available (boss-section pick).
                structural_pool = _structural_presence_summary_pool(
                    candidate=candidate,
                    instance_name=instance_name,
                    source_pool=source_pool,
                )
                if structural_pool:
                    summary_pool = structural_pool
                    used_structural_fallback = True
                    safe_evidence_count = 0
            if not summary_pool:
                continue
            # Fix 1: hand the synthesizer coherent reconstructed paragraph prose (safe sentences
            # only) instead of atomized claim fragments. Skipped for the structural-presence
            # template, which is already a purpose-built sentence.
            if used_structural_fallback:
                synthesis_items = summary_pool
            else:
                para_excerpts = reconstruct_safe_paragraph_excerpts(source_pool, KEY_CHARACTER_ROUTE)
                synthesis_items = _synthesis_items_from_pool(summary_pool, para_excerpts)
            summary_kwargs: dict[str, Any] = {}
            if avoid_hints:
                summary_kwargs["avoid_hints"] = avoid_hints
            if ag_framing:
                summary_kwargs["reference_framing"] = ag_framing
            # Anti-copy: gate the summary against both the synthesis excerpts and the Adventure Guide
            # framing, so a run copied from either the evidence or the reference framing is rejected.
            gate_sources = [str(row.get("snippet", "")) for row in synthesis_items]
            if ag_framing:
                gate_sources.append(ag_framing)

            def _summary_reasons(
                candidate_summary: str, gate_sources: list[str] = gate_sources
            ) -> list[str]:
                reasons = list(
                    lint_key_character_summary(
                        candidate_summary,
                        boss_name=candidate.name,
                        instance_name=instance_name,
                    )
                )
                reasons.extend(lint_passthrough_fragment(candidate_summary))
                reasons.extend(
                    lint_key_character_spoilers(
                        candidate_summary,
                        self_name=candidate.name,
                        other_cast_names=other_cast_names,
                    )
                )
                reasons.extend(
                    prose_gate_violations(candidate_summary, source_snippets=gate_sources)
                )
                return reasons

            if llm_synthesis_active():

                def _run_validated(
                    items: list[dict[str, Any]],
                    summary_kwargs: dict[str, Any] = summary_kwargs,
                    *,
                    soft_through_line: bool = True,
                ) -> Any:
                    gate = [str(row.get("snippet", "")) for row in items]
                    if ag_framing:
                        gate.append(ag_framing)
                    # Evidence-proportional target: never ask for more words than the source can
                    # support, so a rich figure gets the full arc while a thin one (a short seed,
                    # a lone sentence) is not padded toward the ceiling. Anti-filler by construction.
                    evidence_words = sum(
                        word_count(str(row.get("snippet", ""))) for row in items
                    )
                    effective_target = max(
                        MIN_KEY_CHARACTER_WORDS,
                        min(TARGET_KEY_CHARACTER_WORDS, evidence_words),
                    )

                    def _call(
                        reinforce: str,
                        items: list[dict[str, Any]] = items,
                        target: int = effective_target,
                    ) -> dict[str, Any]:
                        text, used_ids = synthesize_key_character_summary(
                            items,
                            boss_name=candidate.name,
                            instance_name=instance_name,
                            structural_role=structural_role,
                            max_words=MAX_KEY_CHARACTER_WORDS,
                            target_words=target,
                            reinforce=reinforce,
                            **summary_kwargs,
                        )
                        return {"text": text, "used": used_ids}

                    # Drive one retry toward the target when an evidence-backed card lands as a short
                    # origin stub. Soft: it never fails the field, so a thin figure still ships. Not
                    # applied to the structural-presence seed (a fixed template with no evidence to
                    # expand — retries there would only burn calls and re-ship the same blurb), and
                    # bounded by the same evidence-proportional target so a thin card is not pushed.
                    validate_soft = (
                        (lambda payload: _through_line_soft_reasons(
                            str(payload.get("text", "")),
                            instance_name=instance_name,
                            target_words=effective_target,
                        ))
                        if soft_through_line
                        else None
                    )
                    return synthesize_with_validation(
                        call=_call,
                        extract_bodies=lambda payload: [str(payload.get("text", ""))],
                        validate=lambda payload: _summary_reasons(
                            str(payload.get("text", "")), gate_sources=gate
                        ),
                        validate_soft=validate_soft,
                        # Copy detection runs inside _summary_reasons via the source-aware gate.
                        source_snippets=None,
                        label=f"key_character.{candidate.boss_id}",
                    )

                result = _run_validated(synthesis_items)
                if not result.ok and is_floor_candidate and not used_structural_fallback:
                    # Cause 2a: a confirmed boss must ship. When its evidence-rich summary can't
                    # pass validation, retry once from the spoiler-free structural-presence seed
                    # (the Adventure Guide framing still supplies its identity) before giving up.
                    seed_items = _structural_presence_item(
                        candidate=candidate,
                        instance_name=instance_name,
                        source_pool=source_pool,
                    )
                    if seed_items:
                        seed_result = _run_validated(seed_items, soft_through_line=False)
                        if seed_result.ok:
                            result = seed_result
                            synthesis_items = seed_items
                            used_structural_fallback = True
                if not result.ok:
                    # Live path never borrows: a non-floor candidate whose summary cannot pass
                    # validation is dropped (recorded via the synth_guard trace) rather than
                    # shipped as copy or template filler.
                    continue
                summary = str(result.payload.get("text", ""))
                used = list(result.payload.get("used", []))
            else:
                summary, used = synthesize_key_character_summary(
                    synthesis_items,
                    boss_name=candidate.name,
                    instance_name=instance_name,
                    structural_role=structural_role,
                    max_words=MAX_KEY_CHARACTER_WORDS,
                    **summary_kwargs,
                )
                if _summary_reasons(summary, gate_sources=[]):
                    summary, used = fallback_key_character_summary(
                        synthesis_items,
                        boss_name=candidate.name,
                        instance_name=instance_name,
                    )
                if not summary or _summary_reasons(summary, gate_sources=[]):
                    continue
            pointers = _cap_card_pointers(
                _pointers_for_evidence_ids(synthesis_items, used, revision_map),
                max_count=3,
            )
            if not pointers and boss_pool is not synthesis_items:
                pointers = _cap_card_pointers(
                    _pointers_for_evidence_ids(boss_pool, used, revision_map),
                    max_count=3,
                )
            if not pointers:
                # The reported used-ids resolved to no pointer. Fall back to the pool the card
                # was actually synthesized from (Slice 6 pattern) — grounded provenance, not a
                # count backfill — so an emitted card carries >=1 pointer when any pool source
                # is resolvable; otherwise the candidate is dropped below.
                best_pool = synthesis_items if synthesis_items else boss_pool
                pool_ids = [
                    evidence_id
                    for item in best_pool
                    if (evidence_id := evidence_id_for_item(item))
                ]
                pointers = _cap_card_pointers(
                    _pointers_for_evidence_ids(best_pool, pool_ids, revision_map),
                    max_count=3,
                )
            if not pointers:
                continue
            role = candidate.role or "uncertain"
            role_reason = candidate.role_reason or "no_signal"
            # Hybrid: only spend an LLM call when deterministic signals were inconclusive.
            if role == "uncertain":
                role = classify_key_character_role_llm(
                    synthesis_items,
                    character_name=candidate.name,
                    instance_name=instance_name,
                    fallback_role="uncertain",
                    reference_framing=ag_framing,
                )
                if role != "uncertain":
                    role_reason = "llm_tiebreaker"
            candidate.role = role
            candidate.role_reason = role_reason
            # WS-4 confidence gate: stop padding the roster to the cap with narrative-only
            # mentions. A non-floor candidate must carry a real in-instance structural
            # signal; a pure narrative fallback (no boss/denizen section, no adventure-guide
            # signal) is dropped rather than emitted as a low-confidence "uncertain" card.
            # The boss floor (must_include) always passes, so confident bosses are never
            # dropped. card is still None here, so breaking the pool loop drops the
            # candidate via the `if card is None` guard below.
            if not is_floor_candidate and candidate.source_section_role == "narrative_fallback":
                break
            reason_codes: list[str] = []
            selection_reason = (selection_reasons or {}).get(candidate.name)
            if selection_reason:
                reason_codes.append(selection_reason)
            if candidate.source_section_role:
                reason_codes.append(candidate.source_section_role)
            reason_codes.extend(candidate.admission_reason_codes)
            reason_codes.append(f"entity_kind:{candidate.entity_kind.value}")
            reason_codes.extend(
                f"instance_presence:{evidence}"
                for evidence in candidate.instance_presence_evidence
            )
            reason_codes.append(f"retail_scope:{candidate.retail_scope}")
            if role_reason:
                reason_codes.append(f"role:{role}:{role_reason}")
            # Slice 9 spoiler-safety audit. With claim views, record how much safe vs unsafe
            # evidence backed the summary and whether spoiler-unsafe evidence forced the restrained
            # structural fallback. Without claim views (paragraph fallback), no claim-level safety
            # was assessed, so say so honestly rather than reporting an unvetted "safe" count.
            if has_claim_views:
                reason_codes.append(
                    f"summary_evidence:safe={safe_evidence_count}:unsafe={len(unsafe_views)}"
                )
                if used_structural_fallback:
                    reason_codes.append("summary_source:structural_presence")
                # Fix 4: beat-selection audit — how many safe beats were available vs kept, and how.
                if beat_decision.get("available_beats"):
                    reason_codes.append(
                        f"beat_selection:available={beat_decision['available_beats']}"
                        f":kept={beat_decision.get('kept_beats', 0)}"
                        f":method={beat_decision.get('method', 'na')}"
                    )
            else:
                reason_codes.append("summary_evidence:paragraph_fallback")
            if ag_framing:
                reason_codes.append(f"reference:adventure_guide:{ag_source}")
            card = {
                "id": candidate.boss_id,
                "name": candidate.name,
                "summary": summary,
                "role": role,
                "wiki_ref": candidate.wiki_url or None,
                "decision_reason_codes": reason_codes,
                "thumbnail_asset_id": None,
            }
            card_pointers = pointers
            # Slice 7: a named participant's identity evidence is the very material its summary was
            # synthesized from (its own crawled biography / boss-section presence, scoped to this
            # named actor). Recorded so every emitted key-character card carries an evidence pack.
            card_pack = build_card_evidence_pack(
                card_id=candidate.boss_id,
                card_type="key_character",
                subject_id=candidate.boss_id,
                subject_name=candidate.name,
                identity_items=synthesis_items,
            )
            break
        if card is None:
            continue
        cards.append(card)
        if pack_sink is not None and card_pack is not None:
            pack_sink.append(card_pack)
        provenance_map[str(card["id"])] = card_pointers
        used_source_ids.update(str(pointer["source_id"]) for pointer in card_pointers)
        if len(cards) >= INSTANCE_MAX_KEY_CHARACTERS:
            break
    return cards, provenance_map, used_source_ids
