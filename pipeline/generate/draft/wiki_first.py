"""Wiki-first draft builders that consume deterministic evidence packs."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from pipeline.common.text_normalize import clean_wiki_snippet
from pipeline.generate.draft.prose_election import (
    fallback_at_a_glance,
    fallback_currently,
    fallback_history_sections,
    history_section_cap,
    select_at_a_glance_pool,
    select_currently_pool,
    select_history_pool,
)
from pipeline.generate.draft.prose_lint import (
    MAX_AT_A_GLANCE_WORDS,
    MAX_HISTORY_SECTIONS,
    MIN_HISTORY_SECTIONS,
    lint_at_a_glance,
    lint_currently,
    lint_history_sections,
)
from pipeline.generate.draft.wiki_first_workers import (
    synthesize_at_a_glance,
    synthesize_card_summary,
    synthesize_currently,
    synthesize_history_sections,
)

_FACTION_HINTS: tuple[tuple[str, str], ...] = (
    ("faction-argent-crusade", "Argent Crusade"),
    ("faction-scarlet-crusade", "Scarlet Crusade"),
    ("faction-scourge", "Scourge"),
    ("faction-cenarion-circle", "Cenarion Circle"),
    ("faction-cult-of-the-damned", "Cult of the Damned"),
    ("faction-alliance", "Alliance"),
    ("faction-horde", "Horde"),
    ("faction-forsaken", "Forsaken"),
)

_NAME_STOP_WORDS = {
    "The",
    "This",
    "That",
    "From",
    "World",
    "Warcraft",
    "Section",
    "Cataclysm",
    "Legion",
    "Mists",
}


def _clean_snippet(text: str) -> str:
    return clean_wiki_snippet(text)


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w']+\b", text))


def _source_entries(fact_pack: dict[str, Any]) -> list[dict[str, Any]]:
    source_entries: list[dict[str, Any]] = []
    source_urls = fact_pack.get("source_urls") or {}
    source_ids = fact_pack.get("source_ids") or []
    revision_ids = fact_pack.get("revision_ids") or []
    source_to_revision = {
        str(source_id): str(revision_ids[index])
        for index, source_id in enumerate(source_ids)
        if index < len(revision_ids)
    }
    for source_id, url in source_urls.items():
        if not source_id or not url:
            continue
        source_entries.append(
            {
                "source_id": str(source_id),
                "url": str(url),
                "revision_id": source_to_revision.get(str(source_id)),
            }
        )
    return source_entries


def _iter_evidence_items(
    evidence_rows: list[dict[str, Any]],
    field_names: set[str] | None = None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in evidence_rows:
        if field_names is not None and str(row.get("field_name", "")) not in field_names:
            continue
        evidence_items = row.get("evidence_items")
        if not isinstance(evidence_items, list):
            continue
        for item in evidence_items:
            if not isinstance(item, dict):
                continue
            snippet = _clean_snippet(str(item.get("snippet", "")))
            if not snippet:
                continue
            items.append(
                {
                    "snippet": snippet,
                    "source_url": str(item.get("source_url", "")),
                    "source_title": str(item.get("source_title", "")),
                    "section_role": str(item.get("section_role", "")),
                    "source_id": str((row.get("build_meta") or {}).get("source_id", "")),
                    "field_name": str(row.get("field_name", "")),
                    "cluster_id": str((row.get("build_meta") or {}).get("cluster_id", "")),
                }
            )
    return items


def _source_revision_map(fact_pack: dict[str, Any]) -> dict[str, str]:
    source_ids = [str(source_id) for source_id in (fact_pack.get("source_ids") or []) if str(source_id).strip()]
    revision_ids = [str(revision_id) for revision_id in (fact_pack.get("revision_ids") or [])]
    return {
        source_id: revision_ids[index]
        for index, source_id in enumerate(source_ids)
        if index < len(revision_ids) and revision_ids[index]
    }


def _source_url_map(fact_pack: dict[str, Any]) -> dict[str, str]:
    urls = fact_pack.get("source_urls") or {}
    if not isinstance(urls, dict):
        return {}
    return {str(source_id): str(url) for source_id, url in urls.items() if str(source_id) and str(url)}


def _items_for_source_ids(
    items: list[dict[str, Any]],
    source_ids: list[str],
) -> list[dict[str, Any]]:
    wanted = {source_id for source_id in source_ids if source_id}
    if not wanted:
        return []
    return [item for item in items if str(item.get("source_id", "")) in wanted]


def _pointers_for_source_ids(
    items: list[dict[str, Any]],
    source_ids: list[str],
    revision_map: dict[str, str],
) -> list[dict[str, str]]:
    pointers: list[dict[str, str]] = []
    for index, item in enumerate(_items_for_source_ids(items, source_ids), start=1):
        pointer = _pointer_for_item(item, revision_map, index)
        if pointer:
            pointers.append(pointer)
    return pointers


def _pointer_for_item(
    item: dict[str, Any],
    revision_map: dict[str, str],
    locator_index: int,
) -> dict[str, str] | None:
    source_id = str(item.get("source_id", "")).strip()
    snippet = str(item.get("snippet", "")).strip()
    section_role = str(item.get("section_role", "other")).strip() or "other"
    if not source_id or not snippet:
        return None
    revision_id = revision_map.get(source_id)
    if not revision_id:
        return None
    digest = hashlib.sha256(snippet.encode("utf-8")).hexdigest()[:16]
    return {
        "source_id": source_id,
        "locator": f"section:{section_role} paragraph:{locator_index}",
        "revision_id": revision_id,
        "excerpt_hash": f"sha256:{digest}",
    }


def _build_evidence_pools(evidence_rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    history_pool = _iter_evidence_items(evidence_rows, {"history_digest"})
    at_a_glance_pool = _iter_evidence_items(evidence_rows, {"at_a_glance_input"})
    currently_pool = _iter_evidence_items(evidence_rows, {"currently_input"})
    questline_pool = _iter_evidence_items(evidence_rows, {"questline_pool"})
    quest_cluster_lore_pool = _iter_evidence_items(evidence_rows, {"quest_cluster_lore"})
    quest_lore_pool = _iter_evidence_items(evidence_rows, {"quest_lore"})
    faction_pool = _iter_evidence_items(evidence_rows, {"faction_pool"})
    location_pool_items = _iter_evidence_items(evidence_rows, {"location_pool"})
    instance_pool = _iter_evidence_items(evidence_rows, {"instances_or_dungeons", "history_digest"})
    faction_role_pool = faction_pool or _iter_evidence_items(
        evidence_rows, {"history_digest", "currently_input", "questline_pool"}
    )
    location_pool = location_pool_items or _iter_evidence_items(evidence_rows, {"history_digest"})
    return {
        "at_a_glance_pool": at_a_glance_pool,
        "currently_pool": currently_pool,
        "history_pool": history_pool,
        "faction_role_pool": faction_role_pool,
        "location_pool": location_pool,
        "instance_pool": instance_pool,
        "questline_pool": questline_pool,
        "quest_cluster_lore_pool": quest_cluster_lore_pool,
        "quest_lore_pool": quest_lore_pool,
        "faction_pool": faction_pool,
    }


def _best_snippet_for_term(items: list[dict[str, Any]], term: str, min_words: int = 8) -> str:
    term_lower = term.lower()
    best = ""
    for item in items:
        snippet = str(item.get("snippet", "")).strip()
        if not snippet:
            continue
        if term_lower in snippet.lower() and _word_count(snippet) >= min_words:
            return snippet
        if _word_count(snippet) > _word_count(best):
            best = snippet
    return best


def _history_sections_from_pool(
    history_pool: list[dict[str, Any]],
    *,
    evidence_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    pool = history_pool or select_history_pool(_iter_evidence_items(evidence_rows, {"history_digest"}))
    cap = history_section_cap(pool) or MIN_HISTORY_SECTIONS
    sections, used = fallback_history_sections(pool, max_sections=cap)
    if sections:
        return sections, used
    return [], []


def _finalize_at_a_glance(
    *,
    zone_name: str,
    at_pool: list[dict[str, Any]],
    evidence_rows: list[dict[str, Any]],
) -> tuple[str, list[str]]:
    text, used = synthesize_at_a_glance(at_pool, max_words=MAX_AT_A_GLANCE_WORDS)
    if lint_at_a_glance(text, zone_name=zone_name):
        text, used = fallback_at_a_glance(at_pool)
        if lint_at_a_glance(text, zone_name=zone_name):
            text, used = "", []
    if not text:
        rescue_pool = at_pool or select_at_a_glance_pool(
            _iter_evidence_items(evidence_rows, {"at_a_glance_input", "history_digest"})
        )
        text, used = fallback_at_a_glance(rescue_pool)
        if lint_at_a_glance(text, zone_name=zone_name):
            text, used = "", []
    if not text:
        text = f"{zone_name} is a retail-era World of Warcraft zone with active conflicts."
        used = []
    return text, used


def _finalize_currently(
    *,
    zone_name: str,
    currently_pool: list[dict[str, Any]],
    evidence_rows: list[dict[str, Any]],
    pools: dict[str, list[dict[str, Any]]],
) -> tuple[str, list[str]]:
    text, used = synthesize_currently(currently_pool, max_words=120)
    if lint_currently(text, zone_name=zone_name):
        text, used = fallback_currently(currently_pool)
        if lint_currently(text, zone_name=zone_name):
            text, used = "", []
    if not text:
        rescue_pool = currently_pool or select_currently_pool(pools, zone_name=zone_name)
        text, used = fallback_currently(rescue_pool)
        if lint_currently(text, zone_name=zone_name):
            text, used = "", []
    if not text:
        text = f"{zone_name} currently has active quest and faction conflict dynamics."
        used = []
    return text, used


def _finalize_history_sections(
    *,
    history_pool: list[dict[str, Any]],
    evidence_rows: list[dict[str, Any]],
    max_history: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    section_cap = max_history or MIN_HISTORY_SECTIONS
    lint_cap = max_history or MAX_HISTORY_SECTIONS
    sections, used = synthesize_history_sections(history_pool, max_sections=section_cap)
    if lint_history_sections(sections, max_sections=lint_cap):
        sections, used = fallback_history_sections(history_pool, max_sections=section_cap)
        if lint_history_sections(sections, max_sections=lint_cap):
            sections, used = [], []
    if not sections:
        sections, used = _history_sections_from_pool(history_pool, evidence_rows=evidence_rows)
    return sections, used


def _first_snippet(
    evidence_rows: list[dict[str, Any]],
    fields: set[str],
    min_words: int = 1,
) -> str:
    item = _first_item(evidence_rows, fields, min_words=min_words)
    if item is None:
        return ""
    return str(item["snippet"])


def _first_item(
    evidence_rows: list[dict[str, Any]],
    fields: set[str],
    min_words: int = 1,
) -> dict[str, Any] | None:
    items = _iter_evidence_items(evidence_rows, fields)
    if not items:
        return None
    for item in items:
        snippet = str(item["snippet"])
        lowered = snippet.lower()
        if "(lore)" in lowered and _word_count(snippet) < 10:
            continue
        if _word_count(snippet) >= min_words:
            return item
    return items[0]


def _extract_factions(evidence_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pools = _build_evidence_pools(evidence_rows)
    text_blob = " ".join(item["snippet"] for item in pools["faction_role_pool"])
    lowered = text_blob.lower()
    faction_cards: list[dict[str, Any]] = []
    for faction_id, name in _FACTION_HINTS:
        if name.lower() not in lowered:
            continue
        role_snippet = _best_snippet_for_term(pools["faction_role_pool"], name, min_words=10)
        summary = role_snippet or f"{name} appears in this zone's active conflicts and political narrative."
        faction_cards.append(
            {
                "id": faction_id,
                "name": name,
                "summary": summary,
                "wiki_url": f"https://warcraft.wiki.gg/wiki/{name.replace(' ', '_')}",
            }
        )
    return faction_cards[:6]


def _build_location_cards(
    zone_id: str,
    location_rows: list[dict[str, Any]],
    location_candidate_map: dict[str, dict[str, Any]],
    location_decision_map: dict[str, dict[str, Any]],
    location_pool: list[dict[str, Any]],
    *,
    revision_map: dict[str, str],
    max_defer_cards: int = 6,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, str]]]]:
    cards: list[dict[str, Any]] = []
    provenance_map: dict[str, list[dict[str, str]]] = {}
    ranked: list[tuple[float, dict[str, Any]]] = []
    for row in location_rows:
        if str(row.get("zone_id", "")) != zone_id:
            continue
        classification = str(row.get("classification", ""))
        location_id = str(row.get("location_id", ""))
        if not location_id or classification == "reject":
            continue
        if classification not in {"city", "starter_area", "major_location_candidate"}:
            continue
        decision = location_decision_map.get(location_id, {})
        final_decision = str(decision.get("final_decision", "")).strip()
        if final_decision == "exclude":
            continue
        if final_decision not in {"include", "defer"}:
            continue
        score = float(decision.get("score", 0.0) or 0.0)
        ranked.append((score, row))
    ranked.sort(key=lambda item: item[0], reverse=True)
    include_rows = [row for score, row in ranked if location_decision_map.get(str(row.get("location_id", "")), {}).get("final_decision") == "include"]
    defer_rows = [row for score, row in ranked if location_decision_map.get(str(row.get("location_id", "")), {}).get("final_decision") == "defer"]
    selected_rows = include_rows + defer_rows[: max(0, max_defer_cards - len(include_rows))]
    seen: set[str] = set()
    for row in selected_rows:
        location_id = str(row.get("location_id", ""))
        if location_id in seen:
            continue
        seen.add(location_id)
        candidate = location_candidate_map.get(location_id, {})
        source_link = str(candidate.get("source_link", "")).strip()
        wiki_url = f"https://warcraft.wiki.gg{source_link}" if source_link.startswith("/wiki/") else "https://warcraft.wiki.gg/"
        location_type = (
            "major_location" if str(row.get("classification", "")) == "major_location_candidate" else str(row.get("classification", ""))
        )
        name = str(row.get("name", location_id))
        scoped_pool = [
            item
            for item in location_pool
            if name.lower() in str(item.get("snippet", "")).lower()
            or str(item.get("source_title", "")).lower() == name.lower()
        ] or location_pool
        summary, used_ids = synthesize_card_summary(scoped_pool, subject=name, max_words=40)
        if not summary:
            summary = _best_snippet_for_term(location_pool, name, min_words=10)
        cards.append(
            {
                "id": location_id,
                "name": name,
                "location_type": location_type,
                "zone_id": zone_id,
                "wiki_url": wiki_url,
                "summary": summary,
                "significance": str(row.get("classification", "")),
                "decision_reason_codes": list(location_decision_map.get(location_id, {}).get("reason_codes") or ["classification"]),
                "ui_hints": {"render_as": location_type},
                "provenance": [],
            }
        )
        pointers = _pointers_for_source_ids(scoped_pool, used_ids, revision_map)
        if pointers:
            provenance_map[location_id] = pointers
        if len(cards) >= 8:
            break
    return cards, provenance_map


def _build_instance_links(
    zone_id: str,
    instance_rows: list[dict[str, Any]],
    instance_pool: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    for row in instance_rows:
        if str(row.get("source_zone_id", "")) != zone_id:
            continue
        name = str(row.get("name", "")).strip()
        instance_id = str(row.get("instance_id", "")).strip()
        if not name or not instance_id:
            continue
        summary = _best_snippet_for_term(instance_pool, name, min_words=10)
        if not summary:
            summary = f"{name} anchors a key conflict thread linked to this zone."
        links.append(
            {
                "id": instance_id,
                "name": name,
                "summary": summary,
                "thumbnail_asset_id": None,
            }
        )
    return links[:8]


def _extract_key_enemy_names(evidence_rows: list[dict[str, Any]]) -> list[str]:
    text_blob = " ".join(item["snippet"] for item in _iter_evidence_items(evidence_rows))
    names: list[str] = []
    for match in re.finditer(r"\b[A-Z][a-z'`-]+(?:\s+[A-Z][a-z'`-]+){0,2}\b", text_blob):
        name = match.group(0).strip()
        if not name or name.split()[0] in _NAME_STOP_WORDS:
            continue
        if len(name) < 4:
            continue
        if name in names:
            continue
        names.append(name)
        if len(names) >= 8:
            break
    return names


def _build_key_enemies(evidence_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enemies: list[dict[str, Any]] = []
    for name in _extract_key_enemy_names(evidence_rows):
        enemy_id = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        if not enemy_id:
            continue
        enemies.append(
            {
                "id": f"character-{enemy_id}",
                "name": name,
                "summary": f"{name} is a key enemy presence tied to the instance narrative.",
                "thumbnail_asset_id": None,
            }
        )
    return enemies[:6]


def _sized_summary(base: str, min_words: int) -> str:
    text = _clean_snippet(base)
    if _word_count(text) >= min_words:
        return text
    suffix = (
        " This entry focuses on core conflict stakes, major actors, and why this location remains "
        "important to ongoing narrative context."
    )
    return _clean_snippet(f"{text}{suffix}")


def _group_v3_clusters(questline_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    clusters: dict[str, dict[str, Any]] = {}
    for row in questline_rows:
        if str(row.get("node_type", "quest")) != "quest":
            continue
        cluster_id = str(row.get("cluster_id", "")).strip() or "cluster-main"
        bucket = clusters.get(cluster_id)
        if bucket is None:
            bucket = {
                "cluster_id": cluster_id,
                "cluster_title": str(row.get("cluster_title", "Main storylines")),
                "cluster_order": int(row.get("cluster_order", 0) or 0),
                "quests": [],
            }
            clusters[cluster_id] = bucket
        bucket["quests"].append(row)
    grouped = list(clusters.values())
    grouped.sort(key=lambda item: (int(item.get("cluster_order", 0)), str(item.get("cluster_id", ""))))
    for bucket in grouped:
        bucket["quests"].sort(key=lambda row: int(row.get("order_in_cluster", 0) or 0))
    return grouped


def _majority_faction(bindings: list[str]) -> str:
    counts: dict[str, int] = {}
    for binding in bindings:
        key = binding.strip().lower() or "shared"
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return "shared"
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return "shared"
    winner = ranked[0][0]
    if winner == "neutral":
        return "shared"
    if winner in {"alliance", "horde", "shared"}:
        return winner
    return "shared"


def _cluster_lore_pool(
    pools: dict[str, list[dict[str, Any]]],
    cluster_id: str,
) -> list[dict[str, Any]]:
    cluster_items = [
        item for item in pools.get("quest_cluster_lore_pool", []) if str(item.get("cluster_id", "")) == cluster_id
    ]
    if cluster_items:
        return cluster_items
    return [
        item
        for item in pools.get("quest_lore_pool", [])
        if str(item.get("cluster_id", "")) == cluster_id
    ]


def _provenance_bucket_for_faction(faction: str) -> str:
    if faction == "alliance":
        return "major_questlines_alliance"
    if faction == "horde":
        return "major_questlines_horde"
    return "major_questlines_shared"


def build_zone_page(
    fact_pack: dict[str, Any],
    evidence_rows: list[dict[str, Any]],
    questline_rows: list[dict[str, Any]],
    location_rows: list[dict[str, Any]],
    instance_rows: list[dict[str, Any]],
    location_candidate_map: dict[str, dict[str, Any]],
    location_decision_map: dict[str, dict[str, Any]],
    questline_decision: dict[str, Any] | None,
) -> dict[str, Any]:
    zone_id = str(fact_pack.get("entity_id", "zone-unknown"))
    name = str(fact_pack.get("name", zone_id))
    source_url = ""
    for source_id, url in (fact_pack.get("source_urls") or {}).items():
        if source_id and url:
            source_url = str(url)
            break
    pools = _build_evidence_pools(evidence_rows)
    revision_map = _source_revision_map(fact_pack)
    source_urls = _source_url_map(fact_pack)
    used_source_ids: set[str] = set()

    at_pool = select_at_a_glance_pool(pools["at_a_glance_pool"])
    currently_pool = select_currently_pool(pools, zone_name=name)
    history_pool = select_history_pool(pools["history_pool"])
    max_history = history_section_cap(history_pool)

    at_a_glance, at_glance_used = _finalize_at_a_glance(
        zone_name=name,
        at_pool=at_pool,
        evidence_rows=evidence_rows,
    )

    currently, currently_used = _finalize_currently(
        zone_name=name,
        currently_pool=currently_pool,
        evidence_rows=evidence_rows,
        pools=pools,
    )

    at_a_glance_pointers = _pointers_for_source_ids(at_pool or pools["at_a_glance_pool"], at_glance_used, revision_map)
    currently_pointers = _pointers_for_source_ids(
        currently_pool or pools["currently_pool"], currently_used, revision_map
    )
    for pointer in at_a_glance_pointers + currently_pointers:
        used_source_ids.add(pointer["source_id"])

    history_sections, history_used = _finalize_history_sections(
        history_pool=history_pool,
        evidence_rows=evidence_rows,
        max_history=max_history,
    )
    history_pointers = _pointers_for_source_ids(history_pool or pools["history_pool"], history_used, revision_map)
    for pointer in history_pointers:
        used_source_ids.add(pointer["source_id"])

    major_questlines: list[dict[str, Any]] = []
    questline_provenance_by_bucket: dict[str, dict[str, list[dict[str, str]]]] = {
        "major_questlines_alliance": {},
        "major_questlines_horde": {},
        "major_questlines_shared": {},
    }
    questline_decision_value = str((questline_decision or {}).get("final_decision", "")).strip()
    active_questline_rows = questline_rows
    if questline_decision_value not in {"", "include", "defer"}:
        active_questline_rows = []
    cluster_groups = _group_v3_clusters(active_questline_rows)
    max_clusters = min(len(cluster_groups), 8)
    for cluster in cluster_groups[:max_clusters]:
        cluster_id = str(cluster.get("cluster_id", "cluster-main"))
        quests = cluster.get("quests", [])
        if not isinstance(quests, list) or not quests:
            continue
        cluster_title = str(cluster.get("cluster_title", "Main storylines"))
        card_id = f"cluster-{cluster_id}"
        faction = _majority_faction([str(row.get("faction_binding", "shared")) for row in quests if isinstance(row, dict)])
        first_quest = quests[0] if isinstance(quests[0], dict) else {}
        start_anchor = str(first_quest.get("title", cluster_title))
        chain_refs = [str(row.get("node_id", "")) for row in quests if isinstance(row, dict) and row.get("node_id")]
        wiki_refs = [
            str(row.get("source_link", ""))
            for row in quests
            if isinstance(row, dict) and str(row.get("source_link", "")).strip()
        ]
        scoped_pool = _cluster_lore_pool(pools, cluster_id)
        if not scoped_pool:
            continue
        cta, cta_used = synthesize_card_summary(scoped_pool, subject=cluster_title, max_words=35)
        if not cta:
            cta = _best_snippet_for_term(scoped_pool, cluster_title, min_words=8) or (
                f"Follow the {cluster_title} arc through its linked quests."
            )
        major_questlines.append(
            {
                "id": card_id,
                "title": cluster_title,
                "faction": faction,
                "cta_hook": cta,
                "start_anchor": start_anchor,
                "chain_refs": chain_refs,
                "include_decision": "include",
                "reason_codes": list((questline_decision or {}).get("reason_codes") or ["graph_depth"]),
                "wiki_refs": wiki_refs,
            }
        )
        pointers = _pointers_for_source_ids(scoped_pool, cta_used, revision_map)
        if pointers:
            bucket = _provenance_bucket_for_faction(faction)
            questline_provenance_by_bucket[bucket][card_id] = pointers
            for pointer in pointers:
                used_source_ids.add(pointer["source_id"])

    location_cards, landmark_provenance_map = _build_location_cards(
        zone_id,
        location_rows,
        location_candidate_map,
        location_decision_map,
        pools["location_pool"],
        revision_map=revision_map,
    )
    for pointers in landmark_provenance_map.values():
        for pointer in pointers:
            used_source_ids.add(pointer["source_id"])

    instance_links = _build_instance_links(zone_id, instance_rows, pools["instance_pool"])
    instance_provenance_map: dict[str, list[dict[str, str]]] = {}
    for card in instance_links:
        scoped = [item for item in pools["instance_pool"] if str(card.get("name", "")).lower() in str(item.get("snippet", "")).lower()] or pools["instance_pool"]
        summary, used_ids = synthesize_card_summary(scoped, subject=str(card.get("name", "")), max_words=35)
        if summary:
            card["summary"] = summary
        pointers = _pointers_for_source_ids(scoped, used_ids, revision_map)
        if pointers:
            instance_provenance_map[str(card["id"])] = pointers
            for pointer in pointers:
                used_source_ids.add(pointer["source_id"])

    faction_cards = _extract_factions(evidence_rows)
    faction_provenance_map: dict[str, list[dict[str, str]]] = {}
    for card in faction_cards:
        scoped = [item for item in pools["faction_role_pool"] if str(card.get("name", "")).lower() in str(item.get("snippet", "")).lower()] or pools["faction_role_pool"]
        summary, used_ids = synthesize_card_summary(scoped, subject=str(card.get("name", "")), max_words=40)
        if summary:
            card["summary"] = summary
        pointers = _pointers_for_source_ids(scoped, used_ids, revision_map)
        if pointers:
            faction_provenance_map[str(card["id"])] = pointers
            for pointer in pointers:
                used_source_ids.add(pointer["source_id"])
    sources = [
        {"source_id": source_id, "url": source_urls[source_id], "revision_id": revision_map.get(source_id)}
        for source_id in sorted(used_source_ids)
        if source_id in source_urls
    ]
    return {
        "zone_id": zone_id,
        "name": name,
        "wiki_url": source_url or "https://warcraft.wiki.gg/",
        "parent_continent": "unknown",
        "expansion_context": "retail",
        "at_a_glance": at_a_glance,
        "currently": currently,
        "history_sections": history_sections,
        "major_factions": faction_cards,
        "major_questlines": major_questlines,
        "location_cards": location_cards,
        "instance_links": instance_links,
        "glossary_refs": [],
        "sources": sources or _source_entries(fact_pack),
        "provenance": {
            "at_a_glance": at_a_glance_pointers,
            "currently": currently_pointers,
            "history": history_pointers,
            "major_questlines_alliance": questline_provenance_by_bucket["major_questlines_alliance"],
            "major_questlines_horde": questline_provenance_by_bucket["major_questlines_horde"],
            "major_questlines_shared": questline_provenance_by_bucket["major_questlines_shared"],
            "major_characters": {},
            "major_factions": faction_provenance_map,
            "instances": instance_provenance_map,
            "major_landmarks": landmark_provenance_map,
            "glossary": {},
        },
    }


def build_instance_page(
    fact_pack: dict[str, Any],
    evidence_rows: list[dict[str, Any]],
    lore_source: dict[str, Any] | None,
) -> dict[str, Any]:
    instance_id = str(fact_pack.get("entity_id", "instance-unknown"))
    name = str(fact_pack.get("name", instance_id))
    source_url = ""
    for source_id, url in (fact_pack.get("source_urls") or {}).items():
        if source_id and url:
            source_url = str(url)
            break
    inferred_type = "dungeon"
    lower_claims = " ".join(str(claim) for claim in fact_pack.get("claims", [])).lower()
    if "raid" in lower_claims:
        inferred_type = "raid"
    pools = _build_evidence_pools(evidence_rows)
    revision_map = _source_revision_map(fact_pack)
    source_urls = _source_url_map(fact_pack)
    used_source_ids: set[str] = set()
    at_a_glance_item = _first_item(
        evidence_rows, {"history_digest", "instances_or_dungeons", "other"}, min_words=10
    )
    overview_item = _first_item(
        evidence_rows, {"history_digest", "history", "other", "instances_or_dungeons"}, min_words=20
    )
    at_a_glance_pointer = (
        _pointer_for_item(at_a_glance_item, revision_map, 1) if at_a_glance_item else None
    )
    overview_pointer = _pointer_for_item(overview_item, revision_map, 1) if overview_item else None
    if at_a_glance_pointer:
        used_source_ids.add(at_a_glance_pointer["source_id"])
    if overview_pointer:
        used_source_ids.add(overview_pointer["source_id"])
    history_pool = select_history_pool(pools["history_pool"])
    history_sections, history_used = _history_sections_from_pool(history_pool, evidence_rows=evidence_rows)
    history_pointers = _pointers_for_source_ids(
        history_pool or select_history_pool(_iter_evidence_items(evidence_rows, {"history_digest"})),
        history_used,
        revision_map,
    )
    for pointer in history_pointers:
        used_source_ids.add(pointer["source_id"])
    key_enemy_provenance: dict[str, list[dict[str, str]]] = {}
    key_enemies = _build_key_enemies(evidence_rows)
    enemy_pointer = overview_pointer or at_a_glance_pointer or (history_pointers[0] if history_pointers else None)
    if enemy_pointer:
        for card in key_enemies:
            key_enemy_provenance[str(card["id"])] = [enemy_pointer]
    for source_id in source_urls:
        used_source_ids.add(source_id)
    sources = [
        {"source_id": source_id, "url": source_urls[source_id], "revision_id": revision_map.get(source_id)}
        for source_id in sorted(used_source_ids)
        if source_id in source_urls
    ]
    return {
        "instance_id": instance_id,
        "name": name,
        "instance_type": inferred_type,
        "parent_zone_id": str(fact_pack.get("parent_zone_id", "zone-unknown")),
        "expansion_context": "retail",
        "wiki_url": source_url or "https://warcraft.wiki.gg/",
        "at_a_glance": (
            str(at_a_glance_item["snippet"])
            if at_a_glance_item
            else f"{name} is a lore-significant retail instance."
        ),
        "overview": _sized_summary(
            str(overview_item["snippet"])
            if overview_item
            else f"{name} contains key enemies and encounter stakes captured from Warcraft Wiki.",
            20,
        ),
        "history_sections": history_sections,
        "key_enemies": key_enemies,
        "major_factions": _extract_factions(evidence_rows),
        "related_quest_chains": [],
        "lore_source": str((lore_source or {}).get("lore_source", "instance_page")),
        "lore_source_reason": (lore_source or {}).get("fallback_reason"),
        "variant_policy": "standalone",
        "variant_reason_codes": [],
        "glossary_refs": [],
        "sources": sources or _source_entries(fact_pack),
        "provenance": {
            "identity_header": [at_a_glance_pointer] if at_a_glance_pointer else [],
            "story_context": [overview_pointer] if overview_pointer else history_pointers,
            "key_characters": key_enemy_provenance,
        },
    }
