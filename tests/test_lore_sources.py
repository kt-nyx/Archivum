from __future__ import annotations

from pipeline.discovery.lore_sources import (
    build_instance_lore_candidates,
    compute_instance_lore_density,
    is_classic_variant_title,
    variant_cluster_key,
)


def _structured(href: str, role: str, parent: str = "") -> dict[str, str]:
    row = {"href": href, "section_role": role}
    if parent:
        row["parent_section_role"] = parent
    return row


def test_parent_candidate_requires_lead_and_infobox_corroboration() -> None:
    candidates = build_instance_lore_candidates(
        instance_id="instance-mana-tombs",
        instance_name="Mana-Tombs",
        section_blocks=[],
        wiki_links=["/wiki/Auchindoun", "/wiki/Outland"],
        structured_links=[
            _structured("/wiki/Auchindoun", "lead"),
            _structured("/wiki/Auchenai_Crypts", "history"),
        ],
    )
    parents = [c for c in candidates if c["candidate_kind"] == "parent"]
    related = [c for c in candidates if c["candidate_kind"] == "related"]
    assert [c["title"] for c in parents] == ["Auchindoun"]
    assert "Auchenai Crypts" in {c["title"] for c in related}


def test_parent_detected_even_when_history_mention_precedes_lead() -> None:
    # Document order puts a history mention before the lead mention; the infobox-
    # corroborated lead link must still resolve to the parent (occurrence-aware).
    candidates = build_instance_lore_candidates(
        instance_id="instance-mana-tombs",
        instance_name="Mana-Tombs",
        section_blocks=[],
        wiki_links=["/wiki/Auchindoun"],
        structured_links=[
            _structured("/wiki/Auchindoun", "history"),
            _structured("/wiki/Auchindoun", "lead"),
        ],
    )
    parents = [c for c in candidates if c["candidate_kind"] == "parent"]
    assert [c["title"] for c in parents] == ["Auchindoun"]
    # And it is not double-emitted as a related candidate.
    assert not [c for c in candidates if c["candidate_kind"] == "related"]


def test_lead_link_without_infobox_is_not_parent() -> None:
    candidates = build_instance_lore_candidates(
        instance_id="instance-x",
        instance_name="Some Dungeon",
        section_blocks=[],
        wiki_links=[],  # no infobox corroboration
        structured_links=[_structured("/wiki/Random_Lead_Link", "lead")],
    )
    assert not [c for c in candidates if c["candidate_kind"] == "parent"]


def test_classic_variant_and_self_and_noise_excluded() -> None:
    candidates = build_instance_lore_candidates(
        instance_id="instance-scholomance",
        instance_name="Scholomance",
        section_blocks=[],
        wiki_links=["/wiki/Caer_Darrow"],
        structured_links=[
            _structured("/wiki/Scholomance_(Classic)", "history"),  # explicit Classic
            _structured("/wiki/Scholomance", "history"),  # self
            _structured("/wiki/File:Map.jpg", "history"),  # noise
            _structured("/wiki/Caer_Darrow", "history"),  # legitimate related
        ],
    )
    titles = {c["title"] for c in candidates}
    assert "Scholomance (Classic)" not in titles
    assert "Scholomance" not in titles
    assert not any(t.startswith("File:") for t in titles)
    assert "Caer Darrow" in titles


def test_registry_organizations_are_excluded_without_title_role_hints() -> None:
    candidates = build_instance_lore_candidates(
        instance_id="instance-x",
        instance_name="Some Dungeon",
        section_blocks=[],
        wiki_links=[],
        structured_links=[
            _structured("/wiki/Prince_Malchezaar", "history"),  # unresolved target identity
            _structured("/wiki/Argent_Crusade", "history"),  # registry organization
            _structured("/wiki/Ancient_Battlefield", "history"),  # place -> kept
        ],
    )
    titles = {c["title"] for c in candidates}
    assert "Prince Malchezaar" in titles
    assert "Argent Crusade" not in titles
    assert "Ancient Battlefield" in titles


def test_related_candidates_are_capped_and_deterministic() -> None:
    structured = [_structured(f"/wiki/Place_{i}", "history") for i in range(8)]
    candidates = build_instance_lore_candidates(
        instance_id="instance-x",
        instance_name="Some Dungeon",
        section_blocks=[],
        wiki_links=[],
        structured_links=structured,
        max_related=3,
    )
    related = [c["title"] for c in candidates if c["candidate_kind"] == "related"]
    assert len(related) == 3
    assert related == sorted(related, key=str.lower)


def test_density_flags_sparse_vs_rich() -> None:
    sparse = compute_instance_lore_density(
        [{"block_type": "paragraph", "section_role": "lead", "text": "a b c d"}]
    )
    rich = compute_instance_lore_density(
        [{"block_type": "paragraph", "section_role": "history", "text": "word " * 120}]
    )
    assert sparse["is_sparse"] is True
    assert rich["is_sparse"] is False
    assert rich["history_word_count"] >= 120


def test_classic_and_variant_helpers() -> None:
    assert is_classic_variant_title("Dire Maul (Classic)") is True
    assert is_classic_variant_title("Dire Maul") is False
    assert variant_cluster_key("Dire Maul (Classic)") == "dire maul"
