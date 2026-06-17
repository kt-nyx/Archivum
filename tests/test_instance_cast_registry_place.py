"""Tests for registry place rejection in instance key-character casts."""

from __future__ import annotations

from pipeline.generate.draft.instance_lint import cast_registry_place_violations


def test_cast_registry_place_violations_detects_place() -> None:
    violations = cast_registry_place_violations(["Darkmaster Gandling", "Caer Darrow"])
    assert len(violations) == 1
    assert "Caer Darrow" in violations[0]


def test_cast_registry_place_violations_ignores_characters() -> None:
    assert cast_registry_place_violations(["Darkmaster Gandling", "Rattlegore"]) == []
