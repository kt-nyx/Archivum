from __future__ import annotations

from pipeline.common.linguistics import sentence_spans
from pipeline.generate.draft.evidence_identity import translate_used_evidence_ids
from pipeline.generate.draft.pages.assembly import _iter_evidence_items
from pipeline.generate.draft.prose_synthesis import _format_evidence_block


def test_format_evidence_block_collapses_paragraph_by_excerpt() -> None:
    items = [
        {
            "canonical_evidence_id": "canonical-a",
            "snippet": "fragment one",
            "_route_safe_excerpt": "Reconstructed paragraph one.",
            "source_id": "s1",
        },
        {
            "canonical_evidence_id": "canonical-a",
            "snippet": "fragment two",
            "_route_safe_excerpt": "Reconstructed paragraph one.",
            "source_id": "s1",
        },
        {
            "canonical_evidence_id": "canonical-b",
            "snippet": "fragment three",
            "_route_safe_excerpt": "Reconstructed paragraph two.",
            "source_id": "s1",
        },
    ]
    block, alias_map = _format_evidence_block(items, max_items=8)
    lines = block.splitlines()
    # Labels are paragraph aliases (Slice 7): canonical-a's two fragments collapse into a single
    # reconstructed line; canonical-b is its own line even though it shares s1's source id.
    assert lines == [
        "[p1] Reconstructed paragraph one.",
        "[p2] Reconstructed paragraph two.",
    ]
    assert alias_map["p1"] == "canonical-a"
    assert alias_map["p2"] == "canonical-b"
    # The shared source id names two distinct paragraphs, so it must not translate to either.
    assert "s1" not in alias_map


def test_format_evidence_block_per_item_without_excerpt() -> None:
    # Offline / paragraph pools carry no reconstructed excerpt: one line per item, as before.
    items = [
        {"snippet": "alpha", "source_id": "s1"},
        {"snippet": "beta", "source_id": "s2"},
    ]
    block, alias_map = _format_evidence_block(items, max_items=8)
    assert block.splitlines() == ["[p1] alpha", "[p2] beta"]
    # No canonical ids: the paragraph identity falls back to the (unambiguous) source id.
    assert alias_map["p1"] == "s1"
    assert alias_map["p2"] == "s2"
    assert alias_map["s1"] == "s1"


def test_translate_used_evidence_ids_maps_aliases_and_drops_unknown() -> None:
    items = [
        {"snippet": "alpha", "source_id": "s1", "canonical_evidence_id": "canonical-a"},
        {"snippet": "beta", "source_id": "s1", "canonical_evidence_id": "canonical-b"},
    ]
    _block, alias_map = _format_evidence_block(items, max_items=8)
    used = translate_used_evidence_ids(
        ["p2", "canonical-a", "p2", "hallucinated-id", ""], alias_map
    )
    # Aliases and echoed canonical ids resolve; dupes collapse; unknown tokens are dropped so a
    # hallucinated citation can never become a provenance pointer.
    assert used == ["canonical-b", "canonical-a"]


_VIEW_PARAGRAPH = "Alpha first. Beta spoiler. Gamma safe."


def _claim_view(sentence_index: int, *, scope: str, safety: str, text: str) -> dict:
    span = sentence_spans(_VIEW_PARAGRAPH)[sentence_index]
    return {
        "canonical_evidence_id": "c1",
        "source_excerpt": _VIEW_PARAGRAPH,
        "source_sentence_indexes": [sentence_index],
        "source_char_spans": [[span.start, span.end]],
        "temporal_scope": scope,
        "spoiler_safety": safety,
        "claim_text": text,
        "snippet": text,
        "is_claim_view": True,
    }


def test_iter_evidence_items_attaches_route_safe_excerpt() -> None:
    row = {
        "field_name": "faction_pool",
        "subject_id": "zone-x",
        "evidence_items": [
            {
                "snippet": "Alpha first. Beta spoiler. Gamma safe.",
                "_claim_views": [
                    _claim_view(0, scope="pre_entry_history", safety="safe_background", text="Alpha"),
                    _claim_view(
                        1, scope="active_storyline_outcome", safety="active_outcome", text="Beta"
                    ),
                    _claim_view(2, scope="pre_entry_history", safety="safe_background", text="Gamma"),
                ],
            }
        ],
    }
    out = _iter_evidence_items([row], {"faction_pool"}, claim_route="faction_context")
    assert out  # routed claim views survived
    excerpts = {item.get("_route_safe_excerpt", "") for item in out}
    assert len(excerpts) == 1
    excerpt = next(iter(excerpts))
    assert "Alpha first." in excerpt
    assert "Gamma safe." in excerpt
    assert "Beta" not in excerpt  # spoiler sentence excluded from the reconstructed excerpt
