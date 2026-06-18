"""Audit gold fixtures for retail correctness + contract conformance (WS-E).

Gold fixtures are canonical: this script **reports** discrepancies; it never rewrites
them. Re-run it after wiki revisions or when adding fixtures.

Offline checks (CI-safe, no network):
- contract + release-gate validation of the instance-page gold (0 hard fails)
- Classic-contamination scan: ``(Classic)`` markers in wiki refs/urls + a small,
  documented denylist of known Classic-only entities
- cross-fixture consistency: zone-questline gold ids ↔ questline registry arcs

Online check (``--online``; hits the live wiki via the ingest fetch, using the
INGEST-CAT category capture):
- per-entity MediaWiki categories; flags pages in Classic/legacy/removed categories
  as the authoritative retail-eligibility signal.

Usage:
    python -m scripts.audit_gold_fixtures            # offline report
    python -m scripts.audit_gold_fixtures --online   # + live category check
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import httpx

from pipeline.common.io import read_json
from pipeline.common.retail import CLASSIC_CATEGORY_MARKERS, KNOWN_CLASSIC_ENTITIES
from pipeline.ingest.fetch_wiki import _categories_from_parse_blob
from pipeline.validate.engine import validate_payload

PILOT_DIR = Path("tests/fixtures/pilot")
INSTANCE_GOLD = PILOT_DIR / "instance_page_scholomance_gold.json"
ZONE_QUESTLINE_GOLD = PILOT_DIR / "zone_page_western_plaguelands_gold.json"
QUESTLINE_REGISTRY = PILOT_DIR / "western_plaguelands_questline_registry.json"

# Retail-eligibility signals are centralized in pipeline.common.retail (S3):
# - KNOWN_CLASSIC_ENTITIES: documented offline backstop denylist (clean-href Classic NPCs).
# - CLASSIC_CATEGORY_MARKERS: authoritative wiki-category substrings (used by --online).


@dataclass(frozen=True)
class Finding:
    level: str  # "error" | "warn"
    fixture: str
    code: str
    message: str


def _norm(text: str) -> str:
    return " ".join(str(text).strip().casefold().split())


def _classic_ref(ref: str) -> bool:
    return "(classic" in str(ref).casefold()


def audit_instance_page_gold(path: Path = INSTANCE_GOLD) -> list[Finding]:
    findings: list[Finding] = []
    name = path.name
    payload = read_json(path)
    report = validate_payload(
        "instance_page", payload, {"release_gate": True, "fact_check_profile": "off"}
    )
    if not report.passed:
        for issue in report.issues:
            if issue.severity.value == "hard-fail":
                findings.append(
                    Finding("error", name, "contract", f"{issue.code}: {issue.message}")
                )
    for card in payload.get("key_characters", []):
        if not isinstance(card, dict):
            continue
        nm = card.get("name", "")
        if _norm(nm) in KNOWN_CLASSIC_ENTITIES:
            findings.append(Finding("error", name, "classic_entity", f"Classic-only cast: {nm}"))
        if _classic_ref(card.get("wiki_ref", "")):
            findings.append(
                Finding("error", name, "classic_ref", f"Classic wiki_ref: {card.get('wiki_ref')}")
            )
    for ref in payload.get("glossary_refs", []):
        if isinstance(ref, dict) and _norm(ref.get("label", "")) in KNOWN_CLASSIC_ENTITIES:
            findings.append(
                Finding("error", name, "classic_glossary", f"Classic-only term: {ref.get('label')}")
            )
    return findings


def audit_zone_questline_gold(
    zone_path: Path = ZONE_QUESTLINE_GOLD, registry_path: Path = QUESTLINE_REGISTRY
) -> list[Finding]:
    findings: list[Finding] = []
    name = zone_path.name
    zone = read_json(zone_path)
    cards = zone.get("major_questlines", [])
    if not isinstance(cards, list) or not cards:
        findings.append(Finding("error", name, "structure", "major_questlines is empty"))
        return findings
    for card in cards:
        if not isinstance(card, dict):
            continue
        cid = card.get("id", "?")
        for field in ("id", "title", "faction", "start_anchor", "chain_refs", "wiki_refs"):
            if not card.get(field):
                findings.append(Finding("error", name, "structure", f"{cid} missing {field}"))
        for ref in card.get("wiki_refs", []):
            if _classic_ref(ref):
                findings.append(
                    Finding("error", name, "classic_ref", f"{cid} Classic wiki_ref: {ref}")
                )
    # Cross-fixture: every gold card id should exist as an included registry arc.
    registry = read_json(registry_path)
    arc_ids = {
        str(arc.get("id"))
        for arc in registry.get("included_arcs", [])
        if isinstance(arc, dict) and arc.get("id")
    }
    if arc_ids:
        for card in cards:
            cid = str(card.get("id", ""))
            if cid and cid not in arc_ids:
                findings.append(
                    Finding("warn", name, "registry_parity", f"gold arc '{cid}' not in registry")
                )
    return findings


def _collect_entities(path: Path) -> dict[str, str]:
    """Map entity label -> wiki url/ref from a gold fixture (for the online check)."""
    entities: dict[str, str] = {}
    payload = read_json(path)
    for card in payload.get("key_characters", []) if isinstance(payload, dict) else []:
        if isinstance(card, dict) and card.get("name"):
            entities[str(card["name"])] = str(card.get("wiki_ref", ""))
    return entities


def audit_offline() -> list[Finding]:
    return audit_instance_page_gold() + audit_zone_questline_gold()


def audit_online() -> list[Finding]:
    """Fetch live categories for instance-gold entities; flag Classic/legacy pages."""
    findings: list[Finding] = []
    for label, ref in _collect_entities(INSTANCE_GOLD).items():
        title = ref.rsplit("/wiki/", 1)[-1] if ref else label.replace(" ", "_")
        api = (
            "https://warcraft.wiki.gg/api.php?action=parse&prop=categories"
            f"&format=json&formatversion=2&page={quote(title)}"
        )
        gold = INSTANCE_GOLD.name
        try:
            data = httpx.get(api, headers={"User-Agent": "wow-lore-audit/1.0"}, timeout=30).json()
        except Exception as exc:  # noqa: BLE001 - audit tool, network best-effort
            findings.append(Finding("warn", gold, "online_fetch", f"{label}: {exc!r}"))
            continue
        cats = [c.casefold() for c in _categories_from_parse_blob(data.get("parse", {}))]
        hits = [c for c in cats if any(m in c for m in CLASSIC_CATEGORY_MARKERS)]
        if hits:
            findings.append(Finding("error", gold, "classic_category", f"{label}: {hits}"))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit gold fixtures (WS-E).")
    parser.add_argument("--online", action="store_true", help="also run the live category check")
    args = parser.parse_args(argv)

    findings = audit_offline()
    if args.online:
        findings += audit_online()

    if not findings:
        print("gold fixture audit: OK (no findings)")
        return 0
    errors = [f for f in findings if f.level == "error"]
    for finding in findings:
        print(f"[{finding.level}] {finding.fixture} {finding.code}: {finding.message}")
    print(f"\n{len(errors)} error(s), {len(findings) - len(errors)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
