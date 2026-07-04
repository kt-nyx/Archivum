"""Adventure Guide crawl: per-instance / per-boss Blizzard-authored journal blurbs.

The game's Adventure Guide lives on dedicated wiki index pages (``Adventure Guide <expansion>
dungeons``/``raids``), not on each instance's own article. Each index page has one L1 section per
instance whose heading links to the instance's own page (``== [[Scholomance]] ==``); the section
holds an intro overview plus one ``{{BossIcon|Name}}`` table per boss carrying a crafted,
spoiler-light backstory blurb.

We index by the section heading's linked instance page across *all* index pages, so an instance
resolves regardless of which expansion page it was filed under (Scholomance is listed under
"Classic dungeons" despite its MoP revamp). These blurbs are used downstream only as *reference
framing* for character synthesis — never copied, and never used to dictate prose length or tone.

The crawl is network-bound; callers gate it to live runs and treat any failure as "no Adventure
Guide data" (empty result), so offline / deterministic paths are unaffected.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Protocol
from urllib.parse import unquote, urlencode

from pipeline.common import http
from pipeline.common.text_ids import slugify
from pipeline.discovery.entity_typing import normalize_title

_WIKI_ORIGIN = "https://warcraft.wiki.gg"
_USER_AGENT = "LoreAddonBot/0.1 (nymphipoo@gmail.com)"
_HUB_PAGE = "Adventure Guide"
_TIMEOUT_SECONDS = 15.0
_RETRIES = 2
_BACKOFF_BASE = 0.5
_CACHE_VERSION = 1

# Parenthetical qualifiers on a boss link ("(tactics)", "(Classic)") that are not part of the
# character's identity when matching an Adventure Guide entry to a cast member.
_QUALIFIER_RE = re.compile(r"\s*\([^)]*\)\s*$")


@dataclass(frozen=True)
class AdventureGuideEntry:
    """One boss's Adventure Guide journal blurb."""

    boss_name: str
    display_name: str
    course: str
    description: str


@dataclass(frozen=True)
class AdventureGuideInstance:
    """An instance's Adventure Guide content: intro overview + per-boss entries."""

    instance_title: str
    overview: str
    entries: tuple[AdventureGuideEntry, ...]

    def entry_for(self, name: str) -> AdventureGuideEntry | None:
        """Best Adventure Guide entry for a cast member, tolerant of qualifiers and minor typos.

        Matches on both the ``{{BossIcon}}`` page name and the displayed link text (the page has
        e.g. ``[[Lilian Voss|Lillian Voss]]``), trying exact normalized match, then containment,
        then a high-threshold fuzzy match — so cast-name vs page-title drift still binds.
        """
        target = _match_key(name)
        if not target:
            return None
        # Exact normalized match on either the boss page name or the displayed name.
        for entry in self.entries:
            if target in {_match_key(entry.boss_name), _match_key(entry.display_name)}:
                return entry
        # Containment either direction (e.g. "Gandling" vs "Darkmaster Gandling").
        for entry in self.entries:
            for candidate in (_match_key(entry.boss_name), _match_key(entry.display_name)):
                if candidate and (candidate in target or target in candidate):
                    return entry
        # Fuzzy tolerance for typos ("Lillian" vs "Lilian").
        best: tuple[float, AdventureGuideEntry | None] = (0.0, None)
        for entry in self.entries:
            for candidate in (_match_key(entry.boss_name), _match_key(entry.display_name)):
                if not candidate:
                    continue
                ratio = SequenceMatcher(None, target, candidate).ratio()
                if ratio > best[0]:
                    best = (ratio, entry)
        if best[0] >= 0.88:
            return best[1]
        return None


def _match_key(name: str) -> str:
    return normalize_title(_QUALIFIER_RE.sub("", str(name or "")).strip())


# --------------------------------------------------------------------------------------------------
# Wikitext parsing (pure — no network, unit-tested directly)
# --------------------------------------------------------------------------------------------------

_INDEX_LINK_RE = re.compile(r"\[\[\s*(Adventure Guide[^\]|#<>]+?)\s*(?:\||\]\])")
_HEADING_RE = re.compile(r"^\s*==+[^=].*?==+\s*", re.DOTALL)
_HREF_RE = re.compile(r'/wiki/([^"#?]+)')
_TAG_RE = re.compile(r"<[^>]+>")
_BOSSICON_RE = re.compile(r"\{\{\s*BossIcon\s*\|\s*([^}|]+?)\s*(?:\|[^}]*)?\}\}", re.IGNORECASE)
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_TABLE_START_RE = re.compile(r"\{\|")


def parse_index_page_titles(hub_wikitext: str) -> list[str]:
    """Extract the ``Adventure Guide <expansion> dungeons``/``raids`` index page titles from the hub.

    Reads the titles from the hub page rather than hardcoding them, so a new expansion's index
    appears automatically. Keeps only ``dungeons``/``raids``/``removed`` index pages and drops the
    hub self-link and unrelated "Adventure Guide" mentions.
    """
    titles: list[str] = []
    seen: set[str] = set()
    for raw in _INDEX_LINK_RE.findall(hub_wikitext or ""):
        title = re.sub(r"\s+", " ", str(raw).replace("_", " ")).strip()
        lowered = title.lower()
        if not (lowered.endswith("dungeons") or lowered.endswith("raids")):
            continue
        if lowered in seen:
            continue
        seen.add(lowered)
        titles.append(title)
    return titles


def _strip_html(value: str) -> str:
    return _TAG_RE.sub("", value or "").strip()


def instance_keys_from_section(section: dict[str, object]) -> list[str]:
    """Normalized lookup keys for a prop=sections L1 section heading (``== [[Instance]] ==``).

    Returns keys for both the linked page title (from the heading anchor's href) and the visible
    heading text, so an instance resolves whether callers key by page title or display name.
    """
    keys: list[str] = []
    line = str(section.get("line", ""))
    href_match = _HREF_RE.search(line)
    if href_match:
        page_title = unquote(href_match.group(1)).replace("_", " ")
        key = normalize_title(page_title)
        if key:
            keys.append(key)
    text_key = normalize_title(_strip_html(line))
    if text_key and text_key not in keys:
        keys.append(text_key)
    anchor_key = normalize_title(str(section.get("anchor", "")).replace("_", " "))
    if anchor_key and anchor_key not in keys:
        keys.append(anchor_key)
    return keys


def _clean_wikitext(text: str) -> str:
    """Reduce a fragment of MediaWiki wikitext to plain prose."""
    if not text:
        return ""
    cleaned = re.sub(r"<ref[^>]*>.*?</ref>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<ref[^>]*/>", " ", cleaned, flags=re.IGNORECASE)
    previous = ""
    while previous != cleaned:  # collapse nested templates innermost-first
        previous = cleaned
        cleaned = re.sub(r"\{\{[^{}]*\}\}", " ", cleaned)
    cleaned = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", cleaned)
    cleaned = re.sub(r"\[\[([^\]]*)\]\]", r"\1", cleaned)
    cleaned = re.sub(r"\[https?://\S+\s+([^\]]+)\]", r"\1", cleaned)
    cleaned = re.sub(r"\[https?://\S+\]", " ", cleaned)
    cleaned = cleaned.replace("'''", "").replace("''", "")
    cleaned = _TAG_RE.sub(" ", cleaned)
    cleaned = cleaned.replace("|", " ")
    return re.sub(r"\s+", " ", cleaned).strip()


def _split_intro_and_body(section_wikitext: str) -> tuple[str, str]:
    text = _HEADING_RE.sub("", section_wikitext or "", count=1)
    cut = len(text)
    for match in (_TABLE_START_RE.search(text), _BOSSICON_RE.search(text)):
        if match:
            cut = min(cut, match.start())
    return text[:cut], text[cut:]


def _parse_boss_entries(body: str) -> list[AdventureGuideEntry]:
    entries: list[AdventureGuideEntry] = []
    matches = list(_BOSSICON_RE.finditer(body))
    for index, match in enumerate(matches):
        boss_name = _clean_wikitext(match.group(1)) or match.group(1).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        chunk = body[start:end]
        segments = [_clean_wikitext(seg) for seg in _BR_RE.split(chunk)]

        display = ""
        rest_start = 0
        for position, segment in enumerate(segments):
            if segment:
                display = segment
                rest_start = position + 1
                break

        course = ""
        description_parts: list[str] = []
        for segment in segments[rest_start:]:
            if not segment:
                continue
            if not course and segment.lower().startswith("course:"):
                course = segment.split(":", 1)[1].strip()
                continue
            description_parts.append(segment)

        entries.append(
            AdventureGuideEntry(
                boss_name=boss_name,
                display_name=display or boss_name,
                course=course,
                description=" ".join(description_parts).strip(),
            )
        )
    return entries


def parse_instance_section(
    section_wikitext: str, *, instance_title: str = ""
) -> AdventureGuideInstance:
    """Parse one instance's Adventure Guide section wikitext into overview + per-boss entries."""
    intro, body = _split_intro_and_body(section_wikitext)
    return AdventureGuideInstance(
        instance_title=instance_title,
        overview=_clean_wikitext(intro),
        entries=tuple(_parse_boss_entries(body)),
    )


# --------------------------------------------------------------------------------------------------
# Fetch layer (network — injectable for tests)
# --------------------------------------------------------------------------------------------------


class AdventureGuideFetcher(Protocol):
    def page_wikitext(self, title: str) -> str: ...
    def page_sections(self, title: str) -> list[dict[str, object]]: ...
    def section_wikitext(self, title: str, section_index: str) -> str: ...


class MediaWikiFetcher:
    """Default fetcher against the warcraft.wiki.gg MediaWiki ``action=parse`` API."""

    def __init__(self, *, origin: str = _WIKI_ORIGIN) -> None:
        self._origin = origin.rstrip("/")

    def _get(self, params: dict[str, str]) -> dict[str, object]:
        query = {**params, "format": "json", "formatversion": "2"}
        url = f"{self._origin}/api.php?{urlencode(query)}"
        raw = http.get_text(
            url,
            headers={"User-Agent": _USER_AGENT},
            timeout=_TIMEOUT_SECONDS,
            retries=_RETRIES,
            backoff_base=_BACKOFF_BASE,
        )
        data = json.loads(raw)
        if isinstance(data, dict) and "error" in data:
            error = data["error"]
            code = error.get("code", "unknown") if isinstance(error, dict) else "unknown"
            raise RuntimeError(f"MediaWiki API error {code}")
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _wikitext(parse_blob: object) -> str:
        if not isinstance(parse_blob, dict):
            return ""
        wikitext = parse_blob.get("wikitext")
        if isinstance(wikitext, dict):  # legacy formatversion
            return str(wikitext.get("*", ""))
        return str(wikitext or "")

    def page_wikitext(self, title: str) -> str:
        data = self._get({"action": "parse", "page": title, "prop": "wikitext"})
        return self._wikitext(data.get("parse"))

    def page_sections(self, title: str) -> list[dict[str, object]]:
        data = self._get({"action": "parse", "page": title, "prop": "sections"})
        parse_blob = data.get("parse")
        if not isinstance(parse_blob, dict):
            return []
        sections = parse_blob.get("sections")
        return [s for s in sections if isinstance(s, dict)] if isinstance(sections, list) else []

    def section_wikitext(self, title: str, section_index: str) -> str:
        data = self._get(
            {"action": "parse", "page": title, "prop": "wikitext", "section": str(section_index)}
        )
        return self._wikitext(data.get("parse"))


# --------------------------------------------------------------------------------------------------
# Provider (index build + per-instance lookup, with in-process + optional disk cache)
# --------------------------------------------------------------------------------------------------


def _coerce_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    return None


def _is_l1_section(section: dict[str, object]) -> bool:
    toclevel = _coerce_int(section.get("toclevel"))
    if toclevel is not None:
        return toclevel == 1
    # Heading level (``== ==``) when toclevel is absent.
    return _coerce_int(section.get("level")) == 2


class AdventureGuideProvider:
    """Builds the Adventure-Guide instance index once, then serves per-instance content lazily."""

    def __init__(
        self,
        *,
        fetcher: AdventureGuideFetcher | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        self._fetcher: AdventureGuideFetcher = fetcher or MediaWikiFetcher()
        self._cache_dir = cache_dir
        self._index: dict[str, tuple[str, str]] | None = None
        self._instances: dict[str, AdventureGuideInstance | None] = {}

    # -- index -----------------------------------------------------------------------------------

    def _index_map(self) -> dict[str, tuple[str, str]]:
        if self._index is not None:
            return self._index
        cached = self._cache_read("index")
        if isinstance(cached, dict) and cached.get("version") == _CACHE_VERSION:
            raw_map = cached.get("map")
            if isinstance(raw_map, dict):
                self._index = {
                    str(key): (str(value[0]), str(value[1]))
                    for key, value in raw_map.items()
                    if isinstance(value, list) and len(value) == 2
                }
                return self._index
        self._index = self._build_index_map()
        self._cache_write(
            "index",
            {"version": _CACHE_VERSION, "map": {k: list(v) for k, v in self._index.items()}},
        )
        return self._index

    def _build_index_map(self) -> dict[str, tuple[str, str]]:
        index: dict[str, tuple[str, str]] = {}
        hub_wikitext = self._fetcher.page_wikitext(_HUB_PAGE)
        for page_title in parse_index_page_titles(hub_wikitext):
            for section in self._fetcher.page_sections(page_title):
                if not _is_l1_section(section):
                    continue
                section_index = str(section.get("index", "")).strip()
                if not section_index:
                    continue
                for key in instance_keys_from_section(section):
                    # First index page wins for a given instance key (stable across runs).
                    index.setdefault(key, (page_title, section_index))
        return index

    # -- per-instance content --------------------------------------------------------------------

    def instance_content(self, instance_name: str) -> AdventureGuideInstance | None:
        key = normalize_title(instance_name)
        if not key:
            return None
        if key in self._instances:
            return self._instances[key]
        content = self._load_instance(key, instance_name)
        self._instances[key] = content
        return content

    def _load_instance(self, key: str, instance_name: str) -> AdventureGuideInstance | None:
        cached = self._cache_read(f"instance-{slugify(key, separator='_') or 'x'}")
        if isinstance(cached, dict) and cached.get("version") == _CACHE_VERSION:
            return _instance_from_cache(cached)
        located = self._index_map().get(key)
        if located is None:
            self._cache_write(
                f"instance-{slugify(key, separator='_') or 'x'}",
                {"version": _CACHE_VERSION, "found": False},
            )
            return None
        page_title, section_index = located
        wikitext = self._fetcher.section_wikitext(page_title, section_index)
        content = parse_instance_section(wikitext, instance_title=instance_name)
        self._cache_write(
            f"instance-{slugify(key, separator='_') or 'x'}",
            _instance_to_cache(content),
        )
        return content

    # -- disk cache ------------------------------------------------------------------------------

    def _cache_path(self, name: str) -> Path | None:
        if self._cache_dir is None:
            return None
        return self._cache_dir / f"{name}.json"

    def _cache_read(self, name: str) -> object | None:
        path = self._cache_path(name)
        if path is None or not path.exists():
            return None
        try:
            loaded: object = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return loaded

    def _cache_write(self, name: str, payload: object) -> None:
        path = self._cache_path(name)
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload), encoding="utf-8")
        except OSError:
            return


def _instance_to_cache(content: AdventureGuideInstance) -> dict[str, object]:
    return {
        "version": _CACHE_VERSION,
        "found": True,
        "instance_title": content.instance_title,
        "overview": content.overview,
        "entries": [
            {
                "boss_name": entry.boss_name,
                "display_name": entry.display_name,
                "course": entry.course,
                "description": entry.description,
            }
            for entry in content.entries
        ],
    }


def _instance_from_cache(cached: dict[str, object]) -> AdventureGuideInstance | None:
    if not cached.get("found"):
        return None
    raw_entries = cached.get("entries")
    entries = tuple(
        AdventureGuideEntry(
            boss_name=str(row.get("boss_name", "")),
            display_name=str(row.get("display_name", "")),
            course=str(row.get("course", "")),
            description=str(row.get("description", "")),
        )
        for row in (raw_entries if isinstance(raw_entries, list) else [])
        if isinstance(row, dict)
    )
    return AdventureGuideInstance(
        instance_title=str(cached.get("instance_title", "")),
        overview=str(cached.get("overview", "")),
        entries=entries,
    )


# --------------------------------------------------------------------------------------------------
# Process-level default provider (draft stage entry point)
# --------------------------------------------------------------------------------------------------

_DEFAULT_PROVIDER: AdventureGuideProvider | None = None


def _default_cache_dir() -> Path | None:
    raw = os.environ.get("WOW_LORE_ADVENTURE_GUIDE_CACHE", "").strip()
    if raw:
        return Path(raw).expanduser()
    repo_root = Path(__file__).resolve().parent.parent.parent
    return repo_root / ".cache" / "adventure_guide"


def default_provider() -> AdventureGuideProvider:
    """Process-wide provider so the index builds once per run across all instances."""
    global _DEFAULT_PROVIDER
    if _DEFAULT_PROVIDER is None:
        _DEFAULT_PROVIDER = AdventureGuideProvider(cache_dir=_default_cache_dir())
    return _DEFAULT_PROVIDER


def reset_default_provider() -> None:
    """Drop the cached process provider (tests)."""
    global _DEFAULT_PROVIDER
    _DEFAULT_PROVIDER = None
