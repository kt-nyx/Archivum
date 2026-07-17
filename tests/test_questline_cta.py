from __future__ import annotations

import pytest

from pipeline.generate.draft import finalize_trace
from pipeline.generate.draft.card_lint import finalize_cta_hook, lint_cta_hook
from pipeline.generate.draft.pages.zone import _cta_contract_inputs
from pipeline.generate.draft.prose_synthesis import (
    filter_early_chain_evidence_pool,
    synthesize_questline_cta_hook,
)


def test_lint_cta_hook_accepts_complete_zone_leading_declarative_clause() -> None:
    # Zone words are valid when they are the clause subject; CTA generation must not remove them.
    assert not lint_cta_hook("Glasswarren faces a spreading threat beyond its gates.")


def test_lint_cta_hook_accepts_imperative_clause() -> None:
    assert not lint_cta_hook("Rally the wardens and secure the signal fires.")


@pytest.mark.parametrize(
    ("hook", "reason"),
    [
        ("Rally the wardens. Secure the signal fires.", "exactly one sentence"),
        ("Across the ruined bridge.", "finite predicate or imperative"),
        ("Rally the wardens -.", "malformed join"),
        ("Answer the call to, where the threat gathers.", "mid-sentence gap"),
        ("Rally the wardens before.", "truncated"),
    ],
)
def test_lint_cta_hook_rejects_incomplete_or_malformed_final_clause(hook: str, reason: str) -> None:
    assert any(reason in issue for issue in lint_cta_hook(hook))


def test_lint_cta_hook_rejects_excluded_outcome_phrase() -> None:
    assert any(
        "excluded outcome" in issue
        for issue in lint_cta_hook(
            "Rally the wardens after the citadel falls.",
            forbidden_phrases=("the citadel falls",),
        )
    )


def test_finalize_cta_hook_trims_to_complete_sentence() -> None:
    hook = (
        "Rally the wardens at the signal fires before the outer defenses fail. Secure the ridge "
        "and answer the captain's command before the fortress falls."
    )
    out = finalize_cta_hook(hook, max_words=12)
    assert out.endswith((".", "!", "?"))
    assert not out.rstrip(".").endswith("captain's")
    assert lint_cta_hook(out) == []


def test_finalize_cta_hook_repairs_dangling_before_tail() -> None:
    out = finalize_cta_hook("Rally the wardens before.")
    assert out == "Rally the wardens."
    assert lint_cta_hook(out) == []


def test_filter_early_chain_evidence_pool_never_substitutes_late_evidence() -> None:
    scoped = filter_early_chain_evidence_pool(
        [{"quest_node_id": "late", "snippet": "A late outcome."}],
        ["entry", "middle", "late"],
        arc_title="The Lantern Accord",
    )
    assert scoped == []


def test_cta_contract_inputs_select_only_the_matching_slice_four_card_setup() -> None:
    setup, excluded = _cta_contract_inputs(
        {
            "source_anchor_refs": [
                {
                    "kind": "questline_setup",
                    "metadata_id": "metadata-selected",
                    "cluster_id": "arc-selected",
                    "setup_quest_refs": ["quest-entry"],
                    "setup_snippets": ["Wardens request aid at the lantern tower."],
                },
                {
                    "kind": "questline_setup",
                    "metadata_id": "metadata-other",
                    "cluster_id": "arc-other",
                    "setup_quest_refs": ["quest-other"],
                    "setup_snippets": ["An unrelated campaign begins elsewhere."],
                },
            ],
            "excluded_outcome_hints": [
                {"cluster_id": "arc-selected", "outcome_snippets": ["The tower later collapses."]},
                {"cluster_id": "arc-other", "outcome_snippets": ["Another campaign resolves."]},
            ],
        },
        metadata_id="metadata-selected",
        card_id="card-selected",
        cluster_id="arc-selected",
    )
    assert setup == [
        {
            "quest_ref": "quest-entry",
            "source_id": "quest-entry",
            "snippet": "Wardens request aid at the lantern tower.",
        }
    ]
    assert excluded == ("The tower later collapses.",)


@pytest.mark.parametrize("no_llm", ["1"])
def test_synthesize_cta_uses_setup_evidence_and_records_final_fallback(
    monkeypatch, no_llm: str
) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", no_llm)
    finalize_trace.begin("zone-synthetic")
    hook, used = synthesize_questline_cta_hook(
        [{"quest_node_id": "late", "snippet": "The citadel falls after the final battle."}],
        arc_title="The Lantern Accord",
        start_anchor="First Light",
        faction="shared",
        chain_refs=["entry", "late"],
        setup_evidence=[
            {
                "quest_ref": "entry",
                "source_id": "entry",
                "snippet": "Wardens ask for aid at the first signal fire.",
            }
        ],
        excluded_outcome_phrases=("the citadel falls",),
    )
    records = finalize_trace.drain()
    assert hook == "Begin with First Light to follow this storyline."
    assert used == ["entry"]
    assert lint_cta_hook(hook, forbidden_phrases=("the citadel falls",)) == []
    assert records == [
        {
            "entity_id": "zone-synthetic",
            "stage": "questline_cta.finalize",
            "outcome": "fallback_no_llm",
            "final_text": hook,
            "final_lint_issues": [],
            "initial_lint_issues": [],
            "retry_lint_issues": [],
            "setup_evidence_ids": ["entry"],
        }
    ]


@pytest.mark.parametrize("no_llm", ["1"])
def test_synthesize_cta_missing_setup_uses_complete_metadata_grounded_fallback(
    monkeypatch, no_llm: str
) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", no_llm)
    hook, used = synthesize_questline_cta_hook(
        [],
        arc_title="The Lantern Accord",
        start_anchor="First Light",
        faction="shared",
        chain_refs=["entry"],
    )
    assert hook == "Begin with First Light to follow this storyline."
    assert used == []
    assert lint_cta_hook(hook) == []


def test_synthesize_cta_retries_once_then_records_the_validated_rewrite(monkeypatch) -> None:
    from types import SimpleNamespace

    import pipeline.generate.draft.prose_synthesis as prose_synthesis

    responses = iter(
        [
            {"summary": "Rally the wardens. Secure the signal fires.", "used_evidence_ids": ["p1"]},
            {"summary": "Rally the wardens and secure the signal fires.", "used_evidence_ids": ["p1"]},
        ]
    )
    monkeypatch.setattr(prose_synthesis, "load_ai_settings", lambda: SimpleNamespace(openai_ready=True))
    monkeypatch.setattr(prose_synthesis, "llm_json_with_retry", lambda **_: next(responses))
    finalize_trace.begin("zone-synthetic")
    hook, used = synthesize_questline_cta_hook(
        [],
        arc_title="The Lantern Accord",
        start_anchor="First Light",
        faction="shared",
        chain_refs=["entry"],
        setup_evidence=[{"quest_ref": "entry", "source_id": "entry", "snippet": "Signal fires need aid."}],
    )
    records = finalize_trace.drain()
    assert hook == "Rally the wardens and secure the signal fires."
    assert used == ["entry"]
    assert records[0]["outcome"] == "retry_accepted"
    assert "exactly one sentence" in records[0]["initial_lint_issues"][0]
    assert records[0]["final_lint_issues"] == []


def test_synthesize_cta_uses_validated_fallback_after_two_generation_failures(monkeypatch) -> None:
    from types import SimpleNamespace

    import pipeline.generate.draft.prose_synthesis as prose_synthesis

    monkeypatch.setattr(prose_synthesis, "load_ai_settings", lambda: SimpleNamespace(openai_ready=True))
    monkeypatch.setattr(
        prose_synthesis,
        "llm_json_with_retry",
        lambda **_: (_ for _ in ()).throw(RuntimeError("synthetic failure")),
    )
    finalize_trace.begin("zone-synthetic")
    hook, used = synthesize_questline_cta_hook(
        [],
        arc_title="The Lantern Accord",
        start_anchor="First Light",
        faction="shared",
        chain_refs=["entry"],
        setup_evidence=[{"quest_ref": "entry", "source_id": "entry", "snippet": "Signal fires need aid."}],
    )
    records = finalize_trace.drain()
    assert hook == "Begin with First Light to follow this storyline."
    assert used == ["entry"]
    assert records[0]["outcome"] == "fallback_after_retry"
    assert records[0]["initial_lint_issues"] == ["synthesis_error:RuntimeError"]
    assert records[0]["retry_lint_issues"] == ["rewrite_error:RuntimeError"]
    assert records[0]["final_lint_issues"] == []
