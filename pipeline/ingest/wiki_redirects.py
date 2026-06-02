"""Wiki identity resolution via MediaWiki ``action=query`` (redirects + page ids).

The ``action=parse`` ingest path fetches an instance page's HTML but never records
the canonical identity of the *links* inside it. Two roster links can point at the
same real character through redirects/title variants (e.g. ``Razuvious`` ->
``Instructor Razuvious``) or differ only by a title alias. Resolving each roster
link to a canonical page identity (``page_id`` + canonical title) lets the offline
draft stage collapse duplicate character candidates.

This module is the network boundary for that resolution. It is intentionally
dependency-light: the snapshot-annotation helper takes the roster predicate by
injection so ingest never imports the discovery layer.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

_REDIRECT_USER_AGENT = "wow-lore-ingest/1.0"
_QUERY_BATCH_SIZE = 50


def normalize_wiki_path(href_or_path: str) -> str:
    """Return a bare ``Title_With_Underscores`` path (no host, ``/wiki/`` or fragment)."""
    value = str(href_or_path).strip()
    if not value:
        return ""
    if "/wiki/" in value:
        value = value[value.index("/wiki/") + len("/wiki/") :]
    value = value.split("#", 1)[0].strip().strip("/")
    return value


def _title_from_path(path: str) -> str:
    return path.replace("_", " ").strip()


def _path_from_title(title: str) -> str:
    return title.strip().replace(" ", "_")


def _http_get_json(url: str, *, timeout_seconds: int) -> dict[str, Any]:
    """Fetch and decode a JSON API response. Isolated for test monkeypatching."""
    request = Request(url, headers={"User-Agent": _REDIRECT_USER_AGENT})
    with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
        raw = response.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def _chunked(values: list[str], size: int) -> list[list[str]]:
    return [values[i : i + size] for i in range(0, len(values), size)]


def _follow_mapping(title: str, mapping: dict[str, str]) -> str:
    """Follow a from->to mapping chain (normalized/redirects), guarding against cycles."""
    seen: set[str] = set()
    current = title
    while current in mapping and current not in seen:
        seen.add(current)
        current = mapping[current]
    return current


def resolve_wiki_identities(
    paths: list[str],
    *,
    origin: str,
    timeout_seconds: int = 15,
    retries: int = 2,
    retry_backoff_seconds: float = 0.5,
) -> dict[str, dict[str, Any]]:
    """Resolve wiki paths to canonical identity via ``action=query&redirects=1``.

    Returns a map keyed by the normalized requested path with values
    ``{"canonical_title", "canonical_path", "page_id"}``. ``page_id`` is ``None``
    for missing pages or when the API omits it. Unresolved paths are returned with
    their own title as the canonical fallback so callers always get an entry.
    """
    normalized_paths = [p for p in (normalize_wiki_path(path) for path in paths) if p]
    unique_paths = list(dict.fromkeys(normalized_paths))
    if not unique_paths:
        return {}

    identities: dict[str, dict[str, Any]] = {}
    for batch in _chunked(unique_paths, _QUERY_BATCH_SIZE):
        titles = [_title_from_path(path) for path in batch]
        params = {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "redirects": "1",
            "titles": "|".join(titles),
        }
        api_url = f"{origin}/api.php?{urlencode(params)}"
        payload = _request_with_retry(
            api_url,
            timeout_seconds=timeout_seconds,
            retries=retries,
            retry_backoff_seconds=retry_backoff_seconds,
        )
        identities.update(_identities_from_payload(batch, payload))
    return identities


def _request_with_retry(
    api_url: str,
    *,
    timeout_seconds: int,
    retries: int,
    retry_backoff_seconds: float,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return _http_get_json(api_url, timeout_seconds=timeout_seconds)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(retry_backoff_seconds * (attempt + 1))
    raise RuntimeError(f"wiki identity query failed for {api_url!r}: {last_error!r}")


def _identities_from_payload(
    batch_paths: list[str], payload: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    query = payload.get("query") if isinstance(payload, dict) else None
    query = query if isinstance(query, dict) else {}

    normalized_map = {
        str(item.get("from", "")): str(item.get("to", ""))
        for item in query.get("normalized", [])
        if isinstance(item, dict)
    }
    redirect_map = {
        str(item.get("from", "")): str(item.get("to", ""))
        for item in query.get("redirects", [])
        if isinstance(item, dict)
    }
    page_ids: dict[str, int | None] = {}
    for page in query.get("pages", []):
        if not isinstance(page, dict):
            continue
        title = str(page.get("title", ""))
        if not title:
            continue
        if page.get("missing"):
            page_ids[title] = None
        else:
            pid = page.get("pageid")
            page_ids[title] = int(pid) if isinstance(pid, int) else None

    resolved: dict[str, dict[str, Any]] = {}
    for path in batch_paths:
        title = _title_from_path(path)
        canonical = _follow_mapping(title, normalized_map)
        canonical = _follow_mapping(canonical, redirect_map)
        resolved[path] = {
            "canonical_title": canonical,
            "canonical_path": _path_from_title(canonical),
            "page_id": page_ids.get(canonical),
        }
    return resolved


def annotate_snapshots_with_canonical_identity(
    snapshots: list[dict[str, Any]],
    *,
    roster_predicate: Callable[[dict[str, Any]], bool],
    resolver: Callable[..., dict[str, dict[str, Any]]] = resolve_wiki_identities,
    timeout_seconds: int = 15,
) -> dict[str, dict[str, Any]]:
    """Annotate instance roster structured_links in place with canonical identity.

    For each ``entity_type == "instance"`` snapshot, gather roster-role structured
    links (per ``roster_predicate``), resolve them per wiki origin, and write
    ``canonical_path`` + ``page_id`` onto each matching link. Returns a run-level
    map keyed by ``"{origin}|{path}"`` for QA/reuse.
    """
    paths_by_origin: dict[str, set[str]] = {}
    for snapshot in snapshots:
        if not isinstance(snapshot, dict) or snapshot.get("entity_type") != "instance":
            continue
        origin = _origin_for_snapshot(snapshot)
        if not origin:
            continue
        for link in snapshot.get("structured_links", []) or []:
            if not isinstance(link, dict) or not roster_predicate(link):
                continue
            path = normalize_wiki_path(str(link.get("href", "")))
            if path:
                paths_by_origin.setdefault(origin, set()).add(path)

    run_map: dict[str, dict[str, Any]] = {}
    resolved_by_origin: dict[str, dict[str, dict[str, Any]]] = {}
    for origin, paths in paths_by_origin.items():
        identities = resolver(sorted(paths), origin=origin, timeout_seconds=timeout_seconds)
        resolved_by_origin[origin] = identities
        for path, identity in identities.items():
            run_map[f"{origin}|{path}"] = identity

    for snapshot in snapshots:
        if not isinstance(snapshot, dict) or snapshot.get("entity_type") != "instance":
            continue
        origin = _origin_for_snapshot(snapshot)
        identities = resolved_by_origin.get(origin, {})
        if not identities:
            continue
        for link in snapshot.get("structured_links", []) or []:
            if not isinstance(link, dict) or not roster_predicate(link):
                continue
            path = normalize_wiki_path(str(link.get("href", "")))
            identity = identities.get(path)
            if not identity:
                continue
            link["canonical_path"] = identity["canonical_path"]
            if identity.get("page_id") is not None:
                link["page_id"] = identity["page_id"]
    return run_map


def _origin_for_snapshot(snapshot: dict[str, Any]) -> str:
    parsed = urlparse(str(snapshot.get("url", "")))
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"
