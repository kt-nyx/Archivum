from __future__ import annotations

from typing import Any

import pipeline.ingest.wiki_redirects as wiki_redirects
from pipeline.ingest.wiki_redirects import (
    annotate_snapshots_with_canonical_identity,
    normalize_wiki_path,
    resolve_wiki_identities,
)


def test_normalize_wiki_path_strips_host_prefix_and_fragment() -> None:
    assert normalize_wiki_path("https://warcraft.wiki.gg/wiki/Loken#Abilities") == "Loken"
    assert normalize_wiki_path("/wiki/Instructor_Razuvious") == "Instructor_Razuvious"
    assert normalize_wiki_path("") == ""


def test_resolve_wiki_identities_follows_redirects_and_pageids(monkeypatch) -> None:
    captured: dict[str, str] = {}

    def fake_get_json(url: str, *, timeout_seconds: int) -> dict[str, Any]:
        captured["url"] = url
        return {
            "query": {
                "normalized": [{"from": "Razuvious", "to": "Razuvious"}],
                "redirects": [{"from": "Razuvious", "to": "Instructor Razuvious"}],
                "pages": [
                    {"pageid": 4242, "title": "Instructor Razuvious"},
                    {"pageid": 7, "title": "Loken"},
                ],
            }
        }

    monkeypatch.setattr(wiki_redirects, "_http_get_json", fake_get_json)
    identities = resolve_wiki_identities(
        ["/wiki/Razuvious", "Loken"], origin="https://warcraft.wiki.gg"
    )
    assert identities["Razuvious"]["canonical_path"] == "Instructor_Razuvious"
    assert identities["Razuvious"]["page_id"] == 4242
    assert identities["Loken"]["canonical_path"] == "Loken"
    assert identities["Loken"]["page_id"] == 7
    assert "action=query" in captured["url"]
    assert "redirects=1" in captured["url"]


def test_resolve_wiki_identities_handles_missing_pages(monkeypatch) -> None:
    def fake_get_json(url: str, *, timeout_seconds: int) -> dict[str, Any]:
        return {"query": {"pages": [{"title": "Ghost Page", "missing": True}]}}

    monkeypatch.setattr(wiki_redirects, "_http_get_json", fake_get_json)
    identities = resolve_wiki_identities(["Ghost_Page"], origin="https://warcraft.wiki.gg")
    assert identities["Ghost_Page"]["canonical_path"] == "Ghost_Page"
    assert identities["Ghost_Page"]["page_id"] is None


def test_annotate_snapshots_writes_canonical_identity_on_roster_links() -> None:
    def roster_predicate(row: dict[str, Any]) -> bool:
        return str(row.get("section_role", "")) in {"bosses", "denizens"}

    def fake_resolver(paths: list[str], *, origin: str, timeout_seconds: int = 15):
        assert origin == "https://warcraft.wiki.gg"
        return {
            "Razuvious": {
                "canonical_title": "Instructor Razuvious",
                "canonical_path": "Instructor_Razuvious",
                "page_id": 4242,
            }
        }

    snapshots = [
        {
            "entity_type": "instance",
            "url": "https://warcraft.wiki.gg/wiki/Naxxramas",
            "structured_links": [
                {"href": "/wiki/Razuvious", "section_role": "bosses"},
                {"href": "/wiki/Patch_3.3.0", "section_role": "patch_changes"},
            ],
        },
        {"entity_type": "zone", "url": "https://warcraft.wiki.gg/wiki/Dragonblight"},
    ]
    run_map = annotate_snapshots_with_canonical_identity(
        snapshots, roster_predicate=roster_predicate, resolver=fake_resolver
    )
    roster_link = snapshots[0]["structured_links"][0]
    assert roster_link["canonical_path"] == "Instructor_Razuvious"
    assert roster_link["page_id"] == 4242
    # Non-roster links are left untouched.
    assert "canonical_path" not in snapshots[0]["structured_links"][1]
    assert run_map["https://warcraft.wiki.gg|Razuvious"]["page_id"] == 4242
