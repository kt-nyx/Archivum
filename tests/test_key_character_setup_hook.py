from __future__ import annotations

from pipeline.generate.draft.claim_routing import CLAIM_VIEW_KEY
from pipeline.generate.draft.pages.key_characters import (
    _beat_is_self_motivation,
    _recover_instance_setup_hooks,
)

_CAST = ["Darkmaster Gandling", "Instructor Chillheart", "Jandice Barov", "Rattlegore"]


def test_beat_is_self_motivation_keeps_self_agent_aim() -> None:
    # The card character is the grammatical agent and no other cast member is named.
    assert _beat_is_self_motivation(
        "Lilian Voss turned her wrath on the Scourge necromancers of Scholomance.",
        self_name="Lilian Voss",
        other_cast_names=_CAST,
    )


def test_beat_is_self_motivation_drops_character_as_patient() -> None:
    # An in-encounter mechanic: another cast member acts upon the card character.
    assert not _beat_is_self_motivation(
        "Darkmaster Gandling forced Lilian Voss to fight the adventurers.",
        self_name="Lilian Voss",
        other_cast_names=_CAST,
    )


def test_beat_is_self_motivation_drops_other_cast_named_even_at_sentence_end() -> None:
    # A cast member named anywhere disqualifies — including at a clause/sentence boundary, where a
    # trailing period must not hide the name from the token match.
    assert not _beat_is_self_motivation(
        "Lilian Voss caught up with Darkmaster Gandling.",
        self_name="Lilian Voss",
        other_cast_names=_CAST,
    )


def test_beat_is_self_motivation_drops_outcome_where_character_is_freed() -> None:
    assert not _beat_is_self_motivation(
        "The adventurers defeated and freed Lilian Voss.",
        self_name="Lilian Voss",
        other_cast_names=_CAST,
    )


def _hook_view(text: str, *, safety: str = "safe_setup_hook") -> dict:
    return {
        "is_claim_view": True,
        "spoiler_safety": safety,
        "claim_text": text,
        "snippet": text,
        "claim_id": text[:12],
        "entities": [],
        "canonical_evidence_id": f"canon-{abs(hash(text)) % 99999}",
    }


def _item(views: list[dict]) -> dict:
    return {CLAIM_VIEW_KEY: views}


def test_recover_instance_setup_hooks_recovers_only_the_motivation() -> None:
    pool = [
        _item(
            [
                _hook_view(
                    "Lilian Voss turned her wrath on the Scourge necromancers of Scholomance."
                ),
                _hook_view(
                    "Darkmaster Gandling forced Lilian Voss to fight the adventurers in Scholomance."
                ),
            ]
        )
    ]
    recovered = _recover_instance_setup_hooks(
        pool,
        instance_name="Scholomance",
        boss_name="Lilian Voss",
        other_cast_names=["Darkmaster Gandling"],
        selected=[],
    )
    texts = [str(v.get("claim_text", "")) for v in recovered]
    assert any("turned her wrath" in t for t in texts)
    assert not any("forced" in t for t in texts)
    # The recovered hook is detached from its source paragraph so synthesis keeps its text.
    assert all(v.get("canonical_evidence_id") == "" for v in recovered)


def test_recover_instance_setup_hooks_noop_when_instance_beat_already_selected() -> None:
    pool = [
        _item(
            [_hook_view("Lilian Voss turned her wrath on the necromancers of Scholomance.")]
        )
    ]
    selected = [
        {
            "is_claim_view": True,
            "claim_text": "Her story is bound to Scholomance.",
            "snippet": "Her story is bound to Scholomance.",
            "entities": [],
        }
    ]
    recovered = _recover_instance_setup_hooks(
        pool,
        instance_name="Scholomance",
        boss_name="Lilian Voss",
        other_cast_names=["Darkmaster Gandling"],
        selected=selected,
    )
    assert recovered == []
