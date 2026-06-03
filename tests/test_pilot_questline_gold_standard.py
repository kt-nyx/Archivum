"""Tests for Western Plaguelands pilot questline fixtures (registry + zone page gold)."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import pytest

from pipeline.contracts.models import QuestlineCardV2
from pipeline.discovery.entity_typing import is_valid_quest_graph_link
from pipeline.discovery.storyline_parser import _to_entity_id, _wiki_title
from pipeline.generate.draft.card_lint import lint_cta_hook, strip_zone_name_from_cta
from pipeline.ingest.fetch_wiki import _validate_manifest_schema
from pipeline.validate.engine import validate_payload

from tests.test_validation_engine import _validation_ready_zone_page_payload

PILOT_DIR = Path("tests/fixtures/pilot")
from pipeline.discovery.pilot_questline_registry import load_registry, registry_path_for_zone

REGISTRY_PATH = registry_path_for_zone("zone-western-plaguelands") or (
    PILOT_DIR / "western_plaguelands_questline_registry.json"
)
ZONE_PAGE_GOLD_PATH = PILOT_DIR / "zone_page_western_plaguelands_gold.json"
SOURCE_MANIFEST_PATH = PILOT_DIR / "source_manifest.json"
_FILLER_RE = re.compile(r"\blocated in\b|\bis a zone\b|\bis located\b", re.IGNORECASE)
_MAX_CHAIN_REFS = 12


def _load_registry() -> dict:
    registry = load_registry("zone-western-plaguelands")
    if registry is not None:
        return registry
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _load_zone_page_gold() -> dict:
    return json.loads(ZONE_PAGE_GOLD_PATH.read_text(encoding="utf-8"))


def _load_source_manifest() -> list[dict]:
    return json.loads(SOURCE_MANIFEST_PATH.read_text(encoding="utf-8"))


def _registry_included_card_chain_refs(registry: dict) -> set[str]:
    """Quest refs listed on included-arc cards (primary chain_refs only)."""
    refs: set[str] = set()
    for row in registry.get("included_arcs", []):
        refs.update(row.get("chain_refs") or [])
    return refs


def _registry_shared_beat_refs(registry: dict) -> set[str]:
    refs: set[str] = set()
    for row in registry.get("included_arcs", []):
        refs.update(row.get("shared_beat_refs") or [])
    return refs


def _registry_all_assigned_quest_refs(registry: dict) -> set[str]:
    """Every v3 quest node the registry accounts for (included, excluded, breadcrumbs)."""
    assigned = _registry_included_card_chain_refs(registry)
    assigned.update(_registry_shared_beat_refs(registry))
    for row in registry.get("included_arcs", []):
        assigned.update(row.get("overflow_chain_refs") or [])
    for row in registry.get("excluded_arcs", []):
        assigned.update(row.get("chain_refs") or [])
    entry = registry.get("andorhal_entry_breadcrumbs") or {}
    assigned.update(entry.get("chain_refs") or [])
    return assigned


def _questline_provenance_bucket(faction: str) -> str:
    if faction == "alliance":
        return "major_questlines_alliance"
    if faction == "horde":
        return "major_questlines_horde"
    return "major_questlines_shared"


def _validation_ready_payload_with_gold_questlines() -> dict:
    payload = _validation_ready_zone_page_payload()
    gold = _load_zone_page_gold()
    payload["major_questlines"] = gold["major_questlines"]
    for card in payload["major_questlines"]:
        bucket = _questline_provenance_bucket(str(card["faction"]))
        payload["provenance"][bucket][card["id"]] = [
            {
                "source_id": "src-wiki-wpl",
                "locator": f"section:quests paragraph:{card['id']}",
                "revision_id": "oldid:111",
                "excerpt_hash": f"sha256:gold{card['id'][-8:]}",
            }
        ]
    return payload


def test_pilot_fixtures_zone_id_consistent() -> None:
    registry = _load_registry()
    gold = _load_zone_page_gold()
    zone_id = "zone-western-plaguelands"
    assert registry["zone_id"] == zone_id
    assert gold["zone_id"] == zone_id
    manifest = _load_source_manifest()
    zone_rows = [row for row in manifest if row["entity_type"] == "zone"]
    assert zone_rows
    assert {row["entity_id"] for row in zone_rows} == {zone_id}


def test_source_manifest_validates_against_schema() -> None:
    manifest = _load_source_manifest()
    _validate_manifest_schema(manifest)


def test_source_manifest_storyline_url_matches_registry_authority() -> None:
    registry = _load_registry()
    manifest = _load_source_manifest()
    authority_url = str(registry["wiki_authority"]["primary_source_url"])
    manifest_urls = {str(row["source_url"]) for row in manifest}
    assert authority_url in manifest_urls
    scholomance_rows = [
        row for row in manifest if row["entity_id"] == "instance-scholomance"
    ]
    assert len(scholomance_rows) == 1
    assert scholomance_rows[0]["parent_zone_id"] == registry["zone_id"]


def test_registry_expected_included_card_count_matches_gold() -> None:
    registry = _load_registry()
    gold = _load_zone_page_gold()
    expected = int(registry["pipeline_gap_analysis"]["expected_included_card_count"])
    assert expected == len(registry["included_arcs"])
    assert expected == len(gold["major_questlines"])


def test_excluded_arc_ids_absent_from_zone_page_gold() -> None:
    registry = _load_registry()
    gold = _load_zone_page_gold()
    excluded_ids = {row["id"] for row in registry["excluded_arcs"]}
    gold_ids = {row["id"] for row in gold["major_questlines"]}
    assert excluded_ids.isdisjoint(gold_ids)


def test_zone_page_gold_passes_validation_with_provenance_shell() -> None:
    report = validate_payload("zone_page", _validation_ready_payload_with_gold_questlines())
    assert report.passed is True
    assert report.hard_fail_count == 0


def test_zone_page_gold_matches_questline_card_v2_contract() -> None:
    gold = _load_zone_page_gold()
    assert gold["entity_type"] == "zone_page"
    cards = gold["major_questlines"]
    assert len(cards) == 4
    for card in cards:
        parsed = QuestlineCardV2.model_validate(card)
        assert parsed.cta_hook
        assert parsed.chain_refs
        assert parsed.include_decision.value == "include"


def test_registry_and_zone_page_gold_ids_align() -> None:
    registry = _load_registry()
    gold = _load_zone_page_gold()
    registry_ids = {row["zone_page_gold_id"] for row in registry["included_arcs"]}
    gold_ids = {row["id"] for row in gold["major_questlines"]}
    assert registry_ids == gold_ids


def test_zone_page_gold_chain_refs_match_registry() -> None:
    registry = _load_registry()
    gold = _load_zone_page_gold()
    gold_by_id = {row["id"]: row for row in gold["major_questlines"]}
    for arc in registry["included_arcs"]:
        card = gold_by_id[arc["zone_page_gold_id"]]
        assert card["chain_refs"] == arc["chain_refs"]
        assert card["wiki_refs"] == arc["wiki_refs"]
        assert card["title"] == arc["title"]
        assert card["faction"] == arc["faction"]
        assert card["start_anchor"] == arc["start_anchor"]


def test_registry_chain_refs_derive_from_wiki_titles() -> None:
    registry = _load_registry()
    mismatches: list[str] = []
    ref_pairs = (
        ("included_arcs", "chain_refs", "wiki_refs"),
        ("included_arcs", "overflow_chain_refs", "overflow_wiki_refs"),
        ("excluded_arcs", "chain_refs", "wiki_refs"),
    )
    for section, chain_key, wiki_key in ref_pairs:
        for arc in registry.get(section, []):
            chain_refs = arc.get(chain_key) or []
            wiki_refs = arc.get(wiki_key) or []
            assert len(chain_refs) == len(wiki_refs), (
                f"{arc['id']} {chain_key} length mismatch"
            )
            for chain_ref, wiki_ref in zip(chain_refs, wiki_refs, strict=True):
                expected = _to_entity_id("quest", _wiki_title(str(wiki_ref)))
                if chain_ref != expected:
                    mismatches.append(f"{arc['id']} {chain_ref} != {expected} from {wiki_ref}")
    entry = registry.get("andorhal_entry_breadcrumbs") or {}
    for chain_ref, wiki_ref in zip(
        entry.get("chain_refs") or [],
        entry.get("wiki_refs") or [],
        strict=True,
    ):
        expected = _to_entity_id("quest", _wiki_title(str(wiki_ref)))
        if chain_ref != expected:
            mismatches.append(f"entry breadcrumb {chain_ref} != {expected}")
    assert not mismatches, "\n".join(mismatches)


@pytest.mark.parametrize(
    "questline_id",
    [
        "ql-andorhal-horde",
        "ql-andorhal-alliance",
        "ql-menders-stead-healing",
        "ql-hearthglen-tirion-legacy",
    ],
)
def test_zone_page_gold_cta_hooks_pass_card_lint(questline_id: str) -> None:
    registry = _load_registry()
    gold = _load_zone_page_gold()
    zone_name = str(registry["zone_name"])
    row = next(item for item in gold["major_questlines"] if item["id"] == questline_id)
    cta = str(row["cta_hook"]).strip()
    assert not lint_cta_hook(cta), lint_cta_hook(cta)
    stripped = strip_zone_name_from_cta(cta, zone_name=zone_name)
    assert zone_name.lower() not in stripped.lower()
    assert not _FILLER_RE.search(stripped)


@pytest.mark.parametrize("questline_id", ["ql-andorhal-horde", "ql-andorhal-alliance"])
def test_andorhal_gold_cards_respect_chain_ref_cap(questline_id: str) -> None:
    gold = _load_zone_page_gold()
    row = next(item for item in gold["major_questlines"] if item["id"] == questline_id)
    chain_refs = row.get("chain_refs") or []
    assert len(chain_refs) <= _MAX_CHAIN_REFS
    registry = _load_registry()
    arc = next(item for item in registry["included_arcs"] if item["id"] == questline_id)
    assert arc.get("overflow_chain_refs"), f"{questline_id} should document overflow in registry"


def test_registry_included_card_chain_refs_have_no_intra_arc_duplicates() -> None:
    registry = _load_registry()
    duplicates: list[str] = []
    for arc in registry["included_arcs"]:
        refs = arc.get("chain_refs") or []
        seen: set[str] = set()
        for ref in refs:
            if ref in seen:
                duplicates.append(f"{arc['id']}:{ref}")
            seen.add(ref)
    assert not duplicates, f"duplicate refs within arc chain_refs: {duplicates}"


def test_registry_documents_cross_faction_shared_card_refs() -> None:
    registry = _load_registry()
    documented = frozenset(
        registry.get("pipeline_gap_analysis", {}).get("cross_faction_shared_card_refs") or []
    )
    per_arc: dict[str, list[str]] = {
        arc["id"]: list(arc.get("chain_refs") or []) for arc in registry["included_arcs"]
    }
    cross_arc = {
        ref
        for ref, count in Counter(
            ref for refs in per_arc.values() for ref in refs
        ).items()
        if count > 1
    }
    assert cross_arc == documented
    assert documented == frozenset({"quest-combat-training"})


def test_registry_shared_andorhal_beats_do_not_overlap_included_card_refs() -> None:
    registry = _load_registry()
    card_refs = _registry_included_card_chain_refs(registry)
    shared = _registry_shared_beat_refs(registry)
    assert not (card_refs & shared)
    assert "quest-scholomancer" in shared
    gahrrons = next(
        row for row in registry["excluded_arcs"] if row["id"] == "ql-gahrrons-withering-cleanup"
    )
    assert "quest-scholomancer" not in set(gahrrons.get("chain_refs") or [])


def test_registry_wiki_refs_pass_quest_graph_classifier() -> None:
    registry = _load_registry()
    zone_name = str(registry["zone_name"])
    for section in ("included_arcs", "excluded_arcs"):
        for row in registry.get(section, []):
            for key in ("wiki_refs", "overflow_wiki_refs"):
                for link in row.get(key) or []:
                    valid, reasons = is_valid_quest_graph_link(str(link), zone_name=zone_name)
                    assert valid, f"{row['id']} {key} denied: {link!r} ({reasons})"
    entry = registry.get("andorhal_entry_breadcrumbs") or {}
    for link in entry.get("wiki_refs") or []:
        valid, reasons = is_valid_quest_graph_link(str(link), zone_name=zone_name)
        assert valid, f"entry breadcrumb denied: {link!r} ({reasons})"


def test_registry_documents_seven_storyline_parts() -> None:
    registry = _load_registry()
    parts = registry["wiki_authority"]["storyline_parts"]
    assert len(parts) == 7
    assert {part["part"] for part in parts} == set(range(1, 8))


def test_registry_covers_all_v3_quest_nodes_when_artifact_present() -> None:
    v3_path = Path("artifacts/runs/test-run-wpl-1/data/discovery/zone_quest_graph_v3.json")
    if not v3_path.exists():
        pytest.skip("pilot run artifact not present")
    registry = _load_registry()
    v3 = json.loads(v3_path.read_text(encoding="utf-8"))
    all_v3 = {row["node_id"] for row in v3 if row.get("node_type") == "quest"}
    assigned = _registry_all_assigned_quest_refs(registry)
    missing = sorted(all_v3 - assigned)
    assert not missing, f"registry missing v3 quests: {missing}"
    unknown_assigned = sorted(assigned - all_v3)
    assert not unknown_assigned, f"registry references unknown v3 quests: {unknown_assigned}"
