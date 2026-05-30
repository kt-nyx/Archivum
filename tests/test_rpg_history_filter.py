from __future__ import annotations

from pipeline.discovery.enrich import _build_evidence_packs, _is_history_digest_role
from pipeline.ingest.fetch_wiki import _extract_sections_and_links


def test_extract_sections_prefixes_rpg_nested_history() -> None:
    html = """
    <p>Lead paragraph about the zone overview.</p>
    <h2>In the RPG</h2>
    <p>This section contains information from the Warcraft RPG and is non-canon.</p>
    <h3>History</h3>
    <p>RPG history paragraph that should not become bare history_edit content.</p>
    <h2>Cataclysm</h2>
    <p>Recovery efforts after the Cataclysm reshaped the zone.</p>
    """
    sections, _, _ = _extract_sections_and_links(html)
    roles = [block["section_role"] for block in sections]
    assert "history_edit" not in roles
    assert any(role.startswith("in_the_rpg_") for role in roles)
    assert roles[-1] == "cataclysm"


def test_rpg_blocks_excluded_from_history_digest() -> None:
    html = """
    <p>Lead paragraph about the zone overview.</p>
    <h2>In the RPG</h2>
    <p>This section contains information from the Warcraft RPG and is non-canon.</p>
    <h3>History</h3>
    <p>RPG history paragraph with non-canon details about the region.</p>
    <h2>History</h2>
    <p>
        The region suffered catastrophic collapse before long-term military campaigns
        began restoring order across the ruined frontier and broken keeps.
    </p>
    """
    sections, _, _ = _extract_sections_and_links(html)
    snapshots = [
        {
            "entity_id": "zone-example",
            "entity_type": "zone",
            "name": "Example Zone",
            "source_id": "src-zone",
            "url": "https://warcraft.wiki.gg/wiki/Example_Zone",
            "section_blocks": sections,
            "auxiliary_role": "",
        }
    ]
    packs = _build_evidence_packs(snapshots, "run-test")
    history_snippets = [
        item["snippet"]
        for row in packs
        if row.get("field_name") == "history_digest"
        for item in row.get("evidence_items", [])
    ]
    assert history_snippets
    assert not any("Warcraft RPG" in snippet for snippet in history_snippets)
    assert not any("non-canon details" in snippet for snippet in history_snippets)


def test_is_history_digest_role_rejects_in_the_rpg_history() -> None:
    assert not _is_history_digest_role("in_the_rpg_history")
