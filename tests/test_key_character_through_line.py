from __future__ import annotations

from pipeline.generate.draft.pages.key_characters import (
    _KEY_CHARACTER_THROUGH_LINE_MIN_WORDS,
    _through_line_soft_reasons,
)

# Real wpl-28 outputs: evidence-rich figures whose cards collapsed to a single origin sentence
# because the synthesis prompt bounded only the ceiling. These must trigger the soft retry.
_GANDLING_STUB = (
    "Darkmaster Gandling is a human necromancer of the Cult of the Damned who rose to oversee "
    "Scholomance's teaching in death magic, alongside Ras Frostwhisper in its early cruelties."
)
_JANDICE_STUB = (
    "Jandice Barov was once an archmage of Dalaran and a gifted illusionist, known for spells that "
    "hid her true form behind near-perfect false images."
)
# The wpl-27 rich card from the same evidence — a full origin -> presence arc — must NOT trigger.
_GANDLING_RICH = (
    "Darkmaster Gandling was a human necromancer of the Cult of the Damned and the headmaster of "
    "Scholomance, where he and Ras Frostwhisper oversaw cruelty against innocent souls. After "
    "surviving into the years after Cataclysm and taking sole control of Scholomance and the Scourge "
    "in the Western Plaguelands, he was driven back there after defeat at Andorhal."
)


def test_through_line_soft_reason_fires_on_short_origin_stub() -> None:
    reasons = _through_line_soft_reasons(_GANDLING_STUB, instance_name="Scholomance")
    assert reasons
    assert "Scholomance" in reasons[0]
    # A passing mention of the instance is not enough — the stub still lacks the through-line, so
    # the trigger is length-based, not an instance-name check (Gandling names Scholomance yet fires).
    assert "Scholomance" in _GANDLING_STUB


def test_through_line_soft_reason_fires_when_instance_unnamed() -> None:
    reasons = _through_line_soft_reasons(_JANDICE_STUB, instance_name="Scholomance")
    assert reasons


def test_through_line_soft_reason_silent_on_full_arc() -> None:
    assert _through_line_soft_reasons(_GANDLING_RICH, instance_name="Scholomance") == []


def test_through_line_soft_reason_silent_on_empty() -> None:
    assert _through_line_soft_reasons("   ", instance_name="Scholomance") == []


def test_through_line_soft_reason_not_pushed_when_evidence_is_thin() -> None:
    # Anti-filler: when the evidence-proportional target is near the hard floor (a thin figure),
    # a short card is NOT pushed — there is nothing to develop the through-line from.
    assert _through_line_soft_reasons(_JANDICE_STUB, instance_name="Scholomance", target_words=27) == []


def test_through_line_soft_reason_uses_adaptive_target() -> None:
    # With a rich target, a short card fires and the retry aims for that target (not a fixed one).
    reasons = _through_line_soft_reasons(_JANDICE_STUB, instance_name="Scholomance", target_words=80)
    assert reasons
    assert "80 words" in reasons[0]


def test_through_line_threshold_sits_between_floor_and_target() -> None:
    # The soft floor must be above the hard minimum (else it never fires) and below the target
    # (else a card at target would still be re-prompted).
    from pipeline.generate.draft.instance_lint import (
        MIN_KEY_CHARACTER_WORDS,
        TARGET_KEY_CHARACTER_WORDS,
    )

    assert MIN_KEY_CHARACTER_WORDS < _KEY_CHARACTER_THROUGH_LINE_MIN_WORDS < TARGET_KEY_CHARACTER_WORDS
