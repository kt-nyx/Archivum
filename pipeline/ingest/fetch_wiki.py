"""Ingest source snapshot fetch stage.

Supported MediaWiki manifest classes (see ``_MEDIAWIKI_PARSE_SOURCE_CLASSES``) use
canonical ``/wiki/Title`` article URLs resolved to ``api.php?action=parse`` for
stable, policy-aligned retrieval; other URL shapes fall back to direct HTML fetch.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, NotRequired, TypedDict
from urllib.parse import parse_qsl, unquote, urlencode, urlparse, urlunparse

import httpx
from jsonschema import Draft202012Validator

from pipeline.common import http, wiki_html
from pipeline.common.io import write_json
from pipeline.common.run_context import RunContext
from pipeline.common.text_ids import slugify
from pipeline.ingest.retrieval_profiles import RetrievalProfile, profile_for_source_class

_INGEST_USER_AGENT = "wow-lore-ingest/1.0"

# Ingest via MediaWiki action=parse (api.php) for these manifest source_class values.
# Extend when adding another MediaWiki-backed farm; non-MediaWiki wikis need a separate adapter.
_MEDIAWIKI_PARSE_SOURCE_CLASSES: frozenset[str] = frozenset({"warcraft_wiki"})

REVISION_RE = re.compile(r'"wgRevisionId"\s*:\s*([0-9]+)')
_PARSE_HTML_CAP = 524288


def _cap_parse_html(html: str) -> str:
    if not html:
        return ""
    if len(html) <= _PARSE_HTML_CAP:
        return html
    return html[:_PARSE_HTML_CAP]


@dataclass
class FetchedSource:
    """Parsed result of fetching one wiki source (MediaWiki parse API or HTML fallback)."""

    body: str
    revision_id: str
    locator: str
    section_blocks: list[dict[str, str]]
    wiki_links: list[str]
    structured_links: list[dict[str, str]]
    html: str
    parse_tree: str = ""
    categories: list[str] = field(default_factory=list)


def _categories_from_parse_blob(parse_blob: dict[str, Any]) -> list[str]:
    """Extract category names from a MediaWiki parse payload (formatversion 2 or legacy)."""
    raw = parse_blob.get("categories")
    names: list[str] = []
    if not isinstance(raw, list):
        return names
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("category") or entry.get("*") or "").replace("_", " ").strip()
        if name and name not in names:
            names.append(name)
    return names


def _category_lookup_key(title: str) -> str:
    """Normalize a page title/path for category-map lookup (spaces, casefold)."""
    return str(title or "").replace("_", " ").strip().casefold()


def fetch_categories_for_titles(
    titles: Iterable[str],
    *,
    source_class: str = "warcraft_wiki",
    origin: str = "https://warcraft.wiki.gg",
    batch_size: int = 20,
    retries: int = 0,
) -> dict[str, list[str]]:
    """Return ``{lookup_key -> [category names]}`` for many wiki titles in batches.

    Uses MediaWiki ``action=query&prop=categories`` (the authoritative retail-eligibility
    signal for S3). Title normalization and redirects are resolved so a requested title
    maps to its canonical page's categories. ``retries=0`` by default so an offline caller
    fails fast; callers should treat any raised error as "no category data".
    """
    profile = profile_for_source_class(source_class)
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw_title in titles:
        title = str(raw_title or "").replace("_", " ").strip()
        key = title.casefold()
        if title and key not in seen:
            seen.add(key)
            cleaned.append(title)

    result: dict[str, list[str]] = {}
    for start in range(0, len(cleaned), batch_size):
        batch = cleaned[start : start + batch_size]
        params = {
            "action": "query",
            "prop": "categories",
            "cllimit": "max",
            "redirects": "1",
            "titles": "|".join(batch),
            "formatversion": "2",
            "format": "json",
        }
        api_url = f"{origin}/api.php?{urlencode(params)}"
        raw = http.get_text(
            api_url,
            headers={"User-Agent": _INGEST_USER_AGENT},
            timeout=profile.timeout_seconds,
            retries=retries,
            backoff_base=profile.retry_backoff_seconds,
        )
        data = json.loads(raw)
        query = data.get("query")
        if not isinstance(query, dict):
            continue
        # from -> to aliasing across both normalization and redirect hops.
        alias: dict[str, str] = {}
        for row in (query.get("normalized") or []) + (query.get("redirects") or []):
            if isinstance(row, dict) and row.get("from"):
                alias[_category_lookup_key(str(row.get("from")))] = str(row.get("to") or "")
        cats_by_title: dict[str, list[str]] = {}
        for page in query.get("pages") or []:
            if not isinstance(page, dict):
                continue
            names = []
            for entry in page.get("categories") or []:
                if not isinstance(entry, dict):
                    continue
                name = str(entry.get("title") or entry.get("*") or "")
                name = name.split(":", 1)[-1].replace("_", " ").strip()
                if name:
                    names.append(name)
            cats_by_title[_category_lookup_key(str(page.get("title") or ""))] = names
        for original in batch:
            key = _category_lookup_key(original)
            target = key
            for _ in range(3):  # follow normalization -> redirect chain
                nxt = alias.get(target)
                if not nxt:
                    break
                target = _category_lookup_key(nxt)
            result[key] = cats_by_title.get(target, cats_by_title.get(key, []))
    return result


def fetch_wiki_html(url: str, source_class: str) -> str:
    """Return raw parse HTML for a wiki URL (empty when unavailable)."""
    try:
        return _fetch_url_text(url, source_class).html
    except RuntimeError:
        return ""


class SourceSnapshot(TypedDict):
    entity_id: str
    entity_type: str
    slug: str
    name: str
    source_id: str
    source_class: str
    url: str
    revision_id: str
    captured_at: str
    locator: str
    body: str
    section_blocks: list[dict[str, str]]
    wiki_links: list[str]
    structured_links: list[dict[str, str]]
    categories: list[str]
    infobox: dict[str, str]
    retrieval_mode: str
    selection_version: str
    policy_version: str
    manifest_run_id: str
    parent_zone_id: str
    requested_revision_id: str
    priority: int
    # Set only for storyline pages (see the auxiliary-role snapshot enrichment below).
    auxiliary_role: NotRequired[str]
    auxiliary_target_id: NotRequired[str]
    parse_html: NotRequired[str]
    parse_html_truncated: NotRequired[bool]


class ValidatedManifestRow(TypedDict):
    entity_id: str
    entity_type: str
    slug: str
    name: str
    source_id: str
    source_url: str
    source_class: str
    selection_version: str
    policy_version: str
    manifest_run_id: str
    parent_zone_id: str
    requested_revision_id: str
    priority: int


def _fallback_priority(row_index: int) -> int:
    """Return deterministic fallback priority within contract range 1..10.

    Row-order modulo 10 is used intentionally, so rows 11+ collide with earlier
    priority buckets while remaining stable across runs.
    """
    return ((row_index - 1) % 10) + 1


def _load_manifest(context: RunContext) -> list[dict[str, Any]]:
    manifest_path = context.root_dir / "source_manifest.json"
    if not manifest_path.exists():
        raise RuntimeError(
            "missing ingest manifest at run root: expected source_manifest.json "
            f"at '{manifest_path}'"
        )
    blob = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(blob, list):
        raise RuntimeError("source_manifest.json must be a JSON array")
    for index, row in enumerate(blob, start=1):
        if not isinstance(row, dict):
            raise RuntimeError(f"source_manifest.json row {index} is not an object")
    _validate_manifest_schema(blob)
    return blob


def _manifest_schema_path() -> Path:
    return Path(__file__).with_name("source_manifest.schema.json")


def _validate_manifest_schema(rows: list[dict[str, Any]]) -> None:
    schema_path = _manifest_schema_path()
    if not schema_path.exists():
        return
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(rows), key=lambda err: list(err.path))
    if not errors:
        return
    first_error = errors[0]
    path_tokens = [str(token) for token in first_error.absolute_path]
    path = "$" if not path_tokens else "$." + ".".join(path_tokens)
    raise RuntimeError(f"source_manifest.json schema error at {path}: {first_error.message}")


def _validate_manifest_row(row: dict[str, Any], index: int) -> ValidatedManifestRow:
    required_fields = (
        "entity_id",
        "entity_type",
        "slug",
        "name",
        "source_id",
        "source_url",
        "source_class",
        "selection_version",
        "policy_version",
        "manifest_run_id",
    )
    missing = [field for field in required_fields if not str(row.get(field, "")).strip()]
    if missing:
        raise RuntimeError(f"manifest row {index} missing required fields: {', '.join(missing)}")
    entity_type = str(row["entity_type"]).strip()
    if entity_type not in {"zone", "sub_zone", "instance", "character", "glossary_term", "asset"}:
        raise RuntimeError(f"manifest row {index} has unsupported entity_type '{entity_type}'")
    source_class = str(row["source_class"]).strip()
    if source_class != "warcraft_wiki":
        raise RuntimeError(
            f"manifest row {index} has unsupported source_class '{source_class}' "
            "(only warcraft_wiki is allowed)"
        )
    parent_zone_id = str(row.get("parent_zone_id", "")).strip()
    if entity_type == "instance" and not parent_zone_id:
        raise RuntimeError(
            f"manifest row {index} for instance entity requires non-empty parent_zone_id"
        )
    priority = row.get("priority")
    normalized_priority: int | None = None
    if isinstance(priority, int):
        normalized_priority = priority
    elif isinstance(priority, str) and priority.isdigit():
        normalized_priority = int(priority)
    if normalized_priority is not None and not 1 <= normalized_priority <= 10:
        normalized_priority = None

    return {
        "entity_id": str(row["entity_id"]).strip(),
        "entity_type": entity_type,
        "slug": str(row["slug"]).strip(),
        "name": str(row["name"]).strip(),
        "source_id": str(row["source_id"]).strip(),
        "source_url": str(row["source_url"]).strip(),
        "source_class": source_class,
        "selection_version": str(row["selection_version"]).strip(),
        "policy_version": str(row["policy_version"]).strip(),
        "manifest_run_id": str(row["manifest_run_id"]).strip(),
        "parent_zone_id": parent_zone_id,
        "requested_revision_id": str(
            row.get("revision_id", row.get("requested_revision_id", ""))
        ).strip(),
        "priority": (
            normalized_priority if normalized_priority is not None else _fallback_priority(index)
        ),
    }


def _normalize_locator_section(value: str) -> str:
    return slugify(value, separator="_") or "lead"


def _extract_main_text(html: str, *, max_chars: int) -> tuple[str, str]:
    first_locator = "section:lead paragraph:1"
    current_section = "lead"
    paragraph_index_by_section: dict[str, int] = {"lead": 0}
    for block in wiki_html.iter_tagged_text(html, ("h1", "h2", "h3", "h4", "h5", "h6", "p")):
        cleaned = block["text"]
        if not cleaned:
            continue
        if block["tag"].startswith("h"):
            current_section = _normalize_locator_section(cleaned)
            paragraph_index_by_section.setdefault(current_section, 0)
            continue
        paragraph_index_by_section[current_section] = (
            paragraph_index_by_section.get(current_section, 0) + 1
        )
        if first_locator == "section:lead paragraph:1":
            first_locator = (
                f"section:{current_section} paragraph:{paragraph_index_by_section[current_section]}"
            )
            break
    cleaned_chunks = wiki_html.paragraph_texts(html)
    if not cleaned_chunks:
        cleaned_chunks = [wiki_html.strip_tags(html)]
    text = "\n".join(cleaned_chunks)
    return text[:max_chars], first_locator


def _wiki_href_label(href: str) -> str:
    return unquote(href.split("/wiki/", 1)[-1].split("#", 1)[0]).replace("_", " ")


def build_structured_links_from_sections(
    section_blocks: list[dict[str, str]],
    wiki_links: list[str],
) -> list[dict[str, str]]:
    """Attach section context to wiki links when href appears in section text.

    A link can legitimately live in several sections (e.g. a boss named in the
    lead collapsible, the dungeon-denizens table, and a narrative paragraph). We
    emit one entry per distinct (href, section_role) pair so downstream consumers
    can pick the role they care about: the roster collector keeps entries whose
    role is roster-relevant even when an earlier narrative section also mentions
    the link. Links matched by no section fall back to a single "other" entry.
    """
    structured: list[dict[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()
    matched: set[str] = set()
    for block in section_blocks:
        section_role = str(block.get("section_role", "other"))
        parent_section_role = str(block.get("parent_section_role", ""))
        text_lower = str(block.get("text", "")).lower()
        if not text_lower:
            continue
        compact_text = text_lower.replace(" ", "")
        for href in wiki_links:
            pair = (href, section_role)
            if pair in seen_pairs:
                continue
            title = href.split("/wiki/", 1)[-1].split("#", 1)[0].replace("_", " ").lower()
            if not title:
                continue
            if title in text_lower or title.replace(" ", "") in compact_text:
                seen_pairs.add(pair)
                matched.add(href)
                entry = {
                    "href": href,
                    "section_role": section_role,
                    "label": _wiki_href_label(href),
                }
                if parent_section_role:
                    entry["parent_section_role"] = parent_section_role
                structured.append(entry)
    for href in wiki_links:
        if href in matched:
            continue
        structured.append({"href": href, "section_role": "other", "label": _wiki_href_label(href)})
        matched.add(href)
    return structured


def _heading_level(tag_name: str) -> int:
    lowered = tag_name.lower()
    if len(lowered) == 2 and lowered[0] == "h" and lowered[1].isdigit():
        return int(lowered[1])
    return 6


def _apply_rpg_section_prefix(section: str, *, in_rpg: bool) -> str:
    if not in_rpg:
        return section
    if section.startswith("in_the_rpg"):
        return section
    return f"in_the_rpg_{section}"


_BLOCK_TYPE_BY_TAG = {"p": "paragraph", "li": "list_item", "td": "table_cell", "th": "table_cell"}


def _extract_sections_and_links(
    html: str, *, max_links: int = 300
) -> tuple[list[dict[str, str]], list[str], list[dict[str, str]]]:
    sections: list[dict[str, str]] = []
    current_section = "lead"
    current_top_section = "lead"
    in_rpg = False
    # wiki_html.content_blocks drops chrome tables and folds nested blocks into their
    # ancestor, mirroring the previous regex section walk.
    for block in wiki_html.content_blocks(html):
        tag = block["tag"]
        cleaned = block["text"]
        if tag.startswith("h"):
            if not cleaned:
                continue
            heading_level = _heading_level(tag)
            # Parse-API fragments have no <h1> page title; ignore stray level-1
            # headings so they never override the lead section.
            if heading_level == 1:
                continue
            normalized = _normalize_locator_section(cleaned)
            if heading_level <= 2:
                in_rpg = normalized in {"in_the_rpg", "in_the_rpg_edit"}
                current_section = normalized
                current_top_section = current_section
            elif in_rpg:
                current_section = _apply_rpg_section_prefix(normalized, in_rpg=True)
            else:
                current_section = normalized
            continue
        if not cleaned:
            continue
        section_role = _apply_rpg_section_prefix(current_section, in_rpg=in_rpg)
        parent_section_role = _apply_rpg_section_prefix(current_top_section, in_rpg=in_rpg)
        sections.append(
            {
                "section_role": section_role,
                "parent_section_role": parent_section_role,
                "text": cleaned,
                "block_type": _BLOCK_TYPE_BY_TAG[tag],
            }
        )
    links = wiki_html.extract_links(html, max_links=max_links)
    structured = build_structured_links_from_sections(sections, links)
    return sections, links, structured


def _mediawiki_parse_ingest_eligible(url: str, source_class: str) -> bool:
    """True when this source uses MediaWiki parse API (allowed class + /wiki/ path)."""
    normalized = source_class.strip().lower()
    if normalized not in _MEDIAWIKI_PARSE_SOURCE_CLASSES:
        return False
    path = urlparse(url).path
    return path.startswith("/wiki/")


def _fetch_mediawiki_via_parse_api(
    url: str, profile: RetrievalProfile, *, include_parsetree: bool = False
) -> FetchedSource:
    """Fetch article HTML via MediaWiki api.php action=parse (returns stable revid).

    Always requests ``prop=...|categories``; when ``include_parsetree`` is set also
    requests ``prop=parsetree`` (only the quest-traversal path opts in).
    """
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    wiki_prefix = "/wiki/"
    if not parsed.path.startswith(wiki_prefix):
        raise RuntimeError(
            f"mediawiki ingest expected article path starting with {wiki_prefix!r}, got {url!r}"
        )
    title = unquote(parsed.path[len(wiki_prefix) :])
    if not title.strip():
        raise RuntimeError(f"mediawiki ingest missing page title in url {url!r}")

    query_pairs = dict(parse_qsl(parsed.query, keep_blank_values=True))
    oldid = str(query_pairs.get("oldid", "")).strip()

    params: dict[str, str] = {
        "action": "parse",
        "prop": "text|revid|categories|parsetree" if include_parsetree else "text|revid|categories",
        "formatversion": "2",
        "format": "json",
    }
    if oldid:
        if not oldid.isdigit():
            raise RuntimeError(f"mediawiki ingest oldid must be numeric, got {oldid!r}")
        params["oldid"] = oldid
    else:
        params["page"] = title

    api_url = f"{origin}/api.php?{urlencode(params)}"
    raw = http.get_text(
        api_url,
        headers={"User-Agent": _INGEST_USER_AGENT},
        timeout=profile.timeout_seconds,
        retries=profile.retries,
        backoff_base=profile.retry_backoff_seconds,
    )
    data = json.loads(raw)
    if "error" in data:
        err = data["error"]
        code = err.get("code", "unknown")
        info = err.get("info", str(err))
        raise RuntimeError(f"MediaWiki API error {code}: {info}")
    parse_blob = data.get("parse")
    if not isinstance(parse_blob, dict):
        raise RuntimeError("MediaWiki API returned no parse payload")
    html = parse_blob.get("text") or ""
    if not str(html).strip():
        raise RuntimeError("MediaWiki API returned empty parse text")
    html_str = str(html)
    revid = parse_blob.get("revid")
    if revid is None:
        revision_id = "sha256:" + sha256(html_str.encode("utf-8")).hexdigest()[:16]
    else:
        revision_id = f"mw:{int(revid)}"
    body, locator = _extract_main_text(html_str, max_chars=profile.max_chars)
    sections, links, structured = _extract_sections_and_links(html_str)
    categories = _categories_from_parse_blob(parse_blob)
    parse_tree = ""
    if include_parsetree:
        raw_tree = parse_blob.get("parsetree")
        if isinstance(raw_tree, dict):
            parse_tree = str(raw_tree.get("*", ""))
        elif raw_tree is not None:
            parse_tree = str(raw_tree)
    return FetchedSource(
        body=body,
        revision_id=revision_id,
        locator=locator,
        section_blocks=sections,
        wiki_links=links,
        structured_links=structured,
        html=html_str,
        parse_tree=parse_tree,
        categories=categories,
    )


def _fetch_url_text(
    url: str, source_class: str, *, include_parsetree: bool = False
) -> FetchedSource:
    profile = profile_for_source_class(source_class)
    use_parse_api = _mediawiki_parse_ingest_eligible(url, source_class)
    # Transient transport/timeout/HTTP-status errors are retried inside http.get_text
    # (exponential backoff). MediaWiki "API error"/"empty parse" RuntimeErrors are not
    # retried and propagate unchanged.
    try:
        if use_parse_api:
            return _fetch_mediawiki_via_parse_api(url, profile, include_parsetree=include_parsetree)
        html = http.get_text(
            url,
            headers={"User-Agent": _INGEST_USER_AGENT},
            timeout=profile.timeout_seconds,
            retries=profile.retries,
            backoff_base=profile.retry_backoff_seconds,
        )
        body, locator = _extract_main_text(html, max_chars=profile.max_chars)
        sections, links, structured = _extract_sections_and_links(html)
        revision_match = REVISION_RE.search(html)
        if revision_match:
            revision_id = f"mw:{revision_match.group(1)}"
        else:
            revision_id = "sha256:" + sha256(html.encode("utf-8")).hexdigest()[:16]
        # Non-MediaWiki/HTML fallback has no parse-API categories or parse tree.
        return FetchedSource(
            body=body,
            revision_id=revision_id,
            locator=locator,
            section_blocks=sections,
            wiki_links=links,
            structured_links=structured,
            html=html,
        )
    except (httpx.HTTPError, ValueError) as exc:
        raise RuntimeError(f"unable to fetch source url '{url}': {exc!r}") from exc


def _build_revision_pinned_url(url: str, requested_revision_id: str) -> str:
    revision = requested_revision_id.strip()
    if not revision:
        return url
    if revision.startswith("mw:"):
        revision = revision.split(":", 1)[1]
    if not revision.isdigit():
        return url
    parsed = urlparse(url)
    query_pairs = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)]
    query_without_oldid = [(key, value) for key, value in query_pairs if key.lower() != "oldid"]
    query_without_oldid.append(("oldid", revision))
    updated_query = urlencode(query_without_oldid, doseq=True)
    return urlunparse(parsed._replace(query=updated_query))


def run_fetch_wiki(context: RunContext) -> Path:
    """Fetch source snapshots from manifest-driven wiki URLs."""
    manifest_rows = _load_manifest(context)
    captured_at = datetime.now(UTC).isoformat()
    snapshots: list[SourceSnapshot] = []
    raw_dir = context.data_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    for index, raw_row in enumerate(manifest_rows, start=1):
        row = _validate_manifest_row(raw_row, index)
        source_id = row["source_id"]
        requested_revision_id = row["requested_revision_id"]
        url = _build_revision_pinned_url(row["source_url"], requested_revision_id)
        source_class = row["source_class"]
        fetched = _fetch_url_text(url, source_class)
        body = fetched.body
        revision_id = fetched.revision_id
        locator = fetched.locator
        section_blocks = fetched.section_blocks
        wiki_links = fetched.wiki_links
        structured_links = fetched.structured_links
        raw_html = fetched.html
        if requested_revision_id and revision_id.startswith("mw:"):
            normalized_requested = requested_revision_id
            if not normalized_requested.startswith("mw:"):
                normalized_requested = f"mw:{normalized_requested}"
            if normalized_requested != revision_id:
                raise RuntimeError(
                    f"manifest row {index} expected revision '{normalized_requested}' "
                    f"but fetched '{revision_id}'"
                )

        snapshot: SourceSnapshot = {
            "entity_id": row["entity_id"],
            "entity_type": row["entity_type"],
            "slug": row["slug"],
            "name": row["name"],
            "source_id": source_id,
            "source_class": source_class,
            "url": url,
            "revision_id": revision_id,
            "captured_at": captured_at,
            "locator": locator,
            "body": body,
            "section_blocks": section_blocks,
            "wiki_links": wiki_links,
            "structured_links": structured_links,
            "categories": fetched.categories,
            "infobox": wiki_html.parse_infobox(raw_html),
            "retrieval_mode": "revision-pinned" if requested_revision_id else "live",
            "selection_version": row["selection_version"],
            "policy_version": row["policy_version"],
            "manifest_run_id": row["manifest_run_id"],
            "parent_zone_id": row["parent_zone_id"],
            "requested_revision_id": requested_revision_id,
            "priority": int(row["priority"]),
        }
        if "_storyline" in url.lower() and raw_html.strip():
            snapshot["auxiliary_role"] = "storyline"
            snapshot["auxiliary_target_id"] = f"storyline-{row['slug']}"
            snapshot["parse_html"] = raw_html[:524288]
            if len(raw_html) > 524288:
                snapshot["parse_html_truncated"] = True
        snapshots.append(snapshot)

    stage_dir = context.stage_dir("ingest")
    output_path = stage_dir / "source_snapshots.json"
    write_json(output_path, snapshots)
    raw_ndjson_path = raw_dir / "source_snapshots.ndjson"
    raw_ndjson_path.write_text(
        "\n".join(json.dumps(snapshot) for snapshot in snapshots) + "\n",
        encoding="utf-8",
    )
    return output_path
