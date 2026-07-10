"""Assertion-level fact-check validation (Slice 15).

The fact-check verdict comes solely from an LLM adjudicator that judges each drafted
passage against the *cited source text* — the paragraphs a passage's provenance
pointers name, plus their surrounding section context. The former token-overlap
scoring path (which passed "built **above** Caer Darrow" against a source saying
"beneath") is deleted: no lexical-overlap score ever decides
``supported`` / ``unsupported`` / ``contradicted``. Slice 8's lemmatized scoring
stays on the synthesis/retrieval side and never participates in a fact-check verdict.

A checked passage with no provenance pointers is a provenance defect (Slice 7 makes
pointers honest), not something to fuzzy-match around: it is recorded as a
``fact_check.unchecked_missing_pointers`` WARN and skipped.

Retrieval granularity: provenance pointer locators are synthesis-relative (Slice 7
assembly numbers them over the kept pointers, not over source offsets), so the
retrievable evidence unit is the cited *source body* — which contains the cited
paragraph together with its immediate section context. That whole body is handed to
the adjudicator.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from html import unescape
from typing import Any, cast
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pydantic import BaseModel

from pipeline.ai.config import AISettings, load_ai_settings
from pipeline.ai.openai_client import chat_json_completion
from pipeline.validate.profiles import FactCheckProfile, parse_fact_check_profile
from pipeline.validate.types import ValidationIssue, ValidationSeverity

HTML_TAG_RE = re.compile(r"<[^>]+>")
HISTORY_SECTION_BODY_RE = re.compile(r"^history_sections\[(?P<index>\d+)\]\.body$")

# Verdict vocabulary. ``unchecked_missing_pointers`` and ``unchecked`` are bookkeeping
# statuses (no adjudication happened) — only the first three come from the adjudicator.
_ADJUDICATED_STATUSES = frozenset({"supported", "unsupported", "contradicted"})

# Per-source evidence body cap handed to the adjudicator (tags stripped only): generous
# enough to carry the cited paragraph's section context, bounded so a huge page body
# can't blow the prompt.
_EVIDENCE_BODY_MAX_LEN = 2000


@dataclass(frozen=True)
class CheckedUnit:
    """One passage whose assertions are checked against its cited sources.

    ``central`` marks an identity / relationship / central-storyline assertion (a card's defining
    sentence or a page's central section claim). In the strict release profile an unsupported or
    contradicted *central* unit is a hard failure; a noncentral stylistic unit stays a warning
    (Slice 8, item 4).
    """

    path: str
    text: str
    source_ids: tuple[str, ...]
    central: bool = True


def _section_claims(entity_type: str, payload: dict[str, Any]) -> list[tuple[str, str]]:
    sections: tuple[str, ...]
    if entity_type in {"zone", "sub_zone"}:
        sections = ("at_a_glance", "currently", "history")
    elif entity_type == "instance":
        sections = ("identity_header", "story_context")
    elif entity_type == "character":
        sections = ("summary", "short_history")
    elif entity_type == "glossary_term":
        sections = ("summary", "brief_history")
    elif entity_type == "zone_page":
        sections = ("at_a_glance", "currently")
    elif entity_type == "instance_page":
        sections = ("at_a_glance", "overview")
    else:
        sections = ()
    claims: list[tuple[str, str]] = []
    for section in sections:
        value = payload.get(section)
        if isinstance(value, str) and value.strip():
            claims.append((section, value))
    if entity_type in {"zone_page", "instance_page"}:
        history_sections = payload.get("history_sections")
        if isinstance(history_sections, list):
            for index, section_row in enumerate(history_sections):
                if not isinstance(section_row, dict):
                    continue
                body = section_row.get("body")
                if isinstance(body, str) and body.strip():
                    claims.append((f"history_sections[{index}].body", body))
    return claims


def _clean_snippet(text: str, *, max_len: int = 280) -> str:
    cleaned = HTML_TAG_RE.sub(" ", text)
    cleaned = " ".join(unescape(cleaned).split())
    return cleaned[:max_len]


def _claim_provenance_keys(entity_type: str, section_name: str) -> list[str]:
    keys = [section_name]
    if section_name.startswith("history_sections["):
        if entity_type == "instance_page":
            keys.append("story_context")
        else:
            keys.append("history")
    elif entity_type == "instance_page":
        if section_name == "at_a_glance":
            keys.append("identity_header")
        elif section_name == "overview":
            keys.append("story_context")
    return list(dict.fromkeys(keys))


def _pointer_source_ids(pointers: object) -> list[str]:
    if not isinstance(pointers, list):
        return []
    source_ids: list[str] = []
    for pointer in pointers:
        if not isinstance(pointer, dict):
            continue
        source_id = pointer.get("source_id")
        if isinstance(source_id, str) and source_id and source_id not in source_ids:
            source_ids.append(source_id)
    return source_ids


def _history_section_source_ref_ids(payload: dict[str, Any], section_name: str) -> list[str]:
    match = HISTORY_SECTION_BODY_RE.match(section_name)
    if match is None:
        return []
    history_sections = payload.get("history_sections")
    if not isinstance(history_sections, list):
        return []
    section_index = int(match.group("index"))
    if section_index >= len(history_sections):
        return []
    section_row = history_sections[section_index]
    if not isinstance(section_row, dict):
        return []
    return _pointer_source_ids(section_row.get("source_refs"))


def _section_pointer_source_ids(
    payload: dict[str, Any],
    *,
    entity_type: str,
    section_name: str,
) -> list[str]:
    history_source_ids = _history_section_source_ref_ids(payload, section_name)
    if history_source_ids:
        return history_source_ids

    provenance = payload.get("provenance")
    if not isinstance(provenance, dict):
        return []
    for provenance_key in _claim_provenance_keys(entity_type, section_name):
        source_ids = _pointer_source_ids(provenance.get(provenance_key))
        if source_ids:
            return source_ids
    return []


def _card_provenance_source_ids(payload: dict[str, Any], group_key: str, card_id: str) -> list[str]:
    provenance = payload.get("provenance")
    if not isinstance(provenance, dict):
        return []
    group = provenance.get(group_key)
    if not isinstance(group, dict):
        return []
    return _pointer_source_ids(group.get(card_id))


def _card_units(entity_type: str, payload: dict[str, Any]) -> list[CheckedUnit]:
    """Faction / location / key-character card summaries (Slice 15 checked set).

    Card provenance lives per-card: zone/instance faction and instance key-character
    pointers hang off ``provenance.<group>[card_id]``; location cards carry their
    pointers inline on ``LocationCard.provenance``.
    """
    units: list[CheckedUnit] = []

    def _summary_units(field: str, group_key: str | None) -> None:
        cards = payload.get(field)
        if not isinstance(cards, list):
            return
        for index, card in enumerate(cards):
            if not isinstance(card, dict):
                continue
            summary = card.get("summary")
            if not isinstance(summary, str) or not summary.strip():
                continue
            card_id = str(card.get("id", "")).strip()
            if group_key is None:
                source_ids = _pointer_source_ids(card.get("provenance"))
            else:
                source_ids = _card_provenance_source_ids(payload, group_key, card_id)
            units.append(
                CheckedUnit(
                    path=f"{field}[{index}].summary",
                    text=summary,
                    source_ids=tuple(source_ids),
                )
            )

    if entity_type == "zone_page":
        _summary_units("major_factions", "major_factions")
        _summary_units("location_cards", None)
    elif entity_type == "instance_page":
        _summary_units("major_factions", "major_factions")
        _summary_units("key_characters", "key_characters")
    return units


def _checked_units(entity_type: str, payload: dict[str, Any]) -> list[CheckedUnit]:
    units: list[CheckedUnit] = [
        CheckedUnit(
            path=section_name,
            text=claim_text,
            source_ids=tuple(
                _section_pointer_source_ids(
                    payload, entity_type=entity_type, section_name=section_name
                )
            ),
        )
        for section_name, claim_text in _section_claims(entity_type, payload)
    ]
    units.extend(_card_units(entity_type, payload))
    return units


def _local_snapshot_map(
    validation_context: Mapping[str, object] | None,
) -> dict[str, dict[str, str]]:
    if not validation_context:
        return {}
    snapshots = validation_context.get("fact_check_source_snapshots")
    if not isinstance(snapshots, list):
        return {}
    source_map: dict[str, dict[str, str]] = {}
    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            continue
        source_id = snapshot.get("source_id")
        body = snapshot.get("body")
        url = snapshot.get("url")
        if (
            isinstance(source_id, str)
            and source_id
            and isinstance(body, str)
            and isinstance(url, str)
        ):
            source_map[source_id] = {"body": body, "url": url}
    return source_map


def _search_google_custom(
    *,
    query: str,
    max_results: int,
    api_key: str,
    cse_id: str,
) -> list[dict[str, str]]:
    params = urlencode({"key": api_key, "cx": cse_id, "q": query, "num": max_results})
    endpoint = f"https://www.googleapis.com/customsearch/v1?{params}"
    request = Request(endpoint, headers={"User-Agent": "wow-lore-factcheck/1.0"})
    with urlopen(request, timeout=15) as response:  # noqa: S310
        payload = json.loads(response.read().decode("utf-8"))
    items = payload.get("items", [])
    results: list[dict[str, str]] = []
    if not isinstance(items, list):
        return results
    for item in items:
        if not isinstance(item, dict):
            continue
        link = item.get("link")
        snippet = item.get("snippet")
        title = item.get("title")
        if isinstance(link, str) and isinstance(snippet, str):
            results.append(
                {
                    "url": link,
                    "snippet": _clean_snippet(snippet),
                    "title": title if isinstance(title, str) else "",
                }
            )
    return results


_ADJUDICATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["status", "confidence", "reason"],
    "properties": {
        "status": {"type": "string", "enum": sorted(_ADJUDICATED_STATUSES)},
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
    },
}


def _adjudicate_with_openai(
    *,
    settings: AISettings,
    claim_text: str,
    evidence_snippets: list[str],
    model: str,
) -> dict[str, object] | None:
    system_prompt = (
        "You are a strict fact-check adjudicator. Judge the DRAFTED PASSAGE only against the "
        "SOURCE EVIDENCE provided — never against outside knowledge. Verdicts: 'supported' when "
        "every assertion in the passage is stated by or directly entailed by the evidence; "
        "'contradicted' when any assertion conflicts with the evidence (for example an inverted "
        "spatial, temporal, or causal relation such as 'above' where the source says 'beneath'); "
        "'unsupported' when the evidence neither confirms nor contradicts the passage's "
        "assertions. Respond only with JSON: "
        '{"status":"supported|unsupported|contradicted","confidence":0.0,"reason":"..."}'
    )
    user_prompt = f"Drafted passage:\n{claim_text}\n\nSource evidence:\n" + "\n".join(
        f"- {snippet}" for snippet in evidence_snippets[:8]
    )
    parsed = chat_json_completion(
        settings,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=model,
        response_json_schema=_ADJUDICATION_SCHEMA,
        response_schema_name="fact_check_adjudication",
    )
    if not isinstance(parsed, dict):
        return None
    status = parsed.get("status")
    confidence = parsed.get("confidence")
    reason = parsed.get("reason")
    if status not in _ADJUDICATED_STATUSES:
        return None
    if not isinstance(confidence, (float, int)):
        confidence = 0.5
    if not isinstance(reason, str):
        reason = "no reason provided"
    return {
        "status": status,
        "confidence": float(confidence),
        "reason": reason,
        "model": model,
    }


def _status_issue(
    *,
    path: str,
    status: str,
    profile: FactCheckProfile,
    central: bool,
) -> ValidationIssue | None:
    strict = profile == FactCheckProfile.STRICT
    if status == "contradicted":
        # A contradiction is always a hard failure in the strict profile (item 4); noncentral
        # stylistic contradictions still hard-fail because a contradiction is never merely stylistic.
        severity = ValidationSeverity.HARD_FAIL if strict else ValidationSeverity.WARN
        return ValidationIssue(
            code="fact_check.contradiction",
            message=f"passage at {path} was adjudicated as contradicted by its cited sources",
            severity=severity,
            path=path,
        )
    if status == "unsupported":
        # Strict release: an unsupported *central* assertion (identity/relationship/central
        # storyline) is a hard failure; a noncentral stylistic unit stays a distinct warning.
        severity = (
            ValidationSeverity.HARD_FAIL if (strict and central) else ValidationSeverity.WARN
        )
        return ValidationIssue(
            code="fact_check.unsupported",
            message=f"passage at {path} is not supported by its cited sources",
            severity=severity,
            path=path,
        )
    if status == "unchecked_missing_pointers":
        return ValidationIssue(
            code="fact_check.unchecked_missing_pointers",
            message=(
                f"passage at {path} has no provenance pointers, so its assertions cannot be "
                "verified against a cited source"
            ),
            severity=ValidationSeverity.WARN,
            path=path,
        )
    return None


def _off_report(entity_type: str, entity_id: str, settings: AISettings) -> dict[str, Any]:
    return {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "profile": FactCheckProfile.OFF.value,
        "web_search_enabled": False,
        "web_search_available": settings.google_ready,
        "llm_enabled": False,
        "llm_available": settings.openai_ready,
        "llm_model": settings.openai_model,
        "targeted_for_adjudication": False,
        "risk_flagged": False,
        "target_reasons": [],
        "claim_count": 0,
        "claims": [],
        "review_queue": [],
    }


def validate_fact_check_rules(
    entity_type: str,
    parsed_entity: BaseModel,
    *,
    validation_context: Mapping[str, object] | None = None,
) -> tuple[list[ValidationIssue], dict[str, Any] | None]:
    """Adjudicate each checked passage against its cited sources with an LLM (structured output)."""
    settings = load_ai_settings()
    profile_value = None
    if validation_context:
        profile_value = validation_context.get("fact_check_profile")
    profile = parse_fact_check_profile(profile_value if isinstance(profile_value, str) else None)

    payload = parsed_entity.model_dump(mode="json")
    entity_id_value = payload.get("id") or payload.get("zone_id") or payload.get("instance_id")
    entity_id = str(entity_id_value) if isinstance(entity_id_value, str) else ""

    if profile == FactCheckProfile.OFF:
        return [], _off_report(entity_type, entity_id, settings)

    units = _checked_units(entity_type, payload)
    source_map = _local_snapshot_map(validation_context)

    web_search_enabled = bool(
        validation_context and validation_context.get("fact_check_web_search")
    )
    llm_enabled = bool(validation_context and validation_context.get("fact_check_enable_llm"))
    max_web_results_raw = (
        validation_context.get("fact_check_max_web_results") if validation_context else 3
    )
    max_web_results = int(max_web_results_raw) if isinstance(max_web_results_raw, int) else 3
    llm_model = settings.openai_model
    if validation_context and isinstance(validation_context.get("fact_check_llm_model"), str):
        llm_model = str(validation_context["fact_check_llm_model"])
    target_entity_ids: set[str] = set()
    if validation_context and isinstance(
        validation_context.get("fact_check_target_entity_ids"),
        list,
    ):
        raw_target_entity_ids = cast(
            list[object],
            validation_context["fact_check_target_entity_ids"],
        )
        target_entity_ids = {
            str(value) for value in raw_target_entity_ids if isinstance(value, str) and value
        }
    target_reason_map: dict[str, list[str]] = {}
    if validation_context and isinstance(validation_context.get("fact_check_target_reasons"), dict):
        raw_reason_map = cast(
            dict[object, object],
            validation_context["fact_check_target_reasons"],
        )
        target_reason_map = {
            str(key): [
                str(reason) for reason in cast(list[object], value) if isinstance(reason, str)
            ]
            for key, value in raw_reason_map.items()
            if isinstance(key, str) and isinstance(value, list)
        }
    # Slice 8, item 3: fact-check coverage is no longer confined to manual-link / coalescing risk
    # entities. Every drafted page's central section claims and every selected card's identity /
    # relationship summary are adjudicated. The risk set is retained only as recorded *reasons*, so
    # a run with no manual-link event still fact-checks its cards.
    targeted_for_adjudication = profile in {FactCheckProfile.WARN, FactCheckProfile.STRICT} and bool(
        entity_id
    )
    risk_flagged = entity_id in target_entity_ids
    target_reasons = target_reason_map.get(entity_id, [])

    issues: list[ValidationIssue] = []
    claim_rows: list[dict[str, Any]] = []
    review_queue: list[str] = []
    web_search_available = settings.google_ready
    llm_available = settings.openai_ready

    if web_search_enabled and targeted_for_adjudication and not web_search_available:
        issues.append(
            ValidationIssue(
                code="fact_check.web_unavailable",
                message=(
                    "web fact-check requested but GOOGLE_API_KEY/GOOGLE_CSE_ID are not configured"
                ),
                severity=ValidationSeverity.WARN,
                path="$",
            )
        )
    if llm_enabled and targeted_for_adjudication and not llm_available:
        severity = (
            ValidationSeverity.HARD_FAIL
            if profile == FactCheckProfile.STRICT
            else ValidationSeverity.WARN
        )
        issues.append(
            ValidationIssue(
                code="fact_check.llm_unavailable",
                message="LLM adjudication requested but OPENAI_API_KEY is not configured",
                severity=severity,
                path="$",
            )
        )

    entity_label = payload.get("name") or payload.get("label") or payload.get("id") or entity_type
    entity_label_text = str(entity_label)

    adjudicate = (
        llm_enabled
        and targeted_for_adjudication
        and llm_available
        and profile in {FactCheckProfile.WARN, FactCheckProfile.STRICT}
    )

    for unit in units:
        path = f"$.{unit.path}"
        claim_status, claim_confidence, adjudication_model, evidence_rows = _check_unit(
            unit,
            settings=settings,
            source_map=source_map,
            entity_label_text=entity_label_text,
            adjudicate=adjudicate,
            web_search_enabled=web_search_enabled and targeted_for_adjudication,
            web_search_available=web_search_available,
            max_web_results=max_web_results,
            llm_model=llm_model,
        )

        claim_issue = _status_issue(
            path=path, status=claim_status, profile=profile, central=unit.central
        )
        if claim_issue is not None:
            issues.append(claim_issue)
            review_queue.append(path)

        claim_rows.append(
            {
                "path": path,
                "status": claim_status,
                "confidence": round(claim_confidence, 3),
                "model": adjudication_model,
                "evidence": evidence_rows,
            }
        )

    report = {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "profile": profile.value,
        "web_search_enabled": web_search_enabled,
        "web_search_available": web_search_available,
        "llm_enabled": llm_enabled,
        "llm_available": llm_available,
        "llm_model": llm_model,
        "targeted_for_adjudication": targeted_for_adjudication,
        "risk_flagged": risk_flagged,
        "target_reasons": target_reasons,
        "claim_count": len(claim_rows),
        "claims": claim_rows,
        "review_queue": sorted(set(review_queue)),
    }
    return issues, report


def _check_unit(
    unit: CheckedUnit,
    *,
    settings: AISettings,
    source_map: dict[str, dict[str, str]],
    entity_label_text: str,
    adjudicate: bool,
    web_search_enabled: bool,
    web_search_available: bool,
    max_web_results: int,
    llm_model: str,
) -> tuple[str, float, str | None, list[dict[str, Any]]]:
    evidence_rows: list[dict[str, Any]] = []

    # Deterministic control markers for tests / offline control paths. Evaluated before the
    # pointer check so a marked passage always yields its intended verdict.
    normalized_upper = unit.text.upper()
    if "[CONTRADICTED]" in normalized_upper:
        return "contradicted", 0.95, None, evidence_rows
    if "[UNSUPPORTED]" in normalized_upper:
        return "unsupported", 0.9, None, evidence_rows

    if not unit.source_ids:
        # Provenance defect (Slice 7 makes pointers honest): nothing to verify against.
        return "unchecked_missing_pointers", 0.0, None, evidence_rows

    for source_id in unit.source_ids:
        source_snapshot = source_map.get(source_id)
        if source_snapshot is None:
            continue
        evidence_rows.append(
            {
                "kind": "local_snapshot",
                "source_id": source_id,
                "url": source_snapshot["url"],
                # Raw source text (tags stripped only): proper nouns and exact location
                # prepositions stay visible for the assertion adjudicator.
                "snippet": _clean_snippet(source_snapshot["body"], max_len=_EVIDENCE_BODY_MAX_LEN),
            }
        )

    if web_search_enabled and web_search_available:
        query = f"{entity_label_text} {unit.text[:170]}"
        try:
            web_hits = _search_google_custom(
                query=query,
                max_results=max_web_results,
                api_key=settings.google_api_key,
                cse_id=settings.google_cse_id,
            )
        except Exception as exc:  # pragma: no cover - external API/network variability
            web_hits = []
            evidence_rows.append({"kind": "web_error", "error": repr(exc)})
        for hit in web_hits:
            evidence_rows.append(
                {
                    "kind": "web_result",
                    "url": hit["url"],
                    "title": hit["title"],
                    "snippet": hit["snippet"],
                }
            )

    evidence_snippets = [
        str(row.get("snippet", ""))
        for row in evidence_rows
        if isinstance(row.get("snippet"), str) and row.get("snippet")
    ]
    if not evidence_snippets:
        # Pointers exist but no cited-source text is available to check against.
        return "unchecked", 0.0, None, evidence_rows

    if not adjudicate:
        return "unchecked", 0.0, None, evidence_rows

    try:
        adjudication = _adjudicate_with_openai(
            settings=settings,
            claim_text=unit.text,
            evidence_snippets=evidence_snippets,
            model=llm_model,
        )
    except Exception as exc:  # pragma: no cover - external API/network variability
        evidence_rows.append({"kind": "llm_error", "error": repr(exc)})
        return "unchecked", 0.0, None, evidence_rows
    if adjudication is None:
        return "unchecked", 0.0, None, evidence_rows

    claim_status = str(adjudication["status"])
    confidence_value = adjudication.get("confidence")
    claim_confidence = float(confidence_value) if isinstance(confidence_value, (float, int)) else 0.5
    adjudication_model = str(adjudication.get("model", llm_model))
    evidence_rows.append(
        {
            "kind": "llm_adjudication",
            "model": adjudication["model"],
            "reason": adjudication["reason"],
        }
    )
    return claim_status, claim_confidence, adjudication_model, evidence_rows
