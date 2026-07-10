from __future__ import annotations

import pytest

from pipeline.discovery.questline_arc_map import map_cluster_to_card_id


@pytest.mark.parametrize(
    ("cluster_id", "expected"),
    [
        ("main-story-alliance", "ql-main-story-alliance"),
        ("main-story-horde-entry-quest", "ql-main-story-horde-entry-quest"),
        ("same-title-second-anchor", "ql-same-title-second-anchor"),
    ],
)
def test_card_id_preserves_disambiguated_graph_identity(cluster_id: str, expected: str) -> None:
    assert map_cluster_to_card_id(cluster_id) == expected


def test_card_id_rejects_missing_cluster_identity() -> None:
    with pytest.raises(ValueError, match="cluster_id"):
        map_cluster_to_card_id("")
