from __future__ import annotations

from pipeline.generate.draft.pages.cards import (
    _apply_history_section_budget,
    _merge_consecutive_history_headings,
)


def test_merge_collapses_consecutive_same_heading_sections() -> None:
    sections = [
        {
            "heading": "Scourging of Lordaeron",
            "body": "First paragraph.",
            "source_refs": [{"source_id": "s1", "locator": "l1", "excerpt_hash": "h1"}],
        },
        {
            "heading": "Scourging of Lordaeron",
            "body": "Second paragraph.",
            "source_refs": [{"source_id": "s1", "locator": "l2", "excerpt_hash": "h2"}],
        },
        {
            "heading": "Cataclysm",
            "body": "Third paragraph.",
            "source_refs": [{"source_id": "s1", "locator": "l3", "excerpt_hash": "h3"}],
        },
    ]
    merged = _merge_consecutive_history_headings(sections)
    assert [s["heading"] for s in merged] == ["Scourging of Lordaeron", "Cataclysm"]
    assert merged[0]["body"] == "First paragraph. Second paragraph."
    # source_refs union, de-duplicated by (source_id, locator, excerpt_hash).
    assert len(merged[0]["source_refs"]) == 2


def test_merge_is_case_insensitive_and_dedupes_refs() -> None:
    ref = {"source_id": "s1", "locator": "l1", "excerpt_hash": "h1"}
    sections = [
        {"heading": "Historical Era", "body": "A.", "source_refs": [ref]},
        {"heading": "historical era", "body": "B.", "source_refs": [ref]},
    ]
    merged = _merge_consecutive_history_headings(sections)
    assert len(merged) == 1
    assert merged[0]["body"] == "A. B."
    assert len(merged[0]["source_refs"]) == 1


def test_merge_keeps_non_adjacent_repeats_separate() -> None:
    # Only *consecutive* runs merge; an interleaved heading is preserved.
    sections = [
        {"heading": "War", "body": "A.", "source_refs": []},
        {"heading": "Peace", "body": "B.", "source_refs": []},
        {"heading": "War", "body": "C.", "source_refs": []},
    ]
    merged = _merge_consecutive_history_headings(sections)
    assert [s["heading"] for s in merged] == ["War", "Peace", "War"]


def test_merge_does_not_mutate_input() -> None:
    sections = [
        {"heading": "X", "body": "A.", "source_refs": []},
        {"heading": "X", "body": "B.", "source_refs": []},
    ]
    _merge_consecutive_history_headings(sections)
    assert sections[0]["body"] == "A."


def _sentence(n: int) -> str:
    # ~10 words per sentence.
    return " ".join(["word"] * 9 + [f"end{n}."])


def test_budget_trims_overlong_section_to_word_cap() -> None:
    # 16 sentences (~160 words) must trim to whole leading sentences within [40, 110].
    body = " ".join(_sentence(i) for i in range(16))
    out = _apply_history_section_budget([{"heading": "Scourging", "body": body, "source_refs": []}])
    assert len(out) == 1
    words = len(out[0]["body"].split())
    assert 40 <= words <= 110
    assert out[0]["body"].endswith(".")  # trimmed on a sentence boundary


def test_budget_absorbs_subfloor_section_into_previous() -> None:
    # 3 full sections + 1 sub-floor trailing section: the short one folds into its
    # predecessor (count stays >= MIN_HISTORY_SECTIONS), so nothing ships under the floor.
    full = lambda: " ".join(_sentence(i) for i in range(5))  # noqa: E731  (~50 words)
    out = _apply_history_section_budget(
        [
            {"heading": "Before", "body": full(), "source_refs": []},
            {"heading": "Scourging", "body": full(), "source_refs": []},
            {"heading": "Cataclysm", "body": full(), "source_refs": []},
            {"heading": "Battle", "body": "A brief note.", "source_refs": []},
        ]
    )
    assert len(out) == 3
    assert out[-1]["heading"] == "Cataclysm"
    assert "brief note" in out[-1]["body"]


def test_budget_absorbs_subfloor_even_below_minimum_sections() -> None:
    # Exactly MIN sections, one sub-floor: absorption is still allowed (Slice 2). Validate's
    # own floor is one section, and shipping a budget-violating section is the worse outcome
    # — the old keep-at-minimum behavior shipped a guaranteed budget.history_section hard-fail.
    full = lambda: " ".join(_sentence(i) for i in range(5))  # noqa: E731
    out = _apply_history_section_budget(
        [
            {"heading": "A", "body": full(), "source_refs": []},
            {"heading": "B", "body": full(), "source_refs": []},
            {"heading": "C", "body": "Too short.", "source_refs": []},
        ]
    )
    assert [s["heading"] for s in out] == ["A", "B"]
    assert "Too short." in out[-1]["body"]


def test_budget_keeps_subfloor_section_when_it_cannot_be_absorbed() -> None:
    # A leading sub-floor section with no predecessor is kept as-is (never drop content;
    # sparse pages legitimately yield short sections).
    out = _apply_history_section_budget([{"heading": "Stub", "body": "Too short.", "source_refs": []}])
    assert [s["heading"] for s in out] == ["Stub"]
