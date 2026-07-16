from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _runner_module():
    path = Path(".vscode/run-incrementing-pipeline.py")
    spec = importlib.util.spec_from_file_location("run_incrementing_pipeline", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_run_prefix_copies_latest_matching_manifest_and_increments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner_module()
    runs_root = tmp_path / "runs"
    for number, contents in ((1, "old"), (3, "latest")):
        run_dir = runs_root / f"test-feralas-{number}"
        run_dir.mkdir(parents=True)
        (run_dir / "source_manifest.json").write_text(contents, encoding="utf-8")
    monkeypatch.setenv("WOW_LORE_ARTIFACTS_ROOT", str(runs_root))

    assert runner.prepare_next_run("test-feralas") == "test-feralas-4"
    assert (runs_root / "test-feralas-4" / "source_manifest.json").read_text(encoding="utf-8") == "latest"


def test_run_prefix_fails_before_creating_a_folder_without_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner_module()
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    monkeypatch.setenv("WOW_LORE_ARTIFACTS_ROOT", str(runs_root))

    with pytest.raises(RuntimeError, match="could not find source_manifest"):
        runner.prepare_next_run("test-feralas")
    assert not list(runs_root.iterdir())


def test_run_prefix_can_seed_a_new_family_from_a_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner_module()
    runs_root = tmp_path / "runs"
    seed_manifest = tmp_path / "westfall_manifest.json"
    seed_manifest.write_text("westfall", encoding="utf-8")
    monkeypatch.setenv("WOW_LORE_ARTIFACTS_ROOT", str(runs_root))

    assert runner.prepare_next_run("test-run-westfall", seed_manifest=seed_manifest) == "test-run-westfall-1"
    assert (
        runs_root / "test-run-westfall-1" / "source_manifest.json"
    ).read_text(encoding="utf-8") == "westfall"


def test_run_prefix_rejects_a_numbered_name() -> None:
    runner = _runner_module()
    with pytest.raises(RuntimeError, match="must not end with a number"):
        runner.prepare_next_run("test-feralas-1")
