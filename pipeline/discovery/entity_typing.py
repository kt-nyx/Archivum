"""Evidence-based entity-kind decisions for linked wiki pages.

The discovery pass may keep an unclassified link as a crawl lead, but it must
never promote that lead to a renderable card kind from its title, capitalization,
or a hand-maintained Warcraft vocabulary.  This module therefore treats missing
target-page evidence as ``unknown``.
"""

from __future__ import annotations

import re
from typing import Any, Literal
from urllib.parse import unquote

from pipeline.common.text_ids import slugify
from pipeline.contracts.models import EntityKind, EntityKindDecision
from pipeline.discovery.world_registry import entry_kinds

_SUBZONE_CATEGORY_SUFFIX = " subzones"
_WIKI_NAMESPACE_PREFIXES = frozenset(
    {"file", "template", "category", "help", "special", "module", "talk", "user"}
)

TraverseRole = Literal[
    "storyline",
    "quest",
    "faction_profile",
    "location_profile",
    "character_profile",
    "instance_lore",
]

_QUEST_GRAPH_REGISTRY_KINDS = frozenset(
    {"zone", "continent", "capital", "region", "instance", "person", "place"}
)
_TRAVERSE_BLOCK_BY_ROLE: dict[str, frozenset[str]] = {
    "quest": _QUEST_GRAPH_REGISTRY_KINDS,
    "faction_profile": frozenset({"zone", "continent", "instance"}),
    "location_profile": frozenset({"zone", "continent", "capital", "region", "instance"}),
    "character_profile": frozenset({"zone", "continent", "capital", "region", "instance"}),
    "storyline": frozenset(),
    "instance_lore": frozenset({"zone", "continent", "capital", "region"}),
    "parent_lore": frozenset({"continent"}),
    "related_lore": frozenset({"continent", "capital"}),
}


def location_subzone_zone_slugs(categories: list[str] | None) -> set[str]:
    """Return source-native zone-of-record slugs from ``<Zone> subzones`` categories."""
    slugs: set[str] = set()
    for category in categories or []:
        text = str(category).strip()
        if text.lower().endswith(_SUBZONE_CATEGORY_SUFFIX):
            zone_part = text[: -len(_SUBZONE_CATEGORY_SUFFIX)].strip()
            if zone_part:
                slugs.add(slugify(zone_part))
    return slugs


def location_is_offzone(categories: list[str] | None, zone_id: str) -> bool:
    """Whether a target page's own subzone category names another zone."""
    subzone_slugs = location_subzone_zone_slugs(categories)
    return bool(subzone_slugs) and zone_id.strip().removeprefix("zone-") not in subzone_slugs


def _wiki_title_from_link(link: str) -> str:
    value = str(link or "").strip()
    if "/wiki/" not in value:
        return ""
    title = value.split("/wiki/", 1)[1].split("#", 1)[0].split("?", 1)[0]
    return unquote(title).strip().replace("_", " ")


def canonical_path_for_link(link: str) -> str:
    title = _wiki_title_from_link(link)
    return f"/wiki/{title.replace(' ', '_')}" if title else ""


def normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", title.strip()).lower()


def is_bogus_traversal_link(link: str) -> bool:
    """Reject only generic URL/namespace/redlink hygiene failures."""
    value = str(link or "").strip()
    title = _wiki_title_from_link(value)
    if not title or "#" in value.split("/wiki/", 1)[-1]:
        return True
    lowered = title.lower()
    if "redlink=1" in value.lower() or "action=edit" in value.lower() or lowered.startswith("see "):
        return True
    namespace = lowered.split(":", 1)[0] if ":" in lowered else ""
    return namespace in _WIKI_NAMESPACE_PREFIXES


def _category_kinds(categories: list[str]) -> set[EntityKind]:
    """Map target-page category *structure* to the output enum.

    These are category-family labels supplied by the source wiki, not article
    titles or Warcraft entity vocabularies.  Conflicting source families abstain.
    """
    joined = " ".join(normalize_title(category) for category in categories)
    kinds: set[EntityKind] = set()
    if " subzones" in joined or " locations" in joined:
        kinds.add(EntityKind.PLACE)
    if any(marker in joined for marker in (" characters", " npcs", " bosses")):
        kinds.add(EntityKind.NAMED_ACTOR)
    if any(marker in joined for marker in (" organizations", " factions")):
        kinds.add(EntityKind.ORGANIZATION)
    if any(marker in joined for marker in (" races", " species", " creature types")):
        kinds.add(EntityKind.GROUP_OR_SPECIES)
    if any(
        marker in joined
        for marker in (" abilities", " spells", " items", " concepts", " events", " quests")
    ):
        kinds.add(EntityKind.OBJECT_OR_CONCEPT)
    return kinds


def _infobox_kinds(infobox: dict[str, Any]) -> set[EntityKind]:
    """Use explicit source infobox entity labels when available."""
    values = {
        normalize_title(str(value))
        for key, value in infobox.items()
        if normalize_title(str(key)) in {"type", "kind", "entity type", "subject type"}
        and str(value).strip()
    }
    kinds: set[EntityKind] = set()
    if values & {"place", "location", "subzone", "settlement", "landmark"}:
        kinds.add(EntityKind.PLACE)
    if values & {"character", "npc", "person"}:
        kinds.add(EntityKind.NAMED_ACTOR)
    if values & {"organization", "faction", "guild"}:
        kinds.add(EntityKind.ORGANIZATION)
    if values & {"race", "species", "creature type", "group"}:
        kinds.add(EntityKind.GROUP_OR_SPECIES)
    if values & {"ability", "spell", "item", "concept", "event", "quest"}:
        kinds.add(EntityKind.OBJECT_OR_CONCEPT)
    return kinds


def _registry_kind(title: str) -> EntityKind | None:
    kinds = entry_kinds(title)
    if "place" in kinds:
        return EntityKind.PLACE
    if "person" in kinds:
        return EntityKind.NAMED_ACTOR
    if "organization" in kinds:
        return EntityKind.ORGANIZATION
    return None


def decide_entity_kind(
    *,
    candidate_id: str,
    canonical_title: str,
    canonical_path: str,
    source_snapshot: dict[str, Any] | None = None,
    source_relation: str = "",
    source_ids: list[str] | None = None,
) -> EntityKindDecision:
    """Make one fail-closed entity-kind decision from target-page evidence.

    The registry may supply a positive source-native category signal, but absence
    from it has no meaning.  A source-page relationship is retained for audit but
    never settles the entity kind by itself.
    """
    signals: list[str] = []
    reasons: list[str] = []
    ids = [value for value in (source_ids or []) if value]
    kinds: set[EntityKind] = set()

    registry_kind = _registry_kind(canonical_title)
    if registry_kind is not None:
        kinds.add(registry_kind)
        signals.append(f"registry:{registry_kind.value}")

    if source_snapshot is not None:
        snapshot_id = str(source_snapshot.get("source_id", "")).strip()
        if snapshot_id and snapshot_id not in ids:
            ids.append(snapshot_id)
        categories = [
            str(category) for category in source_snapshot.get("categories", []) if str(category).strip()
        ]
        category_kinds = _category_kinds(categories)
        if category_kinds:
            kinds.update(category_kinds)
            signals.extend(f"category:{kind.value}" for kind in sorted(category_kinds, key=str))
        infobox = source_snapshot.get("infobox")
        if isinstance(infobox, dict):
            infobox_kinds = _infobox_kinds(infobox)
            if infobox_kinds:
                kinds.update(infobox_kinds)
                signals.extend(f"infobox:{kind.value}" for kind in sorted(infobox_kinds, key=str))
    if source_relation:
        signals.append(f"source_relation:{source_relation}")

    if len(kinds) == 1:
        kind = next(iter(kinds))
        confidence = 0.95 if len(signals) > 1 else 0.8
        reasons.append("affirmative_target_evidence")
    elif len(kinds) > 1:
        kind = EntityKind.UNKNOWN
        confidence = 0.0
        reasons.append("conflicting_target_evidence")
    else:
        kind = EntityKind.UNKNOWN
        confidence = 0.0
        reasons.append("insufficient_target_evidence")

    decision_id = f"entity-kind-{slugify(canonical_title)}"
    return EntityKindDecision(
        decision_id=decision_id,
        candidate_id=candidate_id,
        canonical_title=canonical_title,
        canonical_path=canonical_path,
        kind=kind,
        confidence=confidence,
        source_signals=signals,
        source_ids=ids,
        reason_codes=reasons,
    )


def is_valid_quest_graph_link(link: str, *, zone_name: str = "") -> tuple[bool, list[str]]:
    """Return generic-hygiene and structural-registry validity for a quest node link."""
    value = str(link or "").strip()
    if "/wiki/" not in value:
        return False, ["missing_wiki_path"]
    if "#" in value.split("/wiki/", 1)[1]:
        return False, ["fragment_link"]
    if "redlink=1" in value.lower() or "action=edit" in value.lower():
        return False, ["meta_url"]
    title = _wiki_title_from_link(link)
    if not title:
        return False, ["empty_title"]
    namespace = title.lower().split(":", 1)[0] if ":" in title else ""
    if namespace in _WIKI_NAMESPACE_PREFIXES:
        return False, ["namespace"]
    if normalize_title(title) == normalize_title(zone_name):
        return False, ["self_zone"]
    blocked = entry_kinds(title) & _QUEST_GRAPH_REGISTRY_KINDS
    if blocked:
        return False, [f"registry_{sorted(blocked)[0]}"]
    return True, []


def should_skip_registry_traversal(
    link: str,
    *,
    auxiliary_role: str,
    zone_name: str = "",
    allowed_instance_titles: frozenset[str] | None = None,
) -> tuple[bool, list[str]]:
    """Apply generic link hygiene and source-taxonomy traversal bounds."""
    role = auxiliary_role.strip().lower()
    if role == "storyline":
        return False, []
    if is_bogus_traversal_link(link):
        return True, ["bogus_link"]
    title = _wiki_title_from_link(link)
    if not title:
        return True, ["empty_title"]
    if normalize_title(title) == normalize_title(zone_name) and role in {"quest", "location_profile"}:
        return True, ["self_zone"]
    allowed_instances = {normalize_title(value) for value in (allowed_instance_titles or frozenset())}
    if normalize_title(title) in allowed_instances and role in {"location_profile", "instance_lore"}:
        return False, []
    blocked = entry_kinds(title) & _TRAVERSE_BLOCK_BY_ROLE.get(
        role, frozenset({"zone", "continent", "instance"})
    )
    if blocked:
        return True, [f"registry_{sorted(blocked)[0]}_for_{role}"]
    return False, []
