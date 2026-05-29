"""Draft generation: legacy single-call and staged multi-call pipelines."""

from __future__ import annotations

from typing import Any

from pipeline.common.run_context import RunContext
from pipeline.contracts.models import ENTITY_MODEL_MAP
from pipeline.generate.draft import legacy, staged
from pipeline.generate.draft.mode import draft_pipeline_mode
from pipeline.generate.draft.trace import DraftTraceContext


def is_valid_draft(entity_type: str, payload: dict[str, Any]) -> bool:
    model_type = ENTITY_MODEL_MAP[entity_type]
    try:
        model_type.model_validate(payload)
    except Exception:
        return False
    return True


def generate_entity_draft(
    fact_pack: dict[str, Any],
    entity_type: str,
    *,
    context: RunContext | None = None,
    trace: DraftTraceContext | None = None,
) -> tuple[dict[str, Any], str]:
    """Dispatch to staged or legacy generator for the entity type."""
    mode = draft_pipeline_mode()
    if mode == "staged" and entity_type == "zone":
        return staged.staged_zone_draft(fact_pack, context=context, trace=trace)
    if mode == "staged" and entity_type == "sub_zone":
        return staged.staged_sub_zone_draft(fact_pack, context=context, trace=trace)

    generators = {
        "zone": legacy.zone_draft,
        "sub_zone": legacy.sub_zone_draft,
        "instance": legacy.instance_draft,
        "character": legacy.character_draft,
        "glossary_term": legacy.glossary_term_draft,
        "asset": legacy.asset_draft,
    }
    generator = generators.get(entity_type)
    if generator is None:
        raise RuntimeError(
            f"draft stage does not support entity_type '{entity_type}' for "
            f"entity '{fact_pack.get('entity_id', 'unknown')}'"
        )
    return generator(fact_pack, trace=trace)
