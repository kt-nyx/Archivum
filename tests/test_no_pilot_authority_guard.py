"""No-pilot-authority guard (Slice 9, item 5).

A pilot subject name may appear in a developer run configuration or an evaluation fixture, never in
shared classification or selection logic. This guard parses every shared-runtime Python module
(``pipeline/`` and ``scripts/``) and flags a pilot subject name used inside an *executable string
literal* — the position a branch, lookup, registry, or filter would key off. Comments and
docstrings are excluded (they may use a pilot name as an illustrative example of a general
mechanism), and source-native data files (``*.json`` registries/harvests) are out of scope because
they carry harvested wiki vocabulary, not authored pilot logic.

This complements two existing guards:
- ``test_no_zone_specific_scaffolding`` forbids specific scaffolding ids in any shared file.
- ``test_pilot_prompt_leak_guard`` forbids pilot names in rendered LLM prompts.

Together they cover code, configuration, prompts, and the shared-logic boundary the plan requires.
"""

from __future__ import annotations

import ast
from pathlib import Path

# Distinctive pilot subject names and their id forms. The two universal player factions are
# game-wide vocabulary and are intentionally not pilot facts, so they are not listed here.
PILOT_SUBJECT_TOKENS = frozenset(
    token.casefold()
    for token in (
        "Western Plaguelands",
        "western_plaguelands",
        "zone-western-plaguelands",
        "Scholomance",
        "instance-scholomance",
        "Desolace",
        "zone-desolace",
        "Maraudon",
        "instance-maraudon",
        "Westfall",
        "zone-westfall",
    )
)

SCAN_ROOTS = (Path("pipeline"), Path("scripts"))


def _docstring_constant_ids(tree: ast.AST) -> set[int]:
    """Object ids of string Constant nodes that are module/class/function docstrings."""
    docstring_ids: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        body = getattr(node, "body", [])
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            docstring_ids.add(id(first.value))
    return docstring_ids


def _executable_string_literals(source: str) -> list[tuple[int, str]]:
    """Every string literal in executable position (docstrings excluded), with its line number."""
    tree = ast.parse(source)
    docstring_ids = _docstring_constant_ids(tree)
    literals: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in docstring_ids:
            continue
        literals.append((node.lineno, node.value))
    return literals


def test_no_pilot_subject_name_in_shared_logic() -> None:
    violations: list[str] = []
    for root in SCAN_ROOTS:
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            source = path.read_text(encoding="utf-8")
            for lineno, literal in _executable_string_literals(source):
                lowered = literal.casefold()
                for token in PILOT_SUBJECT_TOKENS:
                    if token in lowered:
                        violations.append(f"{path}:{lineno}: pilot name in code literal {token!r}")
    assert not violations, "pilot names must not drive shared logic:\n" + "\n".join(violations)


def test_guard_detects_a_planted_pilot_literal(tmp_path: Path) -> None:
    """Sanity: the guard flags a pilot name in an executable literal but not in a docstring."""
    planted = tmp_path / "planted.py"
    planted.write_text(
        '"""Docstring mentioning Scholomance is fine as an example."""\n'
        "SPECIAL_ZONES = ['Western Plaguelands']\n",
        encoding="utf-8",
    )
    literals = _executable_string_literals(planted.read_text(encoding="utf-8"))
    flagged = [
        text
        for _lineno, text in literals
        if any(token in text.casefold() for token in PILOT_SUBJECT_TOKENS)
    ]
    assert flagged == ["Western Plaguelands"]
