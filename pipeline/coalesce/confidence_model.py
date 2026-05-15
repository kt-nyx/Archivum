"""Confidence model for coalesced entity outputs."""

from __future__ import annotations


def compute_confidence(
    *,
    mode: str,
    source_count: int,
    claim_count: int,
    minimum: float,
) -> float:
    """Compute bounded coalesce confidence with simple coverage weighting."""
    source_factor = min(0.08, 0.02 * max(source_count - 1, 0))
    claim_factor = min(0.06, 0.01 * max(claim_count - 1, 0))
    mode_bias = 0.86 if mode == "openai" else 0.75
    return max(minimum, min(0.98, mode_bias + source_factor + claim_factor))
