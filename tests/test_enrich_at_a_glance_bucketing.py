"""RC3: at_a_glance_input carries essence (lead + one origin-arc paragraph), not event history.

The enrich-stage seed routing used to feed every narrative/history paragraph into
``at_a_glance_input``, flooding the essence field with granular event narration. Only the first
history paragraph (the origin/identity arc) may join the pool; the rest feed ``history_digest``
alone.
"""

from __future__ import annotations

from typing import Any

from pipeline.discovery.enrich import (
    _build_evidence_packs,
    _instance_seed_field_names,
    _seed_field_names,
)


def test_zone_seed_first_history_paragraph_joins_at_a_glance() -> None:
    names = _seed_field_names("history", lead_emitted=0, history_at_glance_emitted=0)
    assert "history_digest" in names
    assert "at_a_glance_input" in names


def test_zone_seed_later_history_paragraphs_feed_history_only() -> None:
    names = _seed_field_names("history", lead_emitted=2, history_at_glance_emitted=1)
    assert "history_digest" in names
    assert "at_a_glance_input" not in names


def test_zone_seed_lead_routing_unaffected_by_history_budget() -> None:
    names = _seed_field_names("lead", lead_emitted=0, history_at_glance_emitted=1)
    assert names == ["at_a_glance_input"]


def test_instance_seed_history_at_a_glance_budget() -> None:
    first = _instance_seed_field_names("history", lead_emitted=0, history_at_glance_emitted=0)
    later = _instance_seed_field_names("history", lead_emitted=0, history_at_glance_emitted=1)
    assert "at_a_glance_input" in first
    assert "at_a_glance_input" not in later
    assert "history_digest" in later


def _zone_seed_snapshot(history_texts: list[str]) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = [
        {
            "section_role": "lead",
            "parent_section_role": "",
            "block_type": "paragraph",
            "text": "A blighted frontier of fallen Lordaeron, its farmland scarred by plague.",
        }
    ]
    blocks.extend(
        {
            "section_role": "history",
            "parent_section_role": "",
            "block_type": "paragraph",
            "text": text,
        }
        for text in history_texts
    )
    return {
        "entity_id": "zone-testlands",
        "entity_type": "zone",
        "source_id": "src-zone",
        "url": "https://example.test/zone",
        "name": "Testlands",
        "page_title": "Testlands",
        "section_blocks": blocks,
    }


def test_build_evidence_packs_caps_history_in_at_a_glance_pool() -> None:
    snapshot = _zone_seed_snapshot(
        [
            "The land was once the fertile heartland of Lordaeron before the plague consumed it.",
            "Cauldron lords seized four farms and commanders fought over each in a long campaign.",
            "Later the Argent forces retook the towers and the mills in a series of battles.",
        ]
    )

    packs = _build_evidence_packs([snapshot], "run-test")

    at_glance_roles = [
        pack["build_meta"]["section_role"]
        for pack in packs
        if pack["field_name"] == "at_a_glance_input"
    ]
    history_packs = [pack for pack in packs if pack["field_name"] == "history_digest"]
    # Lead + exactly one origin-arc history paragraph reach the essence pool.
    assert at_glance_roles.count("history") == 1
    assert len(history_packs) == 3  # history_digest still carries the full chain
    origin_pack = next(
        pack
        for pack in packs
        if pack["field_name"] == "at_a_glance_input"
        and pack["build_meta"]["section_role"] == "history"
    )
    assert "fertile heartland" in origin_pack["evidence_items"][0]["snippet"]
