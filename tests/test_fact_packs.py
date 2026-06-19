"""Unit tests for the coalesce fact-pack reshape and missing-URL guard (S6)."""

import pytest

from pipeline.coalesce.fact_packs import build_fact_pack


def _row(**overrides):
    row = {
        "entity_id": "zone-western-plaguelands-abc123",
        "entity_type": "zone",
        "slug": "western-plaguelands",
        "name": "Western Plaguelands",
        "parent_zone_id": "",
        "confidence": 0.91,
        "source_ids": ["src-1"],
        "revision_ids": ["rev-1"],
        "source_urls": {"src-1": "https://wiki.example/wp"},
        "coalesce_mode": "openai",
        "fact_items": [
            {
                "claim_index": 0,
                "claim": "The zone was scoured by the Scourge.",
                "source_id": "src-1",
                "url": "https://wiki.example/wp",
                "revision_id": "rev-1",
                "locator": "intro",
                "excerpt_hash": "sha1:deadbeef",
                "source_selection_reason": "highest_priority",
            }
        ],
    }
    row.update(overrides)
    return row


def test_build_fact_pack_reshapes_row() -> None:
    pack = build_fact_pack(_row())
    assert pack["entity_id"] == "zone-western-plaguelands-abc123"
    assert pack["claims"] == ["The zone was scoured by the Scourge."]
    assert pack["source_urls"] == {"src-1": "https://wiki.example/wp"}
    assert pack["coalesce_mode"] == "openai"
    # No coalesce-internal bookkeeping leaks into the fact pack.
    assert "coalesce_ai" not in pack
    assert "merge_policy" not in pack


def test_build_fact_pack_falls_back_to_fact_item_urls() -> None:
    row = _row(source_urls={})
    pack = build_fact_pack(row)
    assert pack["source_urls"] == {"src-1": "https://wiki.example/wp"}


def test_build_fact_pack_raises_on_missing_source_url() -> None:
    row = _row(source_urls={}, fact_items=[])
    with pytest.raises(RuntimeError, match="coalesce missing source URLs"):
        build_fact_pack(row)
