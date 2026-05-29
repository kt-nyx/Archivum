"""Discovery pipeline package for wiki-first deterministic extraction."""

from .enrich import run_discovery_enrich
from .workflow import run_discovery_workflow

__all__ = ["run_discovery_workflow", "run_discovery_enrich"]
