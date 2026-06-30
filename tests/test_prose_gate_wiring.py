"""The prose gate is wired into the builder finalizers, not just unit-tested.

Each test forces a synthesizer (and its deterministic fallback) to emit one of the
two known artifact classes and asserts the artifact never survives into the page
output — the finalizer routes around it exactly as it does for a lint failure.
"""

from __future__ import annotations

import pipeline.generate.draft.pages.instance as instance_page
import pipeline.generate.draft.pages.zone as zone_page


def test_instance_overview_finalizer_rejects_script_mixed_synthesis(monkeypatch) -> None:
    # Cyrillic homoglyphs spliced into Latin prose: long enough to clear the word-count
    # lints, so only the prose gate can catch it.
    artifact = "The vault кеpt its гrim secrets " + " ".join(["guarded"] * 40) + "."
    monkeypatch.setattr(
        instance_page, "synthesize_instance_overview", lambda *a, **k: (artifact, ["s1"])
    )
    monkeypatch.setattr(
        instance_page, "fallback_instance_overview", lambda *a, **k: (artifact, ["s1"])
    )

    text, used, pool = instance_page._finalize_instance_overview(
        instance_name="Archive Vault",
        overview_pool=[{"snippet": "x", "source_id": "s1"}],
        zone_mention_pool=[],
    )
    assert text == ""
    assert used == []
    assert pool == []


def test_zone_at_a_glance_finalizer_rejects_dangling_terminal(monkeypatch) -> None:
    # Ends on a dangling preposition ("...toward.") — passes the passthrough lint
    # (has a terminator, capitalized start) so only the prose gate rejects it.
    artifact = "Crusaders and undead clashed across the frontier toward."
    monkeypatch.setattr(zone_page, "synthesize_at_a_glance", lambda *a, **k: (artifact, ["s1"]))
    monkeypatch.setattr(zone_page, "fallback_at_a_glance", lambda *a, **k: (artifact, ["s1"]))

    text, used = zone_page._finalize_at_a_glance(
        zone_name="Western Plaguelands",
        at_pool=[{"snippet": "x", "source_id": "s1"}],
        evidence_rows=[],
    )
    # Both synthesis and fallback were rejected, so the deterministic default stands.
    assert artifact not in text
    assert text.endswith("ruin left by past conflict.")
    assert used == []
