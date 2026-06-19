"""WS-C: guard the externalized classification-vocab data files + loaders.

These lock the data-file contract so an accidental edit (missing key, wrong shape)
fails fast, and confirm the loaders return the immutable shapes call sites rely on.
"""

from __future__ import annotations

from pipeline.common import discovery_vocab, draft_vocab


def test_discovery_vocab_loaders_return_expected_shapes() -> None:
    tuple_loaders = [
        discovery_vocab.faction_title_tokens,
        discovery_vocab.event_title_tokens,
        discovery_vocab.character_role_hints,
        discovery_vocab.non_location_title_tokens,
        discovery_vocab.location_hard_reject_tokens,
        discovery_vocab.location_rpg_tokens,
        discovery_vocab.lore_faction_tokens,
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
    for loader in (draft_vocab.era_section_role_tokens, draft_vocab.historical_framing_markers):
        value = loader()
        assert isinstance(value, tuple) and value, loader.__name__


def test_vocab_values_preserved_from_pre_externalization() -> None:
    # Spot-check representative members survived the move into JSON unchanged.
    assert "crusade" in discovery_vocab.faction_title_tokens()
    assert "human" in discovery_vocab.race_species_denylist()
    assert "orgrimmar" in discovery_vocab.quest_horde_binding_tokens()
    assert "hero's call" in discovery_vocab.entry_quest_title_keywords()
    assert "the burning legion" in discovery_vocab.non_person_narrative_titles()
    assert "cataclysm" in draft_vocab.era_section_role_tokens()
    assert "formerly" in draft_vocab.historical_framing_markers()
