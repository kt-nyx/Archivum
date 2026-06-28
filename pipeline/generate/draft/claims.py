"""Source-side evidence claim extraction for draft temporal routing.

This module intentionally models *evidence* claims, not coalesced entity facts or
post-draft validation claims. Slice 3 keeps extraction deterministic and conservative:
one source-side claim per sentence in a canonical evidence paragraph, with no routing changes.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from pipeline.common.text_normalize import clean_wiki_snippet
from pipeline.generate.draft.prose_lint import split_sentences

_CLAIM_EXTRACTOR_VERSION = "evidence_claim_sentence_v1"


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
        claims = [
            claim.to_dict()
            for claim in extract_sentence_claims(
                canonical_evidence_id=canonical_evidence_id,
                subject_id=subject_id,
                source_id=source_id,
                source_title=source_title,
                snippet=snippet,
                appearances=appearances,
            )
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
                "extractor_version": _CLAIM_EXTRACTOR_VERSION,
                "extraction_mode": "deterministic_sentence",
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
