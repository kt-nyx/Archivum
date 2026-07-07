"""WS-C: guard the externalized classification-vocab data files + loaders.

These lock the data-file contract so an accidental edit (missing key, wrong shape)
fails fast, and confirm the loaders return the immutable shapes call sites rely on.
"""

from __future__ import annotations

from pipeline.common import discovery_vocab, draft_vocab


def test_discovery_vocab_loaders_return_expected_shapes() -> None:
    # faction_title_tokens / lore_faction_tokens were deleted in Slice 13: faction-ness
    # now comes from the organization registry (wiki category taxonomy), never a vocab.
    tuple_loaders = [
        discovery_vocab.event_title_tokens,
        discovery_vocab.character_role_hints,
        discovery_vocab.non_location_title_tokens,
        discovery_vocab.location_hard_reject_tokens,
        discovery_vocab.location_rpg_tokens,
        discovery_vocab.lore_character_role_hints,
        discovery_vocab.quest_alliance_binding_tokens,
        discovery_vocab.quest_horde_binding_tokens,
        discovery_vocab.non_canon_body_markers,
    ]
    for loader in tuple_loaders:
        value = loader()
        assert isinstance(value, tuple) and value, loader.__name__
        assert all(isinstance(token, str) for token in value), loader.__name__

    frozenset_loaders = [
        discovery_vocab.race_species_denylist,
        discovery_vocab.meta_page_denylist,
        discovery_vocab.location_meta_titles,
        discovery_vocab.faction_as_location_denylist,
        discovery_vocab.entry_quest_title_keywords,
        discovery_vocab.generic_non_person_words,
        discovery_vocab.boss_reject_section_titles,
        discovery_vocab.non_character_titles,
        discovery_vocab.non_person_narrative_titles,
    ]
    for loader in frozenset_loaders:
        value = loader()
        assert isinstance(value, frozenset) and value, loader.__name__


def test_draft_vocab_loaders_return_expected_shapes() -> None:
    # historical_framing_markers was retired in Slice 5 (tense judgments moved to the NLP grammar
    # substrate); Slice 14 single-homed era_section_role_tokens onto expansion_release_order (it now
    # derives from it), leaving expansion_release_order as the draft path's only externalized vocab.
    for loader in (draft_vocab.era_section_role_tokens, draft_vocab.expansion_release_order):
        value = loader()
        assert isinstance(value, tuple) and value, loader.__name__


def test_vocab_values_preserved_from_pre_externalization() -> None:
    # Spot-check representative members survived the move into JSON unchanged.
    assert "human" in discovery_vocab.race_species_denylist()
    assert "orgrimmar" in discovery_vocab.quest_horde_binding_tokens()
    assert "hero's call" in discovery_vocab.entry_quest_title_keywords()
    assert "the burning legion" in discovery_vocab.non_person_narrative_titles()
    assert "cataclysm" in draft_vocab.era_section_role_tokens()
