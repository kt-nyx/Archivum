#!/usr/bin/env python3
"""Generate pipeline/discovery/world_registry.json from Warcraft Wiki categories."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pipeline.discovery.world_registry import summarize_registry, write_world_registry


def main() -> None:
    parser = argparse.ArgumentParser(description="Build world_registry.json from Warcraft Wiki.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("pipeline/discovery/world_registry.json"),
        help="Output path for generated registry JSON",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print kind counts and sample entries after generation",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.35,
        help="Seconds to wait between wiki API requests (default: 0.35)",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Ignore and do not write the category fetch cache",
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=Path("pipeline/discovery/.world_registry_category_cache.json"),
        help="Path for resumable category member cache",
    )
    args = parser.parse_args()
    output = write_world_registry(
        args.output,
        sleep_seconds=args.sleep,
        cache_path=args.cache,
        use_cache=not args.no_cache,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    counts = summarize_registry(payload)
    print(f"Wrote {output} ({payload.get('entry_count', 0)} entries)")
    for kind, count in counts.items():
        print(f"  {kind}: {count}")
    if args.summary:
        print("\nSample zone entries:")
        shown = 0
        for row in payload.get("entries", []):
            if "zone" in row.get("kinds", []) and "instance" not in row.get("kinds", []):
                print(f"  - {row['title']}")
                shown += 1
                if shown >= 15:
                    break
        print("\nSample instance entries:")
        shown = 0
        for row in payload.get("entries", []):
            if "instance" in row.get("kinds", []):
                print(f"  - {row['title']}")
                shown += 1
                if shown >= 15:
                    break
        print("\nSample place entries:")
        shown = 0
        for row in payload.get("entries", []):
            if "place" in row.get("kinds", []) and "zone" not in row.get("kinds", []):
                print(f"  - {row['title']}")
                shown += 1
                if shown >= 15:
                    break
        print("\nSample person entries:")
        shown = 0
        for row in payload.get("entries", []):
            if "person" in row.get("kinds", []):
                print(f"  - {row['title']}")
                shown += 1
                if shown >= 15:
                    break
    if payload.get("entry_count", 0) < 50:
        print("WARNING: unexpectedly small registry; review API results", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
