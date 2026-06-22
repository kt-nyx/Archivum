from __future__ import annotations

from pipeline.generate.draft.prose_gate import (
    detect_dangling_terminal,
    detect_list_shape,
    detect_midsentence_gap,
    detect_script_mixing,
    detect_source_passthrough,
    detect_splice_passthrough,
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


# --- Fix E: the central gate now backstops the navbox/splice/mid-sentence defect classes ---


def test_gate_rejects_navbox_list_summary() -> None:
    # Defect #2: the Argent Crusade faction summary shipped as a raw navbox place-name dump.
    navbox = (
        "Plaguelands Western Plaguelands The Bulwark Chillwind Camp Hearthglen "
        "Menders' Stead Northridge Lumber Camp Eastern Plaguelands Light's Hope Chapel "
        "Sanctum of Light Tyr's Hand Scarlet Bastion Crown Guard Tower Eastwall Tower."
    )
    assert prose_gate_rejects(navbox) is True


def test_gate_rejects_midsentence_broken_cta() -> None:
    # Defect #3: a raw zone-name strip left a dangling preposition mid-sentence.
    assert prose_gate_rejects("Answer the call to, where the Scourge festers.") is True


def test_detect_splice_passthrough_flags_features_prominently_splice() -> None:
    # Defect #4: the old key-character fallback colon-spliced a raw, truncated snippet.
    splice = (
        "Barov features prominently in Scholomance: the Barov family once ruled these halls "
        "before the"
    )
    assert detect_splice_passthrough(splice) is True
    assert prose_gate_rejects(splice) is True


def test_detect_splice_passthrough_allows_prose_without_colon_splice() -> None:
    clean = "Jandice Barov features prominently in Scholomance as an illusionist boss."
    assert detect_splice_passthrough(clean) is False
    assert prose_gate_rejects(clean) is False


def test_detect_source_passthrough_flags_verbatim_copy() -> None:
    snippet = "The Forsaken seized Andorhal and drove the Alliance from the ruined town."
    # A summary that is the snippet verbatim is a copy, not synthesis.
    assert detect_source_passthrough(snippet, [snippet]) is True


def test_detect_source_passthrough_allows_borrowed_sentence() -> None:
    # A deterministic fallback that borrows one clean sentence from a longer source is allowed.
    source = (
        "Andorhal sits at the heart of the Western Plaguelands. The Forsaken and the Alliance "
        "have fought for years over its grain stores, its crypts, and the roads that cross it, "
        "while the Scourge still claws at the city's edges from the surrounding fields."
    )
    summary = "Andorhal sits at the heart of the Western Plaguelands."
    assert detect_source_passthrough(summary, [source]) is False


def test_gate_source_passthrough_only_active_with_sources() -> None:
    snippet = "The Forsaken seized Andorhal and drove the Alliance from the ruined town."
    # Without sources the copy is invisible to the gate; with sources it is rejected.
    assert prose_gate_rejects(snippet) is False
    assert prose_gate_rejects(snippet, source_snippets=[snippet]) is True


def test_gate_passes_legitimate_short_summary() -> None:
    # Negative case: real terse prose must survive the expanded gate.
    summary = "The Argent Crusade holds the Bulwark and presses the Scourge across the fields."
    assert prose_gate_rejects(summary) is False
    assert prose_gate_rejects(summary, source_snippets=["unrelated evidence snippet here"]) is False
