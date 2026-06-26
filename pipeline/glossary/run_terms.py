"""Build run-scoped glossary terms from wiki-first drafts and discovery artifacts.

Terms and aliases are derived from run signals so a per-zone glossary is
comprehensive without leaning on the static ``dictionary/glossary_aliases.v1.json``
fallback. Three run-derived sources feed the accumulator:

* **Drafts** — the selected zone/instance cards (factions, locations, key
  characters, instance links).
* **Discovered canonical entities** — ``discovery/canonical_entity_map.jsonl``,
  which is itself built from the captured wiki links, so the "captured wiki
  links" signal reaches the glossary through it.
* **Ingest snapshots** — every fetched page's ``name``, plus its MediaWiki
  ``categories`` (to classify a term whose discovered type is unknown) and
  ``infobox`` alternate-name fields (to harvest aliases).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from pipeline.common.io import read_json
from pipeline.common.retail import is_non_retail_title
from pipeline.common.run_context import RunContext
from pipeline.common.text_ids import slugify

WIKI_BASE = "https://warcraft.wiki.gg/wiki"
_LINK_CATEGORY_CACHE_NAME = "link_category_cache.json"

# Snapshot entity types whose own page is a seed (zone/instance overview). Their
# outbound lore links are the lexicon the page actually references.
_SEED_ENTITY_TYPES: frozenset[str] = frozenset({"zone", "instance"})

# MediaWiki namespace prefixes that are never glossary terms.
_LINK_NAMESPACE_PREFIXES: tuple[str, ...] = (
    "file:",
    "category:",
    "template:",
    "help:",
    "special:",
    "module:",
    "talk:",
    "user:",
    "portal:",
    "mediawiki:",
    "wikipedia:",
)

_ENTITY_CATEGORY: dict[str, str] = {
    "zone": "place",
    "instance": "place",
    "location": "place",
    "faction": "faction",
    "character": "person",
    "person": "person",
    "event": "event",
    "artifact": "artifact",
    "concept": "concept",
}
_CATEGORY_SIGNAL_BUCKETS: frozenset[str] = frozenset(
    {"person", "place", "faction", "event", "artifact"}
)

# Infobox header labels (lower-cased) that carry alternate names for an entity.
# Values are split on the punctuation below into individual alias candidates.
_INFOBOX_ALIAS_FIELDS: frozenset[str] = frozenset(
    {
        "alias",
        "aliases",
        "aka",
        "also known as",
        "other name",
        "other names",
        "nickname",
        "nicknames",
        "full name",
        "former name",
        "former names",
    }
)

_ALIAS_SPLIT_RE = re.compile(r"[,;/\n]")

# A short, all-uppercase single token (ADP, NPC, BDP) is a wiki abbreviation/date
# notation, not a lore proper noun — proper nouns are mixed-case. Requires at least
# one letter so this is a *shape* rule, not a content list.
_ABBREVIATION_RE = re.compile(r"[A-Z0-9]{2,5}")

# A leading article is dropped when deriving the dedup key/slug so "The Battle for
# Andorhal" and "Battle for Andorhal" collapse to one term (one rule, no per-term data).
_LEADING_ARTICLE_RE = re.compile(r"^the\s+", re.IGNORECASE)


def _is_abbreviation_shape(label: str) -> bool:
    token = label.strip()
    if not token or " " in token or "-" in token:
        return False
    return bool(_ABBREVIATION_RE.fullmatch(token)) and any(ch.isalpha() for ch in token)


def _strip_leading_article(label: str) -> str:
    stripped = _LEADING_ARTICLE_RE.sub("", label).strip()
    return stripped or label

# Structural MediaWiki-category -> glossary-category decoder. It matches against
# the authoritative category names captured at ingest (INGEST-CAT), not free body
# text, so it is the structural signal WS-C/D-6 sanctions. Used only to refine a
# term whose discovered entity_type is the generic "concept" (i.e. unknown).
_CATEGORY_SIGNAL_TOKENS: tuple[tuple[str, str], ...] = (
    ("npc", "person"),
    ("character", "person"),
    ("boss", "person"),
    ("faction", "faction"),
    ("organization", "faction"),
    ("order", "faction"),
    ("zone", "place"),
    ("subzone", "place"),
    ("region", "place"),
    ("dungeon", "place"),
    ("raid", "place"),
    ("instance", "place"),
    ("city", "place"),
    ("town", "place"),
    ("location", "place"),
    ("battle", "event"),
    ("war", "event"),
    ("event", "event"),
)


def _normalize_alias(text: str) -> str:
    return " ".join(text.lower().split())


def _term_slug(label: str) -> str:
    return slugify(label) or "unknown"


def _wiki_url(label: str, existing_url: str = "") -> str:
    url = existing_url.strip()
    if url.startswith("http"):
        return url
    wiki_slug = label.replace(" ", "_")
    return f"{WIKI_BASE}/{wiki_slug}"


def _title_from_href(href: str) -> str:
    if "://" in href:
        path = urlparse(href).path
    else:
        path = href
    if "/wiki/" not in path:
        return ""
    title = path.split("/wiki/", 1)[-1].split("#", 1)[0]
    return unquote(title).replace("_", " ").strip()


def _link_category_lookup_key(title: str) -> str:
    return title.replace("_", " ").strip().casefold()


def _category_for_entity_type(entity_type: str) -> str:
    return _ENTITY_CATEGORY.get(entity_type.strip().lower(), "concept")


def _category_from_categories(categories: list[Any]) -> str:
    """Map MediaWiki category names to a glossary category, or "" when unclear."""
    for category in categories:
        lowered = str(category).lower()
        for token, glossary_category in _CATEGORY_SIGNAL_TOKENS:
            if token in lowered:
                return glossary_category
    return ""


def _glossary_category(entity_type: str, categories: list[Any]) -> str:
    """Prefer the discovered entity type; fall back to category signal when unknown."""
    base = _category_for_entity_type(entity_type)
    if base != "concept":
        return base
    return _category_from_categories(categories) or "concept"


def _aliases_from_infobox(infobox: dict[str, Any]) -> list[str]:
    """Harvest alternate-name aliases from alias-bearing infobox fields."""
    aliases: list[str] = []
    for key, value in infobox.items():
        if str(key).strip().lower() not in _INFOBOX_ALIAS_FIELDS:
            continue
        for part in _ALIAS_SPLIT_RE.split(str(value)):
            cleaned = part.strip()
            if len(cleaned) >= 2:
                aliases.append(cleaned)
    return aliases


def _load_json(path: Path) -> Any:
    return read_json(path)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _load_snapshots(context: RunContext) -> list[dict[str, Any]]:
    snapshots_path = context.data_dir / "ingest" / "source_snapshots.json"
    if not snapshots_path.exists():
        return []
    blob = _load_json(snapshots_path)
    if not isinstance(blob, list):
        return []
    return [snapshot for snapshot in blob if isinstance(snapshot, dict)]


def _load_link_category_cache(context: RunContext) -> dict[str, dict[str, Any]]:
    cache_path = context.data_dir / "ingest" / _LINK_CATEGORY_CACHE_NAME
    if not cache_path.exists():
        return {}
    blob = _load_json(cache_path)
    if not isinstance(blob, dict):
        return {}
    entries = blob.get("entries")
    if not isinstance(entries, dict):
        return {}
    return {str(key): value for key, value in entries.items() if isinstance(value, dict)}


def _ingest_url_by_entity(snapshots: list[dict[str, Any]]) -> dict[str, str]:
    urls: dict[str, str] = {}
    for snapshot in snapshots:
        entity_id = str(snapshot.get("entity_id", "")).strip()
        url = str(snapshot.get("url", "")).strip()
        if entity_id and url.startswith("http"):
            urls.setdefault(entity_id, url)
    return urls


def _card_wiki_url(card: dict[str, Any], card_id: str, ingest_urls: dict[str, str]) -> str:
    url = str(card.get("wiki_url", "")).strip()
    if url.startswith("http"):
        return url
    return ingest_urls.get(card_id, "")


class _TermAccumulator:
    def __init__(self) -> None:
        self._by_label: dict[str, dict[str, Any]] = {}
        self._term_ids: set[str] = set()

    def add(
        self,
        *,
        label: str,
        category: str,
        wiki_url: str = "",
        source_entity_id: str = "",
        source_entity_type: str = "",
        extra_aliases: list[str] | None = None,
    ) -> None:
        cleaned = label.strip()
        if not cleaned or len(cleaned) < 2:
            return
        # Key (and slug) on the article-stripped form so "The Battle for Andorhal"
        # dedups against "Battle for Andorhal"; both surface forms stay as aliases so
        # the linker can still match either in prose.
        keyed = _strip_leading_article(cleaned)
        norm = _normalize_alias(keyed)
        if not norm:
            return
        url = _wiki_url(keyed, wiki_url)
        aliases = {_normalize_alias(cleaned), _normalize_alias(keyed)}
        if extra_aliases:
            for alias in extra_aliases:
                normalized = _normalize_alias(alias)
                if normalized:
                    aliases.add(normalized)
        existing = self._by_label.get(norm)
        if existing is not None:
            existing_aliases = set(existing.get("aliases", []))
            existing_aliases.update(aliases)
            existing["aliases"] = sorted(existing_aliases)
            if not existing.get("wiki_url") and url:
                existing["wiki_url"] = url
            if not existing.get("source_entity_id") and source_entity_id:
                existing["source_entity_id"] = source_entity_id
            if not existing.get("source_entity_type") and source_entity_type:
                existing["source_entity_type"] = source_entity_type
            # Upgrade a generic classification when a later source supplies a
            # specific one, so category resolution is order-independent.
            if existing.get("category", "concept") == "concept" and category != "concept":
                existing["category"] = category
            return
        base_slug = _term_slug(keyed)
        term_id = f"term-{base_slug}"
        suffix = 2
        while term_id in self._term_ids:
            term_id = f"term-{base_slug}-{suffix}"
            suffix += 1
        self._term_ids.add(term_id)
        self._by_label[norm] = {
            "term_id": term_id,
            "label": keyed,
            "wiki_url": url,
            "category": category,
            "aliases": sorted(aliases),
            "source_entity_id": source_entity_id,
            "source_entity_type": source_entity_type,
        }

    def rows(self) -> list[dict[str, Any]]:
        return sorted(self._by_label.values(), key=lambda row: str(row.get("term_id", "")))


def _collect_from_draft(
    draft: dict[str, Any],
    *,
    draft_kind: str,
    ingest_urls: dict[str, str],
    acc: _TermAccumulator,
) -> None:
    if draft_kind == "zone_page":
        zone_id = str(draft.get("zone_id", "")).strip()
        name = str(draft.get("name", "")).strip()
        wiki_url = str(draft.get("wiki_url", "")).strip() or ingest_urls.get(zone_id, "")
        if name:
            acc.add(
                label=name,
                category="place",
                wiki_url=wiki_url,
                source_entity_id=zone_id,
                source_entity_type="zone",
            )
        for card in draft.get("major_factions") or []:
            if not isinstance(card, dict):
                continue
            card_name = str(card.get("name", "")).strip()
            card_id = str(card.get("id", "")).strip()
            if card_name:
                acc.add(
                    label=card_name,
                    category="faction",
                    wiki_url=_card_wiki_url(card, card_id, ingest_urls),
                    source_entity_id=card_id,
                    source_entity_type="faction",
                )
        for card in draft.get("location_cards") or []:
            if not isinstance(card, dict):
                continue
            card_name = str(card.get("name", "")).strip()
            card_id = str(card.get("id", "")).strip()
            if card_name:
                acc.add(
                    label=card_name,
                    category="place",
                    wiki_url=_card_wiki_url(card, card_id, ingest_urls),
                    source_entity_id=card_id,
                    source_entity_type="location",
                )
        for card in draft.get("instance_links") or []:
            if not isinstance(card, dict):
                continue
            card_name = str(card.get("name", "")).strip()
            card_id = str(card.get("id", "")).strip()
            if card_name:
                acc.add(
                    label=card_name,
                    category="place",
                    wiki_url=ingest_urls.get(card_id, ""),
                    source_entity_id=card_id,
                    source_entity_type="instance",
                )
    elif draft_kind == "instance_page":
        instance_id = str(draft.get("instance_id", "")).strip()
        name = str(draft.get("name", "")).strip()
        wiki_url = str(draft.get("wiki_url", "")).strip() or ingest_urls.get(instance_id, "")
        if name:
            acc.add(
                label=name,
                category="place",
                wiki_url=wiki_url,
                source_entity_id=instance_id,
                source_entity_type="instance",
            )
        for card in draft.get("key_characters") or []:
            if not isinstance(card, dict):
                continue
            card_name = str(card.get("name", "")).strip()
            card_id = str(card.get("id", "")).strip()
            if card_name:
                acc.add(
                    label=card_name,
                    category="person",
                    wiki_url=ingest_urls.get(card_id, ""),
                    source_entity_id=card_id,
                    source_entity_type="character",
                )
        for card in draft.get("major_factions") or []:
            if not isinstance(card, dict):
                continue
            card_name = str(card.get("name", "")).strip()
            card_id = str(card.get("id", "")).strip()
            if card_name:
                acc.add(
                    label=card_name,
                    category="faction",
                    wiki_url=_card_wiki_url(card, card_id, ingest_urls),
                    source_entity_id=card_id,
                    source_entity_type="faction",
                )


def _collect_from_snapshots(
    snapshots: list[dict[str, Any]],
    acc: _TermAccumulator,
) -> None:
    """Add a term per fetched page, classified by category and aliased by infobox."""
    for snapshot in snapshots:
        name = str(snapshot.get("name", "")).strip()
        if not name:
            continue
        entity_type = str(snapshot.get("entity_type", "")).strip().lower()
        categories = snapshot.get("categories")
        category_list = categories if isinstance(categories, list) else []
        infobox = snapshot.get("infobox")
        infobox_map = infobox if isinstance(infobox, dict) else {}
        acc.add(
            label=name,
            category=_glossary_category(entity_type, category_list),
            wiki_url=str(snapshot.get("url", "")).strip(),
            source_entity_id=str(snapshot.get("entity_id", "")).strip(),
            source_entity_type=entity_type,
            extra_aliases=_aliases_from_infobox(infobox_map),
        )


def _is_harvestable_link(href: str, label: str) -> bool:
    """A seed page's outbound link is a glossary candidate when it is a real article
    link (not a File:/Category:/etc. namespace), carries a label, and is retail
    (no ``(Classic)``/expansion parenthetical)."""
    if not href or not label or len(label.strip()) < 2:
        return False
    title = href.split("/wiki/", 1)[-1].split("#", 1)[0]
    if not title:
        return False
    if label.strip().lower().startswith(_LINK_NAMESPACE_PREFIXES):
        return False
    if _is_abbreviation_shape(label):
        return False
    if is_non_retail_title(label) or is_non_retail_title(title.replace("_", " ")):
        return False
    return True


def _seed_link_category_from_cache(
    *,
    href: str,
    label: str,
    link_category_cache: dict[str, dict[str, Any]],
) -> str | None:
    """Return a glossary category from cached wiki category signals.

    ``None`` means the link should be skipped. ``"concept"`` means the cache did
    not provide a strong type, so the legacy seed-link behavior remains.
    """

    title = _title_from_href(href) or label
    entry = link_category_cache.get(_link_category_lookup_key(title))
    if not entry:
        return "concept"
    signal = entry.get("signal")
    if not isinstance(signal, dict):
        return "concept"
    disposition = str(signal.get("disposition", "")).strip()
    if disposition in {"strong_drop", "soft_drop"}:
        return None
    bucket = str(signal.get("bucket", "")).strip()
    if disposition in {"strong_include", "weak_include"} and bucket in _CATEGORY_SIGNAL_BUCKETS:
        return bucket
    return "concept"


def _collect_from_seed_links(
    snapshots: list[dict[str, Any]],
    acc: _TermAccumulator,
    *,
    link_category_cache: dict[str, dict[str, Any]],
) -> None:
    """Harvest the lore lexicon from the seed pages' outbound wiki links (RC-5).

    The zone/instance overview pages link to the lore proper-nouns that belong in the
    glossary (Scourge, Lordaeron, Kel'Thuzad, Plague of Undeath, ...). Earlier passes
    only emit terms for *entities the pipeline selected*, so this prose lexicon was
    missing. We harvest the seed pages' ``structured_links`` (which carry section roles
    and labels), skipping RPG (non-canon) sections, navbox/namespace links,
    non-retail titles, and links whose cached wiki categories classify them as
    noise. Strong cached category signals upgrade generic links into person,
    place, faction, event, or artifact terms.
    """
    for snapshot in snapshots:
        if str(snapshot.get("auxiliary_role", "")).strip():
            continue
        if str(snapshot.get("entity_type", "")).strip().lower() not in _SEED_ENTITY_TYPES:
            continue
        links = snapshot.get("structured_links")
        if not isinstance(links, list):
            continue
        for link in links:
            if not isinstance(link, dict):
                continue
            section_role = str(link.get("section_role", "")).lower()
            parent_role = str(link.get("parent_section_role", "")).lower()
            if section_role.startswith("in_the_rpg") or parent_role.startswith("in_the_rpg"):
                continue
            href = str(link.get("href", "")).strip()
            label = str(link.get("label", "")).strip()
            if not _is_harvestable_link(href, label):
                continue
            category = _seed_link_category_from_cache(
                href=href,
                label=label,
                link_category_cache=link_category_cache,
            )
            if category is None:
                continue
            absolute = (
                f"https://warcraft.wiki.gg{href}" if href.startswith("/wiki/") else href
            )
            acc.add(label=label, category=category, wiki_url=absolute)


def _collect_from_canonical_map(
    rows: list[dict[str, Any]],
    acc: _TermAccumulator,
) -> None:
    for row in rows:
        title = str(row.get("wiki_title", "")).strip()
        if not title:
            continue
        entity_type = str(row.get("entity_type", "")).strip().lower()
        entity_id = str(row.get("entity_id", "")).strip()
        wiki_url = str(row.get("wiki_url", "")).strip()
        acc.add(
            label=title,
            category=_category_for_entity_type(entity_type),
            wiki_url=wiki_url,
            source_entity_id=entity_id,
            source_entity_type=entity_type,
        )


def build_run_terms(context: RunContext) -> Path:
    """Generate data/glossary/run_terms.jsonl from drafts and discovery artifacts."""
    acc = _TermAccumulator()
    snapshots = _load_snapshots(context)
    link_category_cache = _load_link_category_cache(context)
    ingest_urls = _ingest_url_by_entity(snapshots)
    draft_root = context.data_dir / "drafts"

    for draft_dir_name in ("zone_page", "instance_page"):
        draft_dir = draft_root / draft_dir_name
        if not draft_dir.exists():
            continue
        for draft_path in sorted(draft_dir.glob("*.json")):
            draft = _load_json(draft_path)
            if isinstance(draft, dict):
                _collect_from_draft(
                    draft, draft_kind=draft_dir_name, ingest_urls=ingest_urls, acc=acc
                )

    _collect_from_snapshots(snapshots, acc)
    _collect_from_seed_links(snapshots, acc, link_category_cache=link_category_cache)

    canonical_path = context.data_dir / "discovery" / "canonical_entity_map.jsonl"
    _collect_from_canonical_map(_load_jsonl(canonical_path), acc)

    glossary_dir = context.data_dir / "glossary"
    glossary_dir.mkdir(parents=True, exist_ok=True)
    output_path = glossary_dir / "run_terms.jsonl"
    rows = acc.rows()
    output_path.write_text(
        "\n".join(json.dumps(row) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )
    return output_path


def load_run_terms(context: RunContext) -> list[dict[str, Any]]:
    path = context.data_dir / "glossary" / "run_terms.jsonl"
    return _load_jsonl(path)


def run_terms_to_alias_dictionary(terms: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Expand run terms into linker alias rows."""
    rows: list[dict[str, str]] = []
    for term in terms:
        term_id = str(term.get("term_id", "")).strip()
        label = str(term.get("label", "")).strip()
        category = str(term.get("category", "")).strip().lower()
        if not term_id or not label:
            continue
        aliases = term.get("aliases")
        alias_list = [label]
        if isinstance(aliases, list):
            for alias in aliases:
                text = str(alias).strip()
                if text and text.lower() != label.lower():
                    alias_list.append(text)
        seen: set[str] = set()
        for index, alias in enumerate(alias_list):
            norm = alias.lower()
            if norm in seen:
                continue
            seen.add(norm)
            rows.append(
                {
                    "term_id": term_id,
                    "alias": alias if index == 0 else alias,
                    "alias_type": "canonical" if index == 0 else "exact_synonym",
                    "case_rule": "insensitive",
                    "category": category,
                }
            )
    return rows


def run_terms_metadata_map(terms: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    metadata: dict[str, dict[str, str]] = {}
    for term in terms:
        term_id = str(term.get("term_id", "")).strip()
        label = str(term.get("label", "")).strip()
        if not term_id:
            continue
        metadata[term_id] = {
            "term_id": term_id,
            "label": label or term_id,
            "wiki_url": str(term.get("wiki_url", "")).strip() or _wiki_url(label),
            "category": str(term.get("category", "")).strip().lower(),
        }
    return metadata
