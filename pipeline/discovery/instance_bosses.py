"""Structural boss/encounter parsing from instance wiki section blocks."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from collections.abc import Callable
from typing import Any

from pipeline.discovery.entity_typing import _DATING_CONVENTION_TITLE_RE, normalize_title
from pipeline.discovery.world_registry import entry_kinds
from pipeline.common.text_normalize import clean_wiki_snippet

_WIKI_LINK_RE = re.compile(r"/wiki/([^|\s\]#<>\"']+)")
_WIKITEXT_LINK_RE = re.compile(r"\[\[([^|\]#]+)(?:\|[^\]]+)?\]\]")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_BOSS_SECTION_TOKENS = (
    "adventurer",
    "encounter",
    "boss",
    "dungeon",
    "adventure_guide",
    "walkthrough",
    "faculty",
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
# Registry kinds that mark a link as a location/geography, never an individual character.
# Shared by both the roster path (should_reject_boss_title) and the narrative path
# (_looks_like_person) so the two filters can never drift. Includes "place" so instance
# subzones/areas (e.g. Caer Darrow, Chamber of Summoning) are rejected as candidates.
_NON_CHARACTER_KINDS = frozenset({"place", "zone", "instance", "continent", "capital", "region"})
_REJECT_TITLES = frozenset(
    {
        "adventurers",
        "encounters",
        "bosses",
        "loot",
        "achievements",
        "strategy",
        "tactics",
        "abilities",
        "quotes",
        "gallery",
        "notes",
        "trivia",
    }
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


def _normalize_role(section_role: str) -> str:
    return re.sub(r"\s+", " ", section_role.strip()).lower().replace(" ", "_")


def is_high_confidence_boss_section(section_role: str) -> bool:
    """True when boss_pool evidence should contribute to the must-include floor."""
    lowered = _normalize_role(section_role)
    return any(token in lowered for token in HIGH_CONFIDENCE_BOSS_SECTION_TOKENS)


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
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"character-{slug}" if slug else ""


def should_reject_boss_title(title: str, *, instance_name: str = "") -> bool:
    lowered = normalize_title(title)
    if not lowered or len(lowered) < 3:
        return True
    if instance_name and lowered == normalize_title(instance_name):
        return True
    if lowered in _REJECT_TITLES:
        return True
    if _DATING_CONVENTION_TITLE_RE.search(title):
        return True
    kinds = entry_kinds(title)
    if kinds & _NON_CHARACTER_KINDS:
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
    return clean_wiki_snippet(_HTML_TAG_RE.sub(" ", text))


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
    default_source_id = str(boss_pool_items[0].get("source_id", "")).strip() if boss_pool_items else ""
    pool: list[dict[str, Any]] = []
    for item in boss_pool_items:
        raw_snippet = str(item.get("snippet", ""))
        snippet = _plain_snippet(raw_snippet)
        if pattern.search(snippet) or slug_pattern.search(snippet) or slug_pattern.search(raw_snippet):
            pool.append({**item, "snippet": snippet})
    for block in section_blocks:
        if not isinstance(block, dict):
            continue
        raw_text = str(block.get("text", ""))
        text = _plain_snippet(raw_text)
        if not (
            pattern.search(text)
            or slug_pattern.search(text)
            or slug_pattern.search(raw_text)
        ):
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


# Section roles whose membership implies hostility (boss/encounter rosters), versus
# roles that merely list characters and need descriptor evidence to classify.
# "force"/"faction" rosters are intentionally excluded: pages like Culling of
# Stratholme list Alliance allies and Scourge enemies under the same heading, so
# membership alone is not a hostility signal - those defer to descriptors/LLM.
_ENEMY_LEAN_TOKENS = (
    "boss",
    "encounter",
    "denizen",
    "inhabit",
    "monster",
    "faculty",
    "dungeon_journal",
    "adventure_guide",
    "walkthrough",
    "layout",
)
_NPC_LEAN_TOKENS = ("npc", "notable", "character", "ally", "allies", "friendly")

# Per-character hostility markers only. Broad scourge/corruption words are excluded
# because they appear in shared instance context and would tag every candidate.
_ENEMY_DESCRIPTORS = (
    "final boss",
    "boss of",
    "is a boss",
    "is the boss",
    "must be defeated",
    "must be slain",
    "servant of",
    "minion of",
    "commander of the scourge",
)
_ALLY_DESCRIPTORS = (
    "aids the",
    "assists the",
    "fights alongside",
    "ally of",
    "allied with",
    "helps the",
    "must be escorted",
    "must be rescued",
    "is rescued",
    "rescued by",
    "to rescue",
    "freed by",
    "joins the",
)
_NEUTRAL_DESCRIPTORS = (
    "merchant",
    "vendor",
    "innkeeper",
    "quest giver",
    "questgiver",
    "trainer",
    "flight master",
    "banker",
    "auctioneer",
    "repair",
    "reagent",
)


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


def _candidate_profile_text(candidate: BossCandidate) -> str:
    return " ".join(
        _plain_snippet(str(item.get("snippet", ""))) for item in candidate.profile_pool or []
    ).lower()


def classify_character_role(
    candidate: BossCandidate, *, instance_name: str = ""
) -> tuple[str, str]:
    """Deterministically classify a character's role from section + descriptor signals.

    Returns ``(role, reason_code)``. ``"uncertain"`` is returned when there is no
    signal or signals conflict (a tie), deferring those cases to the LLM tiebreaker.
    """
    section = _normalize_role(candidate.source_section_role)
    text = _candidate_profile_text(candidate)

    enemy = sum(1 for kw in _ENEMY_DESCRIPTORS if kw in text)
    ally = sum(1 for kw in _ALLY_DESCRIPTORS if kw in text)
    neutral = sum(1 for kw in _NEUTRAL_DESCRIPTORS if kw in text)

    # With no per-character descriptor evidence, only an unambiguous hostile section
    # (boss/encounter rosters) is enough to classify; everything else stays uncertain
    # so the LLM tiebreaker can resolve it without us guessing wrong.
    if not (enemy or ally or neutral):
        if any(token in section for token in _ENEMY_LEAN_TOKENS):
            return "enemy", "enemy_section"
        return "uncertain", "no_signal"

    # Descriptor evidence present: decide among the three on that evidence alone, so an
    # explicit ally/neutral marker is never overridden by mere roster membership.
    scores = {"enemy": enemy, "ally": ally, "neutral": neutral}
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    if ranked[0][1] == ranked[1][1]:
        return "uncertain", "conflicting_signal"
    best_role = ranked[0][0]
    return best_role, f"{best_role}_descriptor"


def _rank_candidates(
    candidates: list[BossCandidate], *, instance_name: str
) -> list[BossCandidate]:
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
            return
        candidates[key] = BossCandidate(
            boss_id=boss_id,
            name=display_title,
            wiki_url=url,
            source_section_role=role,
        )

    for block in section_blocks:
        if not isinstance(block, dict):
            continue
        if not row_has_roster_role(block):
            continue
        leaf_role = str(block.get("section_role", "other"))
        role = leaf_role if is_boss_section_role(leaf_role) else str(block.get("parent_section_role", leaf_role))
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
            if not _looks_like_person(title):
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
        _merge_candidate_into(
            merged, candidate, canonical_index=canonical_index, order=order
        )

    combined_pool_items = boss_pool_items + list(narrative_pool or []) + list(history_pool or [])
    result = [merged[key] for key in order]
    for candidate in result:
        candidate.profile_pool = _profile_pool_for_boss(
            candidate.name,
            boss_pool_items=combined_pool_items,
            section_blocks=section_blocks,
        )
    return result


def prefilter_character_pool(
    candidates: list[BossCandidate],
    *,
    instance_name: str,
) -> list[BossCandidate]:
    """Drop registry/meta rejects; preserve discovery order."""
    return [
        candidate
        for candidate in candidates
        if not should_reject_boss_title(candidate.name, instance_name=instance_name)
    ]


def must_include_key_character_names(
    *,
    boss_pool_items: list[dict[str, Any]],
    pool: list[BossCandidate],
    instance_name: str,
) -> list[str]:
    """Boss-class boss_pool names intersected with the prefiltered pool (stable sort)."""
    boss_class_names = valid_boss_names_from_pool_items(
        boss_pool_items,
        instance_name=instance_name,
        section_filter=is_high_confidence_boss_section,
    )
    pool_by_norm = {normalize_title(candidate.name): candidate.name for candidate in pool}
    return sorted(
        [pool_by_norm[name] for name in boss_class_names if name in pool_by_norm],
        key=normalize_title,
    )


def _looks_like_multi_token_proper_name(title: str) -> bool:
    words = [word for word in title.split() if re.search(r"[A-Za-z]", word)]
    return len(words) >= 2 and all(word[0].isupper() for word in words)


def _llm_prompt_rank_key(candidate: BossCandidate) -> tuple[int, int, int, str]:
    kinds = entry_kinds(candidate.name)
    person_first = 0 if "person" in kinds else 1
    multi_token = 0 if _looks_like_multi_token_proper_name(candidate.name) else 1
    return (
        person_first,
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
    eligible = [
        candidate
        for candidate in pool
        if normalize_title(candidate.name) not in exclude
    ]

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

_PERSON_HONORIFICS = frozenset(
    {
        "highlord",
        "high",
        "lord",
        "lady",
        "professor",
        "archmage",
        "king",
        "queen",
        "prince",
        "princess",
        "sir",
        "dame",
        "captain",
        "commander",
        "general",
        "warchief",
        "warlord",
        "grand",
        "master",
        "baron",
        "baroness",
        "bishop",
        "sergeant",
        "marshal",
        "admiral",
        "chief",
        "elder",
        "prophet",
        "overlord",
        "lich",
        "emperor",
        "empress",
        "champion",
        "keeper",
        "prime",
    }
)

# Multi-word capitalized titles that are factions/forces/concepts, not individual characters.
_NON_PERSON_NARRATIVE_TITLES = frozenset(
    {
        "burning legion",
        "the burning legion",
        "scourge",
        "the scourge",
        "alliance",
        "the alliance",
        "horde",
        "the horde",
        "old god",
        "old gods",
        "scarlet crusade",
        "argent crusade",
        "argent dawn",
        "argent tournament",
        "sons of hodir",
        "kirin tor",
        "ashen verdict",
        "knights of the ebon blade",
        "bronze dragonflight",
        "black dragonflight",
        "green dragonflight",
        "red dragonflight",
        "blue dragonflight",
        "dragonflight",
        "twilight's hammer",
        "cult of the damned",
        "forsaken",
        "valarjar",
        "burning crusade",
        "boneguard",
        "warsong offensive",
        "valiance expedition",
        "gnomeregan army",
        "saronite",
        "adventurer",
        "event",
        "faction",
        "novels",
        "novellas",
        "short stories",
        "technology",
    }
)

# Generic common-noun / race / creature-type words that are not named characters.
_GENERIC_NON_PERSON_WORDS = frozenset(
    {
        "class",
        "race",
        "quest",
        "item",
        "mob",
        "boss",
        "comic",
        "comics",
        "novel",
        "engineer",
        "robot",
        "ram",
        "rat",
        "plane",
        "giant",
        "demon",
        "demigod",
        "undead",
        "elemental",
        "human",
        "orc",
        "dwarf",
        "gnome",
        "troll",
        "tauren",
        "goblin",
        "vrykul",
        "earthen",
        "mechagnome",
        "broken",
        "aqir",
        "nathrezim",
        "golem",
        "bloodhound",
        "survivor",
        "dungeon",
    }
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


def _looks_like_person(title: str) -> bool:
    """Heuristic person/NPC detector for narrative-fallback link mining."""
    norm = normalize_title(title)
    if norm in _NON_PERSON_NARRATIVE_TITLES or norm in _GENERIC_NON_PERSON_WORDS:
        return False
    kinds = entry_kinds(title)
    if kinds & _NON_CHARACTER_KINDS:
        return False
    words = title.split()
    if not words:
        return False
    first_word = re.sub(r"[^a-z]", "", words[0].lower())
    if first_word in _PERSON_HONORIFICS:
        return True
    if "person" in kinds:
        return True
    if len(words) > 4:
        return False
    significant = [word for word in words if re.search(r"[A-Za-z]", word)]
    if not significant or not all(word[0].isupper() for word in significant):
        return False
    if len(significant) == 1:
        token = re.sub(r"[^A-Za-z'\-]", "", significant[0])
        return len(token) >= 4
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
        if not _looks_like_person(title):
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
