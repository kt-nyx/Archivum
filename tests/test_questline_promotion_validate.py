from __future__ import annotations

from pipeline.contracts.models import ZonePage
from pipeline.validate.rules.questline_promotion import validate_questline_promotion_rules
from tests.factories.wiki_first_pages import minimal_zone_page_payload


def test_release_validation_rejects_non_graph_card_id() -> None:
    payload = minimal_zone_page_payload()
    payload["major_questlines"] = [{
        "id": "cluster-manual", "title": "Story", "faction": "shared", "cta_hook": "Follow the story through its linked quests.",
        "start_anchor": "Entry", "chain_refs": ["quest-entry"], "include_decision": "include", "reason_codes": ["score_threshold_met"], "wiki_refs": ["/wiki/Entry"],
    }]
    issues = validate_questline_promotion_rules(
        "zone_page",
        ZonePage.model_validate(payload),
        validation_context={"questline_card_metadata_by_cluster": {"manual": {"card_id": "ql-manual"}}},
    )
    assert any(issue.code == "questline_promotion.graph_id" for issue in issues)
