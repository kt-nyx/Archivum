"""Ingest source snapshot fetch stage.

Supported MediaWiki manifest classes (see ``_MEDIAWIKI_PARSE_SOURCE_CLASSES``) use
canonical ``/wiki/Title`` article URLs resolved to ``api.php?action=parse`` for
stable, policy-aligned retrieval; other URL shapes fall back to direct HTML fetch.
"""

from __future__ import annotations

import json
import re
import time
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, TypedDict
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, unquote, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

from jsonschema import Draft202012Validator

from pipeline.common.run_context import RunContext
from pipeline.ingest.retrieval_profiles import RetrievalProfile, profile_for_source_class

_INGEST_USER_AGENT = "wow-lore-ingest/1.0"

# Ingest via MediaWiki action=parse (api.php) for these manifest source_class values.
# Extend when adding another MediaWiki-backed farm; non-MediaWiki wikis need a separate adapter.
_MEDIAWIKI_PARSE_SOURCE_CLASSES: frozenset[str] = frozenset({"warcraft_wiki"})

PARAGRAPH_RE = re.compile(r"<p[^>]*>(.*?)</p>", re.IGNORECASE | re.DOTALL)
BLOCK_RE = re.compile(r"<(h[1-6]|p)[^>]*>(.*?)</\1>", re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")
HREF_RE = re.compile(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
REVISION_RE = re.compile(r'"wgRevisionId"\s*:\s*([0-9]+)')
_PARSE_HTML_CAP = 524288

# Document-order content elements used for section_blocks. Headings update the
# current section; paragraphs, list items, and content-table cells become blocks.
# Lists/tables matter because Warcraft Wiki rosters (bosses, dungeon denizens,
# encounters) are authored as <ul>/<li> and <table> rows, not <p> prose.
SECTION_BLOCK_RE = re.compile(
    r"<(?P<h>h[1-6])\b[^>]*>(?P<htext>.*?)</(?P=h)>"
    r"|<p\b[^>]*>(?P<ptext>.*?)</p>"
    r"|<li\b[^>]*>(?P<litext>.*?)</li>"
    r"|<t(?P<cell>[dh])\b[^>]*>(?P<celltext>.*?)</t(?P=cell)>",
    re.IGNORECASE | re.DOTALL,
)
_TABLE_OPEN_RE = re.compile(r"<table\b[^>]*>", re.IGNORECASE)
_TABLE_TOKEN_RE = re.compile(r"<table\b|</table\s*>", re.IGNORECASE)
_TABLE_CLASS_RE = re.compile(r'class\s*=\s*"([^"]*)"', re.IGNORECASE)
# Chrome tables (infoboxes, navboxes, ToCs, message boxes) carry navigation and
# metadata, not roster content; capturing their cells would pollute the lead and
# section blocks, so they are removed before the section walk.
_EXCLUDED_TABLE_CLASS_TOKENS = (
    "infobox",
    "navbox",
    "toc",
    "metadata",
    "mbox",
    "noprint",
    "navigation",
)


def _cap_parse_html(html: str) -> str:
    if not html:
        return ""
    if len(html) <= _PARSE_HTML_CAP:
        return html
    return html[:_PARSE_HTML_CAP]


def fetch_wiki_html(url: str, source_class: str) -> str:
    """Return raw parse HTML for a wiki URL (empty when unavailable)."""
    try:
        result = _fetch_url_text(url, source_class)
        if len(result) >= 7:
            return str(result[6])
    except RuntimeError:
        return ""
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
    retrieval_mode: str
    selection_version: str
    policy_version: str
    manifest_run_id: str
    parent_zone_id: str
    requested_revision_id: str
    priority: int


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
            normalized_priority
            if normalized_priority is not None
            else _fallback_priority(index)
        ),
    }


def _normalize_locator_section(value: str) -> str:
    section = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return section or "lead"


def _extract_main_text(html: str, *, max_chars: int) -> tuple[str, str]:
    paragraphs = PARAGRAPH_RE.findall(html)
    cleaned_chunks: list[str] = []
    first_locator = "section:lead paragraph:1"
    current_section = "lead"
    paragraph_index_by_section: dict[str, int] = {"lead": 0}
    for tag_name, raw_value in BLOCK_RE.findall(html):
        cleaned = " ".join(TAG_RE.sub(" ", raw_value).split())
        if not cleaned:
            continue
        if tag_name.lower().startswith("h"):
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
    for paragraph in paragraphs:
        stripped = TAG_RE.sub(" ", paragraph)
        collapsed = " ".join(stripped.split())
        if collapsed:
            cleaned_chunks.append(collapsed)
    if not cleaned_chunks:
        fallback = TAG_RE.sub(" ", html)
        cleaned_chunks = [" ".join(fallback.split())]
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


def _is_excluded_table(open_tag: str) -> bool:
    """True for navigation/metadata tables (infobox, navbox, toc, ...) we drop."""
    class_match = _TABLE_CLASS_RE.search(open_tag)
    if not class_match:
        return False
    classes = class_match.group(1).lower()
    return any(token in classes for token in _EXCLUDED_TABLE_CLASS_TOKENS)


def _find_table_end(html: str, start: int) -> int:
    """Return index past the </table> matching the <table> at ``start`` (nesting-aware)."""
    depth = 0
    for token in _TABLE_TOKEN_RE.finditer(html, start):
        if token.group(0).lower().startswith("</"):
            depth -= 1
            if depth <= 0:
                return token.end()
        else:
            depth += 1
    return len(html)


def _strip_excluded_tables(html: str) -> str:
    """Remove chrome tables (and their nested content) before the section walk."""
    out: list[str] = []
    index = 0
    while True:
        match = _TABLE_OPEN_RE.search(html, index)
        if not match:
            out.append(html[index:])
            break
        out.append(html[index : match.start()])
        end = _find_table_end(html, match.start())
        if not _is_excluded_table(match.group(0)):
            out.append(html[match.start() : end])
        index = end
    return "".join(out)


def _extract_sections_and_links(
    html: str, *, max_links: int = 300
) -> tuple[list[dict[str, str]], list[str], list[dict[str, str]]]:
    sections: list[dict[str, str]] = []
    links: list[str] = []
    current_section = "lead"
    current_top_section = "lead"
    in_rpg = False
    walk_html = _strip_excluded_tables(html)
    for match in SECTION_BLOCK_RE.finditer(walk_html):
        heading_tag = match.group("h")
        if heading_tag is not None:
            cleaned = " ".join(TAG_RE.sub(" ", match.group("htext") or "").split())
            if not cleaned:
                continue
            heading_level = _heading_level(heading_tag)
            # Parse-API fragments have no <h1> page title; ignore stray level-1
            # headings so they never override the lead section.
            if heading_level == 1:
                continue
            normalized = _normalize_locator_section(cleaned)
            if heading_level <= 2:
                if normalized in {"in_the_rpg", "in_the_rpg_edit"}:
                    in_rpg = True
                    current_section = normalized
                else:
                    in_rpg = False
                    current_section = normalized
                current_top_section = current_section
            elif in_rpg:
                current_section = _apply_rpg_section_prefix(normalized, in_rpg=True)
            else:
                current_section = normalized
            continue
        if match.group("ptext") is not None:
            raw_value = match.group("ptext")
            block_type = "paragraph"
        elif match.group("litext") is not None:
            raw_value = match.group("litext")
            block_type = "list_item"
        else:
            raw_value = match.group("celltext")
            block_type = "table_cell"
        cleaned = " ".join(TAG_RE.sub(" ", raw_value or "").split())
        if not cleaned:
            continue
        section_role = _apply_rpg_section_prefix(current_section, in_rpg=in_rpg)
        parent_section_role = _apply_rpg_section_prefix(current_top_section, in_rpg=in_rpg)
        sections.append(
            {
                "section_role": section_role,
                "parent_section_role": parent_section_role,
                "text": cleaned,
                "block_type": block_type,
            }
        )
    for href, label_raw in HREF_RE.findall(html):
        href_value = href.strip()
        if not href_value:
            continue
        if href_value.startswith("/wiki/"):
            links.append(href_value)
        elif "warcraft.wiki.gg/wiki/" in href_value:
            links.append(href_value)
        if len(links) >= max_links:
            break
    deduped_links = list(dict.fromkeys(links))
    structured = build_structured_links_from_sections(sections, deduped_links)
    return sections, deduped_links, structured


def _mediawiki_parse_ingest_eligible(url: str, source_class: str) -> bool:
    """True when this source uses MediaWiki parse API (allowed class + /wiki/ path)."""
    normalized = source_class.strip().lower()
    if normalized not in _MEDIAWIKI_PARSE_SOURCE_CLASSES:
        return False
    path = urlparse(url).path
    return path.startswith("/wiki/")


def _fetch_mediawiki_via_parse_api(
    url: str, profile: RetrievalProfile, *, include_parsetree: bool = False
) -> tuple[Any, ...]:
    """Fetch article HTML via MediaWiki api.php action=parse (returns stable revid).

    When ``include_parsetree`` is set, also request ``prop=parsetree`` and append
    the parse-tree XML string as an 8th tuple element. Only the quest-traversal
    path opts in, so other callers keep the historical 7-tuple shape.
    """
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    wiki_prefix = "/wiki/"
    if not parsed.path.startswith(wiki_prefix):
        raise RuntimeError(
            "mediawiki ingest expected article path starting with "
            f"{wiki_prefix!r}, got {url!r}"
        )
    title = unquote(parsed.path[len(wiki_prefix) :])
    if not title.strip():
        raise RuntimeError(f"mediawiki ingest missing page title in url {url!r}")

    query_pairs = dict(parse_qsl(parsed.query, keep_blank_values=True))
    oldid = str(query_pairs.get("oldid", "")).strip()

    params: dict[str, str] = {
        "action": "parse",
        "prop": "text|revid|parsetree" if include_parsetree else "text|revid",
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
    request = Request(api_url, headers={"User-Agent": _INGEST_USER_AGENT})
    with urlopen(request, timeout=profile.timeout_seconds) as response:  # noqa: S310
        raw = response.read().decode("utf-8", errors="replace")
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
    if include_parsetree:
        raw_tree = parse_blob.get("parsetree")
        if isinstance(raw_tree, dict):
            parse_tree = str(raw_tree.get("*", ""))
        elif raw_tree is not None:
            parse_tree = str(raw_tree)
        else:
            parse_tree = ""
        return body, revision_id, locator, sections, links, structured, html_str, parse_tree
    return body, revision_id, locator, sections, links, structured, html_str


def _fetch_url_text(
    url: str, source_class: str, *, include_parsetree: bool = False
) -> tuple[Any, ...]:
    profile = profile_for_source_class(source_class)
    last_error: Exception | None = None
    use_parse_api = _mediawiki_parse_ingest_eligible(url, source_class)
    for attempt in range(profile.retries + 1):
        try:
            if use_parse_api:
                return _fetch_mediawiki_via_parse_api(
                    url, profile, include_parsetree=include_parsetree
                )
            request = Request(url, headers={"User-Agent": _INGEST_USER_AGENT})
            with urlopen(request, timeout=profile.timeout_seconds) as response:  # noqa: S310
                html = response.read().decode("utf-8", errors="replace")
            body, locator = _extract_main_text(html, max_chars=profile.max_chars)
            sections, links, structured = _extract_sections_and_links(html)
            revision_match = REVISION_RE.search(html)
            if revision_match:
                revision_id = f"mw:{revision_match.group(1)}"
            else:
                revision_id = "sha256:" + sha256(html.encode("utf-8")).hexdigest()[:16]
            if include_parsetree:
                # Non-MediaWiki/HTML fallback has no parse tree available.
                return body, revision_id, locator, sections, links, structured, html, ""
            return body, revision_id, locator, sections, links, structured, html
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            last_error = exc
            if attempt < profile.retries:
                time.sleep(profile.retry_backoff_seconds * (2**attempt))
            continue
    msg = f"unable to fetch source url '{url}'"
    if last_error is not None:
        msg = f"{msg}: {last_error!r}"
    raise RuntimeError(msg)


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
        fetch_result = _fetch_url_text(url, source_class)
        if len(fetch_result) == 3:
            body, revision_id, locator = fetch_result
            section_blocks = []
            wiki_links = []
            structured_links: list[dict[str, str]] = []
            raw_html = ""
        else:
            body, revision_id, locator, section_blocks, wiki_links, structured_links, raw_html = (
                fetch_result
            )
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
    output_path.write_text(json.dumps(snapshots, indent=2), encoding="utf-8")
    raw_ndjson_path = raw_dir / "source_snapshots.ndjson"
    raw_ndjson_path.write_text(
        "\n".join(json.dumps(snapshot) for snapshot in snapshots) + "\n",
        encoding="utf-8",
    )
    return output_path
