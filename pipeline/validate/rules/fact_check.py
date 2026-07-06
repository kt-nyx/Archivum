"""Automated fact-check validation pass with optional web + LLM adjudication."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from html import unescape
from typing import Any, cast
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pydantic import BaseModel

from pipeline.ai.config import AISettings, load_ai_settings
from pipeline.ai.openai_client import chat_json_completion
from pipeline.common.text_sim import lemma_support_containment
from pipeline.validate.profiles import FactCheckProfile, parse_fact_check_profile
from pipeline.validate.types import ValidationIssue, ValidationSeverity

WORD_RE = re.compile(r"[a-z0-9']+")
HTML_TAG_RE = re.compile(r"<[^>]+>")
HISTORY_SECTION_BODY_RE = re.compile(r"^history_sections\[(?P<index>\d+)\]\.body$")

# Deterministic support thresholds for the token-overlap heuristics (previously inline).
LOCAL_SUPPORT_THRESHOLD = 0.08
WEB_SUPPORT_THRESHOLD = 0.12


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


def _tokenize(text: str) -> set[str]:
    return {token for token in WORD_RE.findall(text.lower()) if len(token) >= 3}


def _text_overlap_score(claim_text: str, evidence_text: str) -> float:
    claim_tokens = _tokenize(claim_text)
    if not claim_tokens:
        return 0.0
    evidence_tokens = _tokenize(evidence_text)
    if not evidence_tokens:
        return 0.0
    overlap = len(claim_tokens.intersection(evidence_tokens))
    return overlap / float(len(claim_tokens))


def _support_score(claim_text: str, evidence_text: str) -> float:
    """Surface token containment with a lemmatized fallback (Slice 8).

    The lemma variant only runs when the surface score is below every support threshold
    (spaCy over full page bodies is not free), and the result is the max of the two. This is
    a *support* signal only: it can raise a paraphrased/inflected claim to "supported", but
    contradiction is still decided solely by the LLM adjudicator / explicit markers — and the
    lemma token set keeps prepositions visible, so it never equates "above" with "beneath".
    """
    surface = _text_overlap_score(claim_text, evidence_text)
    if surface >= max(LOCAL_SUPPORT_THRESHOLD, WEB_SUPPORT_THRESHOLD):
        return surface  # already supported at every threshold; the fallback can't matter
    return max(surface, lemma_support_containment(claim_text, evidence_text))


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
        if isinstance(source_id, str) and source_id:
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


def _adjudicate_with_openai(
    *,
    settings: AISettings,
    claim_text: str,
    evidence_snippets: list[str],
    model: str,
) -> dict[str, object] | None:
    system_prompt = (
        "You are a strict fact-check adjudicator. Respond only with JSON: "
        '{"status":"supported|contradicted|insufficient_evidence","confidence":0.0,"reason":"..."}'
    )
    user_prompt = f"Claim:\n{claim_text}\n\nEvidence snippets:\n" + "\n".join(
        f"- {snippet}" for snippet in evidence_snippets[:8]
    )
    parsed = chat_json_completion(
        settings,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=model,
    )
    if not isinstance(parsed, dict):
        return None
    status = parsed.get("status")
    confidence = parsed.get("confidence")
    reason = parsed.get("reason")
    if status not in {"supported", "contradicted", "insufficient_evidence"}:
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
) -> ValidationIssue | None:
    if status == "contradicted":
        severity = (
            ValidationSeverity.HARD_FAIL
            if profile == FactCheckProfile.STRICT
            else ValidationSeverity.WARN
        )
        return ValidationIssue(
            code="fact_check.contradiction",
            message=f"claim at {path} was adjudicated as contradicted",
            severity=severity,
            path=path,
        )
    if status == "insufficient_evidence":
        return ValidationIssue(
            code="fact_check.insufficient_evidence",
            message=f"claim at {path} has insufficient supporting evidence",
            severity=ValidationSeverity.WARN,
            path=path,
        )
    return None


def validate_fact_check_rules(
    entity_type: str,
    parsed_entity: BaseModel,
    *,
    validation_context: Mapping[str, object] | None = None,
) -> tuple[list[ValidationIssue], dict[str, Any] | None]:
    """Validate claims against local sources and optional web/LLM adjudication."""
    settings = load_ai_settings()
    profile_value = None
    if validation_context:
        profile_value = validation_context.get("fact_check_profile")
    profile = parse_fact_check_profile(profile_value if isinstance(profile_value, str) else None)

    payload = parsed_entity.model_dump(mode="json")
    entity_id_value = payload.get("id") or payload.get("zone_id") or payload.get("instance_id")
    entity_id = str(entity_id_value) if isinstance(entity_id_value, str) else ""

    if profile == FactCheckProfile.OFF:
        report = {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "profile": profile.value,
            "web_search_enabled": False,
            "web_search_available": settings.google_ready,
            "llm_enabled": False,
            "llm_available": settings.openai_ready,
            "llm_model": settings.openai_model,
            "targeted_for_adjudication": False,
            "target_reasons": [],
            "claim_count": 0,
            "claims": [],
            "review_queue": [],
        }
        return [], report

    claims = _section_claims(entity_type, payload)
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
    targeted_for_adjudication = (
        profile in {FactCheckProfile.WARN, FactCheckProfile.STRICT}
        and bool(entity_id)
        and entity_id in target_entity_ids
    )
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

    for section_name, claim_text in claims:
        path = f"$.{section_name}"
        claim_status = "insufficient_evidence"
        claim_confidence = 0.5
        evidence_rows: list[dict[str, Any]] = []
        adjudication_model: str | None = None

        # Marker overrides remain available for deterministic test/control paths.
        normalized_upper = claim_text.upper()
        if "[CONTRADICTED]" in normalized_upper:
            claim_status = "contradicted"
            claim_confidence = 0.95
        elif "[UNCERTAIN]" in normalized_upper:
            claim_status = "insufficient_evidence"
            claim_confidence = 0.9

        section_source_ids = _section_pointer_source_ids(
            payload,
            entity_type=entity_type,
            section_name=section_name,
        )
        local_best_score = 0.0
        local_supported = False
        for source_id in section_source_ids:
            source_snapshot = source_map.get(source_id)
            if source_snapshot is None:
                continue
            score = _support_score(claim_text, source_snapshot["body"])
            local_best_score = max(local_best_score, score)
            evidence_rows.append(
                {
                    "kind": "local_snapshot",
                    "source_id": source_id,
                    "url": source_snapshot["url"],
                    "score": round(score, 3),
                    # Raw source text (tags stripped only): proper nouns and exact location
                    # prepositions stay visible for downstream assertion adjudication.
                    "snippet": _clean_snippet(source_snapshot["body"]),
                }
            )
            if score >= LOCAL_SUPPORT_THRESHOLD:
                local_supported = True

        if claim_status not in {"contradicted"}:
            if local_supported:
                claim_status = "supported"
                claim_confidence = max(claim_confidence, min(0.95, 0.55 + local_best_score))
            elif not section_source_ids:
                claim_status = "insufficient_evidence"
                claim_confidence = 0.6

        if (
            web_search_enabled
            and targeted_for_adjudication
            and web_search_available
            and claim_status != "contradicted"
            and not local_supported
        ):
            query = f"{entity_label_text} {claim_text[:170]}"
            try:
                web_hits = _search_google_custom(
                    query=query,
                    max_results=max_web_results,
                    api_key=settings.google_api_key,
                    cse_id=settings.google_cse_id,
                )
            except Exception as exc:  # pragma: no cover - external API/network variability
                web_hits = []
                evidence_rows.append(
                    {
                        "kind": "web_error",
                        "error": repr(exc),
                    }
                )
            web_best_score = 0.0
            for hit in web_hits:
                score = _support_score(claim_text, hit["snippet"])
                web_best_score = max(web_best_score, score)
                evidence_rows.append(
                    {
                        "kind": "web_result",
                        "url": hit["url"],
                        "title": hit["title"],
                        "score": round(score, 3),
                        "snippet": hit["snippet"],
                    }
                )
            if web_best_score >= WEB_SUPPORT_THRESHOLD:
                claim_status = "supported"
                claim_confidence = max(claim_confidence, min(0.9, 0.5 + web_best_score))

        if (
            llm_enabled
            and targeted_for_adjudication
            and llm_available
            and profile in {FactCheckProfile.WARN, FactCheckProfile.STRICT}
            and claim_status != "contradicted"
            and (claim_status == "insufficient_evidence" or claim_confidence < 0.85)
        ):
            evidence_snippets = [
                str(row.get("snippet", ""))
                for row in evidence_rows
                if isinstance(row.get("snippet"), str)
            ]
            try:
                adjudication = _adjudicate_with_openai(
                    settings=settings,
                    claim_text=claim_text,
                    evidence_snippets=evidence_snippets,
                    model=llm_model,
                )
            except Exception as exc:  # pragma: no cover - external API/network variability
                adjudication = None
                evidence_rows.append({"kind": "llm_error", "error": repr(exc)})
            if adjudication is not None:
                claim_status = str(adjudication["status"])
                confidence_value = adjudication.get("confidence")
                if isinstance(confidence_value, (float, int)):
                    claim_confidence = float(confidence_value)
                adjudication_model = str(adjudication.get("model", llm_model))
                evidence_rows.append(
                    {
                        "kind": "llm_adjudication",
                        "model": adjudication["model"],
                        "reason": adjudication["reason"],
                    }
                )

        claim_issue = _status_issue(path=path, status=claim_status, profile=profile)
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
        "target_reasons": target_reasons,
        "claim_count": len(claim_rows),
        "claims": claim_rows,
        "review_queue": sorted(set(review_queue)),
    }
    return issues, report
