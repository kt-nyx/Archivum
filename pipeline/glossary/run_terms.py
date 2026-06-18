"""Build run-scoped glossary terms from wiki-first drafts and discovery artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pipeline.common.io import read_json
from pipeline.common.run_context import RunContext
from pipeline.common.text_ids import slugify

WIKI_BASE = "https://warcraft.wiki.gg/wiki"

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


def _category_for_entity_type(entity_type: str) -> str:
    return _ENTITY_CATEGORY.get(entity_type.strip().lower(), "concept")


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


def _ingest_url_by_entity(context: RunContext) -> dict[str, str]:
    urls: dict[str, str] = {}
    snapshots_path = context.data_dir / "ingest" / "source_snapshots.json"
    if not snapshots_path.exists():
        return urls
    blob = _load_json(snapshots_path)
    if not isinstance(blob, list):
        return urls
    for snapshot in blob:
        if not isinstance(snapshot, dict):
            continue
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
        norm = _normalize_alias(cleaned)
        if not norm:
            return
        url = _wiki_url(cleaned, wiki_url)
        aliases = {_normalize_alias(cleaned)}
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
            return
        base_slug = _term_slug(cleaned)
        term_id = f"term-{base_slug}"
        suffix = 2
        while term_id in self._term_ids:
            term_id = f"term-{base_slug}-{suffix}"
            suffix += 1
        self._term_ids.add(term_id)
        self._by_label[norm] = {
            "term_id": term_id,
            "label": cleaned,
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
    ingest_urls = _ingest_url_by_entity(context)
    draft_root = context.data_dir / "drafts"

    for draft_dir_name in ("zone_page", "instance_page"):
        draft_dir = draft_root / draft_dir_name
        if not draft_dir.exists():
            continue
        for draft_path in sorted(draft_dir.glob("*.json")):
            draft = _load_json(draft_path)
            if isinstance(draft, dict):
                _collect_from_draft(draft, draft_kind=draft_dir_name, ingest_urls=ingest_urls, acc=acc)

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
