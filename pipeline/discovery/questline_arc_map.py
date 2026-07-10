"""Map quest-graph cluster identities to stable questline card ids."""

from __future__ import annotations


def map_cluster_to_card_id(cluster_id: str) -> str:
    """Return a stable card id from the graph's disambiguated cluster identity.

    ``cluster_id`` already captures faction and start-anchor disambiguation when titles collide.
    Keeping it intact prevents display-title changes from changing published card identity.
    """
    normalized = str(cluster_id).strip()
    if not normalized:
        raise ValueError("questline cluster_id is required for card identity")
    return f"ql-{normalized}"
