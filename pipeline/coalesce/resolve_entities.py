"""Coalesce stage implementation for stable entity candidate output."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha1
from pathlib import Path
from typing import Any

from pipeline.ai.config import load_ai_settings
from pipeline.ai.openai_client import chat_json_completion
from pipeline.coalesce.confidence_model import compute_confidence
from pipeline.common.run_context import RunContext


def _load_merge_rules() -> dict[str, object]:
    rules_path = Path(__file__).with_name("merge_rules.yaml")
    if not rules_path.exists():
        return {
            "confidence_threshold": 0.8,
            "dedupe_strategy": "exact_text_then_source_overlap",
            "contradiction_bias": "prefer_higher_revision_id",
        }
    confidence_threshold = 0.8
    dedupe_strategy = "exact_text_then_source_overlap"
    contradiction_bias = "prefer_higher_revision_id"
    for raw_line in rules_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("confidence_threshold:"):
            value = line.split(":", 1)[1].strip().strip('"')
            try:
                confidence_threshold = float(value)
            except ValueError:
                confidence_threshold = 0.8
        elif line.startswith("dedupe_strategy:"):
            dedupe_strategy = line.split(":", 1)[1].strip().strip('"')
        elif line.startswith("contradiction_bias:"):
            contradiction_bias = line.split(":", 1)[1].strip().strip('"')
    return {
        "confidence_threshold": confidence_threshold,
        "dedupe_strategy": dedupe_strategy,
        "contradiction_bias": contradiction_bias,
    }


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


def _tokenize(value: str) -> set[str]:
    return {token for token in value.lower().split() if token}


def _source_selection_for_claim(
    claim: str,
    source_rows: list[dict[str, Any]],
    *,
    contradiction_bias: str,
) -> tuple[dict[str, Any], str]:
    claim_tokens = _tokenize(claim)
    scored: list[tuple[float, dict[str, Any]]] = []
    for row in source_rows:
        body_tokens = _tokenize(str(row.get("body", "")))
        if not claim_tokens:
            overlap_score = 0.0
        else:
            overlap_score = len(claim_tokens.intersection(body_tokens)) / float(len(claim_tokens))
        scored.append((overlap_score, row))
    scored.sort(key=lambda item: item[0], reverse=True)
    best_score = scored[0][0]
    tied_rows = [row for score, row in scored if score == best_score]
    if len(tied_rows) == 1:
        return tied_rows[0], "highest_claim_overlap"

    def _priority_rank(row: dict[str, Any]) -> int:
        raw_priority = row.get("priority")
        if isinstance(raw_priority, int):
            return raw_priority
        if isinstance(raw_priority, str):
            return int(raw_priority) if raw_priority.isdigit() else 999
        return 999

    def _source_class_rank(row: dict[str, Any]) -> int:
        source_class = str(row.get("source_class", "")).strip().lower()
        if source_class == "warcraft_wiki":
            return 0
        return 1

    tied_rows = sorted(
        tied_rows,
        key=lambda row: (
            _priority_rank(row),
            _source_class_rank(row),
            str(row.get("source_id", "")),
        ),
    )
    best_priority = _priority_rank(tied_rows[0])
    best_class_rank = _source_class_rank(tied_rows[0])
    same_priority_rows = [
        row
        for row in tied_rows
        if _priority_rank(row) == best_priority and _source_class_rank(row) == best_class_rank
    ]
    if len(same_priority_rows) == 1:
        return same_priority_rows[0], "tie_break_priority_source_class"

    if contradiction_bias == "prefer_higher_revision_id":

        def _revision_rank(row: dict[str, Any]) -> int:
            revision_id = str(row.get("revision_id", "0"))
            if revision_id.startswith("mw:"):
                revision_id = revision_id.split(":", 1)[1]
            return int("".join(ch for ch in revision_id if ch.isdigit()) or "0")

        selected = max(same_priority_rows, key=_revision_rank)
        return selected, "tie_break_priority_then_revision_id"
    selected = same_priority_rows[0]
    return selected, "tie_break_first_source"


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
        source_row, source_selection_reason = _source_selection_for_claim(
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
                        "tie-break order: claim overlap -> priority -> source_class -> "
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
    (stage_dir / "coalesce_decisions.json").write_text(
        json.dumps(decisions, indent=2),
        encoding="utf-8",
    )
    return output_path
