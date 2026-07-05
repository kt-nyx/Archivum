"""Tests for the NLP grammar substrate (generalization refactor Slice 4).

These run the **real** pinned model — no fixture, no fallback. A model-load failure must be
a hard test failure, not a skip: the model is a standard dev/CI dependency, and a skip here
would let the rest of the suite silently exercise degraded behaviour once downstream slices
delegate to this wrapper. Monkeypatching the wrapper is reserved for targeted downstream
unit tests that pin a specific feature shape; the default is real analysis.

The tense-profile cases snapshot the substrate's behaviour on the regression phrases named
in the plan (Slice 4 test list), including known small-model weaknesses (see the "labors"
case) so any behaviour change on a model/library bump is caught deliberately.
"""

from __future__ import annotations

from pipeline.common.linguistics import (
    describe,
    lemmatized_content_tokens,
    linguistic_tokens,
    model_info,
    sentence_spans,
    tense_profile,
)

# Regression phrases from the plan: previously-rejected valid faction summaries (present
# framing), a generic org-history lede (past-dominant), quest-imperative prose, and a
# participial at-a-glance caption.
HEALS = "The Argent Crusade heals the land around Hearthglen."
WORKS_TO_HEAL = "The Cenarion Circle works to further heal the plaguelands."
LABORS_TO_RESTORE = "The Cenarion Circle labors to restore the blighted soil."
ORG_HISTORY_LEDE = "The Argent Dawn was founded after the Third War and fought in the Second War."
QUEST_IMPERATIVES = (
    "Aid the Argent Crusade in cleansing Andorhal. Slay the necromancers within Scholomance."
)
PARTICIPIAL_CAPTION = "A plague-scarred, ruined land of fallen towns and blighted farmland."


def test_model_loads_and_matches_pins() -> None:
    """Hard failure (never skip) when the pinned model is missing or drifts from pyproject."""
    info = model_info()
    assert info["spacy_version"] == "3.8.13"
    assert info["model_name"] == "en_core_web_sm"
    assert info["model_version"] == "3.8.0"
    pipes = info["pipes"].split(",")
    for required in ("tagger", "parser", "lemmatizer"):
        assert required in pipes
    # Entity identity is domain semantics; the wrapper must not even run NER.
    assert "ner" not in pipes


def test_sentence_spans_preserve_source_offsets() -> None:
    text = "The Scourge overran Andorhal. The Argent Crusade holds Hearthglen."
    spans = sentence_spans(text)
    assert [span.text for span in spans] == [
        "The Scourge overran Andorhal.",
        "The Argent Crusade holds Hearthglen.",
    ]
    for span in spans:
        assert text[span.start : span.end] == span.text


def test_linguistic_tokens_reconstruct_source_and_report_features() -> None:
    text = "The Argent Crusade heals the land."
    tokens = linguistic_tokens(text)
    assert "".join(token.text + token.whitespace for token in tokens) == text
    heals = next(token for token in tokens if token.text == "heals")
    assert heals.lemma == "heal"
    assert heals.pos == "VERB"
    assert heals.tag == "VBZ"
    assert heals.dep == "ROOT"
    assert heals.morph.get("Tense") == "Pres"
    assert heals.morph.get("VerbForm") == "Fin"
    # Proper nouns keep their surface text.
    crusade = next(token for token in tokens if token.text == "Crusade")
    assert crusade.pos == "PROPN"


def test_tense_profile_present_finite_summary() -> None:
    profile = tense_profile(HEALS)
    assert profile.present_finite_verbs == ("heals",)
    assert profile.past_count == 0
    assert profile.present_framed
    assert not profile.past_dominant
    assert not profile.imperative_like


def test_tense_profile_infinitive_complement_not_finite() -> None:
    profile = tense_profile(WORKS_TO_HEAL)
    assert profile.present_finite_verbs == ("works",)
    # "to further heal" is an infinitive complement: never a finite verb, never imperative.
    assert "heal" not in profile.present_finite_verbs
    assert profile.present_framed
    assert not profile.past_dominant
    assert not profile.imperative_like


def test_tense_profile_labors_known_small_model_weakness() -> None:
    # en_core_web_sm mis-tags "labors" as a plural noun, so this valid present-tense summary
    # reports NO finite verbs at all. Snapshot the real behaviour: the load-bearing property
    # for downstream gates is that it is neither past-dominant nor imperative — gates must
    # reject on positive past evidence, not require positive present evidence.
    profile = tense_profile(LABORS_TO_RESTORE)
    assert profile.past_count == 0
    assert profile.present_count == 0
    assert not profile.past_dominant
    assert not profile.present_framed
    assert not profile.imperative_like  # "to restore" is an infinitival fragment


def test_tense_profile_org_history_lede_past_dominant() -> None:
    profile = tense_profile(ORG_HISTORY_LEDE)
    # Passive "was founded" carries past narration on the finite auxiliary.
    assert profile.past_auxiliaries == ("was",)
    assert profile.past_finite_verbs == ("fought",)
    assert profile.past_participles == ("founded",)
    assert profile.past_count == 2
    assert profile.present_count == 0
    assert profile.past_dominant
    assert not profile.present_framed


def test_tense_profile_quest_imperatives() -> None:
    profile = tense_profile(QUEST_IMPERATIVES)
    assert profile.imperative_roots == ("Aid", "Slay")
    assert profile.imperative_like
    assert not profile.present_framed


def test_tense_profile_conjoined_imperative() -> None:
    profile = tense_profile("Aid the Argent Crusade and slay the necromancers.")
    assert profile.imperative_roots == ("Aid", "slay")
    assert profile.imperative_like


def test_tense_profile_conjoined_finite_verb_inherits_subject() -> None:
    # "recruit" carries no subject child of its own, but it is conjoined to "spy", whose
    # subject ("they") it shares — finite narration, not a directive. Without conjunction-chain
    # inheritance this false-positives as an imperative (the gold Cult of the Damned card shape).
    profile = tense_profile("They also spy in settlements and recruit the living into the Cult.")
    assert not profile.imperative_like


def test_tense_profile_bare_auxiliary_imperative() -> None:
    # "Be warned" parses as a participial root with a bare-form auxiliary spine.
    profile = tense_profile("Be warned: the Scourge remains active.")
    assert profile.imperative_like
    # The same text still reports its finite present clause.
    assert profile.present_finite_verbs == ("remains",)


def test_tense_profile_infinitival_fragment_not_imperative() -> None:
    profile = tense_profile("To restore the land.")
    assert not profile.imperative_like


def test_tense_profile_modal_passive_fragment_not_imperative() -> None:
    # Wiki-fragment shape: subjectless passive with a modal. Imperatives never take modals,
    # so these must not be flagged despite the bare-form "be" auxiliary.
    assert not tense_profile("Can be found in Scholomance.").imperative_like
    assert not tense_profile("Will be destroyed by the plague.").imperative_like


def test_tense_profile_attributive_amod_verb_is_not_finite_narration() -> None:
    # sm-model mis-parse: "fortified" in "fortified holdings" is reported as a *finite* past
    # verb (dep=amod). An attributive modifier functions as an adjective, so it must land in
    # past_participles, never in the finite past counts — otherwise a present-role sentence
    # gains a phantom past spine.
    profile = tense_profile("The Scarlet Crusade maintains fortified holdings across the zone.")
    assert profile.present_finite_verbs == ("maintains",)
    assert profile.past_count == 0
    assert "fortified" in profile.past_participles
    assert not profile.past_dominant


def test_tense_profile_participial_caption_has_no_finite_spine() -> None:
    profile = tense_profile(PARTICIPIAL_CAPTION)
    assert profile.past_participles == ("scarred", "ruined", "fallen")
    assert profile.past_count == 0
    assert profile.present_count == 0
    assert not profile.past_dominant
    assert not profile.present_framed
    assert not profile.imperative_like


def test_tense_profile_present_copula_counts_as_present_framing() -> None:
    profile = tense_profile("It is a ruined bastion.")
    assert profile.present_auxiliaries == ("is",)
    assert profile.present_framed
    assert not profile.past_dominant


def test_tense_profile_empty_text() -> None:
    profile = tense_profile("")
    assert profile.past_count == 0
    assert profile.present_count == 0
    assert not profile.past_dominant
    assert not profile.present_framed
    assert not profile.imperative_like


def test_lemmatized_content_tokens_drop_stopwords_keep_content_lemmas() -> None:
    lemmas = lemmatized_content_tokens("The Scourge destroyed the villages of Lordaeron.")
    assert lemmas == ["scourge", "destroy", "village", "lordaeron"]


def test_describe_renders_full_analysis() -> None:
    rendered = describe(HEALS)
    assert "model: en_core_web_sm 3.8.0" in rendered
    assert "sentences:" in rendered
    assert "tense profile:" in rendered
    assert "heals | heal | VERB | VBZ | ROOT" in rendered
    assert "present_framed=True" in rendered
