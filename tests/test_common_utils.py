"""Tests for shared common utilities introduced in WS-D (text_ids, text_sim, io)."""

from __future__ import annotations

from pathlib import Path

from pipeline.common.io import read_json, write_json
from pipeline.common.text_ids import slugify
from pipeline.common.text_sim import (
    max_similarity_against_sources,
    token_jaccard,
    whitespace_jaccard,
)


def test_slugify_basic() -> None:
    assert slugify("Hero's Call: Western Plaguelands!") == "hero-s-call-western-plaguelands"
    assert slugify("  Drudges... *Sigh*  ") == "drudges-sigh"
    assert slugify("") == ""


def test_slugify_separator_and_strip_options() -> None:
    assert slugify("In the RPG", separator="_") == "in_the_rpg"
    assert slugify("Foo!", strip_result=False) == "foo-"
    assert slugify("Foo!") == "foo"


def test_token_jaccard_significant_tokens_only() -> None:
    # short (<4 char) tokens are ignored; identical significant token sets -> 1.0
    assert token_jaccard("the cult of the damned", "cult damned") == 1.0
    assert token_jaccard("", "anything") == 0.0
    assert token_jaccard("alpha beta", "gamma delta") == 0.0


def test_whitespace_jaccard_empty_handling() -> None:
    assert whitespace_jaccard("", "") == 1.0  # both empty -> 1.0 (anti-verbatim contract)
    assert whitespace_jaccard("", "x") == 0.0
    assert whitespace_jaccard("a b c", "a b c") == 1.0
    assert whitespace_jaccard("a b", "b c") == 1.0 / 3.0


def test_max_similarity_against_sources() -> None:
    assert max_similarity_against_sources("a b c", []) == 0.0
    assert max_similarity_against_sources("a b c", ["x y", "a b c"]) == 1.0


def test_write_json_canonical_policy(tmp_path: Path) -> None:
    path = tmp_path / "out.json"
    write_json(path, {"name": "Café ’", "n": 1})
    raw = path.read_bytes()
    # unicode preserved (ensure_ascii=False), trailing newline, LF line endings.
    assert b"\\u" not in raw
    assert raw.endswith(b"\n")
    assert b"\r\n" not in raw
    assert read_json(path) == {"name": "Café ’", "n": 1}


def test_read_write_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "rt.json"
    obj = {"b": [1, 2, 3], "a": {"nested": True}}
    write_json(path, obj)
    assert read_json(path) == obj
