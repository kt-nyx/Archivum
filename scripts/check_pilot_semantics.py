#!/usr/bin/env python3
"""Deprecated wrapper — use check_run_semantics.py."""

from __future__ import annotations

import sys
from pathlib import Path

from check_run_semantics import check_run


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: check_pilot_semantics.py <run-root>")
        print("Prefer: python scripts/check_run_semantics.py <run-root> [--zone-id ZONE]")
        sys.exit(2)
    check_run(Path(sys.argv[1]))


if __name__ == "__main__":
    main()
