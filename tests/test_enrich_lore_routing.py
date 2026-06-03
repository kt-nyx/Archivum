from __future__ import annotations

from pipeline.discovery.enrich import _build_evidence_packs


def _aux_snapshot(aux_role: str, source_id: str) -> dict[str, object]:
    return {
        "entity_id": "instance-mana-tombs",
        "entity_type": "instance",
        "source_id": source_id,
        "url": "https://warcraft.wiki.gg/wiki/Auchindoun",
        "name": "Mana-Tombs",
        "page_title": "Auchindoun",
        "auxiliary_role": aux_role,
        "auxiliary_target_id": "parent-auchindoun",
        "section_blocks": [
            {"section_role": "history", "text": "The Mana-Tombs were defiled by ethereal raiders."},
            {"section_role": "loot", "text": "Drops the Ethereal Crystal trinket on heroic."},
            {
                "section_role": "in_the_rpg",
                "text": "In the RPG, the Mana-Tombs were described differently.",
            },
            {"section_role": "strategy_edit", "text": "Mana-Tombs strategy: pull packs carefully."},
        ],
    }


def test_parent_and_related_lore_route_to_scoped_pools() -> None:
    packs = _build_evidence_packs(
        [
            _aux_snapshot("parent_lore", "src-parent"),
            _aux_snapshot("related_lore", "src-related"),
        ],
        run_id="run-test",
    )
    by_field: dict[str, list[dict[str, object]]] = {}
    for pack in packs:
        by_field.setdefault(str(pack["field_name"]), []).append(pack)

    assert "parent_lore_pool" in by_field
    assert "related_lore_pool" in by_field

    parent_pack = by_field["parent_lore_pool"][0]
    assert parent_pack["build_meta"]["lore_scope"] == "parent"
    assert parent_pack["build_meta"]["lore_source_title"] == "Auchindoun"

    related_pack = by_field["related_lore_pool"][0]
    assert related_pack["build_meta"]["lore_scope"] == "related"

    # Only narrative prose is routed: loot, RPG, and strategy sections are excluded.
    snippets = " ".join(
        str(item.get("snippet", ""))
        for pack in by_field["parent_lore_pool"]
        for item in pack["evidence_items"]
    )
    assert "defiled by ethereal raiders" in snippets
    assert "Ethereal Crystal" not in snippets
    assert "In the RPG" not in snippets
    assert "strategy" not in snippets.lower()
