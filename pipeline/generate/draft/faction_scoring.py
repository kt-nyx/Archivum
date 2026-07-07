"""Zone-agnostic faction candidate collection, scoring, and election for major_factions."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from pipeline.common.draft_vocab import era_section_role_tokens
from pipeline.common.text_ids import slugify
from pipeline.discovery.world_registry import (
    entry_affiliations,
    organization_entry,
    organization_entry_for_href,
    umbrella_faction_tags,
    umbrella_organizations,
)
from pipeline.generate.draft.faction_lint import (
    MAX_FACTION_SUMMARY_WORDS,
    MIN_FACTION_SUMMARY_WORDS,
    trim_faction_summary,
)
from pipeline.generate.draft.pool_policy import (
    is_excluded_from_card_pool,
    row_has_admissible_item,
)
from pipeline.generate.draft.prose_gate import detect_list_shape
from pipeline.generate.draft.prose_lint import has_currently_meta, split_sentences, word_count
from pipeline.generate.draft.temporal import HISTORY_ELIGIBLE

MIN_FACTION_CARDS = 2
MAX_FACTION_CARDS = 7
MIN_SCORE = 2.0
ALLIANCE_HORDE_CONFLICT_THRESHOLD = 2
# Quest-binding score is driven by a faction's OWN side's quests (an active belligerent), not the
# generic shared/neutral bindings that every faction in the zone matches. The cap bounds a large
# campaign's contribution; the bonus gives a present-day combatant a decisive edge over factions
# whose relevance is purely historical/profile-based.
_SPECIFIC_BINDING_SCORE_CAP = 6.0
ACTIVE_COMBATANT_BONUS = 3.0

# WS-C: era tokens externalized + de-duplicated (shared with prose_election) in
# pipeline/data/draft_classification_vocab.v1.json (D-6).
_ERA_TOKENS = era_section_role_tokens()

_HIGH_WEIGHT_ROLES = frozenset({"quests_edit", "quests", "quests_or_storyline"})
_LEDE_ROLES = frozenset({"lead", "introduction"})


def _umbrella_tag_by_faction_id() -> dict[str, str]:
    """faction_id -> umbrella tag for the faction-capital orgs, from the registry (Slice 13)."""
    return {
        f"faction-{slugify(title)}": tag for title, tag in umbrella_organizations().items()
    }


def _umbrella_faction_ids() -> frozenset[str]:
    return frozenset(_umbrella_tag_by_faction_id())


@dataclass
class FactionCandidate:
    faction_id: str
    name: str
    wiki_url: str
    profile_items: list[dict[str, Any]] = field(default_factory=list)
    seed_mentions: list[dict[str, Any]] = field(default_factory=list)
    quest_binding_count: int = 0
    specific_quest_binding_count: int = 0
    score: float = 0.0
    has_high_weight_seed: bool = False
    lede_only: bool = False
    # Umbrella affiliations ("alliance"/"horde") from the org registry's category
    # memberships plus the crawled profile page's infobox Affiliation field (Slice 13).
    affiliations: frozenset[str] = frozenset()


def _normalize_role(section_role: str) -> str:
    return re.sub(r"\s+", " ", section_role.strip()).lower().replace(" ", "_")


def _wiki_url_from_link(link: str) -> str:
    link = link.strip()
    if link.startswith("http"):
        return link
    if link.startswith("/wiki/"):
        return f"https://warcraft.wiki.gg{link}"
    slug = link.replace(" ", "_")
    return f"https://warcraft.wiki.gg/wiki/{slug}"


def _wiki_url_from_name(name: str) -> str:
    slug = name.strip().replace(" ", "_")
    return f"https://warcraft.wiki.gg/wiki/{slug}"


def _name_in_text(name: str, text: str) -> bool:
    if not name or not text:
        return False
    pattern = rf"\b{re.escape(name)}\b"
    return bool(re.search(pattern, text, re.IGNORECASE))


def _bindings_for_faction(
    faction_id: str, name: str = "", affiliations: frozenset[str] = frozenset()
) -> frozenset[str]:
    """Quest-binding tags a faction matches, derived structurally (Slice 13).

    An umbrella faction (Alliance/Horde, per the registry's faction-capital orgs) matches only
    its own side's bindings. Every other faction matches its own name slug plus the generic
    shared/neutral bindings, plus any umbrella side it belongs to — membership coming from the
    org registry's category affiliations and the profile infobox (e.g. Forsaken -> horde),
    never a hardcoded per-faction map.
    """
    umbrella = _umbrella_tag_by_faction_id()
    if faction_id in umbrella:
        return frozenset({umbrella[faction_id]})
    slug = (name.strip().lower() or faction_id.removeprefix("faction-").replace("-", " "))
    return frozenset({slug, "shared", "neutral"}) | affiliations


def _bindings_for_candidate(candidate: FactionCandidate) -> frozenset[str]:
    return _bindings_for_faction(candidate.faction_id, candidate.name, candidate.affiliations)


def _count_quest_bindings(
    bindings: frozenset[str], v3_rows: list[dict[str, Any]], zone_id: str
) -> int:
    count = 0
    for row in v3_rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("zone_id", "")) != zone_id:
            continue
        if str(row.get("node_type", "")) != "quest":
            continue
        binding = str(row.get("faction_binding", "shared")).strip().lower()
        if binding in bindings:
            count += 1
    return count


def _count_specific_quest_bindings(
    bindings: frozenset[str], v3_rows: list[dict[str, Any]], zone_id: str
) -> int:
    """Count zone quests bound to this faction's OWN side, excluding the generic ``shared`` /
    ``neutral`` bindings that *every* faction matches. A nonzero count marks the faction as an active
    belligerent in the zone's current quest conflict (e.g. the Alliance / Horde sides of a contested
    zone). Without this, lore factions borrow score uniformly from every shared quest while
    Alliance / Horde — whose bindings are side-specific — never do, so a defunct lore faction can
    outrank an active war combatant."""
    specific = bindings - {"shared", "neutral"}
    if not specific:
        return 0
    return _count_quest_bindings(specific, v3_rows, zone_id)


# A Title-Case proper-noun phrase (allowing of/the/and connectors) — a general grammar pattern,
# used ONLY to harvest frequent proper nouns (places/figures) as summary anchor tokens. Faction
# identity never comes from this regex: mentions are inline links resolved against the
# organization registry (Slice 13).
_PROPER_NOUN_PHRASE_RE = re.compile(
    r"\b([A-Z][A-Za-z']+(?:(?:\s+(?:of|the))*\s+[A-Z][A-Za-z']+){0,4})"
)


def _organization_from_link(link: Any) -> dict[str, Any] | None:
    """Resolve an evidence-block inline link to a registry organization.

    Prefers the ingest redirect-resolution annotation (``canonical_path``) where present,
    so a link through a redirect title still lands on the canonical article.
    """
    if not isinstance(link, dict):
        return None
    href = str(link.get("canonical_path") or link.get("href") or "").strip()
    if not href:
        return None
    return organization_entry_for_href(href)


def _item_organization_links(item: dict[str, Any]) -> list[dict[str, Any]]:
    """The item's linked registry organizations, deduped by normalized title, in link order."""
    raw_links = item.get("links")
    if not isinstance(raw_links, list):
        return []
    orgs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for link in raw_links:
        org = _organization_from_link(link)
        if org is None:
            continue
        key = str(org.get("normalized_title", "")).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        orgs.append(org)
    return orgs


# The instance's own-subject evidence fields (its page prose, lore page, and boss sections).
# Instance faction harvesting is restricted to these: cross-page biography pools —
# ``character_pool`` (crawled character biographies) and the faction/parent/related profile
# pools — describe *other* subjects, so a faction that saturates a character's biography
# (Scarlet Crusade in Lilian Voss's) must not mint an instance faction card (Slice 6).
_INSTANCE_OWN_EVIDENCE_FIELDS = frozenset(
    {"history_digest", "at_a_glance_input", "boss_pool", "instance_lore_pool"}
)


def resolve_canonical_faction_name(phrase: str) -> str:
    """Resolve a variant faction name onto its canonical member faction (RC5 / Slice 13).

    Thin fallback for names that arrive as stored strings rather than links (link-based
    harvesting makes the "[Horde] [Forsaken]" adjacent-link compound structurally impossible,
    but earlier stages' stored targets can still carry one). When a name is an umbrella faction
    qualifying a registry organization, the member org's canonical registry title is the
    identity ("Horde Forsaken" -> "Forsaken"); whether the *umbrella* card also survives stays
    with :func:`_suppress_umbrella_factions` at election time. Registry-consulting, never a
    per-pair mapping or a token vocabulary.
    """
    umbrella_names = {tag.lower() for tag in umbrella_faction_tags()}
    current = phrase.strip()
    for _ in range(2):
        words = current.split()
        if len(words) < 2 or words[0].lower() not in umbrella_names:
            break
        tail = re.sub(r"^the\s+", "", " ".join(words[1:]).strip(), flags=re.IGNORECASE)
        org = organization_entry(tail) if tail else None
        if org is None:
            break
        current = str(org.get("title", tail))
    return current


def harvest_instance_faction_targets(
    *,
    instance_id: str,
    instance_name: str,
    evidence_rows: list[dict[str, Any]],
    snapshots: list[dict[str, Any]] | None = None,
    field_names: frozenset[str] | None = None,
    min_mentions: int = 3,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Harvest faction candidates from the instance's *own* evidence (Slice 13: link-based).

    Instances carry no ``faction_pool`` evidence and no faction_profile_targets of their own, so
    ``build_major_factions`` (scoped to the parent zone) returns nothing — yet pages like Scholomance
    are saturated with Scourge / Cult of the Damned. A faction identity is established by an inline
    link on an evidence block whose target is a registry organization; once established, plain-text
    mentions of that organization's name on the same page also count (wiki style links only the
    first mention), but no open-vocabulary phrase matching happens. Returns synthetic
    profile-target rows scoped to ``instance_id`` plus a flattened seed-mention role pool, which the
    existing faction scorer + summary path consumes unchanged. Returns ``([], [])`` when nothing
    clears ``min_mentions`` (callers then fall back to the parent-zone targets).

    Mention counting and role-pool building are scoped to the instance's OWN evidence
    (``_INSTANCE_OWN_EVIDENCE_FIELDS`` unless the caller narrows further): cross-page biography
    pools must never mint an instance faction (Slice 6).
    """
    if field_names is None:
        field_names = _INSTANCE_OWN_EVIDENCE_FIELDS
    role_pool: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    history_support_counts: dict[str, int] = {}
    structured_support_counts: dict[str, int] = {}
    display: dict[str, str] = {}
    instance_low = instance_name.strip().lower()
    admitted: list[tuple[dict[str, Any], dict[str, Any], frozenset[str]]] = []
    for row in evidence_rows:
        if str(row.get("field_name", "")).strip() not in field_names:
            continue
        section_role = str(row.get("section_role", row.get("field_name", "")))
        build_meta = row.get("build_meta") or {}
        # Evidence items carry no item-level ``source_id``; it lives on the pack's build_meta
        # (the source the whole pack was extracted from). Reading it from the item left every
        # harvested role-pool row with ``source_id=""``, so the faction card's provenance map
        # came back empty and tripped ``provenance.missing_card_pointers`` (instance gate fail).
        # Carry the pack source_id plus the content/raw role so pointer locators stay accurate.
        pack_source_id = str(build_meta.get("source_id", "")).strip()
        for item in row.get("evidence_items", []) or []:
            if not isinstance(item, dict):
                continue
            if is_excluded_from_card_pool(item, row=row):
                continue
            snippet = str(item.get("snippet", ""))
            if not snippet:
                continue
            role_pool.append(
                {
                    "source_id": str(item.get("source_id") or pack_source_id),
                    "snippet": snippet,
                    "section_role": str(item.get("section_role", section_role)),
                    "raw_section_role": str(item.get("raw_section_role", "")),
                    "content_role": str(item.get("content_role", "")),
                    "field_name": str(row.get("field_name", "")),
                    "source_title": str(item.get("source_title", "")),
                    "history_eligibility": str(
                        item.get("history_eligibility", build_meta.get("history_eligibility", ""))
                    ),
                }
            )
            linked_keys: set[str] = set()
            for org in _item_organization_links(item):
                phrase = str(org.get("title", "")).strip()
                if not phrase or phrase.lower() == instance_low:
                    continue
                key = phrase.lower()
                linked_keys.add(key)
                display.setdefault(key, phrase)
            admitted.append((item, row, frozenset(linked_keys)))
    # Second pass: count mentions per admitted item — a link to the organization, or (for
    # identities the page's links established) its name in the item's prose.
    for item, row, item_link_keys in admitted:
        snippet = str(item.get("snippet", ""))
        for key, name in display.items():
            if key in item_link_keys or _name_in_text(name, snippet):
                counts[key] = counts.get(key, 0) + 1
                if _item_history_eligible(item, row=row):
                    history_support_counts[key] = history_support_counts.get(key, 0) + 1
    _add_structured_instance_faction_mentions(
        snapshots=snapshots or [],
        evidence_rows=evidence_rows,
        instance_name=instance_name,
        role_pool=role_pool,
        counts=counts,
        history_support_counts=history_support_counts,
        structured_support_counts=structured_support_counts,
        display=display,
    )
    targets: list[dict[str, Any]] = []
    for key, count in counts.items():
        name = display[key]
        required_mentions = _instance_faction_required_mentions(
            name,
            min_mentions=min_mentions,
            history_support_count=history_support_counts.get(key, 0),
            structured_support_count=structured_support_counts.get(key, 0),
        )
        if count < required_mentions:
            continue
        targets.append(
            {
                "zone_id": instance_id,
                "faction_id": f"faction-{slugify(name)}",
                "name": name,
                "source_link": "",
            }
        )
    targets.sort(key=lambda row: (-counts[str(row["name"]).lower()], str(row["name"]).lower()))
    return targets, role_pool


def _add_structured_instance_faction_mentions(
    *,
    snapshots: list[dict[str, Any]],
    evidence_rows: list[dict[str, Any]],
    instance_name: str,
    role_pool: list[dict[str, Any]],
    counts: dict[str, int],
    history_support_counts: dict[str, int],
    structured_support_counts: dict[str, int],
    display: dict[str, str],
) -> None:
    snippets_by_source_role = _eligible_structured_link_contexts(evidence_rows)
    if not snippets_by_source_role:
        return
    instance_low = instance_name.strip().lower()
    seen: set[tuple[str, str, str, str]] = set()
    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            continue
        source_id = str(snapshot.get("source_id", "")).strip()
        if not source_id:
            continue
        structured_links = snapshot.get("structured_links")
        if not isinstance(structured_links, list):
            continue
        source_title = str(
            snapshot.get("title") or snapshot.get("page_title") or snapshot.get("entity_id") or ""
        )
        for link in structured_links:
            if not isinstance(link, dict):
                continue
            # Slice 13: the link's target settles org identity (registry lookup); the anchor
            # label is only a fallback for links whose href is absent (older fixtures).
            org = _organization_from_link(link) or organization_entry(
                str(link.get("label", "")).strip()
            )
            if org is None:
                continue
            phrase = str(org.get("title", "")).strip()
            if not phrase or phrase.lower() == instance_low:
                continue
            section_role = str(link.get("section_role", "")).strip()
            link_roles = [section_role] if section_role else [str(link.get("parent_section_role", "")).strip()]
            contexts: list[dict[str, Any]] = []
            for role in link_roles:
                if not role:
                    continue
                contexts.extend(snippets_by_source_role.get((source_id, _normalize_role(role)), []))
            if not contexts:
                continue
            context = _best_structured_link_context(phrase, contexts)
            if context is None:
                continue
            base_snippet = str(context.get("snippet", "")).strip()
            if not base_snippet:
                continue
            normalized_role = _normalize_role(str(context.get("raw_section_role") or context.get("section_role") or ""))
            dedupe_key = (source_id, normalized_role, phrase.lower(), base_snippet[:120])
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            key = phrase.lower()
            counts[key] = counts.get(key, 0) + 1
            structured_support_counts[key] = structured_support_counts.get(key, 0) + 1
            if _item_history_eligible(context):
                history_support_counts[key] = history_support_counts.get(key, 0) + 1
            display.setdefault(key, phrase)
            role_pool.append(
                {
                    "source_id": source_id,
                    "snippet": f"{phrase}: {base_snippet}",
                    "section_role": str(context.get("section_role", "")),
                    "raw_section_role": str(context.get("raw_section_role", "")),
                    "content_role": str(context.get("content_role", "")),
                    "field_name": str(context.get("field_name", "")),
                    "source_title": source_title,
                    "history_eligibility": str(context.get("history_eligibility", "")),
                }
            )


def _eligible_structured_link_contexts(
    evidence_rows: list[dict[str, Any]],
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    contexts: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in evidence_rows:
        if not isinstance(row, dict):
            continue
        build_meta = row.get("build_meta") or {}
        if not isinstance(build_meta, dict):
            build_meta = {}
        source_id = str(build_meta.get("source_id", "")).strip()
        if not source_id:
            continue
        field_name = str(row.get("field_name", "")).strip()
        if field_name not in _INSTANCE_OWN_EVIDENCE_FIELDS:
            continue
        for item in row.get("evidence_items", []) or []:
            if not isinstance(item, dict):
                continue
            if is_excluded_from_card_pool(item, row=row):
                continue
            scope = str(item.get("temporal_scope", build_meta.get("temporal_scope", ""))).strip()
            if field_name == "history_digest" and not _item_history_eligible(item, row=row):
                continue
            if field_name != "history_digest" and scope not in {"pre_entry_history", "entry_state"}:
                continue
            context = {
                "source_id": source_id,
                "snippet": str(item.get("snippet", "")),
                "section_role": str(item.get("section_role", row.get("section_role", ""))),
                "raw_section_role": str(
                    item.get("raw_section_role", build_meta.get("raw_section_role", ""))
                ),
                "content_role": str(item.get("content_role", build_meta.get("content_role", ""))),
                "field_name": field_name,
                "history_eligibility": str(
                    item.get("history_eligibility", build_meta.get("history_eligibility", ""))
                ),
            }
            for role in (
                context["raw_section_role"],
                context["section_role"],
                context["content_role"],
            ):
                role_key = _normalize_role(role)
                if role_key:
                    contexts.setdefault((source_id, role_key), []).append(context)
    return contexts


def _best_structured_link_context(
    phrase: str,
    contexts: list[dict[str, Any]],
) -> dict[str, Any] | None:
    phrase_low = phrase.casefold()
    token_stop = {"the", "of", "and", "a", "an", "in", "to", "for", "from"}
    tokens = [
        token.casefold()
        for token in re.findall(r"[A-Za-z']+", phrase)
        if token.casefold() not in token_stop and len(token) > 2
    ]
    best: tuple[int, dict[str, Any]] | None = None
    for context in contexts:
        snippet_low = str(context.get("snippet", "")).casefold()
        if not snippet_low:
            continue
        score = 0
        if phrase_low in snippet_low:
            score += 10
        score += sum(1 for token in tokens if re.search(rf"\b{re.escape(token)}\b", snippet_low))
        if score <= 0:
            continue
        if best is None or score > best[0]:
            best = (score, context)
    return best[1] if best else None


def harvest_instance_anchor_tokens(
    evidence_rows: list[dict[str, Any]],
    *,
    instance_name: str,
    field_names: frozenset[str] | None = None,
    top_n: int = 12,
    min_mentions: int = 3,
) -> list[str]:
    """Frequent proper nouns in the instance's evidence (places/figures: Caer Darrow, Barov,
    Lordaeron, …), used as extra zone-anchor tokens so an instance-native faction summary clears the
    anchor lint without naming the instance verbatim. Multi-word names are favored; the instance name
    and pure stop-words are excluded."""
    counts: dict[str, int] = {}
    display: dict[str, str] = {}
    instance_low = instance_name.strip().lower()
    stop = {"the", "a", "an", "of", "and", "in", "on", "after", "before", "during", "second", "war"}
    for row in evidence_rows:
        if field_names and str(row.get("field_name", "")).strip() not in field_names:
            continue
        for item in row.get("evidence_items", []) or []:
            if not isinstance(item, dict):
                continue
            if is_excluded_from_card_pool(item, row=row):
                continue
            for match in _PROPER_NOUN_PHRASE_RE.finditer(str(item.get("snippet", ""))):
                phrase = re.sub(
                    r"^the\s+", "", match.group(1).strip(), flags=re.IGNORECASE
                ).strip()
                low = phrase.lower()
                if not phrase or low == instance_low or low in stop:
                    continue
                counts[low] = counts.get(low, 0) + 1
                display.setdefault(low, phrase)
    ranked = sorted(
        (key for key, count in counts.items() if count >= min_mentions),
        key=lambda key: (-counts[key], -len(key)),
    )
    return [display[key] for key in ranked[:top_n]]


def _targets_for_zone(
    faction_profile_targets: list[dict[str, Any]] | None,
    zone_id: str,
) -> dict[str, dict[str, Any]]:
    targets: dict[str, dict[str, Any]] = {}
    for row in faction_profile_targets or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("zone_id", "")).strip() != zone_id:
            continue
        faction_id = str(row.get("faction_id", "")).strip()
        if not faction_id:
            continue
        targets[faction_id] = row
    return targets


def _candidates_from_evidence(
    evidence_rows: list[dict[str, Any]],
    zone_id: str,
) -> dict[str, dict[str, str]]:
    discovered: dict[str, dict[str, str]] = {}
    for row in evidence_rows:
        if str(row.get("field_name", "")) != "faction_pool":
            continue
        if not row_has_admissible_item(row):
            continue
        build_meta = row.get("build_meta") or {}
        subject_zone = str(build_meta.get("subject_zone_id", row.get("subject_id", ""))).strip()
        if subject_zone and subject_zone != zone_id:
            continue
        faction_id = str(build_meta.get("faction_id", "")).strip()
        if not faction_id:
            continue
        name = str(build_meta.get("faction_name", "")).strip()
        if not name:
            items = row.get("evidence_items") or []
            if items and isinstance(items[0], dict):
                name = str(items[0].get("source_title", "")).strip()
        discovered[faction_id] = {
            "name": name or faction_id.removeprefix("faction-").replace("-", " ").title(),
            "wiki_url": "",
        }
    return discovered


def _item_history_eligible(item: dict[str, Any], *, row: dict[str, Any] | None = None) -> bool:
    build_meta = (row or {}).get("build_meta") if isinstance(row, dict) else {}
    if not isinstance(build_meta, dict):
        build_meta = {}
    eligibility = str(
        item.get("history_eligibility", build_meta.get("history_eligibility", ""))
    ).strip()
    return eligibility in HISTORY_ELIGIBLE


def _instance_faction_required_mentions(
    name: str,
    *,
    min_mentions: int,
    history_support_count: int,
    structured_support_count: int = 0,
) -> int:
    if (
        min_mentions > 1
        and structured_support_count > 0
        and history_support_count > 0
        and " " in name.strip()
    ):
        return 1
    if min_mentions > 2 and history_support_count > 0 and " " in name.strip():
        return 2
    return min_mentions


def _candidates_from_high_weight_seed_mentions(
    faction_role_pool: list[dict[str, Any]],
) -> dict[str, dict[str, str]]:
    """Discover faction identities from high-weight seed evidence (Slice 13: link-based).

    A mention is an inline link on the evidence block whose target is a registry
    organization; the org's canonical registry title is the identity. No open-vocabulary
    phrase matching — plain-text matching only ever happens downstream for names these
    links (or stored targets) already established (``seed_mentions`` in
    :func:`collect_faction_candidates`).
    """
    discovered: dict[str, dict[str, str]] = {}
    for item in faction_role_pool:
        if not isinstance(item, dict) or not _is_high_weight_seed_item(item):
            continue
        snippet = str(item.get("snippet", "")).strip()
        if not snippet or has_currently_meta(snippet):
            continue
        for org in _item_organization_links(item):
            name = str(org.get("title", "")).strip()
            if not name:
                continue
            wiki_path = str(org.get("wiki_path", "")).strip()
            discovered.setdefault(
                f"faction-{slugify(name)}",
                {
                    "name": name,
                    "wiki_url": _wiki_url_from_link(wiki_path)
                    if wiki_path
                    else _wiki_url_from_name(name),
                },
            )
    return discovered


def _discover_candidates_from_v3_bindings(
    v3_rows: list[dict[str, Any]] | None,
    zone_id: str,
) -> dict[str, str]:
    discovered: dict[str, str] = {}
    if not v3_rows:
        return discovered
    for display_name, tag in umbrella_organizations().items():
        faction_id = f"faction-{slugify(display_name)}"
        bindings = frozenset({tag})
        if _count_quest_bindings(bindings, v3_rows, zone_id) >= ALLIANCE_HORDE_CONFLICT_THRESHOLD:
            discovered[faction_id] = display_name
    return discovered


def _is_high_weight_seed_item(item: dict[str, Any]) -> bool:
    role = _normalize_role(str(item.get("section_role", "")))
    field_name = str(item.get("field_name", "")).strip()
    if field_name == "currently_input":
        return True
    if role in _HIGH_WEIGHT_ROLES:
        return True
    if role.endswith("_edit") and any(token in role for token in _ERA_TOKENS):
        return True
    return False


def _candidate_is_finalize_eligible(candidate: FactionCandidate) -> bool:
    if candidate.lede_only or candidate.score <= 0:
        return False
    return _alliance_horde_conflict_met(candidate)


def _profile_affiliations_by_faction_id(
    snapshots: list[dict[str, Any]] | None,
) -> dict[str, frozenset[str]]:
    """Umbrella affiliations read from crawled faction-profile infoboxes (Slice 13).

    The org registry's category affiliations only cover the wiki's gameplay reputation
    factions (``Category:Horde factions`` holds "Undercity (faction)", not "Forsaken"),
    so lore-org umbrella membership comes from the profile page's own infobox
    ``Affiliation`` field — wiki structure, captured at ingest since Slice 12.
    """
    tags = umbrella_faction_tags()
    out: dict[str, frozenset[str]] = {}
    for snapshot in snapshots or []:
        if not isinstance(snapshot, dict):
            continue
        if str(snapshot.get("auxiliary_role", "")).strip() != "faction_profile":
            continue
        target_id = str(snapshot.get("auxiliary_target_id", "")).strip()
        infobox = snapshot.get("infobox")
        if not target_id or not isinstance(infobox, dict):
            continue
        value = ""
        for key, raw in infobox.items():
            if str(key).strip().lower() == "affiliation":
                value = str(raw)
                break
        found = frozenset(
            tag for tag in tags if re.search(rf"\b{re.escape(tag)}\b", value, re.IGNORECASE)
        )
        if found:
            out[target_id] = out.get(target_id, frozenset()) | found
    return out


def collect_faction_candidates(
    *,
    zone_id: str,
    evidence_rows: list[dict[str, Any]],
    pools: dict[str, list[dict[str, Any]]],
    faction_profile_targets: list[dict[str, Any]] | None = None,
    v3_rows: list[dict[str, Any]] | None = None,
    snapshots: list[dict[str, Any]] | None = None,
) -> list[FactionCandidate]:
    target_map = _targets_for_zone(faction_profile_targets, zone_id)
    discovered = _candidates_from_evidence(evidence_rows, zone_id)
    faction_pool = pools.get("faction_pool", [])
    faction_role_pool = pools.get("faction_role_pool", [])
    seed_discovered = _candidates_from_high_weight_seed_mentions(faction_role_pool)
    profile_affiliations = _profile_affiliations_by_faction_id(snapshots)

    candidate_ids = set(target_map) | set(discovered) | set(seed_discovered)
    v3_discovered = _discover_candidates_from_v3_bindings(v3_rows, zone_id)
    candidate_ids.update(v3_discovered)

    candidates: list[FactionCandidate] = []
    for faction_id in sorted(candidate_ids):
        target = target_map.get(faction_id, {})
        meta = discovered.get(faction_id, seed_discovered.get(faction_id, {}))
        name = str(
            target.get("name") or meta.get("name") or v3_discovered.get(faction_id) or ""
        ).strip()
        if not name:
            name = faction_id.removeprefix("faction-").replace("-", " ").title()
        link = str(target.get("source_link", "")).strip()
        wiki_url = _wiki_url_from_link(link) if link else _wiki_url_from_name(name)

        profile_items = [
            item
            for item in faction_pool
            if str(item.get("faction_id", "")).strip() == faction_id
            or (
                not str(item.get("faction_id", "")).strip()
                and name.lower() in str(item.get("source_title", "")).lower()
            )
        ]
        seed_mentions = [
            item for item in faction_role_pool if _name_in_text(name, str(item.get("snippet", "")))
        ]

        affiliations = profile_affiliations.get(faction_id, frozenset()) | entry_affiliations(name)
        bindings = _bindings_for_faction(faction_id, name, affiliations)
        candidates.append(
            FactionCandidate(
                faction_id=faction_id,
                name=name,
                wiki_url=wiki_url,
                profile_items=profile_items,
                seed_mentions=seed_mentions,
                quest_binding_count=_count_quest_bindings(bindings, v3_rows or [], zone_id),
                specific_quest_binding_count=_count_specific_quest_bindings(
                    bindings, v3_rows or [], zone_id
                ),
                affiliations=affiliations,
            )
        )

    return merge_variant_faction_candidates(candidates)


def merge_variant_faction_candidates(
    candidates: list[FactionCandidate],
) -> list[FactionCandidate]:
    """Collapse variant faction candidates onto one canonical faction, merging evidence (RC5).

    Candidates arrive from several harvests (profile targets, evidence pools, seed mentions), and
    a variant name that slipped past phrase canonicalization in an earlier stage's stored targets
    can mint a second identity for the same faction ("Horde Forsaken" beside "Forsaken"). Each
    candidate's name is resolved to its canonical faction (registry-consulting, Slice 13 —
    link-based harvesting already dedupes by canonical article, so this only catches stored
    string variants): when the canonical sibling was also harvested, the variant's pooled
    evidence is deduped onto that survivor so the retained card is richer; a variant with no
    harvested sibling is renamed to the canonical identity instead.
    """
    by_id = {candidate.faction_id: candidate for candidate in candidates}
    merged: list[FactionCandidate] = []
    for candidate in candidates:
        canonical_name = resolve_canonical_faction_name(candidate.name)
        if canonical_name.strip().lower() == candidate.name.strip().lower():
            merged.append(candidate)
            continue
        canonical_id = f"faction-{slugify(canonical_name)}"
        survivor = by_id.get(canonical_id)
        if survivor is None or survivor is candidate:
            candidate.faction_id = canonical_id
            candidate.name = canonical_name
            candidate.wiki_url = _wiki_url_from_name(canonical_name)
            by_id[canonical_id] = candidate
            merged.append(candidate)
            continue
        for item in candidate.profile_items:
            if item not in survivor.profile_items:
                survivor.profile_items.append(item)
        for item in candidate.seed_mentions:
            if item not in survivor.seed_mentions:
                survivor.seed_mentions.append(item)
        survivor.quest_binding_count = max(
            survivor.quest_binding_count, candidate.quest_binding_count
        )
        survivor.specific_quest_binding_count = max(
            survivor.specific_quest_binding_count, candidate.specific_quest_binding_count
        )
        survivor.affiliations = survivor.affiliations | candidate.affiliations
    return merged


def _is_lede_only_profile(candidate: FactionCandidate) -> bool:
    if candidate.seed_mentions:
        return False
    if not candidate.profile_items:
        return False
    roles = {_normalize_role(str(item.get("section_role", ""))) for item in candidate.profile_items}
    return roles.issubset(_LEDE_ROLES) and len(candidate.profile_items) <= 2


def alliance_horde_conflict_met(
    *,
    faction_id: str,
    quest_binding_count: int,
    seed_mentions: list[dict[str, Any]],
) -> bool:
    if faction_id not in _umbrella_faction_ids():
        return True
    if quest_binding_count >= ALLIANCE_HORDE_CONFLICT_THRESHOLD:
        return True
    for item in seed_mentions:
        snippet = str(item.get("snippet", ""))
        if has_currently_meta(snippet):
            continue
        if _is_high_weight_seed_item(item):
            return True
    return False


def _alliance_horde_conflict_met(candidate: FactionCandidate) -> bool:
    return alliance_horde_conflict_met(
        faction_id=candidate.faction_id,
        quest_binding_count=candidate.quest_binding_count,
        seed_mentions=candidate.seed_mentions,
    )


def score_faction_candidate(
    candidate: FactionCandidate,
    *,
    zone_name: str = "",
    subregion_tokens: list[str] | None = None,
) -> FactionCandidate:
    score = 0.0
    has_high = False
    tokens = subregion_tokens or []

    for item in candidate.seed_mentions:
        snippet = str(item.get("snippet", ""))
        if has_currently_meta(snippet):
            continue
        role = _normalize_role(str(item.get("section_role", "")))
        field_name = str(item.get("field_name", ""))
        zone_hit = _name_in_text(zone_name, snippet) or any(
            _name_in_text(token, snippet) for token in tokens
        )
        if _is_high_weight_seed_item(item):
            score += 3.0 + (1.5 if zone_hit else 0.0)
            has_high = True
        elif field_name in {"currently_input", "history_digest"} or role.startswith("history"):
            score += 1.5 + (1.0 if zone_hit else 0.0)
        else:
            score += 0.75 + (0.5 if zone_hit else 0.0)

    if candidate.profile_items:
        profile_zone_hit = any(
            _name_in_text(zone_name, str(item.get("snippet", "")))
            or any(_name_in_text(token, str(item.get("snippet", ""))) for token in tokens)
            for item in candidate.profile_items
        )
        score += 2.0 if profile_zone_hit else 1.0

    if candidate.specific_quest_binding_count:
        score += min(candidate.specific_quest_binding_count * 1.5, _SPECIFIC_BINDING_SCORE_CAP)
        if candidate.specific_quest_binding_count >= ALLIANCE_HORDE_CONFLICT_THRESHOLD:
            score += ACTIVE_COMBATANT_BONUS

    candidate.has_high_weight_seed = has_high
    candidate.lede_only = _is_lede_only_profile(candidate)

    if (
        candidate.lede_only
        and not candidate.seed_mentions
        and candidate.specific_quest_binding_count == 0
    ):
        lede_has_zone = any(
            _name_in_text(zone_name, str(item.get("snippet", "")))
            or any(_name_in_text(token, str(item.get("snippet", ""))) for token in tokens)
            for item in candidate.profile_items
        )
        if not lede_has_zone:
            candidate.score = 0.0
            return candidate

    if candidate.faction_id in _umbrella_faction_ids() and not _alliance_horde_conflict_met(
        candidate
    ):
        candidate.score = min(score, 1.0)
        return candidate

    candidate.score = score
    return candidate


def rank_faction_candidates(
    candidates: list[FactionCandidate],
    *,
    zone_name: str = "",
    subregion_tokens: list[str] | None = None,
) -> list[FactionCandidate]:
    scored = [
        score_faction_candidate(candidate, zone_name=zone_name, subregion_tokens=subregion_tokens)
        for candidate in candidates
    ]
    return sorted(
        scored,
        key=lambda row: (
            -row.score,
            -len(row.profile_items),
            row.name.lower(),
        ),
    )


def _suppress_umbrella_factions(ranked: list[FactionCandidate]) -> list[FactionCandidate]:
    """Drop a generic umbrella faction when a specific member of its side is elected.

    When a member is already elected (e.g. Forsaken — a Horde sub-faction that controls
    Andorhal), the generic umbrella is redundant and is dropped so the card list names the
    concrete actor instead of "Horde". The opposite side keeps its umbrella when no specific
    member is elected (no Alliance sub-faction surfaces in WPL, so "Alliance" stays). The
    umbrella set and each member's side come from the registry/infobox affiliations (Slice 13).
    """
    elected_ids = {candidate.faction_id for candidate in ranked}
    drop: set[str] = set()
    for umbrella_id, tag in _umbrella_tag_by_faction_id().items():
        if umbrella_id not in elected_ids:
            continue
        for candidate in ranked:
            if candidate.faction_id == umbrella_id:
                continue
            if tag in _bindings_for_candidate(candidate):
                drop.add(umbrella_id)
                break
    if not drop:
        return ranked
    return [candidate for candidate in ranked if candidate.faction_id not in drop]


def select_major_factions(
    candidates: list[FactionCandidate],
    *,
    zone_name: str = "",
    subregion_tokens: list[str] | None = None,
) -> list[FactionCandidate]:
    ranked = rank_faction_candidates(
        candidates, zone_name=zone_name, subregion_tokens=subregion_tokens
    )
    eligible = [
        candidate
        for candidate in ranked
        if candidate.score >= MIN_SCORE and not candidate.lede_only
    ]
    if not eligible:
        thin = [candidate for candidate in ranked if _candidate_is_finalize_eligible(candidate)]
        return _suppress_umbrella_factions(thin)[:MAX_FACTION_CARDS]
    return _suppress_umbrella_factions(eligible)[:MAX_FACTION_CARDS]


def candidates_for_finalize(
    candidates: list[FactionCandidate],
    *,
    zone_name: str = "",
    subregion_tokens: list[str] | None = None,
) -> tuple[int, list[FactionCandidate]]:
    ranked = rank_faction_candidates(
        candidates, zone_name=zone_name, subregion_tokens=subregion_tokens
    )
    target_count = len(
        select_major_factions(candidates, zone_name=zone_name, subregion_tokens=subregion_tokens)
    )
    has_eligible = any(
        candidate.score >= MIN_SCORE and not candidate.lede_only for candidate in ranked
    )
    if has_eligible:
        queue = [
            candidate
            for candidate in ranked
            if candidate.score >= MIN_SCORE
            and not candidate.lede_only
            and _alliance_horde_conflict_met(candidate)
        ]
    else:
        queue = [candidate for candidate in ranked if _candidate_is_finalize_eligible(candidate)]
    return target_count, _suppress_umbrella_factions(queue)


# How many profile-page items join the merged finalize pool as identity context (Slice 6:
# "1-2 profile identity lead items").
_PROFILE_IDENTITY_LEAD_ITEMS = 2


def finalize_evidence_pools(candidate: FactionCandidate) -> list[dict[str, Any]]:
    """Merge a candidate's evidence into ONE synthesis pool: zone-role evidence first (Slice 6).

    The old profile-first pool ladder burned every synthesis retry on the faction's generic
    profile biography and left a single attempt for the zone-role evidence, so a validly-elected
    faction could drop because its *profile* prose never mentions the zone (Cause A). The merged
    pool leads with the zone-role evidence (seed mentions: history/currently/questline/
    at-a-glance claim views naming the faction) and appends 1-2 profile *lead* items as identity
    context, so one full-retry synthesis call sees both. When the profile carries no lede-role
    item, its leading items stand in — a profile-only candidate must still reach synthesis
    rather than silently losing its pool.
    """
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def _add(item: dict[str, Any]) -> bool:
        key = (str(item.get("source_id", "")), str(item.get("snippet", "")))
        if key in seen:
            return False
        seen.add(key)
        merged.append(item)
        return True

    for item in candidate.seed_mentions:
        _add(item)
    lead_items = [
        item
        for item in candidate.profile_items
        if _normalize_role(str(item.get("section_role", ""))) in _LEDE_ROLES
    ] or candidate.profile_items
    added = 0
    for item in lead_items:
        if added >= _PROFILE_IDENTITY_LEAD_ITEMS:
            break
        if _add(item):
            added += 1
    return merged


def fallback_faction_summary(
    items: list[dict[str, Any]],
    *,
    max_words: int = MAX_FACTION_SUMMARY_WORDS,
    zone_name: str = "",
    subregion_tokens: list[str] | None = None,
    faction_name: str = "",
) -> tuple[str, list[str]]:
    if not items:
        return "", []
    tokens = subregion_tokens or []

    def _zone_rank(item: dict[str, Any]) -> tuple[int, int, int]:
        snippet = str(item.get("snippet", ""))
        # Prefer a snippet that actually names this faction over a longer/zone-dense one that does
        # not: borrowing the highest-ranked zone snippet regardless of subject filled an Alliance
        # card with a Cenarion-Circle paragraph (it never mentioned the Alliance at all).
        faction_hit = _name_in_text(faction_name, snippet)
        zone_hit = _name_in_text(zone_name, snippet) or any(
            _name_in_text(token, snippet) for token in tokens
        )
        return (1 if faction_hit else 0, 1 if zone_hit else 0, word_count(snippet))

    from pipeline.generate.draft.faction_lint import (
        lint_faction_summary,
        strip_faction_label_prefix,
    )
    from pipeline.generate.draft.prose_gate import prose_gate_rejects

    ranked = sorted(items, key=_zone_rank, reverse=True)

    def _clean_summary(item: dict[str, Any]) -> str:
        # Strip the internal "<Faction>: " binding label before borrowing the snippet as prose.
        snippet = strip_faction_label_prefix(str(item.get("snippet", "")).strip(), faction_name)
        if has_currently_meta(snippet) or detect_list_shape(snippet):
            return ""
        source = _faction_focused_excerpt(
            snippet,
            faction_name=faction_name,
            zone_name=zone_name,
            subregion_tokens=tokens,
        )
        summary = trim_faction_summary(source or snippet, max_words)
        return summary if summary and not detect_list_shape(summary) else ""

    # First pass: prefer a snippet whose summary actually clears BOTH the faction lint (zone anchor,
    # subject mention, tense floor) and the deterministic prose gate — the same checks the card
    # finalizer applies.
    # The deterministic path must reliably yield a publishable card when the evidence supports one,
    # rather than depending on the LLM summary passing: instance factions (Scourge, Cult of the
    # Damned) otherwise drop to [] on an unlucky LLM phrasing.
    for item in ranked:
        summary = _clean_summary(item)
        if (
            summary
            and not lint_faction_summary(
                summary,
                zone_name=zone_name,
                subregion_tokens=tokens,
                faction_name=faction_name,
            )
            and not prose_gate_rejects(summary)
        ):
            source_id = str(item.get("source_id", "")).strip()
            return summary, [source_id] if source_id else []
    # Second pass: any clean (non-list) snippet, even if it trips a soft lint.
    for item in ranked:
        summary = _clean_summary(item)
        if summary:
            source_id = str(item.get("source_id", "")).strip()
            return summary, [source_id] if source_id else []
    return "", []


def _faction_focused_excerpt(
    snippet: str,
    *,
    faction_name: str,
    zone_name: str,
    subregion_tokens: list[str],
) -> str:
    if not faction_name or not _name_in_text(faction_name, snippet):
        return snippet
    sentences = split_sentences(snippet.strip())
    if len(sentences) <= 1:
        return snippet
    faction_index = next(
        (index for index, sentence in enumerate(sentences) if _name_in_text(faction_name, sentence)),
        -1,
    )
    if faction_index < 0:
        return snippet
    selected = [sentences[faction_index]]
    anchor_terms = [zone_name, *subregion_tokens]

    def _has_anchor(text: str) -> bool:
        return any(term and _name_in_text(term, text) for term in anchor_terms)

    if not _has_anchor(" ".join(selected)) and faction_index + 1 < len(sentences):
        selected.append(sentences[faction_index + 1])
    if word_count(" ".join(selected)) < MIN_FACTION_SUMMARY_WORDS and faction_index > 0:
        selected.insert(0, sentences[faction_index - 1])
    return " ".join(selected)
