"""Launch the full pipeline with the next numbered local run id."""

from __future__ import annotations

import argparse
import os
import re
import shutil
from pathlib import Path
from typing import Any

from pipeline.orchestrator.flow import run_pipeline_flow


def _artifacts_runs_root() -> Path:
    raw = os.environ.get("WOW_LORE_ARTIFACTS_ROOT", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.cwd() / "artifacts" / "runs").resolve()


def _split_numbered_run_id(run_id: str) -> tuple[str, int]:
    match = re.fullmatch(r"(.+?)(\d+)", run_id.strip())
    if not match:
        raise RuntimeError(f"base run id must end with a number: {run_id!r}")
    return match.group(1), int(match.group(2))


def _normalize_run_prefix(run_prefix: str) -> str:
    prefix = run_prefix.strip().rstrip("-")
    if not prefix:
        raise RuntimeError("run prefix must contain text before the numeric suffix")
    if re.search(r"\d$", prefix):
        raise RuntimeError(
            f"run prefix must not end with a number: {run_prefix!r}; use --base-run-id instead"
        )
    return f"{prefix}-"


def _numbered_run_dirs(runs_root: Path, prefix: str) -> list[tuple[int, Path]]:
    if not runs_root.exists():
        return []
    matches: list[tuple[int, Path]] = []
    pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    for child in runs_root.iterdir():
        if not child.is_dir():
            continue
        match = pattern.fullmatch(child.name)
        if match:
            matches.append((int(match.group(1)), child))
    return sorted(matches)


def prepare_next_run(
    run_prefix: str,
    *,
    initial_number: int = 1,
    seed_manifest: Path | None = None,
) -> str:
    runs_root = _artifacts_runs_root()
    prefix = _normalize_run_prefix(run_prefix)
    run_dirs = _numbered_run_dirs(runs_root, prefix)

    highest_number = max([initial_number - 1, *(number for number, _path in run_dirs)])
    next_run_id = f"{prefix}{highest_number + 1}"

    manifest_source = next(
        (
            path / "source_manifest.json"
            for _number, path in sorted(run_dirs, reverse=True)
            if (path / "source_manifest.json").exists()
        ),
        None,
    )
    if manifest_source is None and seed_manifest is not None:
        candidate = seed_manifest.expanduser().resolve()
        if not candidate.is_file():
            raise RuntimeError(f"seed manifest does not exist or is not a file: {candidate}")
        manifest_source = candidate
    if manifest_source is None:
        raise RuntimeError(
            f"could not find source_manifest.json in any existing {prefix}N run under {runs_root}; "
            "provide --seed-manifest to initialize a new run family"
        )

    next_run_dir = runs_root / next_run_id
    next_run_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(manifest_source, next_run_dir / "source_manifest.json")
    print(f"Prepared run_id={next_run_id}")
    print(f"Copied manifest from {manifest_source}")
    return next_run_id


def _fact_check_profile(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"off", "warn", "strict"}:
        raise argparse.ArgumentTypeError("expected one of: off, warn, strict")
    return normalized


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare the next numbered run folder, then run the lore pipeline."
    )
    run_source = parser.add_mutually_exclusive_group(required=True)
    run_source.add_argument(
        "--run-prefix",
        help="Run-family prefix, e.g. test-feralas. The helper creates test-feralas-1, then -2.",
    )
    run_source.add_argument(
        "--base-run-id",
        help="Backward-compatible numbered base id, e.g. test-feralas-1.",
    )
    parser.add_argument(
        "--fact-check-profile",
        default="warn",
        type=_fact_check_profile,
        choices=("off", "warn", "strict"),
    )
    parser.add_argument("--fact-check-web-search", action="store_true")
    parser.add_argument("--fact-check-max-web-results", default=3, type=int)
    parser.add_argument("--no-llm-fact-check", action="store_true")
    parser.add_argument("--fact-check-llm-model", default="gpt-5.5")
    parser.add_argument("--max-entity-concurrency", default=4, type=int)
    parser.add_argument("--retries-per-stage", default=1, type=int)
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--release-gate", action="store_true")
    parser.add_argument(
        "--seed-manifest",
        type=Path,
        help=(
            "Manifest to copy only when this run family has no prior source_manifest.json. "
            "Useful for the first run of an evaluation subject."
        ),
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.run_prefix:
        run_id = prepare_next_run(args.run_prefix, seed_manifest=args.seed_manifest)
    else:
        prefix, initial_number = _split_numbered_run_id(args.base_run_id)
        run_id = prepare_next_run(
            prefix, initial_number=initial_number, seed_manifest=args.seed_manifest
        )
    result: dict[str, Any] = run_pipeline_flow(
        run_id=run_id,
        fact_check_profile=args.fact_check_profile,
        fact_check_web_search=args.fact_check_web_search,
        fact_check_max_web_results=args.fact_check_max_web_results,
        no_llm_fact_check=args.no_llm_fact_check,
        fact_check_llm_model=args.fact_check_llm_model,
        max_entity_concurrency=args.max_entity_concurrency,
        retries_per_stage=args.retries_per_stage,
        verbose=args.verbose,
        release_gate=args.release_gate,
    )
    print(
        f"run_id={result['run_id']} validate_passed={result['validate']['passed']} "
        f"profile={args.fact_check_profile} release_gate={args.release_gate}"
    )


if __name__ == "__main__":
    main()
