from __future__ import annotations

from pipeline.generate.draft.faction_lint import (
    ensure_sentence_terminator,
    lint_faction_summary,
    strip_faction_label_prefix,
    trim_faction_summary,
)
from pipeline.generate.draft.prose_lint import word_count


def test_trim_faction_summary_adds_terminal_punctuation_when_truncated() -> None:
    snippet = " ".join(["reclamation"] * 50)
    summary = trim_faction_summary(snippet, max_words=40)
    assert summary.endswith(".")
    assert word_count(summary) <= 40


def test_strip_faction_label_prefix_removes_internal_binding_label() -> None:
    # Role-pool snippets are stored as "<Faction>: <snippet>"; that label must never ship.
    assert (
        strip_faction_label_prefix("Scourge: The Scholomance is a vile academy.", "Scourge")
        == "The Scholomance is a vile academy."
    )
    # Case-insensitive, and a non-matching leading word is left intact.
    assert strip_faction_label_prefix("scourge: raised the dead.", "Scourge") == "raised the dead."
    assert strip_faction_label_prefix("The Scourge raised the dead.", "Scourge") == (
        "The Scourge raised the dead."
    )


def test_trim_faction_summary_clause_trims_over_long_sentence() -> None:
    # A single over-cap clause chain must cut at a comma boundary, never mid-phrase ("Caer.").
    sentence = (
        "The Cult of the Damned operates within Scholomance under Kel'Thuzad, binding House Barov "
        "to undeath, corrupting Caer Darrow into a school of death magic, spreading plague across "
        "Lordaeron, and raising the fallen into the service of the Scourge for generations here."
    )
    summary = trim_faction_summary(sentence, max_words=40)
    assert word_count(summary) <= 40
    assert summary.endswith(".")
    # The cut lands on a whole word at a clause boundary, not a severed proper noun.
    assert "Caer." not in summary
    assert summary.split()[-1].rstrip(".").isalpha()


def test_ensure_sentence_terminator_preserves_existing_punctuation() -> None:
    assert ensure_sentence_terminator("Crusaders hold the line.") == "Crusaders hold the line."


def test_lint_faction_summary_accepts_zone_role_prose() -> None:
    summary = (
        "The Argent Crusade maintains fortified outposts across the contested frontier in Example Zone, "
        "coordinating reclamation efforts against undead forces throughout the ruined farmland."
    )
    assert not lint_faction_summary(summary, zone_name="Example Zone")


def test_lint_faction_summary_accepts_uses_and_serves_role_prose() -> None:
    summary = (
        "The Cult of the Damned uses Scholomance as a hidden necromantic school, "
        "serving the Scourge through its instructors and acolytes beneath Caer Darrow."
    )
    assert not lint_faction_summary(
        summary,
        zone_name="Scholomance",
        subregion_tokens=["Caer Darrow"],
    )


def test_lint_faction_summary_accepts_previously_whitelist_rejected_verbs() -> None:
    # Slice 5 regression set: valid present-role summaries whose predicates ("heals",
    # "works to further heal", "labors to restore") fell outside the deleted verb whitelist
    # and were rejected as lacking "zone role framing". The gate no longer pins verbs; it
    # only rejects positive past evidence ("labors" is even mis-tagged as a noun by the sm
    # model, so this also proves the gate never *requires* positive present evidence).
    heals = (
        "The Argent Crusade heals the land around Hearthglen, tending plague-blighted farmsteads "
        "across Western Plaguelands while its crusaders hold the line against lingering Scourge "
        "remnants."
    )
    works = (
        "The Cenarion Circle works to further heal the plaguelands, guiding new growth through "
        "Western Plaguelands' blighted soil as its druids tend the recovering groves."
    )
    labors = (
        "The Cenarion Circle labors to restore the blighted soil of Western Plaguelands, "
        "coaxing green shoots from dead earth while crusaders guard the recovering farmland."
    )
    for summary, faction in (
        (heals, "Argent Crusade"),
        (works, "Cenarion Circle"),
        (labors, "Cenarion Circle"),
    ):
        assert not lint_faction_summary(
            summary, zone_name="Western Plaguelands", faction_name=faction
        )


def test_lint_faction_summary_rejects_org_history_lede_on_past_dominance() -> None:
    # A generic organization-history lede (pure finite-past spine, no present anchoring)
    # reads as history, not a present-role summary; the reason tells the model what to do.
    lede = (
        "The Argent Dawn was founded after the Third War and fought across the Western "
        "Plaguelands, and its veterans campaigned through the plaguelands before the order "
        "dissolved at Light's Hope Chapel."
    )
    issues = lint_faction_summary(
        lede, zone_name="Western Plaguelands", faction_name="Argent Dawn"
    )
    assert issues == [
        "write in present tense: describe what Argent Dawn does now in Western Plaguelands, "
        "not its past history"
    ]


def test_lint_faction_summary_tolerates_past_supporting_detail() -> None:
    # The gold Forsaken card shape: a present-role description whose *supporting* sentence
    # recounts one past fact. A single subordinate past verb must not fail the card.
    summary = (
        "The Forsaken control Andorhal in the Western Plaguelands after driving out the Alliance "
        "and ending Scourge presence there. Sylvanas Windrunner and Koltira Deathweaver "
        "commanded their forces in that battle."
    )
    assert not lint_faction_summary(
        summary, zone_name="Western Plaguelands", faction_name="Forsaken"
    )


def test_lint_faction_summary_rejects_self_negating_non_answer() -> None:
    # RC6 category detection: a "summary" asserting the absence of content is a non-answer that
    # must fail the gate (driving the synthesis driver's retry → explicit failure), regardless of
    # its exact phrasing.
    issues = lint_faction_summary(
        "No zone-specific role for the Forsaken is evidenced in the available material here.",
        zone_name="Western Plaguelands",
        faction_name="Forsaken",
    )
    assert any("non-answer" in issue for issue in issues)

    issues = lint_faction_summary(
        "The faction's activities in this region are not stated and remain broadly unclear today.",
        zone_name="Western Plaguelands",
        faction_name="Forsaken",
    )
    assert any("non-answer" in issue for issue in issues)


def test_lint_faction_summary_rejects_off_topic_identity_fact() -> None:
    # Substance gate: a summary that recounts a nearby entity without ever naming the subject
    # faction is off-topic, even when it reads as fluent role prose.
    issues = lint_faction_summary(
        "Darkmaster Gandling controls the secret academy beneath Caer Darrow in Western "
        "Plaguelands, training necromancers for war.",
        zone_name="Western Plaguelands",
        faction_name="Cult of the Damned",
    )
    assert any("never names the faction" in issue for issue in issues)


def test_lint_faction_summary_accepts_on_topic_summary_with_name_token() -> None:
    # A significant token of the faction name ("cult" for "Cult of the Damned") counts as a
    # subject mention, so natural shorthand is not rejected.
    summary = (
        "The cult operates Scholomance as a hidden necromantic school beneath Caer Darrow, "
        "training acolytes in plaguecraft for the Scourge."
    )
    assert not lint_faction_summary(
        summary,
        zone_name="Scholomance",
        subregion_tokens=["Caer Darrow"],
        faction_name="Cult of the Damned",
    )
