from __future__ import annotations

from pipeline.generate.draft.pages.assembly import _iter_evidence_items
from pipeline.generate.draft.prose_synthesis import _format_evidence_block


def test_format_evidence_block_collapses_paragraph_by_excerpt() -> None:
    items = [
        {
            "canonical_evidence_id": "p1",
            "snippet": "fragment one",
            "_route_safe_excerpt": "Reconstructed paragraph one.",
            "source_id": "s1",
        },
        {
            "canonical_evidence_id": "p1",
            "snippet": "fragment two",
            "_route_safe_excerpt": "Reconstructed paragraph one.",
            "source_id": "s1",
        },
        {
            "canonical_evidence_id": "p2",
            "snippet": "fragment three",
            "_route_safe_excerpt": "Reconstructed paragraph two.",
            "source_id": "s2",
        },
    ]
    block = _format_evidence_block(items, max_items=8)
    lines = block.splitlines()
    # p1's two fragments collapse into a single reconstructed line; p2 is its own line.
    assert lines == ["[s1] Reconstructed paragraph one.", "[s2] Reconstructed paragraph two."]


def test_format_evidence_block_per_item_without_excerpt() -> None:
    # Offline / paragraph pools carry no reconstructed excerpt: one line per item, as before.
    items = [
        {"snippet": "alpha", "source_id": "s1"},
        {"snippet": "beta", "source_id": "s2"},
    ]
    block = _format_evidence_block(items, max_items=8)
    assert block.splitlines() == ["[s1] alpha", "[s2] beta"]


def _claim_view(sentence_index: int, *, scope: str, safety: str, text: str) -> dict:
    return {
        "canonical_evidence_id": "c1",
        "source_excerpt": "Alpha first. Beta spoiler. Gamma safe.",
        "source_sentence_indexes": [sentence_index],
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
