from __future__ import annotations

from pipeline.generate.draft.provenance import select_identity_url


def test_identity_url_matches_entity_own_page_not_first_source() -> None:
    # The first source is the parent-zone overview; the entity's own page must win (RC-7).
    source_urls = {
        "src-wpl-overview": "https://warcraft.wiki.gg/wiki/Western_Plaguelands",
        "src-scholomance-overview": "https://warcraft.wiki.gg/wiki/Scholomance",
    }
    assert (
        select_identity_url(source_urls, "Scholomance")
        == "https://warcraft.wiki.gg/wiki/Scholomance"
    )


def test_identity_url_handles_urlencoded_titles() -> None:
    source_urls = {"s1": "https://warcraft.wiki.gg/wiki/Dalson%27s_Tears"}
    assert select_identity_url(source_urls, "Dalson's Tears").endswith("Dalson%27s_Tears")


def test_identity_url_falls_back_to_first_then_default() -> None:
    source_urls = {"s1": "https://warcraft.wiki.gg/wiki/Some_Other_Page"}
    # No slug match -> first usable URL.
    assert select_identity_url(source_urls, "Scholomance").endswith("Some_Other_Page")
    # Nothing usable -> wiki root default.
    assert select_identity_url({}, "Scholomance") == "https://warcraft.wiki.gg/"
