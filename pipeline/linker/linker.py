"""Glossary linker first-pass implementation."""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, TypedDict, cast

from pipeline.common.config_loading import coerce_float, load_yaml_mapping
from pipeline.common.io import write_json
from pipeline.common.run_context import RunContext, append_trace_event
from pipeline.glossary.run_terms import (
    load_run_terms,
    run_terms_metadata_map,
    run_terms_to_alias_dictionary,
)

AUTO_LINK_MIN = 0.87
REVIEW_MIN = 0.65


class LinkCandidate(TypedDict):
    term_id: str
    confidence: float
    category: str
    alias: str
    match_index: int
    section_name: str
    section_text: str


def _load_linker_rules() -> dict[str, float]:
    """Return alias-match thresholds from ``rules.yaml`` (alias_thresholds section)."""
    defaults = {"direct_alias_match": 0.95, "contextual_match": 0.85}
    data = load_yaml_mapping(Path(__file__).with_name("rules.yaml"))
    thresholds = data.get("alias_thresholds")
    rules = dict(defaults)
    if isinstance(thresholds, dict):
        for key, default in defaults.items():
            if key in thresholds:
                rules[key] = coerce_float(thresholds[key], default)
    return rules


def _word_count(payload: dict[str, Any]) -> int:
    text = " ".join(section_text for _section_name, section_text in _matching_sections(payload))
    return len([token for token in text.split() if token.strip()])


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_static_alias_dictionary() -> list[dict[str, str]]:
    dictionary_path = _repo_root() / "dictionary" / "glossary_aliases.v1.json"
    if not dictionary_path.exists():
        return []
    payload = json.loads(dictionary_path.read_text(encoding="utf-8"))
    aliases = payload.get("aliases", []) if isinstance(payload, dict) else []
    normalized: list[dict[str, str]] = []
    if isinstance(aliases, list):
        for row in aliases:
            if not isinstance(row, dict):
                continue
            term_id = str(row.get("term_id", "")).strip()
            alias = str(row.get("alias", "")).strip()
            if not term_id or not alias:
                continue
            normalized.append(
                {
                    "term_id": term_id,
                    "alias": alias,
                    "alias_type": str(row.get("alias_type", "canonical")).strip().lower(),
                    "case_rule": str(row.get("case_rule", "insensitive")).strip().lower(),
                    "category": str(row.get("category", "")).strip().lower(),
                }
            )
        return normalized
    if isinstance(aliases, dict):
        legacy_aliases = cast(dict[str, object], aliases)
        # Backward compatibility path for older dictionary shape.
        for term_id, value in legacy_aliases.items():
            if not isinstance(term_id, str):
                continue
            category = ""
            raw_aliases: list[object] = []
            if isinstance(value, list):
                raw_aliases = value
            elif isinstance(value, dict):
                aliases_value = value.get("aliases")
                if isinstance(aliases_value, list):
                    raw_aliases = aliases_value
                category_value = value.get("category")
                if isinstance(category_value, str):
                    category = category_value.strip().lower()
            for alias_value in raw_aliases:
                alias_text = str(alias_value).strip()
                if not alias_text:
                    continue
                normalized.append(
                    {
                        "term_id": term_id.strip(),
                        "alias": alias_text,
                        "alias_type": "legacy",
                        "case_rule": "insensitive",
                        "category": category,
                    }
                )
    return normalized


def _log_static_fallback(context: RunContext | None, surface: str) -> None:
    """Record that the static glossary dictionary was used as a last resort."""
    if context is None:
        return
    append_trace_event(
        context,
        stage_name="linker",
        attempt=1,
        status="degraded",
        details={
            "glossary": "static_dictionary_fallback",
            "surface": surface,
            "reason": "run_terms_empty",
        },
    )


def _load_alias_dictionary(context: RunContext | None = None) -> list[dict[str, str]]:
    if context is not None:
        run_terms = load_run_terms(context)
        if run_terms:
            return run_terms_to_alias_dictionary(run_terms)
    _log_static_fallback(context, "alias_dictionary")
    return _load_static_alias_dictionary()


def _load_term_metadata(context: RunContext) -> dict[str, dict[str, str]]:
    run_terms = load_run_terms(context)
    if run_terms:
        return run_terms_metadata_map(run_terms)
    _log_static_fallback(context, "term_metadata")
    static_rows = _load_static_alias_dictionary()
    metadata: dict[str, dict[str, str]] = {}
    for row in static_rows:
        term_id = str(row.get("term_id", "")).strip()
        alias = str(row.get("alias", "")).strip()
        if not term_id or not alias:
            continue
        if row.get("alias_type", "") != "canonical" and term_id in metadata:
            continue
        wiki_slug = alias.replace(" ", "_")
        metadata[term_id] = {
            "term_id": term_id,
            "label": alias,
            "wiki_url": f"https://warcraft.wiki.gg/wiki/{wiki_slug}",
            "category": str(row.get("category", "")).strip().lower(),
        }
    return metadata


def _preference_entity_type(entity_type: str) -> str:
    if entity_type == "zone_page":
        return "zone"
    if entity_type == "instance_page":
        return "instance"
    return entity_type


def _glossary_ref_payload(term_id: str, term_metadata: dict[str, dict[str, str]]) -> dict[str, str]:
    meta = term_metadata.get(term_id, {})
    label = str(meta.get("label", "")).strip()
    wiki_url = str(meta.get("wiki_url", "")).strip()
    if not label:
        label = term_id.removeprefix("term-").replace("-", " ").title()
    if not wiki_url.startswith("http"):
        wiki_url = f"https://warcraft.wiki.gg/wiki/{label.replace(' ', '_')}"
    return {"term_id": term_id, "label": label, "wiki_url": wiki_url}


def _append_card_sections(
    sections: list[tuple[str, str]],
    field_name: str,
    cards: object,
) -> None:
    if not isinstance(cards, list):
        return
    for index, card in enumerate(cards, start=1):
        if not isinstance(card, dict):
            continue
        parts: list[str] = []
        name = str(card.get("name", "")).strip()
        summary = str(card.get("summary", "")).strip()
        if name:
            parts.append(name)
        if summary:
            parts.append(summary)
        text = " ".join(parts).strip()
        if text:
            sections.append((f"{field_name}[{index}]", text))


def _load_category_preferences() -> dict[str, list[str]]:
    """Return entity-type -> preferred category list from ``category_preference.v1.yaml``."""
    data = load_yaml_mapping(_repo_root() / "rules" / "category_preference.v1.yaml")
    preferences_raw = data.get("preferences")
    preferences: dict[str, list[str]] = {}
    if isinstance(preferences_raw, dict):
        for key, values in preferences_raw.items():
            if not isinstance(values, list):
                continue
            normalized = [str(value).strip() for value in values if str(value).strip()]
            if normalized:
                preferences[str(key).strip()] = normalized
    return preferences


def _load_disambiguation_rules() -> dict[str, float]:
    """Return disambiguation thresholds from ``disambiguation.v1.yaml`` (policy section)."""
    defaults = {"min_margin": 0.1, "require_manual_review_below": 0.8}
    data = load_yaml_mapping(_repo_root() / "rules" / "disambiguation.v1.yaml")
    policy = data.get("policy")
    rules = dict(defaults)
    if isinstance(policy, dict):
        for key, default in defaults.items():
            if key in policy:
                rules[key] = coerce_float(policy[key], default)
    return rules


def _matching_sections(draft: dict[str, Any]) -> list[tuple[str, str]]:
    fields = (
        "at_a_glance",
        "currently",
        "history",
        "identity_header",
        "story_context",
        "overview",
        "summary",
        "brief_history",
        "short_history",
    )
    sections: list[tuple[str, str]] = [
        (field, str(draft.get(field, "")))
        for field in fields
        if isinstance(draft.get(field), str) and str(draft.get(field, "")).strip()
    ]
    history_sections = draft.get("history_sections")
    if isinstance(history_sections, list):
        for index, section in enumerate(history_sections, start=1):
            if not isinstance(section, dict):
                continue
            body = str(section.get("body", "")).strip()
            if not body:
                continue
            sections.append((f"history_sections[{index}]", body))
    _append_card_sections(sections, "major_factions", draft.get("major_factions"))
    _append_card_sections(sections, "location_cards", draft.get("location_cards"))
    _append_card_sections(sections, "instance_links", draft.get("instance_links"))
    _append_card_sections(sections, "key_characters", draft.get("key_characters"))
    return sections


def _first_match_index(haystack: str, alias: str, *, case_rule: str) -> int | None:
    flags = 0 if case_rule == "exact" else re.IGNORECASE
    pattern = re.compile(rf"\b{re.escape(alias)}\b", flags)
    match = pattern.search(haystack)
    if not match:
        return None
    return match.start()


def _has_contextual_presence(haystack: str, alias: str) -> bool:
    tokens = [token for token in re.split(r"[^a-z0-9]+", alias.lower()) if token]
    if not tokens:
        return False
    haystack_lower = haystack.lower()
    return all(token in haystack_lower for token in tokens)


def _alias_type_adjustment(alias_type: str) -> float:
    if alias_type == "canonical":
        return 0.03
    if alias_type == "exact_synonym":
        return 0.01
    if alias_type == "fuzzy":
        return -0.12
    return 0.0


def _normalize_valid_pointer(row: object) -> dict[str, str] | None:
    if not isinstance(row, dict):
        return None
    source_id = row.get("source_id")
    locator = row.get("locator")
    revision_id = row.get("revision_id")
    excerpt_hash = row.get("excerpt_hash")
    if (
        isinstance(source_id, str)
        and isinstance(locator, str)
        and isinstance(revision_id, str)
        and isinstance(excerpt_hash, str)
        and source_id
        and locator
        and revision_id
        and excerpt_hash
    ):
        return {
            "source_id": source_id,
            "locator": locator,
            "revision_id": revision_id,
            "excerpt_hash": excerpt_hash,
        }
    return None


def _first_valid_pointer(draft: dict[str, Any]) -> dict[str, str] | None:
    provenance = draft.get("provenance")
    if not isinstance(provenance, dict):
        return None
    candidate_sections = (
        "at_a_glance",
        "currently",
        "history",
        "identity_header",
        "story_context",
        "summary",
        "short_history",
        "brief_history",
    )
    for section in candidate_sections:
        section_rows = provenance.get(section)
        if not isinstance(section_rows, list):
            continue
        for row in section_rows:
            pointer = _normalize_valid_pointer(row)
            if pointer is not None:
                return pointer
    return None


_CARD_PROVENANCE_KEYS = {
    "major_factions": "major_factions",
    "location_cards": "major_landmarks",
    "instance_links": "instances",
    "key_characters": "key_characters",
}


def _pointer_for_section(draft: dict[str, Any], section_name: str) -> dict[str, str] | None:
    history_match = re.match(r"history_sections\[(\d+)\]", section_name)
    if history_match:
        index = int(history_match.group(1)) - 1
        history_sections = draft.get("history_sections")
        if isinstance(history_sections, list) and 0 <= index < len(history_sections):
            section = history_sections[index]
            if isinstance(section, dict):
                refs = section.get("source_refs")
                if isinstance(refs, list):
                    for row in refs:
                        pointer = _normalize_valid_pointer(row)
                        if pointer is not None:
                            return pointer
        provenance = draft.get("provenance")
        if isinstance(provenance, dict):
            history_rows = provenance.get("history")
            if isinstance(history_rows, list) and history_rows:
                if 0 <= index < len(history_rows):
                    pointer = _normalize_valid_pointer(history_rows[index])
                    if pointer is not None:
                        return pointer
                pointer = _normalize_valid_pointer(history_rows[0])
                if pointer is not None:
                    return pointer
        return None

    card_match = re.match(
        r"(major_factions|location_cards|instance_links|key_characters)\[(\d+)\]", section_name
    )
    if card_match:
        field_name = card_match.group(1)
        index = int(card_match.group(2)) - 1
        cards = draft.get(field_name)
        provenance = draft.get("provenance")
        if isinstance(cards, list) and isinstance(provenance, dict) and 0 <= index < len(cards):
            card = cards[index]
            if isinstance(card, dict):
                card_id = str(card.get("id", "")).strip()
                prov_key = _CARD_PROVENANCE_KEYS.get(field_name, field_name)
                pointer_map = provenance.get(prov_key)
                if isinstance(pointer_map, dict) and card_id:
                    card_pointers = pointer_map.get(card_id)
                    if isinstance(card_pointers, list):
                        for row in card_pointers:
                            pointer = _normalize_valid_pointer(row)
                            if pointer is not None:
                                return pointer
        return None

    if section_name == "overview":
        section_name = "story_context"
    elif section_name == "at_a_glance":
        provenance = draft.get("provenance")
        if (
            isinstance(provenance, dict)
            and not provenance.get("at_a_glance")
            and provenance.get("identity_header")
        ):
            section_name = "identity_header"

    provenance = draft.get("provenance")
    if not isinstance(provenance, dict):
        return None
    section_rows = provenance.get(section_name)
    if not isinstance(section_rows, list):
        return None
    for row in section_rows:
        pointer = _normalize_valid_pointer(row)
        if pointer is not None:
            return pointer
    return None


def run_glossary_linker(
    context: RunContext,
    draft_paths: list[Path],
    *,
    max_entity_concurrency: int = 4,
) -> Path:
    """Generate a deterministic linker QA report from draft glossary references."""
    rules = _load_linker_rules()
    alias_dictionary = _load_alias_dictionary(context)
    term_metadata = _load_term_metadata(context)
    category_preferences = _load_category_preferences()
    disambiguation_rules = _load_disambiguation_rules()
    linked_terms: dict[str, int] = {}
    term_coverage: dict[str, list[str]] = {}
    auto_link_terms: list[str] = []
    manual_review_candidates: list[dict[str, object]] = []
    false_positive_candidates: list[dict[str, object]] = []
    false_negative_candidates: list[dict[str, object]] = []
    rejected_candidates: list[dict[str, object]] = []

    def _collect_terms(draft_path: Path) -> dict[str, object]:
        draft = json.loads(draft_path.read_text(encoding="utf-8"))
        entity_type = draft_path.parent.name
        preferred_categories = set(
            category_preferences.get(_preference_entity_type(entity_type), [])
        )
        local_manual_candidates: list[dict[str, object]] = []
        local_rejects: list[dict[str, object]] = []
        existing_glossary = draft.get("glossary", draft.get("glossary_refs", []))
        output: list[str] = []
        if isinstance(existing_glossary, list):
            for glossary_link in existing_glossary:
                if not isinstance(glossary_link, dict):
                    continue
                term_id = glossary_link.get("term_id")
                if isinstance(term_id, str):
                    output.append(term_id)
        sections = _matching_sections(draft)
        sorted_alias_entries = sorted(
            alias_dictionary,
            key=lambda row: (-len(row["alias"]), row["alias"].lower(), row["term_id"]),
        )
        exact_candidates_by_alias: dict[tuple[str, str], list[LinkCandidate]] = {}
        contextual_candidates_by_alias: dict[tuple[str, str], list[LinkCandidate]] = {}
        for section_name, section_text in sections:
            for entry in sorted_alias_entries:
                alias = entry["alias"]
                term_id = entry["term_id"]
                category = entry["category"]
                case_rule = entry["case_rule"]
                alias_type = entry["alias_type"]
                category_bonus = 0.03 if category and category in preferred_categories else 0.0
                alias_confidence = min(
                    0.99,
                    (
                        rules["direct_alias_match"]
                        + _alias_type_adjustment(alias_type)
                        + category_bonus
                    ),
                )
                match_index = _first_match_index(section_text, alias, case_rule=case_rule)
                alias_key = alias.lower()
                key = (section_name, alias_key)
                if match_index is not None:
                    exact_candidates_by_alias.setdefault(key, []).append(
                        {
                            "term_id": term_id,
                            "confidence": alias_confidence,
                            "category": category,
                            "alias": alias,
                            "match_index": match_index,
                            "section_name": section_name,
                            "section_text": section_text,
                        }
                    )
                    continue
                if _has_contextual_presence(section_text, alias):
                    contextual_confidence = min(
                        0.99,
                        (
                            rules["contextual_match"]
                            + _alias_type_adjustment(alias_type)
                            + category_bonus
                        ),
                    )
                    contextual_candidates_by_alias.setdefault(key, []).append(
                        {
                            "term_id": term_id,
                            "confidence": contextual_confidence,
                            "category": category,
                            "alias": alias,
                            "match_index": 10**9,
                            "section_name": section_name,
                            "section_text": section_text,
                        }
                    )
        entity_id = str(draft.get("id", draft_path.stem))
        words = _word_count(draft)
        max_total_links = int(words * 0.04) if words > 0 else 0
        added_links = 0
        candidate_matches: list[tuple[str, float, str]] = []
        selected_term_sections: dict[str, tuple[str, str]] = {}
        section_term_links: list[tuple[str, str]] = []
        seen_section_term: set[tuple[str, str]] = set()
        # The link-density budget counts *distinct glossary terms*, not per-section link
        # instances — otherwise a few terms that recur across many sections (Andorhal,
        # Argent Crusade…) consume the whole budget and starve every other matched term,
        # collapsing the glossary index. Terms already present from the seed glossary count
        # as linked so they are never re-spent.
        seen_term_ids: set[str] = set(output)
        # Every section a term appears in (independent of the link budget) so the glossary
        # provenance pointer lookup can fall back across sections — a term linked once must
        # still find a section that carries a provenance pointer.
        term_section_coverage: dict[str, list[str]] = {}

        def _process_candidate_group(
            group_key: tuple[str, str],
            candidates: list[LinkCandidate],
            *,
            source_kind: str,
        ) -> None:
            nonlocal added_links
            if not candidates:
                return
            candidates_sorted = sorted(
                candidates,
                key=lambda row: (
                    row["match_index"],
                    -len(row["alias"]),
                    -row["confidence"],
                    row["term_id"],
                ),
            )
            best = candidates_sorted[0]
            same_alias = sorted(
                candidates,
                key=lambda row: (-row["confidence"], row["term_id"]),
            )
            best_confidence = same_alias[0]["confidence"]
            second_confidence = same_alias[1]["confidence"] if len(same_alias) > 1 else 0.0
            margin = best_confidence - second_confidence
            best_term_id = best["term_id"]
            candidate_matches.append((best_term_id, best_confidence, source_kind))
            section_name = best.get("section_name", "")
            section_text = best.get("section_text", "")
            _section_name_from_key, alias_key = group_key
            if margin < disambiguation_rules["min_margin"] and len(same_alias) > 1:
                local_manual_candidates.append(
                    {
                        "entity_id": entity_id,
                        "term_id": best_term_id,
                        "alias": alias_key,
                        "confidence": round(best_confidence, 2),
                        "reason": "ambiguous alias candidates require disambiguation",
                    }
                )
                return
            if best_confidence >= AUTO_LINK_MIN:
                coverage = term_section_coverage.setdefault(best_term_id, [])
                if section_name not in coverage:
                    coverage.append(section_name)
                section_key = (section_name, best_term_id)
                if section_key in seen_section_term or best_term_id in seen_term_ids:
                    # Already linked this term (here or in an earlier section): record the
                    # section for coverage but don't spend another unit of link budget.
                    seen_section_term.add(section_key)
                    return
                if added_links < max_total_links:
                    seen_section_term.add(section_key)
                    seen_term_ids.add(best_term_id)
                    section_term_links.append(section_key)
                    added_links += 1
                    selected_term_sections[best_term_id] = (section_name, section_text)
                else:
                    local_manual_candidates.append(
                        {
                            "entity_id": entity_id,
                            "term_id": best_term_id,
                            "alias": alias_key,
                            "confidence": round(best_confidence, 2),
                            "reason": "link density cap enforced",
                        }
                    )
                return
            if best_confidence >= REVIEW_MIN:
                local_manual_candidates.append(
                    {
                        "entity_id": entity_id,
                        "term_id": best_term_id,
                        "alias": alias_key,
                        "confidence": round(best_confidence, 2),
                        "reason": "confidence in review band",
                    }
                )
                return
            local_rejects.append(
                {
                    "entity_id": entity_id,
                    "term_id": best_term_id,
                    "alias": alias_key,
                    "confidence": round(best_confidence, 2),
                    "reason": "confidence below reject threshold",
                }
            )

        for alias_key_tuple in sorted(
            exact_candidates_by_alias,
            key=lambda value: (value[0], -len(value[1]), value[1]),
        ):
            _process_candidate_group(
                alias_key_tuple,
                exact_candidates_by_alias[alias_key_tuple],
                source_kind="direct_alias",
            )
        for alias_key_tuple in sorted(
            contextual_candidates_by_alias,
            key=lambda value: (value[0], -len(value[1]), value[1]),
        ):
            _process_candidate_group(
                alias_key_tuple,
                contextual_candidates_by_alias[alias_key_tuple],
                source_kind="contextual_candidate",
            )
        for _section_name, term_id in section_term_links:
            if term_id not in output:
                output.append(term_id)
        if len(output) > max_total_links:
            dropped_terms = output[max_total_links:]
            output = output[:max_total_links]
            for dropped in dropped_terms:
                local_manual_candidates.append(
                    {
                        "entity_id": entity_id,
                        "term_id": dropped,
                        "reason": "link density cap enforced",
                    }
                )
        density = (len(output) * 100.0 / words) if words else 0.0
        if entity_type in {"zone", "sub_zone", "zone_page", "instance_page"}:
            provenance = draft.get("provenance")
            if isinstance(provenance, dict):
                glossary_map = provenance.get("glossary")
                if not isinstance(glossary_map, dict):
                    glossary_map = {}
                for term_id in output:
                    section_candidates: list[str] = []
                    primary_section, _section_text = selected_term_sections.get(term_id, ("", ""))
                    if primary_section:
                        section_candidates.append(primary_section)
                    for section_name in term_section_coverage.get(term_id, []):
                        if section_name not in section_candidates:
                            section_candidates.append(section_name)
                    pointer: dict[str, str] | None = None
                    for section_name in section_candidates:
                        pointer = _pointer_for_section(draft, section_name)
                        if pointer is not None:
                            break
                    if pointer is None:
                        continue
                    # Multiple glossary terms legitimately share a citing paragraph, so the
                    # term's provenance pointer is NOT deduped by (source_id, locator) — doing
                    # so collapsed the glossary to one term per section (the breadth bug).
                    rows = glossary_map.get(term_id)
                    if not isinstance(rows, list) or not rows:
                        glossary_map[term_id] = [pointer]
                provenance["glossary"] = glossary_map
                draft["provenance"] = provenance
                output = [
                    term_id
                    for term_id in output
                    if term_id in glossary_map and glossary_map[term_id]
                ]
                density = (len(output) * 100.0 / words) if words else 0.0
        glossary_payload = [_glossary_ref_payload(term_id, term_metadata) for term_id in output]
        if entity_type in {"zone_page", "instance_page"}:
            draft["glossary_refs"] = glossary_payload
        else:
            draft["glossary"] = glossary_payload
        write_json(draft_path, draft)
        return {
            "entity_id": entity_id,
            "term_ids": output,
            "word_count": words,
            "link_density_per_100_words": round(density, 2),
            "candidate_matches": candidate_matches,
            "manual_candidates": local_manual_candidates,
            "rejected_candidates": local_rejects,
        }

    with ThreadPoolExecutor(max_workers=max_entity_concurrency) as executor:
        futures = [executor.submit(_collect_terms, path) for path in draft_paths]
        for future in futures:
            record = future.result()
            entity_id = str(record["entity_id"])
            raw_term_ids = record.get("term_ids")
            term_ids = (
                [str(term_id) for term_id in raw_term_ids] if isinstance(raw_term_ids, list) else []
            )
            if not term_ids:
                false_negative_candidates.append(
                    {
                        "entity_id": entity_id,
                        "reason": "no glossary links present",
                    }
                )
            density_value = record.get("link_density_per_100_words")
            link_density = float(density_value) if isinstance(density_value, (float, int)) else 0.0
            raw_manual_candidates = record.get("manual_candidates")
            if isinstance(raw_manual_candidates, list):
                for manual_candidate in raw_manual_candidates:
                    if isinstance(manual_candidate, dict):
                        manual_review_candidates.append(manual_candidate)
            raw_rejected = record.get("rejected_candidates")
            if isinstance(raw_rejected, list):
                for rejected in raw_rejected:
                    if isinstance(rejected, dict):
                        rejected_candidates.append(rejected)
            if link_density > 4.0:
                manual_review_candidates.append(
                    {
                        "entity_id": entity_id,
                        "reason": "link density exceeds cap",
                        "link_density_per_100_words": link_density,
                    }
                )
            seen_in_entity: set[str] = set()
            for term_id in term_ids:
                linked_terms[term_id] = linked_terms.get(term_id, 0) + 1
                term_coverage.setdefault(term_id, []).append(entity_id)
                seen_in_entity.add(term_id)
                auto_link_terms.append(term_id)
                if term_ids.count(term_id) > 1:
                    false_positive_candidates.append(
                        {
                            "entity_id": entity_id,
                            "term_id": term_id,
                            "reason": "duplicate term link in single entity",
                        }
                    )
            raw_candidates = record.get("candidate_matches")
            if isinstance(raw_candidates, list):
                for candidate in raw_candidates:
                    if not isinstance(candidate, tuple) and not isinstance(candidate, list):
                        continue
                    if len(candidate) != 3:
                        continue
                    term_id = str(candidate[0])
                    confidence = float(candidate[1])
                    if REVIEW_MIN <= confidence < AUTO_LINK_MIN:
                        manual_review_candidates.append(
                            {
                                "entity_id": entity_id,
                                "term_id": term_id,
                                "confidence": round(confidence, 2),
                                "reason": "candidate requires manual review",
                            }
                        )

    total_links = sum(linked_terms.values())
    manual_count = len(manual_review_candidates)
    precision_estimate = 1.0 if total_links == 0 else max(0.5, 1.0 - (manual_count / total_links))

    report = {
        "run_id": context.run_id,
        "rules": {
            **rules,
            **disambiguation_rules,
            "auto_link_min": AUTO_LINK_MIN,
            "review_min": REVIEW_MIN,
        },
        "linked_terms": linked_terms,
        "term_coverage": term_coverage,
        "auto_link_terms": sorted(set(auto_link_terms)),
        "precision_estimate": round(precision_estimate, 2),
        "false_positive_candidates": false_positive_candidates,
        "false_negative_candidates": false_negative_candidates,
        "manual_review_candidates": manual_review_candidates,
        "rejected_candidates": rejected_candidates,
    }
    stage_dir = context.stage_dir("linker")
    output_path = stage_dir / "linker_qa_report.json"
    write_json(output_path, report)
    return output_path
