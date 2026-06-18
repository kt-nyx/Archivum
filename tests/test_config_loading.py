"""Tests for the shared YAML config loader (WS-B)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from pipeline.common.config_loading import load_yaml, load_yaml_mapping


def test_load_yaml_parses_nested_mapping(tmp_path: Path) -> None:
    path = tmp_path / "cfg.yaml"
    path.write_text("a:\n  b: 1\n  c: two\n", encoding="utf-8")
    assert load_yaml(path) == {"a": {"b": 1, "c": "two"}}


def test_load_yaml_missing_returns_default(tmp_path: Path) -> None:
    missing = tmp_path / "nope.yaml"
    assert load_yaml(missing) == {}
    assert load_yaml(missing, default={"x": 1}) == {"x": 1}
    assert load_yaml(missing, default=[]) == []


def test_load_yaml_empty_file_returns_default(tmp_path: Path) -> None:
    path = tmp_path / "empty.yaml"
    path.write_text("\n# only a comment\n", encoding="utf-8")
    assert load_yaml(path) == {}
    assert load_yaml(path, default={"x": 1}) == {"x": 1}


def test_load_yaml_malformed_raises(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("a: [1, 2\n", encoding="utf-8")  # unterminated flow sequence
    with pytest.raises(yaml.YAMLError):
        load_yaml(path)


def test_load_yaml_mapping_coerces_non_mapping_to_empty(tmp_path: Path) -> None:
    path = tmp_path / "list.yaml"
    path.write_text("- 1\n- 2\n", encoding="utf-8")
    assert load_yaml(path) == [1, 2]
    assert load_yaml_mapping(path) == {}


def test_committed_config_files_round_trip_expected_shapes() -> None:
    """The migrated loaders must return the exact flat shapes the pipeline relies on."""
    from pipeline.coalesce.resolve_entities import _load_merge_rules
    from pipeline.linker.linker import (
        _load_category_preferences,
        _load_disambiguation_rules,
        _load_linker_rules,
    )

    assert _load_merge_rules() == {
        "confidence_threshold": 0.8,
        "dedupe_strategy": "exact_text_then_source_overlap",
        "contradiction_bias": "prefer_higher_revision_id",
    }
    assert _load_linker_rules() == {"direct_alias_match": 0.9, "contextual_match": 0.75}
    assert _load_category_preferences() == {
        "zone": ["place", "event"],
        "instance": ["place", "event"],
        "character": ["person", "faction"],
        "glossary_term": ["concept", "artifact"],
    }
    assert _load_disambiguation_rules() == {
        "min_margin": 0.1,
        "require_manual_review_below": 0.8,
    }
