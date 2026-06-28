from __future__ import annotations

from pipeline.common.text_normalize import normalize_display_payload, normalize_display_punctuation


def test_normalize_display_punctuation_ascii_forms() -> None:
    assert normalize_display_punctuation("Gandling\u2019s halls \u2014 cursed \u201clore\u201d") == (
        "Gandling's halls - cursed \"lore\""
    )


def test_normalize_display_payload_skips_reference_fields() -> None:
    payload = {
        "id": "zone-test\u2019s-id",
        "summary": "Gandling\u2019s halls \u2014 cursed.",
        "wiki_url": "https://example.test/Gandling%E2%80%99s",
        "history_sections": [
            {
                "heading": "Barov\u2019s Bargain",
                "body": "The keep\u2019s crypts \u2014 once sealed \u2014 opened.",
                "source_refs": [
                    {
                        "source_id": "src\u2019raw",
                        "locator": "section:lore\u2019 paragraph:1",
                    }
                ],
            }
        ],
        "provenance": {"history": [{"source_id": "src\u2019raw"}]},
    }

    normalized = normalize_display_payload(payload)

    assert normalized["id"] == "zone-test\u2019s-id"
    assert normalized["summary"] == "Gandling's halls - cursed."
    assert normalized["wiki_url"] == "https://example.test/Gandling%E2%80%99s"
    assert normalized["history_sections"][0]["heading"] == "Barov's Bargain"
    assert normalized["history_sections"][0]["body"] == "The keep's crypts - once sealed - opened."
    assert normalized["history_sections"][0]["source_refs"][0]["source_id"] == "src\u2019raw"
    assert normalized["provenance"]["history"][0]["source_id"] == "src\u2019raw"
