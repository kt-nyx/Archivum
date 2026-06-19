"""Coalesce stage implementation for stable entity candidate output."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha1
from pathlib import Path
from typing import Any

from pipeline.ai.config import load_ai_settings
from pipeline.ai.openai_client import chat_json_completion
from pipeline.coalesce.claim_scoring import select_source_for_claim
from pipeline.coalesce.confidence_model import compute_confidence
from pipeline.common.config_loading import coerce_float, load_yaml_mapping
from pipeline.common.io import write_json
from pipeline.common.run_context import RunContext


def _load_merge_rules() -> dict[str, object]:
    """Return flat merge policy from ``merge_rules.yaml`` (entity_resolution + claim_merge)."""
    defaults: dict[str, object] = {
        "confidence_threshold": 0.8,
        "dedupe_strategy": "exact_text_then_source_overlap",
        "contradiction_bias": "prefer_higher_revision_id",
    }
    data = load_yaml_mapping(Path(__file__).with_name("merge_rules.yaml"))
    entity_resolution = data.get("entity_resolution")
    claim_merge = data.get("claim_merge")
    rules = dict(defaults)
    if isinstance(entity_resolution, dict) and "confidence_threshold" in entity_resolution:
        rules["confidence_threshold"] = coerce_float(
            entity_resolution["confidence_threshold"], 0.8
        )
    if isinstance(claim_merge, dict):
        if claim_merge.get("dedupe_strategy"):
            rules["dedupe_strategy"] = str(claim_merge["dedupe_strategy"])
        if claim_merge.get("contradiction_bias"):
            rules["contradiction_bias"] = str(claim_merge["contradiction_bias"])
    return rules


def _stable_entity_id(seed: str) -> str:
    entity_prefix = seed.split("|", 1)[0].strip().replace("_", "-") or "entity"
    digest = sha1(seed.encode("utf-8")).hexdigest()[:12]
    return f"{entity_prefix}-{digest}"


def _excerpt_for_claim(source_row: dict[str, Any], claim: str) -> str:
    body = str(source_row.get("body", ""))
    normalized_claim = claim.strip()
    if not body:
        return normalized_claim
    lower_body = body.lower()
    lower_claim = normalized_claim.lower()
    if lower_claim:
        idx = lower_body.find(lower_claim)
        if idx >= 0:
            return body[idx : idx + len(normalized_claim)]
    first_sentence = body.split(".")[0].strip()
    return first_sentence or body[:220].strip() or normalized_claim


def _ai_coalesce_claims(
    *,
    entity_name: str,
    source_rows: list[dict[str, Any]],
    max_attempts: int = 3,
) -> tuple[list[str], dict[str, object]]:
    settings = load_ai_settings()
    if not settings.openai_ready:
        raise RuntimeError(
            f"coalesce requires OpenAI for entity '{entity_name}', "
            "but OPENAI_API_KEY is not configured"
        )
    joined_sources = "\n\n".join(
        f"[{row['source_id']}] {str(row.get('body', ''))[:1800]}" for row in source_rows
    )
    system_prompt = (
        "You merge lore source text into concise factual claim bullets. "
        'Return JSON: {"claims":["..."]}.'
    )
    user_prompt = (
        f"Entity: {entity_name}\n"
        "Extract up to 6 concise factual claims that are high-confidence and non-duplicative.\n"
        f"Sources:\n{joined_sources}"
    )
    errors: list[str] = []
    # OpenAI structured outputs (strict json_schema) accept only a subset of JSON Schema.
    # Do not use minItems/maxItems/minLength here — those reject the request with HTTP 400.
    # Length and non-empty checks are enforced in Python below (and claims capped at 6).
    claims_schema = {
        "type": "object",
        "required": ["claims"],
        "additionalProperties": False,
        "properties": {
            "claims": {
                "type": "array",
                "items": {"type": "string"},
            }
        },
    }
    for attempt in range(1, max_attempts + 1):
        response = chat_json_completion(
            settings,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=settings.openai_model,
            response_json_schema=claims_schema,
            response_schema_name="coalesce_claims",
        )
        if not isinstance(response, dict):
            errors.append(f"attempt={attempt}: non-JSON response")
            continue
        claims = response.get("claims")
        if not isinstance(claims, list):
            errors.append(f"attempt={attempt}: missing claims list")
            continue
        output: list[str] = []
        for claim in claims:
            if isinstance(claim, str) and claim.strip():
                output.append(claim.strip())
        if output:
            return output[:6], {
                "provider": getattr(settings, "provider", "openai"),
                "model": settings.openai_model,
                "prompt_profile": "coalesce_v1",
                "response_schema_name": "coalesce_claims",
                "attempts_used": attempt,
            }
        errors.append(f"attempt={attempt}: empty claims")
    joined_errors = "; ".join(errors)
    raise RuntimeError(
        "coalesce failed after "
        f"{max_attempts} attempts for entity '{entity_name}' ({joined_errors})"
    )


def _build_entity_row(
    entity_id: str,
    source_rows: list[dict[str, Any]],
    merge_rules: dict[str, object],
) -> dict[str, Any]:
    source_ids = [str(entry["source_id"]) for entry in source_rows]
    revision_ids = [str(entry["revision_id"]) for entry in source_rows]
    source_urls = {str(entry["source_id"]): str(entry.get("url", "")) for entry in source_rows}
    first = source_rows[0]
    claims, coalesce_ai = _ai_coalesce_claims(
        entity_name=str(first["name"]),
        source_rows=source_rows,
    )
    mode = "openai"
    raw_confidence_threshold = merge_rules.get("confidence_threshold", 0.8)
    confidence_threshold = (
        float(raw_confidence_threshold)
        if isinstance(raw_confidence_threshold, (float, int))
        else 0.8
    )
    contradiction_bias = str(merge_rules.get("contradiction_bias", "prefer_higher_revision_id"))
    fact_items = []
    for index, claim in enumerate(claims):
        source_row, source_selection_reason = select_source_for_claim(
            claim,
            source_rows,
            contradiction_bias=contradiction_bias,
        )
        locator_value = source_row.get("locator")
        if not isinstance(locator_value, str) or not locator_value.strip():
            raise RuntimeError(
                f"coalesce source row for entity '{entity_id}' claim {index} "
                "is missing required locator"
            )
        revision_id_value = source_row.get("revision_id")
        if not isinstance(revision_id_value, str) or not revision_id_value.strip():
            raise RuntimeError(
                f"coalesce source row for entity '{entity_id}' claim {index} "
                "is missing required revision_id"
            )
        excerpt = _excerpt_for_claim(source_row, claim)
        excerpt_hash = sha1(excerpt.encode("utf-8")).hexdigest()[:16]
        fact_items.append(
            {
                "claim_index": index,
                "claim": claim,
                "source_id": source_row["source_id"],
                "url": source_row.get("url", ""),
                "revision_id": revision_id_value,
                "locator": locator_value,
                "excerpt_hash": f"sha1:{excerpt_hash}",
                "source_selection_reason": source_selection_reason,
            }
        )
    return {
        "entity_id": entity_id,
        "entity_type": str(first["entity_type"]),
        "slug": str(first["slug"]),
        "name": str(first["name"]),
        "parent_zone_id": str(first.get("parent_zone_id", "")),
        "confidence": compute_confidence(
            mode=mode,
            source_count=len(source_ids),
            claim_count=len(claims),
            minimum=confidence_threshold,
        ),
        "source_ids": source_ids,
        "revision_ids": revision_ids,
        "source_urls": source_urls,
        "coalesce_mode": mode,
        "coalesce_ai": coalesce_ai,
        "merge_policy": merge_rules,
        "fact_items": fact_items,
    }


def run_resolve_entities(
    context: RunContext,
    source_manifest_path: Path,
    *,
    max_entity_concurrency: int = 4,
) -> Path:
    """Merge normalized sources into coalesced entity graph (AI-assisted by default)."""
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    snapshots_path = context.stage_dir("ingest") / "source_snapshots.json"
    snapshots = json.loads(snapshots_path.read_text(encoding="utf-8"))
    sources_by_id = {entry["source_id"]: entry for entry in snapshots}

    grouped: dict[str, list[dict[str, Any]]] = {}
    missing_snapshots: list[str] = []
    for entry in source_manifest:
        source_id = str(entry["source_id"])
        snapshot = sources_by_id.get(source_id)
        if snapshot is None:
            missing_snapshots.append(source_id)
            continue
        merged_snapshot = dict(snapshot)
        merged_snapshot["source_class"] = str(
            entry.get("source_class", snapshot.get("source_class", ""))
        )
        raw_priority = entry.get("priority")
        priority_value = 999
        if isinstance(raw_priority, int):
            priority_value = raw_priority
        elif isinstance(raw_priority, str) and raw_priority.isdigit():
            priority_value = int(raw_priority)
        merged_snapshot["priority"] = priority_value
        entity_seed = f"{entry['entity_type']}|{entry['slug']}|{entry['name']}"
        entity_id = str(entry.get("entity_id")) or _stable_entity_id(entity_seed)
        grouped.setdefault(entity_id, []).append(merged_snapshot)
    if missing_snapshots:
        joined = ", ".join(sorted(set(missing_snapshots)))
        raise RuntimeError(f"coalesce missing snapshots for source ids: {joined}")

    merge_rules = _load_merge_rules()
    coalesced_rows: list[dict[str, Any]] = []
    decisions: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=max_entity_concurrency) as executor:
        futures = [
            executor.submit(_build_entity_row, entity_id, rows, merge_rules)
            for entity_id, rows in grouped.items()
        ]
        for future in futures:
            row = future.result()
            coalesced_rows.append(row)
            decisions.append(
                {
                    "entity_id": row["entity_id"],
                    "coalesce_mode": row["coalesce_mode"],
                    "ai_provider": row.get("coalesce_ai", {}).get("provider"),
                    "ai_model": row.get("coalesce_ai", {}).get("model"),
                    "prompt_profile": row.get("coalesce_ai", {}).get("prompt_profile"),
                    "response_schema_name": row.get("coalesce_ai", {}).get("response_schema_name"),
                    "attempts_used": row.get("coalesce_ai", {}).get("attempts_used"),
                    "claim_count": len(row.get("fact_items", [])),
                    "source_count": len(row.get("source_ids", [])),
                    "confidence": row["confidence"],
                    "dedupe_strategy": str(row["merge_policy"].get("dedupe_strategy", "unknown")),
                    "contradiction_bias": str(
                        row["merge_policy"].get("contradiction_bias", "unknown")
                    ),
                    "tie_break_reason": (
                        "tie-break order: claim score -> priority -> source_class -> "
                        "merge policy contradiction bias "
                        f"'{row['merge_policy'].get('contradiction_bias', 'unknown')}'"
                    ),
                    "tie_break_events": sum(
                        1
                        for item in row.get("fact_items", [])
                        if str(item.get("source_selection_reason", "")).startswith("tie_break_")
                    ),
                    "claim_source_decisions": [
                        {
                            "claim_index": item.get("claim_index"),
                            "source_id": item.get("source_id"),
                            "source_selection_reason": item.get("source_selection_reason"),
                        }
                        for item in row.get("fact_items", [])
                        if isinstance(item, dict)
                    ],
                }
            )

    stage_dir = context.data_dir / "coalesced"
    stage_dir.mkdir(parents=True, exist_ok=True)
    output_path = stage_dir / "entities.jsonl"
    output_path.write_text(
        "\n".join(json.dumps(row) for row in coalesced_rows) + "\n",
        encoding="utf-8",
    )
    write_json((stage_dir / "coalesce_decisions.json"), decisions)
    return output_path
