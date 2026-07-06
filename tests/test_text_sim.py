from __future__ import annotations

from pipeline.common.text_sim import (
    lemma_support_containment,
    lemma_support_ratio,
    max_shingle_containment_against_sources,
    shingle_containment,
    whitespace_jaccard,
)


def test_shingle_containment_full_for_verbatim_copy() -> None:
    source = "the scourge raised the dead beneath the ruined keep at caer darrow"
    assert shingle_containment(source, source, k=5) == 1.0


def test_shingle_containment_low_for_paraphrase() -> None:
    source = "The Scourge raised the dead beneath the ruined keep at Caer Darrow during the long war."
    paraphrase = "Undead legions climbed from the flooded catacombs once that conflict had finally ended."
    assert shingle_containment(paraphrase, source, k=5) < 0.2


def test_shingle_containment_catches_slice_of_large_source() -> None:
    # The defining property: a short copied body buried in a much larger article still scores high,
    # where set Jaccard is diluted toward zero by the source's size.
    body = "the barons struck a bargain with the lich to preserve their dominion past death"
    padding_head = " ".join(f"filler{i} token{i}" for i in range(200))
    padding_tail = " ".join(f"tail{i} clause{i}" for i in range(200))
    big_source = f"{padding_head} {body} {padding_tail}"
    assert shingle_containment(body, big_source, k=5) == 1.0
    # Contrast: set overlap misses the copy because the union is dominated by the padding.
    assert whitespace_jaccard(body, big_source) < 0.1


def test_shingle_containment_zero_when_text_shorter_than_k() -> None:
    assert shingle_containment("too short", "any longer source text here at all", k=5) == 0.0


def test_max_shingle_containment_picks_best_source() -> None:
    body = "the cult of the damned bargained for power beyond the grave"
    assert (
        max_shingle_containment_against_sources(body, ["wholly unrelated text", body], k=5) == 1.0
    )


# --- Slice 8: lemmatized support scoring ---

_INFLECTED_CLAIM = "Necromancers were slain beneath the academy."
_INFLECTED_EVIDENCE = "The crusaders slay every necromancer beneath the academy's vaults."
_ABOVE = "The academy was built above Caer Darrow."
_BENEATH = "The academy was built beneath Caer Darrow."


def test_lemma_support_containment_bridges_inflection() -> None:
    # Surface tokens miss "slain"/"slay" and "necromancers"/"necromancer"; lemmas do not.
    assert lemma_support_containment(_INFLECTED_CLAIM, _INFLECTED_EVIDENCE) == 1.0
    assert lemma_support_containment("", _INFLECTED_EVIDENCE) == 0.0
    assert lemma_support_containment(_INFLECTED_CLAIM, "") == 0.0


def test_lemma_support_keeps_inverted_spatial_relations_distinguishable() -> None:
    # "above" vs "beneath" stay in the token set (surface adpositions), so an inverted spatial
    # assertion is never a perfect lemma-level match — the fallback cannot silently equate them.
    assert lemma_support_containment(_ABOVE, _BENEATH) < 1.0
    assert lemma_support_ratio(_ABOVE, _BENEATH) < 1.0


def test_lemma_support_ratio_deterministic_and_bounded() -> None:
    first = lemma_support_ratio(_INFLECTED_CLAIM, _INFLECTED_EVIDENCE)
    assert first == lemma_support_ratio(_INFLECTED_CLAIM, _INFLECTED_EVIDENCE)
    assert 0.0 < first <= 1.0
