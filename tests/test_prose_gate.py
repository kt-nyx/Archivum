from __future__ import annotations

from pipeline.generate.draft.prose_gate import (
    detect_dangling_terminal,
    detect_list_shape,
    detect_midsentence_gap,
    detect_script_mixing,
    prose_gate_rejects,
    prose_gate_violations,
)


def test_detect_list_shape_flags_navbox_placename_dump() -> None:
    # The real Argent Crusade defect (#2): a navbox of zone place-names with near-zero
    # connective words is a list, not prose.
    navbox = (
        "Plaguelands Western Plaguelands The Bulwark Chillwind Camp Hearthglen "
        "Menders' Stead Northridge Lumber Camp Eastern Plaguelands Light's Hope Chapel "
        "Sanctum of Light Tyr's Hand Scarlet Bastion Crown Guard Tower Eastwall Tower."
    )
    assert detect_list_shape(navbox) is True


def test_detect_list_shape_allows_real_prose() -> None:
    prose = (
        "The Forsaken control Andorhal in the Western Plaguelands, driving out the Alliance "
        "and ending Scourge presence there after the battle for the city."
    )
    assert detect_list_shape(prose) is False


def test_detect_list_shape_abstains_on_short_text() -> None:
    # Too few tokens to judge — a terse real summary must not be flagged.
    assert detect_list_shape("Argent Crusade forces hold the Bulwark.") is False


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


def test_midsentence_gap_flags_dangling_preposition_before_punctuation() -> None:
    # The first real Andorhal CTA artifact (#3): a raw zone-name strip left the preposition
    # "to" stranded before the comma.
    assert detect_midsentence_gap("Answer the call to, where the Scourge festers.") is True


def test_midsentence_gap_flags_article_before_conjunction() -> None:
    # The second artifact: "...contest the Western Plaguelands and..." -> "contest the and...".
    assert detect_midsentence_gap("Hold the line and contest the and every road.") is True


def test_midsentence_gap_allows_normal_prose() -> None:
    # An article/preposition with its real object between it and the next word is fine.
    assert detect_midsentence_gap("Answer the call, where the Scourge still festers.") is False
    assert detect_midsentence_gap("Push back the Scourge and secure the ruined city.") is False
    assert detect_midsentence_gap("Reclaim Andorhal for the living, then march east.") is False


def test_empty_text_has_no_violations() -> None:
    assert prose_gate_violations("") == []
    assert prose_gate_violations("   ") == []
    assert prose_gate_rejects("") is False


def test_violations_lists_both_artifact_classes() -> None:
    both = "the scourge сeded the vault to the"
    issues = prose_gate_violations(both)
    assert len(issues) == 2
