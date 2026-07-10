"""Guard the runtime boundary against reintroducing a privileged pilot zone."""

from __future__ import annotations

from pathlib import Path

# Pilot names are allowed in developer run configurations.  This guard protects
# shared runtime logic, prompts, and shipped addon data instead.
RUNTIME_ROOTS = (Path("pipeline"), Path("scripts"), Path("addon"))
FORBIDDEN = (
    "pilot_questline_registry",
    "tests/fixtures/pilot",
    "zone-western-plaguelands",
    "test-run-wpl",
    "known_classic_entities",
)


def test_runtime_has_no_wpl_specific_scaffolding() -> None:
    violations: list[str] = []
    for root in RUNTIME_ROOTS:
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".lua", ".json"}:
                continue
            if path.name == "world_registry.json":
                continue
            text = path.read_text(encoding="utf-8").casefold()
            for token in FORBIDDEN:
                if token in text:
                    violations.append(f"{path}: {token}")
    assert not violations, "\n".join(violations)
