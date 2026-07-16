"""Structural boss/encounter parsing from instance wiki section blocks."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pipeline.common import wiki_html
from pipeline.common.text_ids import slugify
from pipeline.common.text_normalize import clean_wiki_snippet
from pipeline.contracts.models import EntityKind
from pipeline.discovery.entity_typing import normalize_title

_WIKI_LINK_RE = re.compile(r"/wiki/([^|\s\]#<>\"']+)")
_WIKITEXT_LINK_RE = re.compile(r"\[\[([^|\]#]+)(?:\|[^\]]+)?\]\]")
_BOSS_SECTION_TOKENS = (
    "adventurer",
    "encounter",
    "boss",
    "dungeon",
    "adventure_guide",
    "walkthrough",
    "denizen",
    "dungeon_journal",
    "adventurers_guide",
    "layout",
    "notable",
    "character",
    "npc",
    "monster",
    "inhabit",
    "force",
)
_BOSS_SECTION_EXACT = frozenset(
    {
        "bosses",
        "denizens",
        "inhabitants",
    }
)
# Boss-class section roles for must-include floor (Option F). Not used for roster harvest.
HIGH_CONFIDENCE_BOSS_SECTION_TOKENS = (
    "boss",
    "encounter",
    "dungeon_journal",
    "adventure_guide",
)
@dataclass
class BossCandidate:
    boss_id: str
    name: str
    wiki_url: str
    source_section_role: str
    profile_pool: list[dict[str, Any]] = field(default_factory=list)
    significance: float = 0.0
    role: str = "uncertain"
    role_reason: str = ""
    canonical_path: str = ""
    entity_kind: EntityKind = EntityKind.UNKNOWN
    entity_kind_decision_id: str = ""
    instance_presence_evidence: list[str] = field(default_factory=list)
    retail_scope: str = "unknown"
    retail_scope_evidence: list[str] = field(default_factory=list)
    encounter_relation_evidence: list[str] = field(default_factory=list)
    admission_reason_codes: list[str] = field(default_factory=list)


def _normalize_role(section_role: str) -> str:
    return re.sub(r"\s+", " ", section_role.strip()).lower().replace(" ", "_")


# Trash/mob roster sections. A name appearing only here (e.g. a random skeleton like
# "Grandmaster Architect Holmberg") is a denizen, not a boss, so it must never reach the floor.
_DENIZEN_SECTION_TOKENS = ("denizen", "inhabitant")


def _is_denizen_section(lowered_role: str) -> bool:
    return any(token in lowered_role for token in _DENIZEN_SECTION_TOKENS)


def is_high_confidence_boss_section(section_role: str) -> bool:
    """True for an authoritative boss-roster section that seeds the must-include floor.

    Covers the dungeon journal / adventure guide / encounter lists and the per-dungeon boss table
    (``dungeon_<name>``) — but never the denizens/inhabitants trash list. This is the structural
    boss roster; a name here is a boss, a name only in denizens is not. Detection is structural
    (no instance-specific theme words — a themed roster heading like "Faculty" reaches boss_pool via
    its per-dungeon table / adventure guide, not a hardcoded label).
    """
    lowered = _normalize_role(section_role)
    if _is_denizen_section(lowered):
        return False
    if any(token in lowered for token in HIGH_CONFIDENCE_BOSS_SECTION_TOKENS):
        return True
    # Per-dungeon boss table, e.g. "dungeon_scholomance" (denizens already excluded above).
    return lowered.startswith("dungeon_")


def is_direct_instance_participant_section(section_role: str) -> bool:
    """Whether a section role itself proves roster membership in this instance.

    Broad Adventure Guide and guide prose supply useful encounter leads, but a
    named link in that prose can describe ancestry, history, or a nearby place.
    Only roster-shaped encounter/journal/table sections establish direct
    participant presence; the entity-kind contract then decides whether the
    participant is an individual actor rather than a generic creature or term.
    """
    lowered = _normalize_role(section_role)
    if _is_denizen_section(lowered):
        return True
    if lowered.startswith("dungeon_"):
        return True
    return any(token in lowered for token in ("encounter", "dungeon_journal")) or lowered == "bosses"


def is_boss_section_role(section_role: str) -> bool:
    """Return True when a wiki section role should contribute boss_pool / encounter evidence."""
    lowered = _normalize_role(section_role)
    if lowered in _BOSS_SECTION_EXACT:
        return True
    if lowered.startswith("dungeon_"):
        return True
    return any(token in lowered for token in _BOSS_SECTION_TOKENS)


def boss_section_role_matches(section_role: str) -> bool:
    """Alias for is_boss_section_role (shared enrich + draft entry point)."""
    return is_boss_section_role(section_role)


def row_has_roster_role(row: dict[str, Any]) -> bool:
    """True when a block/structured link is roster-bearing by its leaf or parent section role."""
    if is_boss_section_role(str(row.get("section_role", "other"))):
        return True
    parent = str(row.get("parent_section_role", "")).strip()
    return bool(parent) and is_boss_section_role(parent)


def _title_from_wiki_path(path: str) -> str:
    return path.replace("_", " ").strip()


def _wiki_path_from_url(url: str) -> str:
    """Return the bare ``Title_With_Underscores`` path from a wiki URL/href."""
    value = str(url).strip()
    if "/wiki/" in value:
        value = value[value.index("/wiki/") + len("/wiki/") :]
    return value.split("#", 1)[0].strip().strip("/")


def _canonical_index_from_structured_links(
    structured_links: list[dict[str, Any]] | None,
) -> dict[str, str]:
    """Map normalized href path -> canonical_path using ingest-resolved identity.

    Lets candidates from any source (structured links, section blocks, boss_pool)
    collapse to the same entry when their links redirect to one canonical page.
    """
    index: dict[str, str] = {}
    for row in structured_links or []:
        if not isinstance(row, dict):
            continue
        href_path = _wiki_path_from_url(str(row.get("href", "")))
        canonical = str(row.get("canonical_path", "")).strip()
        if href_path and canonical:
            index[href_path.lower()] = canonical
    return index


def _slug_id(name: str) -> str:
    slug = slugify(name)
    return f"character-{slug}" if slug else ""


def should_reject_boss_title(title: str, *, instance_name: str = "") -> bool:
    lowered = normalize_title(title)
    if not lowered or len(lowered) < 3:
        return True
    if instance_name and lowered == normalize_title(instance_name):
        return True
    return False


def _append_wiki_link(
    results: list[tuple[str, str]],
    seen: set[str],
    *,
    path: str,
) -> None:
    path = path.split("#", 1)[0].strip()
    if not path:
        return
    title = _title_from_wiki_path(path)
    key = normalize_title(title)
    if not key or key in seen:
        return
    seen.add(key)
    url = f"https://warcraft.wiki.gg/wiki/{path}"
    results.append((title, url))


def _extract_wiki_links(text: str) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    seen: set[str] = set()
    for match in _WIKI_LINK_RE.finditer(text):
        _append_wiki_link(results, seen, path=match.group(1))
    for match in _WIKITEXT_LINK_RE.finditer(text):
        raw = match.group(1).strip()
        if raw.startswith("/wiki/"):
            _append_wiki_link(results, seen, path=raw.removeprefix("/wiki/"))
            continue
        if raw.startswith("http") or "://" in raw:
            continue
        _append_wiki_link(results, seen, path=raw.replace(" ", "_"))
    return results


def valid_boss_names_from_pool_items(
    boss_pool_items: list[dict[str, Any]],
    *,
    instance_name: str = "",
    section_filter: Callable[[str], bool] | None = None,
) -> set[str]:
    """Derive normalized boss names from boss_pool evidence snippets."""
    names: set[str] = set()
    for item in boss_pool_items:
        section_role = str(item.get("section_role", "boss_pool"))
        if section_filter is not None and not section_filter(section_role):
            continue
        for title, _url in _extract_wiki_links(str(item.get("snippet", ""))):
            if should_reject_boss_title(title, instance_name=instance_name):
                continue
            names.add(normalize_title(title))
    return names


def _plain_snippet(text: str) -> str:
    return clean_wiki_snippet(wiki_html.strip_tags(text))


def _profile_pool_for_boss(
    boss_name: str,
    *,
    boss_pool_items: list[dict[str, Any]],
    section_blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    pattern = re.compile(rf"\b{re.escape(boss_name)}\b", re.IGNORECASE)
    slug_pattern = re.compile(
        rf"/wiki/{re.escape(boss_name.replace(' ', '_'))}\b",
        re.IGNORECASE,
    )
    default_source_id = (
        str(boss_pool_items[0].get("source_id", "")).strip() if boss_pool_items else ""
    )
    pool: list[dict[str, Any]] = []
    for item in boss_pool_items:
        raw_snippet = str(item.get("snippet", ""))
        snippet = _plain_snippet(raw_snippet)
        if (
            pattern.search(snippet)
            or slug_pattern.search(snippet)
            or slug_pattern.search(raw_snippet)
        ):
            pool.append({**item, "snippet": snippet})
    for block in section_blocks:
        if not isinstance(block, dict):
            continue
        raw_text = str(block.get("text", ""))
        text = _plain_snippet(raw_text)
        if not (pattern.search(text) or slug_pattern.search(text) or slug_pattern.search(raw_text)):
            continue
        role = str(block.get("section_role", "other"))
        pool.append(
            {
                "snippet": text,
                "section_role": role,
                "source_id": default_source_id,
                "field_name": "boss_pool",
            }
        )
    return pool


def _section_weight(section_role: str) -> int:
    role = _normalize_role(section_role)
    if any(token in role for token in ("boss", "encounter", "dungeon_journal", "adventure_guide")):
        return 5
    if any(token in role for token in ("force", "faculty", "denizen", "inhabit")):
        return 4
    if any(token in role for token in ("npc", "notable", "character")):
        return 3
    if any(token in role for token in ("monster", "walkthrough", "layout", "dungeon")):
        return 2
    if role == "narrative_fallback":
        return 2
    return 1


def _significance_score(candidate: BossCandidate) -> float:
    """Rank a candidate by section weight, evidence depth, and name mentions."""
    weight = _section_weight(candidate.source_section_role)
    pool = candidate.profile_pool or []
    name_lower = candidate.name.lower()
    mentions = sum(str(item.get("snippet", "")).lower().count(name_lower) for item in pool)
    return weight * 100 + min(len(pool), 10) * 5 + min(mentions, 20)


def classify_character_role(
    candidate: BossCandidate, *, instance_name: str = ""
) -> tuple[str, str]:
    """Return the deterministic role verdict, which is always ``("uncertain", "no_signal")``.

    Slice 10 (H-3): character role — enemy / ally / neutral — is a semantic judgment, not one a
    keyword ladder can make reliably (a boss-section roster mixes Scourge enemies with escorted
    allies; "war" prose tags a memorial as a battlefield). The descriptor/lean-token scoring was
    retired here; structural signals (boss-section membership, Adventure Guide, roster links) now
    drive only *presence/eligibility* (see ``is_high_confidence_boss_section`` /
    ``must_include_key_character_names``). Role is deferred to the LLM classifier for every emitted
    card; offline the role stays honestly ``uncertain`` rather than keyword-guessed. ``candidate``
    and ``instance_name`` are retained for call-site symmetry.
    """
    return "uncertain", "no_signal"


def _rank_candidates(candidates: list[BossCandidate], *, instance_name: str) -> list[BossCandidate]:
    """Assign significance + deterministic role, then order by significance desc."""
    for candidate in candidates:
        candidate.significance = _significance_score(candidate)
        candidate.role, candidate.role_reason = classify_character_role(
            candidate, instance_name=instance_name
        )
    return sorted(candidates, key=lambda row: (-row.significance, row.name.lower()))


def _candidate_path_key(
    candidate: BossCandidate,
    *,
    canonical_index: dict[str, str] | None = None,
) -> str:
    href_path = _wiki_path_from_url(candidate.wiki_url)
    canonical_path = (canonical_index or {}).get(href_path.lower(), "")
    identity_path = (canonical_path or href_path).lower()
    if identity_path:
        return f"path:{identity_path}"
    return f"title:{normalize_title(candidate.name)}"


def _merge_profile_pools(
    existing: BossCandidate,
    incoming: BossCandidate,
) -> None:
    seen = {
        (str(item.get("snippet", "")), str(item.get("section_role", "")))
        for item in existing.profile_pool or []
    }
    for item in incoming.profile_pool or []:
        signature = (str(item.get("snippet", "")), str(item.get("section_role", "")))
        if signature in seen:
            continue
        existing.profile_pool.append(item)
        seen.add(signature)


def _merge_candidate_into(
    merged: dict[str, BossCandidate],
    incoming: BossCandidate,
    *,
    canonical_index: dict[str, str],
    order: list[str],
) -> None:
    key = _candidate_path_key(incoming, canonical_index=canonical_index)
    if key not in merged:
        merged[key] = incoming
        order.append(key)
        return
    existing = merged[key]
    if is_boss_section_role(incoming.source_section_role) and not is_boss_section_role(
        existing.source_section_role
    ):
        existing.source_section_role = incoming.source_section_role
    _merge_profile_pools(existing, incoming)
    for attr in ("instance_presence_evidence", "encounter_relation_evidence"):
        existing_values = getattr(existing, attr)
        for value in getattr(incoming, attr):
            if value not in existing_values:
                existing_values.append(value)


def _collect_roster_candidates(
    *,
    section_blocks: list[dict[str, Any]],
    instance_name: str,
    boss_pool_items: list[dict[str, Any]] | None = None,
    structured_links: list[dict[str, Any]] | None = None,
) -> list[BossCandidate]:
    """Parse boss names from encounter sections, structured links, and boss_pool evidence."""
    boss_pool_items = boss_pool_items or []
    candidates: dict[str, BossCandidate] = {}
    canonical_index = _canonical_index_from_structured_links(structured_links)

    def _register(title: str, url: str, role: str) -> None:
        href_path = _wiki_path_from_url(url)
        canonical_path = canonical_index.get(href_path.lower(), "")
        display_title = title
        if canonical_path and canonical_path.lower() != href_path.lower():
            canonical_title = _title_from_wiki_path(canonical_path)
            if canonical_title and not should_reject_boss_title(
                canonical_title, instance_name=instance_name
            ):
                display_title = canonical_title
                url = f"https://warcraft.wiki.gg/wiki/{canonical_path}"
        if should_reject_boss_title(display_title, instance_name=instance_name):
            return
        boss_id = _slug_id(display_title)
        if not boss_id:
            return
        identity_path = (canonical_path or href_path).lower()
        if identity_path:
            key = f"path:{identity_path}"
        else:
            key = f"title:{normalize_title(display_title)}"
        if key in candidates:
            existing = candidates[key]
            new_is_roster = is_boss_section_role(role)
            if new_is_roster and not is_boss_section_role(existing.source_section_role):
                existing.source_section_role = role
            presence = f"instance_section:{_normalize_role(role)}"
            if (
                is_direct_instance_participant_section(role)
                and presence not in existing.instance_presence_evidence
            ):
                existing.instance_presence_evidence.append(presence)
            relation = (
                "high_confidence_encounter_roster"
                if is_high_confidence_boss_section(role)
                else "instance_roster_link"
            )
            if relation not in existing.encounter_relation_evidence:
                existing.encounter_relation_evidence.append(relation)
            return
        relation = (
            "high_confidence_encounter_roster"
            if is_high_confidence_boss_section(role)
            else "instance_roster_link"
        )
        candidates[key] = BossCandidate(
            boss_id=boss_id,
            name=display_title,
            wiki_url=url,
            source_section_role=role,
            canonical_path=f"/wiki/{(canonical_path or href_path).replace(' ', '_')}",
            instance_presence_evidence=(
                [f"instance_section:{_normalize_role(role)}"]
                if is_direct_instance_participant_section(role)
                else []
            ),
            encounter_relation_evidence=[relation],
        )

    for block in section_blocks:
        if not isinstance(block, dict):
            continue
        if not row_has_roster_role(block):
            continue
        leaf_role = str(block.get("section_role", "other"))
        role = (
            leaf_role
            if is_boss_section_role(leaf_role)
            else str(block.get("parent_section_role", leaf_role))
        )
        text = str(block.get("text", ""))
        for title, url in _extract_wiki_links(text):
            _register(title, url, role)

    for row in structured_links or []:
        if not isinstance(row, dict):
            continue
        if not row_has_roster_role(row):
            continue
        href = str(row.get("href", "")).strip()
        if not href.startswith("/wiki/"):
            continue
        path = href.removeprefix("/wiki/").split("#", 1)[0].strip()
        if not path:
            continue
        title = str(row.get("label", "")).strip() or _title_from_wiki_path(path)
        role = str(row.get("section_role", "structured_link"))
        url = href if href.startswith("http") else f"https://warcraft.wiki.gg/wiki/{path}"
        _register(title, url, role)

    for item in boss_pool_items:
        for title, url in _extract_wiki_links(str(item.get("snippet", ""))):
            _register(title, url, str(item.get("section_role", "boss_pool")))

    collected = list(candidates.values())
    for candidate in collected:
        candidate.profile_pool = _profile_pool_for_boss(
            candidate.name,
            boss_pool_items=boss_pool_items,
            section_blocks=section_blocks,
        )
    return collected


def collect_boss_candidates(
    *,
    section_blocks: list[dict[str, Any]],
    instance_name: str,
    boss_pool_items: list[dict[str, Any]] | None = None,
    structured_links: list[dict[str, Any]] | None = None,
) -> list[BossCandidate]:
    """Ranked roster candidates (legacy emit path until Option F S3 wire-up)."""
    return _rank_candidates(
        _collect_roster_candidates(
            section_blocks=section_blocks,
            instance_name=instance_name,
            boss_pool_items=boss_pool_items,
            structured_links=structured_links,
        ),
        instance_name=instance_name,
    )


def _candidates_from_pool_items(
    pool_items: list[dict[str, Any]],
    *,
    instance_name: str,
    default_section_role: str,
) -> list[BossCandidate]:
    """Mine person-like wiki links from evidence pool snippets (history/overview)."""
    results: list[BossCandidate] = []
    seen: set[str] = set()
    for item in pool_items:
        if not isinstance(item, dict):
            continue
        snippet = str(item.get("snippet", ""))
        section_role = str(item.get("section_role", default_section_role))
        for title, url in _extract_wiki_links(snippet):
            if should_reject_boss_title(title, instance_name=instance_name):
                continue
            key = normalize_title(title)
            if key in seen:
                continue
            seen.add(key)
            boss_id = _slug_id(title)
            if not boss_id:
                continue
            candidate = BossCandidate(
                boss_id=boss_id,
                name=title,
                wiki_url=url,
                source_section_role=section_role,
                canonical_path=f"/wiki/{_wiki_path_from_url(url).replace(' ', '_')}",
            )
            candidate.profile_pool = [
                {**item, "snippet": _plain_snippet(snippet), "section_role": section_role}
            ]
            results.append(candidate)
    return results


def collect_character_pool(
    *,
    section_blocks: list[dict[str, Any]],
    instance_name: str,
    boss_pool_items: list[dict[str, Any]] | None = None,
    structured_links: list[dict[str, Any]] | None = None,
    narrative_pool: list[dict[str, Any]] | None = None,
    history_pool: list[dict[str, Any]] | None = None,
) -> list[BossCandidate]:
    """Unified wiki-linked candidate pool: roster + narrative + history (unranked)."""
    boss_pool_items = boss_pool_items or []
    canonical_index = _canonical_index_from_structured_links(structured_links)
    roster = _collect_roster_candidates(
        section_blocks=section_blocks,
        instance_name=instance_name,
        boss_pool_items=boss_pool_items,
        structured_links=structured_links,
    )
    narrative = mine_narrative_character_candidates(
        section_blocks,
        instance_name=instance_name,
        structured_links=structured_links,
        narrative_pool=narrative_pool,
        max_count=100,
        apply_rank=False,
    )
    evidence_items = list(history_pool or []) + list(narrative_pool or [])
    history_candidates = _candidates_from_pool_items(
        evidence_items,
        instance_name=instance_name,
        default_section_role="history_digest",
    )

    merged: dict[str, BossCandidate] = {}
    order: list[str] = []
    for candidate in roster + narrative + history_candidates:
        _merge_candidate_into(merged, candidate, canonical_index=canonical_index, order=order)

    combined_pool_items = boss_pool_items + list(narrative_pool or []) + list(history_pool or [])
    result = [merged[key] for key in order]
    for candidate in result:
        candidate.profile_pool = _profile_pool_for_boss(
            candidate.name,
            boss_pool_items=combined_pool_items,
            section_blocks=section_blocks,
        )
    return result


def _family_surname_names(candidates: list[BossCandidate]) -> set[str]:
    """Surname tokens that recur as the last name of a multi-token character in the pool.

    A bare token equal to such a surname (e.g. "Barov" alongside "Jandice Barov" /
    "Lord Alexei Barov") is a family/house reference, not an individual NPC, and is
    structurally distinguishable without a denylist (#4).
    """
    surnames: set[str] = set()
    for candidate in candidates:
        words = normalize_title(candidate.name).split()
        if len(words) >= 2:
            surnames.add(words[-1])
    return surnames


def _is_family_or_surname_reference(name: str, surnames: set[str]) -> bool:
    norm = normalize_title(name)
    if not norm:
        return False
    if norm.endswith(" family"):
        return True
    words = norm.split()
    if len(words) != 1:
        return False
    token = words[0]
    # Bare surname, or its plural/house form ("Barovs"), shared with a full-name character.
    return token in surnames or (token.endswith("s") and token[:-1] in surnames)


def prefilter_character_pool(
    candidates: list[BossCandidate],
    *,
    instance_name: str,
    excluded_normalized_names: set[str] | None = None,
) -> list[BossCandidate]:
    """Drop registry/meta rejects (and any S3-excluded names); preserve discovery order.

    ``excluded_normalized_names`` carries the S3 retail/Classic exclusion set: the
    page's Classic-categorized candidates (captured at traverse) unioned with the
    known-Classic backstop denylist. Names are compared via ``normalize_title``.

    A bare surname/family token that duplicates a full-name character already in the pool
    is also dropped (#4) — a structural check against the pool, not a denylist.
    """
    excluded = excluded_normalized_names or set()
    surnames = _family_surname_names(candidates)
    return [
        candidate
        for candidate in candidates
        if not should_reject_boss_title(candidate.name, instance_name=instance_name)
        and normalize_title(candidate.name) not in excluded
        and not _is_family_or_surname_reference(candidate.name, surnames)
    ]


def boss_names_from_infobox_roster(
    infobox: dict[str, Any] | None,
    *,
    pool: list[BossCandidate],
    instance_name: str = "",
) -> set[str]:
    """Normalized pool-candidate names the instance infobox lists as bosses.

    The instance infobox's boss-labelled fields ("Bosses", "End boss") are the wiki's own
    authoritative encounter roster. Rather than parse discrete names out of the concatenated
    field text (multi-word names, no delimiters), match already-discovered candidate names
    against it: a candidate whose full name appears in a boss-labelled field is a boss and is
    guaranteed into the cast. Structural signal only — no instance-specific keywords, and the
    match is bounded to names the pool already discovered so infobox chrome can never mint one.
    """
    if not isinstance(infobox, dict) or not infobox:
        return set()
    roster_parts = [
        str(value)
        for label, value in infobox.items()
        if isinstance(label, str) and "boss" in label.lower() and value
    ]
    if not roster_parts:
        return set()
    roster_text = normalize_title(" ".join(roster_parts))
    if not roster_text:
        return set()
    names: set[str] = set()
    for candidate in pool:
        norm = normalize_title(candidate.name)
        if not norm or should_reject_boss_title(candidate.name, instance_name=instance_name):
            continue
        if re.search(rf"\b{re.escape(norm)}\b", roster_text):
            names.add(norm)
    return names


def must_include_key_character_names(
    *,
    boss_pool_items: list[dict[str, Any]],
    pool: list[BossCandidate],
    instance_name: str,
    infobox: dict[str, Any] | None = None,
) -> list[str]:
    """Boss-class names guaranteed into the cast (stable sort), from three sources.

    1. Wiki-linked names harvested from boss-class boss_pool snippets,
    2. prefiltered pool candidates whose *own* discovery ``source_section_role`` is a
       high-confidence boss-class section (Adventure Guide / Dungeon Journal / boss /
       encounter rosters), and
    3. pool candidates the instance infobox's boss-labelled roster names (the wiki's own
       encounter list, which is complete even when section-role classification is not).

    Sources 2 and 3 make structurally-obvious bosses deterministic even when boss_pool snippets
    carry no ``/wiki/`` links and the section classifier under-labels the roster table (the
    common case for this ingest revision — the reason bosses were previously dropped). S0-compliant
    tokens only — no zone/instance keywords drive the floor.
    """
    pool_by_norm = {normalize_title(candidate.name): candidate.name for candidate in pool}
    must_norm: set[str] = {
        name
        for name in valid_boss_names_from_pool_items(
            boss_pool_items,
            instance_name=instance_name,
            section_filter=is_high_confidence_boss_section,
        )
        if name in pool_by_norm
    }
    for candidate in pool:
        if is_high_confidence_boss_section(candidate.source_section_role):
            must_norm.add(normalize_title(candidate.name))
    must_norm |= boss_names_from_infobox_roster(
        infobox, pool=pool, instance_name=instance_name
    )
    return sorted(
        [pool_by_norm[name] for name in must_norm if name in pool_by_norm],
        key=normalize_title,
    )


def _looks_like_multi_token_proper_name(title: str) -> bool:
    words = [word for word in title.split() if re.search(r"[A-Za-z]", word)]
    return len(words) >= 2 and all(word[0].isupper() for word in words)


def _llm_prompt_rank_key(candidate: BossCandidate) -> tuple[int, int, str]:
    multi_token = 0 if _looks_like_multi_token_proper_name(candidate.name) else 1
    return (
        multi_token,
        -_section_weight(candidate.source_section_role),
        candidate.name.lower(),
    )


def _mention_frequency_in_text(title: str, narrative_text: str) -> int:
    """Count word-boundary mentions of a character title in narrative prose."""
    lowered = narrative_text.lower()
    if not lowered:
        return 0
    count = len(re.findall(rf"\b{re.escape(title.lower())}\b", lowered))
    if count == 0:
        last_token = title.split()[-1].lower() if title.split() else ""
        if len(last_token) >= 4:
            count = len(re.findall(rf"\b{re.escape(last_token)}\b", lowered))
    return count


def deterministic_pool_order(
    pool: list[BossCandidate],
    *,
    narrative_text: str = "",
    exclude_normalized_names: set[str] | None = None,
) -> list[str]:
    """Offline cast ordering: mention frequency, then section weight, then name."""
    exclude = exclude_normalized_names or set()
    eligible = [candidate for candidate in pool if normalize_title(candidate.name) not in exclude]

    def _sort_key(candidate: BossCandidate) -> tuple[int, int, str]:
        return (
            -_mention_frequency_in_text(candidate.name, narrative_text),
            -_section_weight(candidate.source_section_role),
            candidate.name.lower(),
        )

    return [candidate.name for candidate in sorted(eligible, key=_sort_key)]


def merge_key_character_cast(
    pool: list[BossCandidate],
    *,
    must_include_names: list[str],
    llm_ordered_names: list[str],
    max_count: int = 10,
) -> tuple[list[str], dict[str, str]]:
    """Floor-first merge of must-include and LLM-ordered cast names."""
    pool_by_name = {candidate.name: candidate for candidate in pool}
    floor_names = list(must_include_names)
    if len(floor_names) > max_count:
        floor_names = floor_names[:max_count]

    merged: list[str] = []
    reasons: dict[str, str] = {}

    for name in floor_names:
        if name in pool_by_name and len(merged) < max_count:
            merged.append(name)
            reasons[name] = "must_include_floor"

    for name in llm_ordered_names:
        if name in pool_by_name and name not in merged and len(merged) < max_count:
            merged.append(name)
            reasons[name] = "llm_selected"

    return merged, reasons


def merged_cast_candidates(
    pool: list[BossCandidate],
    merged_names: list[str],
    *,
    instance_name: str = "",
) -> list[BossCandidate]:
    """Map merged display names to pool rows with deterministic roles (no significance sort)."""
    pool_by_name = {candidate.name: candidate for candidate in pool}
    cast: list[BossCandidate] = []
    for name in merged_names:
        candidate = pool_by_name.get(name)
        if candidate is None:
            continue
        candidate.role, candidate.role_reason = classify_character_role(
            candidate, instance_name=instance_name
        )
        cast.append(candidate)
    return cast


def cap_pool_for_llm_prompt(
    pool: list[BossCandidate],
    *,
    must_include_names: list[str],
    limit: int = 40,
) -> list[BossCandidate]:
    """Deterministic top-N for LLM prompt; must-includes are always present."""
    if len(pool) <= limit:
        return list(pool)
    must_keys = {normalize_title(name) for name in must_include_names}
    must_rows = [candidate for candidate in pool if normalize_title(candidate.name) in must_keys]
    others = [candidate for candidate in pool if normalize_title(candidate.name) not in must_keys]
    remaining = max(0, limit - len(must_rows))
    ranked_others = sorted(others, key=_llm_prompt_rank_key)
    return must_rows + ranked_others[:remaining]


_NARRATIVE_SECTION_TOKENS = (
    "lead",
    "overview",
    "official",
    "history",
    "story",
    "description",
    "lore",
    "introduction",
    "background",
)

def _is_narrative_role(section_role: str) -> bool:
    lowered = _normalize_role(section_role)
    return any(token in lowered for token in _NARRATIVE_SECTION_TOKENS)


def _row_is_narrative_row(row: dict[str, Any]) -> bool:
    if _is_narrative_role(str(row.get("section_role", "other"))):
        return True
    parent = str(row.get("parent_section_role", "")).strip()
    return bool(parent) and _is_narrative_role(parent)


def _narrative_structured_link(row: dict[str, Any]) -> bool:
    """Accept roster-bearing links or narrative-history links; skip lead/patch nav."""
    if row_has_roster_role(row):
        return True
    if not _row_is_narrative_row(row):
        return False
    section = _normalize_role(str(row.get("section_role", "other")))
    if section in {"lead", "patch_changes"} or section.startswith("patch"):
        return False
    return True


def mine_narrative_character_candidates(
    section_blocks: list[dict[str, Any]],
    *,
    instance_name: str,
    structured_links: list[dict[str, Any]] | None = None,
    narrative_pool: list[dict[str, Any]] | None = None,
    max_count: int = 10,
    apply_rank: bool = True,
) -> list[BossCandidate]:
    """Deterministic grounding: mine person-like /wiki/ links from narrative content.

    Used as the narrative fallback when roster extraction yields nothing. Sources
    are narrative section blocks and narrative-scoped structured links (the latter
    survive ingest tag-stripping in real runs). Every returned candidate is backed
    by a real /wiki/ link, ranked by mention frequency then name, and capped. No LLM.
    """
    first_seen: dict[str, tuple[str, str]] = {}
    order: list[str] = []

    narrative_text = " ".join(
        _plain_snippet(str(block.get("text", "")))
        for block in section_blocks
        if isinstance(block, dict) and _row_is_narrative_row(block)
    ).lower()

    def _accept(title: str, url: str) -> None:
        if should_reject_boss_title(title, instance_name=instance_name):
            return
        key = normalize_title(title)
        if key not in first_seen:
            first_seen[key] = (title, url)
            order.append(key)

    for block in section_blocks:
        if not isinstance(block, dict):
            continue
        if not _row_is_narrative_row(block):
            continue
        for title, url in _extract_wiki_links(str(block.get("text", ""))):
            _accept(title, url)

    for row in structured_links or []:
        if not isinstance(row, dict) or not _narrative_structured_link(row):
            continue
        href = str(row.get("href", "")).strip()
        if not href.startswith("/wiki/"):
            continue
        path = href.removeprefix("/wiki/").split("#", 1)[0].strip()
        if not path:
            continue
        title = str(row.get("label", "")).strip() or _title_from_wiki_path(path)
        url = href if href.startswith("http") else f"https://warcraft.wiki.gg/wiki/{path}"
        _accept(title, url)

    ranked = sorted(
        order,
        key=lambda key: (
            -_mention_frequency_in_text(first_seen[key][0], narrative_text),
            key,
        ),
    )
    results: list[BossCandidate] = []
    for key in ranked[:max_count]:
        title, url = first_seen[key]
        boss_id = _slug_id(title)
        if not boss_id:
            continue
        candidate = BossCandidate(
            boss_id=boss_id,
            name=title,
            wiki_url=url,
            source_section_role="narrative_fallback",
            canonical_path=f"/wiki/{_wiki_path_from_url(url).replace(' ', '_')}",
        )
        candidate.profile_pool = _profile_pool_for_boss(
            candidate.name,
            boss_pool_items=narrative_pool or [],
            section_blocks=section_blocks,
        )
        results.append(candidate)
    if apply_rank:
        return _rank_candidates(results, instance_name=instance_name)
    return results
