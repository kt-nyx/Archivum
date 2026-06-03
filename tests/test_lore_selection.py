from __future__ import annotations

from pipeline.generate.draft.lore_selection import (
    build_sparse_lore_rescue_pool,
    dedupe_lore_items,
    filter_relevant_lore_items,
    is_instance_lore_sparse,
    mentions_instance,
)


def test_mentions_instance_is_word_boundary_and_article_tolerant() -> None:
    assert mentions_instance("The Mana-Tombs are burial chambers.", "Mana-Tombs") is True
    assert mentions_instance("Deadmines lie beneath Westfall.", "The Deadmines") is True
    assert mentions_instance("A tale of the Black Temple alone.", "Mana-Tombs") is False


def test_filter_relevant_keeps_only_instance_naming_snippets() -> None:
    items = [
        {"snippet": "Mana-Tombs is one of the wings of Auchindoun.", "source_id": "p1"},
        {"snippet": "Auchindoun was a draenei temple, generally.", "source_id": "p1"},
    ]
    relevant = filter_relevant_lore_items(items, instance_name="Mana-Tombs")
    assert len(relevant) == 1
    assert relevant[0]["snippet"].startswith("Mana-Tombs")


def test_sparse_threshold_and_dedupe() -> None:
    assert is_instance_lore_sparse([{"snippet": "only a few words here"}]) is True
    assert is_instance_lore_sparse([{"snippet": "word " * 80}]) is False
    deduped = dedupe_lore_items(
        [{"snippet": "Same text."}, {"snippet": "same   text."}, {"snippet": "Other."}]
    )
    assert len(deduped) == 2


def test_sparse_rescue_includes_parent_excludes_related_offline(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    parent = [
        {"snippet": "Parent complex lore.", "source_id": "parent", "source_title": "Auchindoun"}
    ]
    related = [
        {"snippet": "Tangential related lore.", "source_id": "rel", "source_title": "Outland"}
    ]
    rescue = build_sparse_lore_rescue_pool(
        parent_lore_pool=parent,
        related_lore_pool=related,
        instance_name="Mana-Tombs",
    )
    snippets = {item["snippet"] for item in rescue}
    # Offline: the parent-complex page is trusted; related pages are not pulled in.
    assert "Parent complex lore." in snippets
    assert "Tangential related lore." not in snippets
