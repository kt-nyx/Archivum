from __future__ import annotations

from pipeline.generate.draft.prose_gate import (
    detect_dangling_terminal,
    detect_script_mixing,
    prose_gate_rejects,
    prose_gate_violations,
)


def test_script_mixing_flags_cyrillic_injection() -> None:
    # The Scholomance artifact: Cyrillic "с"/"е" homoglyphs spliced into a Latin word.
    artifact = "The necromancers смeded the vault to the Scourge."
    assert detect_script_mixing(artifact) is True
    assert prose_gate_rejects(artifact) is True


def test_script_mixing_allows_accented_latin() -> None:
    # Accented Latin (café, Naïve) is still LATIN — must not trip the gate.
    clean = "The café at Naxxramas served the naïve recruits before the siege."
    assert detect_script_mixing(clean) is False
    assert prose_gate_rejects(clean) is False


def test_dangling_terminal_flags_function_word_ending() -> None:
    # The "war in the toward" CTA artifact: ends on a preposition.
    artifact = "Hold the line as the Forsaken press the war in the toward."
    assert detect_dangling_terminal(artifact) is True
    assert prose_gate_rejects(artifact) is True


def test_dangling_terminal_allows_normal_sentence() -> None:
    clean = "Crusaders reclaimed the blighted fields after the Cataclysm."
    assert detect_dangling_terminal(clean) is False
    assert prose_gate_rejects(clean) is False


def test_dangling_terminal_allows_adverbial_particle_cta() -> None:
    # Imperative CTAs legitimately end on adverbial particles; do not reject these.
    assert detect_dangling_terminal("Drive the Scourge out.") is False
    assert detect_dangling_terminal("Push the undead back.") is False


def test_empty_text_has_no_violations() -> None:
    assert prose_gate_violations("") == []
    assert prose_gate_violations("   ") == []
    assert prose_gate_rejects("") is False


def test_violations_lists_both_artifact_classes() -> None:
    both = "the scourge сeded the vault to the"
    issues = prose_gate_violations(both)
    assert len(issues) == 2
