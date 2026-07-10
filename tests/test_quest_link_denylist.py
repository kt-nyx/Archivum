from __future__ import annotations

import pytest

from pipeline.discovery.entity_typing import is_valid_quest_graph_link

ZONE_NAME = "Example Zone"


@pytest.mark.parametrize(
    ("link", "reason_prefix"),
    [
        ("/wiki/Lordaeron", "registry"),
        ("/wiki/Eastern_Kingdoms", "registry"),
        ("/wiki/Hinterlands", "registry"),
        ("/wiki/Example_Zone", "self_zone"),
        ("/wiki/Some_Page#section", "fragment_link"),
        ("Category:Quests", "missing_wiki_path"),
    ],
)
def test_quest_graph_denylist_rejects_invalid_links(link: str, reason_prefix: str) -> None:
    valid, reasons = is_valid_quest_graph_link(link, zone_name=ZONE_NAME)
    assert not valid
    assert any(reason_prefix in reason for reason in reasons)


def test_quest_graph_denylist_accepts_real_quest_link() -> None:
    valid, reasons = is_valid_quest_graph_link(
        "/wiki/Quest_Alpha",
        zone_name=ZONE_NAME,
    )
    assert valid
    assert reasons == []
