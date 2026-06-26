"""Warcraft Wiki category signals for offline glossary significance.

The registry is intentionally small and explainable: it classifies MediaWiki
categories from structural roots captured during ingest, then offline consumers
can use the persisted signal without making network calls.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pipeline.common.config_loading import load_yaml_mapping

_DEFAULT_RULES_PATH = Path(__file__).resolve().parents[2] / "rules" / "wiki_category_registry.v1.yaml"
_WORD_RE = re.compile(r"[a-z0-9']+")
_BUCKET_ORDER: tuple[str, ...] = ("person", "event", "place", "faction", "artifact")


@dataclass(frozen=True)
class CategorySignal:
    """Classification attached to a category or page category set."""

    bucket: str
    disposition: str
    matched_roots: tuple[str, ...] = ()
    matched_tokens: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "bucket": self.bucket,
            "disposition": self.disposition,
            "matched_roots": list(self.matched_roots),
            "matched_tokens": list(self.matched_tokens),
            "reasons": list(self.reasons),
        }


def load_category_registry_rules(path: Path | None = None) -> dict[str, Any]:
    """Load the YAML-backed category registry rules."""

    return load_yaml_mapping(path or _DEFAULT_RULES_PATH)


def classify_category(
    name: str,
    parents: Iterable[str] = (),
    *,
    rules: Mapping[str, Any] | None = None,
) -> CategorySignal:
    """Classify one category from its own name plus known parent categories."""

    loaded_rules = rules or load_category_registry_rules()
    root_values = _root_values(name, parents)
    root_norms = {_normalize_root(value): value for value in root_values}

    strong_drop_roots = _matching_root_values(root_norms, _list_rule(loaded_rules, "strong_drop_roots"))
    if strong_drop_roots:
        return CategorySignal(
            bucket="noise",
            disposition="strong_drop",
            matched_roots=strong_drop_roots,
            reasons=("strong_drop_root",),
        )

    include_matches = _strong_include_matches(root_norms, loaded_rules)
    if include_matches:
        bucket, matched_roots = include_matches
        return CategorySignal(
            bucket=bucket,
            disposition="strong_include",
            matched_roots=matched_roots,
            reasons=(f"strong_include_root:{bucket}",),
        )

    soft_drop_roots = _matching_root_values(root_norms, _list_rule(loaded_rules, "soft_drop_roots"))
    if soft_drop_roots:
        return CategorySignal(
            bucket="noise",
            disposition="soft_drop",
            matched_roots=soft_drop_roots,
            reasons=("soft_drop_root",),
        )

    strong_drop_tokens = _matching_tokens(root_values, _list_rule(loaded_rules, "strong_drop_tokens"))
    strong_drop_phrases = _matching_phrases(
        root_values, _list_rule(loaded_rules, "strong_drop_phrases")
    )
    if strong_drop_tokens or strong_drop_phrases:
        reasons = ["strong_drop_token"] if strong_drop_tokens else []
        reasons.extend(f"strong_drop_phrase:{phrase}" for phrase in strong_drop_phrases)
        return CategorySignal(
            bucket="noise",
            disposition="strong_drop",
            matched_tokens=strong_drop_tokens,
            reasons=tuple(reasons),
        )

    token_match = _include_token_match(root_values, loaded_rules)
    if token_match:
        bucket, tokens = token_match
        return CategorySignal(
            bucket=bucket,
            disposition="review",
            matched_tokens=tokens,
            reasons=(f"include_token:{bucket}",),
        )

    return CategorySignal(bucket="concept", disposition="review", reasons=("unmatched",))


def classify_page_categories(
    categories: Iterable[str],
    parent_map: Mapping[str, Iterable[str]] | None = None,
    *,
    rules: Mapping[str, Any] | None = None,
) -> CategorySignal:
    """Classify a page from its direct categories and optional category-parent map."""

    loaded_rules = rules or load_category_registry_rules()
    category_names = [str(category or "").strip() for category in categories]
    category_names = [name for name in category_names if name]
    normalized_parents = _normalized_parent_map(parent_map or {})
    category_signals: list[CategorySignal] = []
    for name in category_names:
        parents = normalized_parents.get(_normalize_root(name), ())
        category_signals.append(classify_category(name, parents, rules=loaded_rules))

    if not category_signals:
        return CategorySignal(bucket="concept", disposition="review", reasons=("no_categories",))

    direct_strong_drop_roots = _matching_direct_roots(
        category_names,
        _list_rule(loaded_rules, "strong_drop_roots"),
    )
    if direct_strong_drop_roots:
        return CategorySignal(
            bucket="noise",
            disposition="strong_drop",
            matched_roots=direct_strong_drop_roots,
            reasons=("direct_strong_drop_root",),
        )

    strong_includes = [
        signal for signal in category_signals if signal.disposition == "strong_include"
    ]
    if strong_includes:
        return _best_bucket_signal(
            strong_includes,
            disposition="strong_include",
            reason="page_strong_include",
        )

    strong_drops = [signal for signal in category_signals if signal.disposition == "strong_drop"]
    if strong_drops:
        return _combine_page_signal(
            strong_drops,
            bucket="noise",
            disposition="strong_drop",
            reason="page_strong_drop",
        )

    review_includes = [
        signal
        for signal in category_signals
        if signal.disposition == "review" and signal.bucket in _BUCKET_ORDER
    ]
    if review_includes:
        return _best_bucket_signal(
            review_includes,
            disposition="review",
            reason="page_review_include",
        )

    soft_drops = [signal for signal in category_signals if signal.disposition == "soft_drop"]
    if soft_drops:
        return _combine_page_signal(
            soft_drops,
            bucket="noise",
            disposition="soft_drop",
            reason="page_soft_drop",
        )

    return CategorySignal(bucket="concept", disposition="review", reasons=("page_unmatched",))


def _root_values(name: str, parents: Iterable[str]) -> list[str]:
    values = [str(name or "").strip()]
    values.extend(str(parent or "").strip() for parent in parents)
    return [value for value in values if value]


def _normalize_root(value: str) -> str:
    normalized = str(value or "").replace("_", " ").strip()
    if normalized.casefold().startswith("category:"):
        normalized = normalized.split(":", 1)[1].strip()
    return re.sub(r"\s+", " ", normalized).casefold()


def _tokens(value: str) -> set[str]:
    return set(_WORD_RE.findall(_normalize_root(value)))


def _list_rule(rules: Mapping[str, Any], key: str) -> list[str]:
    raw = rules.get(key, [])
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _include_tokens(rules: Mapping[str, Any]) -> dict[str, list[str]]:
    raw = rules.get("include_tokens", {})
    if not isinstance(raw, Mapping):
        return {}
    result: dict[str, list[str]] = {}
    for bucket, tokens in raw.items():
        if not isinstance(tokens, list):
            continue
        result[str(bucket)] = [str(token).strip() for token in tokens if str(token).strip()]
    return result


def _matching_root_values(root_norms: Mapping[str, str], candidates: Iterable[str]) -> tuple[str, ...]:
    candidate_norms = {_normalize_root(candidate) for candidate in candidates}
    matches = sorted(
        {original for normalized, original in root_norms.items() if normalized in candidate_norms}
    )
    return tuple(matches)


def _matching_direct_roots(values: Iterable[str], candidates: Iterable[str]) -> tuple[str, ...]:
    root_norms = {_normalize_root(value): value for value in values}
    return _matching_root_values(root_norms, candidates)


def _strong_include_matches(
    root_norms: Mapping[str, str],
    rules: Mapping[str, Any],
) -> tuple[str, tuple[str, ...]] | None:
    raw = rules.get("strong_include_roots", {})
    if not isinstance(raw, Mapping):
        return None
    for bucket in _BUCKET_ORDER:
        roots = raw.get(bucket, [])
        if not isinstance(roots, list):
            continue
        matched = _matching_root_values(root_norms, [str(root) for root in roots])
        if matched:
            return bucket, matched
    return None


def _matching_tokens(values: Iterable[str], candidates: Iterable[str]) -> tuple[str, ...]:
    candidate_tokens = {_normalize_root(candidate) for candidate in candidates}
    matches: set[str] = set()
    for value in values:
        matches.update(_tokens(value).intersection(candidate_tokens))
    return tuple(sorted(matches))


def _matching_phrases(values: Iterable[str], candidates: Iterable[str]) -> tuple[str, ...]:
    phrases = [_normalize_root(candidate) for candidate in candidates if str(candidate).strip()]
    matches: set[str] = set()
    for value in values:
        normalized = _normalize_root(value)
        for phrase in phrases:
            if phrase and phrase in normalized:
                matches.add(phrase)
    return tuple(sorted(matches))


def _include_token_match(
    values: Iterable[str],
    rules: Mapping[str, Any],
) -> tuple[str, tuple[str, ...]] | None:
    for bucket in _BUCKET_ORDER:
        tokens = _include_tokens(rules).get(bucket, [])
        matched = _matching_tokens(values, tokens)
        if matched:
            return bucket, matched
    return None


def _normalized_parent_map(parent_map: Mapping[str, Iterable[str]]) -> dict[str, tuple[str, ...]]:
    normalized: dict[str, tuple[str, ...]] = {}
    for category, parents in parent_map.items():
        parent_values: tuple[str, ...]
        if isinstance(parents, str):
            parent_values = (parents,)
        else:
            parent_values = tuple(str(parent).strip() for parent in parents if str(parent).strip())
        normalized[_normalize_root(str(category))] = parent_values
    return normalized


def _combine_page_signal(
    signals: Iterable[CategorySignal],
    *,
    bucket: str,
    disposition: str,
    reason: str,
) -> CategorySignal:
    signal_list = list(signals)
    return CategorySignal(
        bucket=bucket,
        disposition=disposition,
        matched_roots=tuple(sorted({root for signal in signal_list for root in signal.matched_roots})),
        matched_tokens=tuple(
            sorted({token for signal in signal_list for token in signal.matched_tokens})
        ),
        reasons=tuple(sorted({reason, *(r for signal in signal_list for r in signal.reasons)})),
    )


def _best_bucket_signal(
    signals: Iterable[CategorySignal],
    *,
    disposition: str,
    reason: str,
) -> CategorySignal:
    signal_list = list(signals)
    by_bucket: dict[str, list[CategorySignal]] = {bucket: [] for bucket in _BUCKET_ORDER}
    for signal in signal_list:
        if signal.bucket in by_bucket:
            by_bucket[signal.bucket].append(signal)
    for bucket in _BUCKET_ORDER:
        bucket_signals = by_bucket[bucket]
        if bucket_signals:
            return _combine_page_signal(
                bucket_signals,
                bucket=bucket,
                disposition=disposition,
                reason=reason,
            )
    return CategorySignal(bucket="concept", disposition="review", reasons=("page_unmatched",))
