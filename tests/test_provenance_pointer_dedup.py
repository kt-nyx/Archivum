from __future__ import annotations

from pipeline.generate.draft.common import pick_pointers
from pipeline.generate.draft.pages.assembly import _pointers_for_evidence_ids


def test_pointers_for_evidence_ids_dedupes_repeated_snippet() -> None:
    # A snippet duplicated in the pool must not yield several pointers that share an
    # excerpt_hash under incrementing locators (RC-6).
    item = {
        "source_id": "src-a",
        "snippet": "Gandling rules the school.",
        "content_role": "history",
    }
    pool = [dict(item), dict(item), dict(item)]
    revision_map = {"src-a": "mw:1"}
    pointers = _pointers_for_evidence_ids(pool, ["src-a"], revision_map)
    assert len(pointers) == 1
    assert len({p["excerpt_hash"] for p in pointers}) == 1


def test_pointers_for_evidence_ids_keeps_distinct_snippets() -> None:
    pool = [
        {"source_id": "src-a", "snippet": "First fact.", "content_role": "history"},
        {"source_id": "src-a", "snippet": "Second fact.", "content_role": "history"},
    ]
    pointers = _pointers_for_evidence_ids(pool, ["src-a"], {"src-a": "mw:1"})
    assert len(pointers) == 2
    assert len({p["excerpt_hash"] for p in pointers}) == 2
    # Locators number sequentially over the kept distinct pointers.
    assert pointers[0]["locator"].endswith("paragraph:1")
    assert pointers[1]["locator"].endswith("paragraph:2")


def test_pointers_for_evidence_ids_resolves_canonical_ids() -> None:
    # Slice 7: used ids are paragraph-level canonical ids; only the cited paragraph of a
    # shared-source pool yields a pointer.
    pool = [
        {
            "source_id": "src-a",
            "canonical_evidence_id": "canonical-1",
            "snippet": "First paragraph.",
            "content_role": "history",
        },
        {
            "source_id": "src-a",
            "canonical_evidence_id": "canonical-2",
            "snippet": "Second paragraph.",
            "content_role": "history",
        },
    ]
    pointers = _pointers_for_evidence_ids(pool, ["canonical-2"], {"src-a": "mw:1"})
    assert len(pointers) == 1
    assert pointers[0]["source_id"] == "src-a"


def test_pick_pointers_does_not_wrap_repeat() -> None:
    fact_items = [
        {
            "source_id": "src-a",
            "revision_id": "mw:1",
            "locator": "section:history paragraph:1",
            "excerpt_hash": "sha256:aaaa",
        }
    ]
    # min_count 3 but only one distinct item -> one distinct pointer, no duplicates.
    pointers = pick_pointers(fact_items, 3, entity_id="entity-x")
    assert len(pointers) == 1
