from __future__ import annotations

from pathlib import Path

from pipeline.discovery.quest_roster import build_quest_roster, category_quest_links

STORYLINE_HTML = Path("tests/fixtures/storyline/western_plaguelands_storyline.html").read_text(encoding="utf-8")
ZONE_ID = "zone-western-plaguelands"
ZONE_NAME = "Western Plaguelands"


def test_roster_from_storyline_links_is_flat_and_unclustered() -> None:
    roster = build_quest_roster(
        zone_id=ZONE_ID,
        zone_name=ZONE_NAME,
        storyline_html=STORYLINE_HTML,
        min_storyline_quests=1,
    )
    assert roster
    assert all(row["node_type"] == "quest" for row in roster)
    assert all(row["cluster_id"] == "unclustered" for row in roster)
    # Source links are unique (deduped).
    links = [row["source_link"] for row in roster]
    assert len(links) == len(set(links))
    # order_in_cluster is a stable 1-based sequence.
    assert [row["order_in_cluster"] for row in roster] == list(range(1, len(roster) + 1))


def test_roster_falls_back_to_category_when_storyline_thin() -> None:
    calls: list[str] = []

    def fake_fetch_members(category: str, *, cmtype: str = "page", sleep_seconds: float = 0.0):
        calls.append(category)
        return [
            {"ns": 0, "title": "The Battle for Andorhal"},
            {"ns": 0, "title": "Mender's Stead"},
            {"ns": 14, "title": "Category:Western Plaguelands quests"},  # dropped (ns != 0)
            {"ns": 0, "title": "Western Plaguelands"},  # dropped (zone self-link)
        ]

    roster = build_quest_roster(
        zone_id=ZONE_ID,
        zone_name=ZONE_NAME,
        storyline_html="",  # no storyline content -> triggers fallback
        min_storyline_quests=3,
        fetch_members=fake_fetch_members,
    )
    assert calls == ["Category:Western Plaguelands quests"]
    titles = {row["title"] for row in roster}
    assert "The Battle for Andorhal" in titles
    assert "Mender's Stead" in titles
    assert "Category:Western Plaguelands quests" not in titles
    assert all(row["cluster_id"] == "unclustered" for row in roster)


def test_roster_skips_fallback_when_storyline_is_sufficient() -> None:
    def boom(*args, **kwargs):  # pragma: no cover - must not be called
        raise AssertionError("category fallback should not run when storyline is rich")

    roster = build_quest_roster(
        zone_id=ZONE_ID,
        zone_name=ZONE_NAME,
        storyline_html=STORYLINE_HTML,
        min_storyline_quests=1,
        fetch_members=boom,
    )
    assert roster


def test_category_quest_links_filters_namespaces() -> None:
    def fake_fetch_members(category: str, *, cmtype: str = "page", sleep_seconds: float = 0.0):
        return [
            {"ns": 0, "title": "Mender's Stead"},
            {"ns": 0, "title": "Mender's Stead"},  # duplicate
            {"ns": 14, "title": "Category:Foo"},
        ]

    links = category_quest_links(ZONE_NAME, fetch_members=fake_fetch_members)
    assert links == ["/wiki/Mender's_Stead"]
