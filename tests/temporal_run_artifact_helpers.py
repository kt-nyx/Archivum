from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


HISTORY_ELIGIBLE = frozenset({"history_background", "history_setup_bridge"})
RESTRICTED_TEMPORAL_SCOPES = frozenset(
    {"active_storyline_outcome", "post_active_lore", "excluded_noncanon"}
)
RESTRICTED_HISTORY_ELIGIBILITY = frozenset(
    {"history_excluded_outcome", "history_excluded_post_active"}
)


@dataclass(frozen=True)
class TemporalRunSummary:
    boundary_anchors_by_subject: dict[str, list[dict[str, Any]]]
    canonical_labels_by_subject: dict[str, list[dict[str, Any]]]
    history_eligible_missing_from_final: list[dict[str, Any]]
    restricted_evidence_in_final_text: list[dict[str, Any]]
    sidecars_present: set[str]
    sidecars_missing: set[str]


def summarize_temporal_run_artifacts(run_dir: Path) -> TemporalRunSummary:
    """Load run-like artifacts and summarize temporal label/draft mismatches.

    This is test instrumentation, not a semantic validator. It answers mechanical questions:
    which boundary anchors exist, which canonical paragraphs got which labels, which history-
    eligible source snippets are absent from final history text, and which restricted snippets
    appear in spoiler-sensitive final fields.
    """
    decisions_dir = run_dir / "data" / "decisions"
    canonical_rows = _read_json(decisions_dir / "canonical_temporal_evidence_decisions.json", [])
    boundary_rows = _read_json(decisions_dir / "content_boundary_decisions.json", [])
    drafts = _load_drafts(run_dir)

    boundary_anchors_by_subject = {
        str(row.get("entity_id", "")).strip(): list(row.get("anchors") or [])
        for row in boundary_rows
        if isinstance(row, dict) and str(row.get("entity_id", "")).strip()
    }
    canonical_labels_by_subject: dict[str, list[dict[str, Any]]] = {}
    for row in canonical_rows:
        if not isinstance(row, dict):
            continue
        subject_id = str(row.get("subject_id", "")).strip()
        if not subject_id:
            continue
        canonical_labels_by_subject.setdefault(subject_id, []).append(_canonical_label_summary(row))

    missing_history: list[dict[str, Any]] = []
    restricted_leaks: list[dict[str, Any]] = []
    for row in canonical_rows:
        if not isinstance(row, dict):
            continue
        subject_id = str(row.get("subject_id", "")).strip()
        if not subject_id:
            continue
        draft = drafts.get(subject_id, {})
        snippet = str(row.get("snippet", "")).strip()
        if not snippet:
            continue
        history_text = _draft_section_text(draft, "history")
        if str(row.get("history_eligibility", "")).strip() in HISTORY_ELIGIBLE:
            if not _snippet_appears(history_text, snippet):
                missing_history.append(_mismatch_row(row, section="history"))
        if _is_restricted(row):
            for section in ("history", "currently", "factions", "characters"):
                if _snippet_appears(_draft_section_text(draft, section), snippet):
                    restricted_leaks.append(_mismatch_row(row, section=section))

    sidecars = {
        "content_boundary_decisions.json",
        "canonical_temporal_evidence_decisions.json",
        "temporal_evidence_decisions.json",
        "entry_state_contract_decisions.json",
        "canonical_claim_extraction_decisions.json",
        "claim_temporal_decisions.json",
        "section_coverage_decisions.json",
    }
    present = {name for name in sidecars if (decisions_dir / name).exists()}
    return TemporalRunSummary(
        boundary_anchors_by_subject=boundary_anchors_by_subject,
        canonical_labels_by_subject=canonical_labels_by_subject,
        history_eligible_missing_from_final=missing_history,
        restricted_evidence_in_final_text=restricted_leaks,
        sidecars_present=present,
        sidecars_missing=sidecars - present,
    )


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _load_drafts(run_dir: Path) -> dict[str, dict[str, Any]]:
    drafts: dict[str, dict[str, Any]] = {}
    for folder in ("zone_page", "instance_page"):
        for path in (run_dir / "data" / "drafts" / folder).glob("*.json"):
            payload = _read_json(path, {})
            if not isinstance(payload, dict):
                continue
            subject_id = str(
                payload.get("zone_id") or payload.get("instance_id") or payload.get("id") or ""
            ).strip()
            if subject_id:
                drafts[subject_id] = payload
    return drafts


def _canonical_label_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "canonical_evidence_id": str(row.get("canonical_evidence_id", "")).strip(),
        "source_id": str(row.get("source_id", "")).strip(),
        "temporal_scope": str(row.get("temporal_scope", "")).strip(),
        "history_eligibility": str(row.get("history_eligibility", "")).strip(),
        "appearance_fields": sorted(
            {
                str(appearance.get("field_name", "")).strip()
                for appearance in row.get("appearances") or []
                if isinstance(appearance, dict)
                and str(appearance.get("field_name", "")).strip()
            }
        ),
        "snippet": str(row.get("snippet", "")).strip(),
    }


def _mismatch_row(row: dict[str, Any], *, section: str) -> dict[str, Any]:
    return {
        "subject_id": str(row.get("subject_id", "")).strip(),
        "canonical_evidence_id": str(row.get("canonical_evidence_id", "")).strip(),
        "source_id": str(row.get("source_id", "")).strip(),
        "temporal_scope": str(row.get("temporal_scope", "")).strip(),
        "history_eligibility": str(row.get("history_eligibility", "")).strip(),
        "section": section,
        "snippet": str(row.get("snippet", "")).strip(),
    }


def _is_restricted(row: dict[str, Any]) -> bool:
    return (
        str(row.get("temporal_scope", "")).strip() in RESTRICTED_TEMPORAL_SCOPES
        or str(row.get("history_eligibility", "")).strip() in RESTRICTED_HISTORY_ELIGIBILITY
    )


def _draft_section_text(draft: dict[str, Any], section: str) -> str:
    if section == "history":
        return " ".join(
            _card_text(card, ("heading", "body")) for card in draft.get("history_sections") or []
        )
    if section == "currently":
        return " ".join(
            str(draft.get(key, "")).strip() for key in ("currently", "at_a_glance")
        )
    if section == "factions":
        return " ".join(_card_text(card, ("name", "summary")) for card in draft.get("major_factions") or [])
    if section == "characters":
        return " ".join(
            _card_text(card, ("name", "summary")) for card in draft.get("key_characters") or []
        )
    return ""


def _card_text(card: Any, keys: tuple[str, ...]) -> str:
    if not isinstance(card, dict):
        return ""
    return " ".join(str(card.get(key, "")).strip() for key in keys if str(card.get(key, "")).strip())


def _snippet_appears(text: str, snippet: str) -> bool:
    normalized_text = _normalize_text(text)
    normalized_snippet = _normalize_text(snippet)
    if not normalized_text or not normalized_snippet:
        return False
    if normalized_snippet in normalized_text:
        return True
    return any(fragment in normalized_text for fragment in _normalized_snippet_fragments(snippet))


def _normalized_snippet_fragments(snippet: str) -> list[str]:
    """Return distinctive exact fragments from a source snippet for mechanical matching.

    Final prose often carries one sentence or clause from a source paragraph, not the full
    paragraph. This remains deliberately non-semantic: it only matches exact normalized fragments.
    """
    fragments: list[str] = []
    for delimiter in (". ", "; ", ": "):
        pieces = [piece for part in (fragments or [snippet]) for piece in part.split(delimiter)]
        fragments = pieces
    normalized: list[str] = []
    for fragment in fragments:
        clean = _normalize_text(fragment.strip(" .;:"))
        if len(clean) >= 40 and len(clean.split()) >= 6:
            normalized.append(clean)
    return normalized


def _normalize_text(text: str) -> str:
    return " ".join(str(text or "").casefold().split())
