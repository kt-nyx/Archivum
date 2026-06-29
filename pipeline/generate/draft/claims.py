"""Source-side evidence claim extraction for draft temporal routing.

This module intentionally models *evidence* claims, not coalesced entity facts or
post-draft validation claims. It emits sidecar-only source claims from canonical evidence
paragraphs, with no draft-routing changes.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Any

from pipeline.ai.config import load_ai_settings
from pipeline.common.text_normalize import clean_wiki_snippet
from pipeline.generate.draft.llm import llm_json_with_retry
from pipeline.generate.draft.prose_lint import split_sentences, word_count

_CLAIM_EXTRACTOR_VERSION = "evidence_claim_sentence_v1"
_LLM_CLAIM_EXTRACTOR_VERSION = "evidence_claim_llm_v1"
# Public aliases consumed by the data-model version manifest (Slice 11).
CLAIM_EXTRACTOR_VERSION = _CLAIM_EXTRACTOR_VERSION
LLM_CLAIM_EXTRACTOR_VERSION = _LLM_CLAIM_EXTRACTOR_VERSION
_LONG_PARAGRAPH_WORD_THRESHOLD = 70
_LONG_SENTENCE_WORD_THRESHOLD = 32
_MIN_SUPPORT_OVERLAP_RATIO = 0.34
_PROMPT_SNIPPET_LIMIT = 2400
_CLAIM_TEXT_LIMIT = 240
_STOPWORDS = frozenset(
    {
        "about",
        "after",
        "again",
        "against",
        "also",
        "among",
        "around",
        "because",
        "before",
        "between",
        "during",
        "from",
        "have",
        "into",
        "itself",
        "later",
        "more",
        "near",
        "over",
        "than",
        "that",
        "their",
        "there",
        "these",
        "they",
        "this",
        "through",
        "under",
        "where",
        "which",
        "while",
        "with",
        "within",
        "without",
    }
)
_WORD_RE = re.compile(r"\b[\w']+\b")


@dataclass(frozen=True)
class EvidenceClaim:
    claim_id: str
    canonical_evidence_id: str
    subject_id: str
    source_id: str
    source_title: str
    claim_text: str
    claim_type: str
    entities: list[dict[str, str]]
    source_sentence_indexes: list[int]
    source_excerpt: str
    extraction_confidence: float
    extraction_reason: str
    source_passthrough_risk: bool = False
    source_passthrough_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "canonical_evidence_id": self.canonical_evidence_id,
            "subject_id": self.subject_id,
            "source_id": self.source_id,
            "source_title": self.source_title,
            "claim_text": self.claim_text,
            "claim_type": self.claim_type,
            "entities": self.entities,
            "source_sentence_indexes": self.source_sentence_indexes,
            "source_excerpt": self.source_excerpt,
            "extraction_confidence": self.extraction_confidence,
            "extraction_reason": self.extraction_reason,
            "source_passthrough_risk": self.source_passthrough_risk,
            "source_passthrough_reason": self.source_passthrough_reason,
        }


def extract_canonical_claim_decision_rows(
    canonical_records: Iterable[Any],
    *,
    run_id: str,
) -> list[dict[str, Any]]:
    """Build deterministic claim-extraction sidecar rows for canonical evidence records."""
    rows: list[dict[str, Any]] = []
    for record in canonical_records:
        canonical_evidence_id = str(getattr(record, "canonical_evidence_id", "")).strip()
        snippet = str(getattr(record, "snippet", "")).strip()
        if not canonical_evidence_id or not snippet:
            continue
        subject_id = str(getattr(record, "subject_id", "")).strip()
        source_id = str(getattr(record, "source_id", "")).strip()
        source_title = str(getattr(record, "source_title", "")).strip()
        appearances = _record_appearances(record)
        sentence_claims = extract_sentence_claims(
            canonical_evidence_id=canonical_evidence_id,
            subject_id=subject_id,
            source_id=source_id,
            source_title=source_title,
            snippet=snippet,
            appearances=appearances,
        )
        candidate_reasons = _llm_candidate_reasons(record, sentence_claims)
        extraction_mode = "deterministic_sentence"
        extraction_reason = "sentence_level_claims_sufficient"
        llm_error = ""
        sentence_backfill_count = 0
        claims_source = sentence_claims
        if candidate_reasons:
            if _llm_claim_extraction_disabled():
                extraction_mode = "sentence_fallback"
                extraction_reason = "llm_unavailable_or_disabled"
            else:
                try:
                    llm_claims = _extract_claims_llm(
                        canonical_evidence_id=canonical_evidence_id,
                        subject_id=subject_id,
                        source_id=source_id,
                        source_title=source_title,
                        snippet=snippet,
                        appearances=appearances,
                        sentence_claims=sentence_claims,
                        candidate_reasons=candidate_reasons,
                    )
                except Exception as exc:  # pragma: no cover - provider failures use fallback
                    llm_claims = []
                    llm_error = exc.__class__.__name__
                if llm_claims:
                    claims_source = _with_uncovered_sentence_backfill(llm_claims, sentence_claims)
                    sentence_backfill_count = len(claims_source) - len(llm_claims)
                    extraction_mode = "llm_semantic"
                    extraction_reason = (
                        "llm_semantic_claim_split_with_sentence_backfill"
                        if sentence_backfill_count
                        else "llm_semantic_claim_split"
                    )
                else:
                    extraction_mode = "sentence_fallback"
                    extraction_reason = "llm_failed_or_returned_no_supported_claims"
        claims = [
            claim.to_dict()
            for claim in claims_source
        ]
        rows.append(
            {
                "canonical_evidence_id": canonical_evidence_id,
                "subject_id": subject_id,
                "subject_type": str(getattr(record, "subject_type", "")).strip(),
                "run_id": run_id or "unknown",
                "source_id": source_id,
                "source_title": source_title,
                "source_excerpt": snippet,
                "snippet_hash": hashlib.sha256(snippet.encode("utf-8")).hexdigest()[:20],
                "appearance_count": len(appearances),
                "appearances": appearances,
                "extractor_version": (
                    _LLM_CLAIM_EXTRACTOR_VERSION
                    if extraction_mode == "llm_semantic"
                    else _CLAIM_EXTRACTOR_VERSION
                ),
                "extraction_mode": extraction_mode,
                "extraction_reason": extraction_reason,
                "candidate_reasons": candidate_reasons,
                "llm_error": llm_error,
                "sentence_backfill_count": sentence_backfill_count,
                "claim_count": len(claims),
                "claims": claims,
            }
        )
    return rows


def extract_sentence_claims(
    *,
    canonical_evidence_id: str,
    subject_id: str,
    source_id: str,
    source_title: str,
    snippet: str,
    appearances: list[dict[str, Any]],
) -> list[EvidenceClaim]:
    """Return one conservative evidence claim for each sentence in ``snippet``."""
    cleaned = clean_wiki_snippet(snippet)
    sentences = split_sentences(cleaned)
    if not sentences and cleaned:
        sentences = [cleaned]
    claim_type = _infer_claim_type(appearances)
    entities = _entities_from_appearances(subject_id=subject_id, appearances=appearances)
    claims: list[EvidenceClaim] = []
    for sentence_index, sentence in enumerate(sentences):
        claim_text = sentence.strip()
        if not claim_text:
            continue
        source_sentence_indexes = [sentence_index]
        passthrough_risk, passthrough_reason = _source_passthrough_check(
            claim_text, [claim_text], extraction_mode="deterministic_sentence"
        )
        claims.append(
            EvidenceClaim(
                claim_id=_claim_id(
                    canonical_evidence_id=canonical_evidence_id,
                    claim_text=claim_text,
                    source_sentence_indexes=source_sentence_indexes,
                ),
                canonical_evidence_id=canonical_evidence_id,
                subject_id=subject_id,
                source_id=source_id,
                source_title=source_title,
                claim_text=claim_text,
                claim_type=claim_type,
                entities=entities,
                source_sentence_indexes=source_sentence_indexes,
                source_excerpt=claim_text,
                extraction_confidence=0.72,
                extraction_reason="deterministic_sentence_split",
                source_passthrough_risk=passthrough_risk,
                source_passthrough_reason=passthrough_reason,
            )
        )
    return claims


def _with_uncovered_sentence_backfill(
    llm_claims: list[EvidenceClaim],
    sentence_claims: list[EvidenceClaim],
) -> list[EvidenceClaim]:
    covered_indexes = {
        index
        for claim in llm_claims
        for index in claim.source_sentence_indexes
    }
    output = list(llm_claims)
    for sentence_claim in sentence_claims:
        if all(index in covered_indexes for index in sentence_claim.source_sentence_indexes):
            continue
        output.append(
            replace(
                sentence_claim,
                extraction_confidence=min(sentence_claim.extraction_confidence, 0.68),
                extraction_reason="sentence_fallback_uncovered_by_llm",
            )
        )
    return output


def _extract_claims_llm(
    *,
    canonical_evidence_id: str,
    subject_id: str,
    source_id: str,
    source_title: str,
    snippet: str,
    appearances: list[dict[str, Any]],
    sentence_claims: list[EvidenceClaim],
    candidate_reasons: list[str],
) -> list[EvidenceClaim]:
    sentences = [claim.claim_text for claim in sentence_claims]
    result = llm_json_with_retry(
        required_keys=("claims",),
        response_json_schema=_claim_extraction_schema(),
        system_prompt=_claim_extraction_system_prompt(),
        user_prompt=_claim_extraction_user_prompt(
            subject_id=subject_id,
            source_id=source_id,
            source_title=source_title,
            snippet=snippet,
            appearances=appearances,
            sentences=sentences,
            candidate_reasons=candidate_reasons,
        ),
        response_schema_name="wiki_first_evidence_claim_extraction",
        substep="wiki_first_evidence_claim_extraction",
        max_attempts=2,
    )
    raw_claims = result.get("claims", [])
    if not isinstance(raw_claims, list):
        return []
    fallback_type = _infer_claim_type(appearances)
    claims: list[EvidenceClaim] = []
    seen: set[tuple[str, tuple[int, ...]]] = set()
    for row in raw_claims:
        if not isinstance(row, dict):
            continue
        claim_text = clean_wiki_snippet(str(row.get("claim_text", ""))).strip()
        claim_text = claim_text[:_CLAIM_TEXT_LIMIT].strip()
        if not claim_text:
            continue
        claim_type = str(row.get("claim_type", "")).strip()
        if claim_type not in _claim_type_values():
            claim_type = fallback_type
        sentence_indexes = _sanitize_sentence_indexes(
            row.get("source_sentence_indexes"),
            sentence_count=len(sentences),
        )
        if not sentence_indexes:
            continue
        source_excerpt = _source_excerpt_for_sentence_indexes(sentences, sentence_indexes)
        if not _claim_supported_by_source(claim_text, source_excerpt or snippet):
            continue
        entities = _sanitize_entities(row.get("entities"))
        if not entities:
            entities = _entities_from_appearances(subject_id=subject_id, appearances=appearances)
        extraction_reason = clean_wiki_snippet(str(row.get("extraction_reason", ""))).strip()
        passthrough_risk, passthrough_reason = _source_passthrough_check(
            claim_text,
            [source_excerpt or snippet],
            extraction_mode="llm_semantic",
        )
        key = (_normalized_claim_text(claim_text), tuple(sentence_indexes))
        if key in seen:
            continue
        seen.add(key)
        claims.append(
            EvidenceClaim(
                claim_id=_claim_id(
                    canonical_evidence_id=canonical_evidence_id,
                    claim_text=claim_text,
                    source_sentence_indexes=sentence_indexes,
                ),
                canonical_evidence_id=canonical_evidence_id,
                subject_id=subject_id,
                source_id=source_id,
                source_title=source_title,
                claim_text=claim_text,
                claim_type=claim_type,
                entities=entities,
                source_sentence_indexes=sentence_indexes,
                source_excerpt=source_excerpt,
                extraction_confidence=0.82 if not passthrough_risk else 0.7,
                extraction_reason=extraction_reason or "llm_semantic_split",
                source_passthrough_risk=passthrough_risk,
                source_passthrough_reason=passthrough_reason,
            )
        )
    return claims


def _claim_id(
    *,
    canonical_evidence_id: str,
    claim_text: str,
    source_sentence_indexes: list[int],
) -> str:
    payload = {
        "canonical_evidence_id": canonical_evidence_id,
        "claim_text": _normalized_claim_text(claim_text),
        "source_sentence_indexes": source_sentence_indexes,
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest()[:20]
    return f"claim-{digest}"


def _normalized_claim_text(text: str) -> str:
    return " ".join(text.casefold().split())


def _record_appearances(record: Any) -> list[dict[str, Any]]:
    appearances = getattr(record, "appearances", [])
    if not isinstance(appearances, list):
        return []
    return [row for row in appearances if isinstance(row, dict)]


def _llm_candidate_reasons(record: Any, sentence_claims: list[EvidenceClaim]) -> list[str]:
    reasons: list[str] = []
    appearances = _record_appearances(record)
    field_names = {str(row.get("field_name", "")).strip() for row in appearances}
    if "history_digest" in field_names and field_names.intersection(
        {"currently_input", "at_a_glance_input"}
    ):
        reasons.append("history_current_shared_paragraph")
    if _distinct_structural_temporal_scopes(record) > 1:
        reasons.append("multiple_structural_temporal_signals")
    snippet = str(getattr(record, "snippet", "")).strip()
    if word_count(snippet) >= _LONG_PARAGRAPH_WORD_THRESHOLD:
        reasons.append("long_paragraph")
    if any(
        ";" in claim.claim_text or word_count(claim.claim_text) >= _LONG_SENTENCE_WORD_THRESHOLD
        for claim in sentence_claims
    ):
        reasons.append("sentence_level_claim_may_contain_multiple_events")
    if _matches_setup_and_outcome_context(record):
        reasons.append("matches_setup_and_outcome_boundary_context")
    return list(dict.fromkeys(reasons))


def _distinct_structural_temporal_scopes(record: Any) -> int:
    scopes: set[str] = set()
    for classification in getattr(record, "structural_classifications", []) or []:
        scope = str(getattr(classification, "scope", "")).strip()
        if scope:
            scopes.add(scope)
    classification = getattr(record, "classification", None)
    scope = str(getattr(classification, "scope", "")).strip()
    if scope:
        scopes.add(scope)
    return len(scopes)


def _matches_setup_and_outcome_context(record: Any) -> bool:
    boundary = getattr(record, "boundary", {})
    if not isinstance(boundary, dict):
        return False
    snippet = str(getattr(record, "snippet", "")).strip()
    if not snippet:
        return False
    setup_text = str(boundary.get("entry_state_digest", "")).strip()
    outcome_parts: list[str] = []
    outcome_hints = boundary.get("outcome_hints")
    if isinstance(outcome_hints, list):
        for hint in outcome_hints:
            if not isinstance(hint, dict):
                continue
            for value in hint.values():
                if isinstance(value, str):
                    outcome_parts.append(value)
                elif isinstance(value, list):
                    outcome_parts.extend(str(item) for item in value if str(item).strip())
    outcome_text = " ".join(outcome_parts)
    return _text_has_structural_overlap(snippet, setup_text) and _text_has_structural_overlap(
        snippet, outcome_text
    )


def _infer_claim_type(appearances: list[dict[str, Any]]) -> str:
    field_names = {str(row.get("field_name", "")).strip() for row in appearances}
    candidates: set[str] = set()
    if "boss_pool" in field_names:
        candidates.add("encounter_state")
    if field_names.intersection({"questline_pool", "quest_cluster_lore", "quest_lore"}):
        candidates.add("objective")
    if "faction_pool" in field_names:
        candidates.add("faction_presence")
    if "location_pool" in field_names:
        candidates.add("location_status")
    if field_names.intersection({"currently_input", "at_a_glance_input"}):
        candidates.add("state")
    if "history_digest" in field_names:
        candidates.add("event")
    if len(candidates) == 1:
        return next(iter(candidates))
    return "other"


def _claim_type_values() -> set[str]:
    return {
        "event",
        "state",
        "identity",
        "relationship",
        "objective",
        "location_status",
        "faction_presence",
        "encounter_state",
        "other",
    }


def _entities_from_appearances(
    *,
    subject_id: str,
    appearances: list[dict[str, Any]],
) -> list[dict[str, str]]:
    entities: dict[tuple[str, str, str], dict[str, str]] = {}
    if subject_id:
        entities[("subject", subject_id, "")] = {
            "role": "subject",
            "entity_id": subject_id,
            "name": "",
        }
    for appearance in appearances:
        for entity_role, id_key, name_key in (
            ("faction", "faction_id", "faction_name"),
            ("location", "location_id", "location_name"),
            ("quest_cluster", "cluster_id", ""),
            ("quest", "quest_node_id", ""),
        ):
            entity_id = str(appearance.get(id_key, "")).strip()
            name = str(appearance.get(name_key, "")).strip() if name_key else ""
            if not entity_id and not name:
                continue
            key = (entity_role, entity_id, name)
            entities[key] = {
                "role": entity_role,
                "entity_id": entity_id,
                "name": name,
            }
    return [entities[key] for key in sorted(entities)]


def _llm_claim_extraction_disabled() -> bool:
    if os.environ.get("WOW_LORE_WIKI_FIRST_NO_LLM", "").casefold() in {"1", "true", "yes"}:
        return True
    settings = load_ai_settings()
    return not settings.openai_ready


def _claim_extraction_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["claims"],
        "properties": {
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "claim_text",
                        "claim_type",
                        "source_sentence_indexes",
                        "entities",
                        "extraction_reason",
                    ],
                    "properties": {
                        "claim_text": {"type": "string", "minLength": 1, "maxLength": 240},
                        "claim_type": {
                            "type": "string",
                            "enum": sorted(_claim_type_values()),
                        },
                        "source_sentence_indexes": {
                            "type": "array",
                            "items": {"type": "integer", "minimum": 0},
                            "minItems": 1,
                        },
                        "entities": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["role", "entity_id", "name"],
                                "properties": {
                                    "role": {"type": "string"},
                                    "entity_id": {"type": "string"},
                                    "name": {"type": "string"},
                                },
                            },
                        },
                        "extraction_reason": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 220,
                        },
                    },
                },
            }
        },
    }


def _claim_extraction_system_prompt() -> str:
    return (
        "You split Warcraft source paragraphs into the smallest useful factual claims for an "
        "internal evidence sidecar. Preserve the source's meaning exactly. Do not invent facts, "
        "do not resolve ambiguity, and do not add lore from memory. Prefer concise paraphrases "
        "over copying full source sentences, but keep named entities, places, factions, and "
        "outcomes explicit. Each claim must cite the source sentence indexes it came from."
    )


def _claim_extraction_user_prompt(
    *,
    subject_id: str,
    source_id: str,
    source_title: str,
    snippet: str,
    appearances: list[dict[str, Any]],
    sentences: list[str],
    candidate_reasons: list[str],
) -> str:
    payload = {
        "subject_id": subject_id,
        "source_id": source_id,
        "source_title": source_title,
        "candidate_reasons": candidate_reasons,
        "source_paragraph": snippet[:_PROMPT_SNIPPET_LIMIT],
        "sentences": [
            {"index": index, "text": sentence}
            for index, sentence in enumerate(sentences)
        ],
        "appearances": appearances,
        "allowed_claim_types": sorted(_claim_type_values()),
        "instructions": [
            "Split independent events, states, objectives, outcomes, and faction/location facts.",
            "Keep each claim grounded in one or more listed source sentence indexes.",
            "Return no claim unless the listed source sentence directly supports it.",
            "Do not include temporal labels or spoiler judgments in this step.",
        ],
    }
    return json.dumps(payload, ensure_ascii=True, indent=2)


def _sanitize_sentence_indexes(value: object, *, sentence_count: int) -> list[int]:
    indexes: list[int] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, int) and 0 <= item < sentence_count:
                indexes.append(item)
    return list(dict.fromkeys(indexes))


def _source_excerpt_for_sentence_indexes(sentences: list[str], indexes: list[int]) -> str:
    selected = [sentences[index] for index in indexes if 0 <= index < len(sentences)]
    return " ".join(selected).strip()


def _sanitize_entities(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    entities: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in value:
        if not isinstance(row, dict):
            continue
        entity = {
            "role": str(row.get("role", "")).strip(),
            "entity_id": str(row.get("entity_id", "")).strip(),
            "name": str(row.get("name", "")).strip(),
        }
        key = (entity["role"], entity["entity_id"], entity["name"])
        if key in seen or not any(entity.values()):
            continue
        seen.add(key)
        entities.append(entity)
    return entities


def _claim_supported_by_source(claim_text: str, source_excerpt: str) -> bool:
    claim_tokens = _content_tokens(claim_text)
    if not claim_tokens:
        return False
    source_tokens = _content_tokens(source_excerpt)
    if not source_tokens:
        return False
    overlap = claim_tokens.intersection(source_tokens)
    required = max(1, math.ceil(len(claim_tokens) * _MIN_SUPPORT_OVERLAP_RATIO))
    if len(claim_tokens) >= 2:
        required = max(2, required)
    return len(overlap) >= required


def _text_has_structural_overlap(text: str, context: str) -> bool:
    text_tokens = _content_tokens(text)
    context_tokens = _content_tokens(context)
    if not text_tokens or not context_tokens:
        return False
    return len(text_tokens.intersection(context_tokens)) >= 2


def _content_tokens(text: str) -> set[str]:
    return {
        token.casefold()
        for token in _WORD_RE.findall(text)
        if len(token) >= 4 and token.casefold() not in _STOPWORDS
    }


def _source_passthrough_check(
    claim_text: str,
    source_texts: list[str],
    *,
    extraction_mode: str,
) -> tuple[bool, str]:
    normalized_claim = _normalized_claim_text(claim_text)
    if not normalized_claim:
        return False, ""
    for source_text in source_texts:
        normalized_source = _normalized_claim_text(source_text)
        if not normalized_source:
            continue
        if normalized_claim == normalized_source and word_count(claim_text) >= 12:
            if extraction_mode == "llm_semantic":
                return True, "llm_claim_matches_source_sentence"
            return True, "sentence_claim_is_source_sentence"
        if extraction_mode == "llm_semantic" and normalized_claim in normalized_source:
            if word_count(claim_text) >= 16:
                return True, "llm_claim_is_long_source_substring"
    return False, "paraphrase_or_short_claim"
