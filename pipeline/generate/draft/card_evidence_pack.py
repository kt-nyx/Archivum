"""Per-card evidence packs and claim-level grounding (generalization recovery Slice 7).

Card synthesis previously drew from whole-paragraph fallback pools that could describe a
*different* entity (a same-name page, a general zone pool) or support only part of a compound
claim. This module builds one typed evidence pack per **selected** card — never per crawled
paragraph — so a card's defining sentence is grounded in direct identity evidence, related
evidence is admitted only with an explicit preserved direction, and the paragraph ids that back
provenance resolve to the card's own subject.

The builder is deliberately card-type agnostic: each page builder resolves *which* evidence items
directly own the card's subject (exact id ownership) versus which merely mention it, and this
module records the pack, runs the targeted claim work on the identity evidence only, and applies
the compound-support check. An empty identity set yields an ``insufficient_identity_evidence``
pack, which the caller turns into a deterministic drop or a neutral structural fallback — a
same-name or general pool can never silently establish the card's identity.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from typing import Any

from pipeline.common.linguistics import (
    action_relations,
    coordinated_finite_clause_split,
    linguistic_tokens,
)
from pipeline.common.text_normalize import clean_wiki_snippet
from pipeline.contracts.models import (
    CardClaimView,
    CardEvidencePackArtifact,
    CardEvidencePackDecision,
    CardEvidencePackSufficiency,
    CardEvidenceRef,
    CardEvidenceRole,
)
from pipeline.generate.draft.claim_routing import CLAIM_VIEW_KEY
from pipeline.generate.draft.evidence_identity import evidence_id_for_item

CARD_EVIDENCE_PACK_SCHEMA_VERSION = "card_evidence_pack.v1"

_WORD_RE = re.compile(r"[\w']+", re.UNICODE)

# The pack claim extractor is invoked once per identity paragraph of a *selected* card. It is the
# single seam where post-selection claim work happens for the location/faction/questline families
# that are cost-scoped out of the enrich-time LLM claim pass, so unselected crawl paragraphs never
# reach it (Slice 7, task 2).
PackClaimExtractor = Callable[[dict[str, Any]], list[dict[str, Any]]]


def _name_tokens(name: str) -> list[str]:
    return [token.lower() for token in _WORD_RE.findall(name) if token]


def _name_hit(text: str, name: str) -> bool:
    """True when ``name`` (or its multi-word phrase) appears in ``text`` on word boundaries.

    A single-token name must match that word; a multi-word name matches either its full phrase or
    its head/first significant token, so "Redstone Keep" is recognized in "The Redstone garrison"
    without over-matching an unrelated "keep the peace" verb — the caller's fixtures own identity,
    and this only decides clause grounding.
    """
    tokens = _name_tokens(name)
    if not tokens:
        return False
    haystack = text.lower()
    words = set(_WORD_RE.findall(haystack))
    if len(tokens) == 1:
        return tokens[0] in words
    phrase = " ".join(tokens)
    if phrase in haystack:
        return True
    # Multi-word: a proper-name head/first content token is a confident hit (both must be present
    # somewhere in the clause to avoid matching a lone generic word like "keep").
    return tokens[0] in words and tokens[-1] in words


def _clause_has_competing_proper_agent(clause: str, subject_name: str) -> bool:
    """True when the clause's grammatical agent is a proper noun that is not the card's subject.

    Uses subject-verb dependency roles (agents) plus proper-noun POS read from the *full clause*
    parse — an agent phrase must never be re-analyzed in isolation, where spaCy mislabels a bare
    unknown name ("Vexthar") as a common noun. A clause whose actor is a different named entity
    ("Lady Vex rules the north") cannot ground a card about another subject; a pronoun/shared-subject
    continuation ("...and later guarded the pass") has no proper agent and still grounds the subject.
    """
    proper_surface = {
        token.text.lower() for token in linguistic_tokens(clause) if token.pos == "PROPN"
    }
    if not proper_surface:
        return False
    subject_tokens = set(_name_tokens(subject_name))
    agent_proper_tokens: set[str] = set()
    for relation in action_relations(clause):
        for agent in relation.agents:
            for token in _WORD_RE.findall(agent.lower()):
                if token in proper_surface:
                    agent_proper_tokens.add(token)
    if not agent_proper_tokens:
        return False
    # Competing when some proper-noun agent token is not part of the subject's own name.
    return any(token not in subject_tokens for token in agent_proper_tokens)


def _clause_grounds_subject(clause: str, subject_name: str) -> bool:
    if not clause.strip():
        return False
    if _name_hit(clause, subject_name):
        return True
    # No direct mention: admit the clause only if it is not asserting a *different* named actor.
    return not _clause_has_competing_proper_agent(clause, subject_name)


def _support_check(claim_text: str, subject_name: str) -> tuple[str, list[str], bool]:
    """Split a compound claim and keep only the clauses grounded in the card's subject.

    Returns ``(admitted_text, dropped_clauses, supported)``. A single-subject claim passes whole;
    a compound claim whose second clause introduces an unrelated actor is *split* (the grounded
    clause is kept, the other recorded as dropped); a claim with no grounded clause is *rejected*
    (``supported`` is ``False``) so it can never carry the card's defining sentence.
    """
    text = clean_wiki_snippet(claim_text)
    if not text:
        return "", [], False
    if not subject_name.strip():
        # No subject to check against: the caller's id-ownership already scoped this evidence to the
        # card, so the claim is admitted whole rather than dropped on an uncheckable name.
        return text, [], True
    clauses = coordinated_finite_clause_split(text) or [text]
    admitted: list[str] = []
    dropped: list[str] = []
    for clause in clauses:
        cleaned = clause.strip()
        if not cleaned:
            continue
        if _clause_grounds_subject(cleaned, subject_name):
            admitted.append(cleaned)
        else:
            dropped.append(cleaned)
    if not admitted:
        return "", dropped, False
    return " ".join(admitted).strip(), dropped, True


def default_pack_claim_extractor(item: dict[str, Any]) -> list[dict[str, Any]]:
    """Route claim views for one identity paragraph, or fall back to its cleaned snippet.

    Reuses the enrich-time claim views already attached to the paragraph when present; otherwise a
    single deterministic claim from the paragraph snippet stands in, so a pool that was cost-scoped
    out of the LLM claim pass (faction/location profile) still produces support-checked claims for
    the bounded, selected set.
    """
    views = item.get(CLAIM_VIEW_KEY)
    if isinstance(views, list) and views:
        out: list[dict[str, Any]] = []
        for view in views:
            if not isinstance(view, dict):
                continue
            claim_text = str(view.get("claim_text") or view.get("snippet") or "").strip()
            if not claim_text:
                continue
            out.append(
                {
                    "claim_id": str(view.get("claim_id", "")).strip(),
                    "claim_text": claim_text,
                    "evidence_id": str(view.get("canonical_evidence_id", "")).strip()
                    or evidence_id_for_item(item),
                }
            )
        return out
    snippet = clean_wiki_snippet(str(item.get("snippet", "")))
    if not snippet:
        return []
    return [{"claim_id": "", "claim_text": snippet, "evidence_id": evidence_id_for_item(item)}]


def _owner_subject_id(item: dict[str, Any]) -> str:
    for key in ("faction_id", "location_id", "character_id", "cluster_id", "subject_id"):
        value = str(item.get(key, "")).strip()
        if value:
            return value
    return ""


def build_card_evidence_pack(
    *,
    card_id: str,
    card_type: str,
    subject_id: str,
    subject_name: str,
    identity_items: Sequence[dict[str, Any]],
    relationship_items: Sequence[dict[str, Any]] = (),
    claim_extractor: PackClaimExtractor | None = None,
) -> CardEvidencePackDecision:
    """Construct the typed evidence pack for one selected card.

    ``identity_items`` must already be scoped to the card's subject by exact id ownership (the
    caller owns that judgment). ``relationship_items`` mention the subject but are owned elsewhere;
    they are recorded with their preserved direction and never contribute identity or claim views.
    The claim extractor runs on identity paragraphs only, confining post-selection claim work to
    material that reaches the user.
    """
    extractor = claim_extractor or default_pack_claim_extractor

    identity_refs: list[CardEvidenceRef] = []
    provenance_ids: list[str] = []
    seen_ids: set[str] = set()
    claim_views: list[CardClaimView] = []
    for item in identity_items:
        evidence_id = evidence_id_for_item(item)
        if not evidence_id:
            continue
        if evidence_id not in seen_ids:
            seen_ids.add(evidence_id)
            provenance_ids.append(evidence_id)
            identity_refs.append(
                CardEvidenceRef(
                    role=CardEvidenceRole.IDENTITY,
                    evidence_id=evidence_id,
                    source_id=str(item.get("source_id", "")).strip(),
                    owner_subject_id=subject_id,
                    direction="identity",
                )
            )
        for claim in extractor(item):
            claim_text = str(claim.get("claim_text", "")).strip()
            if not claim_text:
                continue
            admitted, dropped, supported = _support_check(claim_text, subject_name)
            if not supported or not admitted:
                # A claim with no clause grounded in the card's subject is rejected outright — it
                # cannot become the card's defining sentence.
                continue
            claim_views.append(
                CardClaimView(
                    claim_id=str(claim.get("claim_id", "")).strip(),
                    evidence_id=str(claim.get("evidence_id", "")).strip() or evidence_id,
                    claim_text=admitted,
                    supported=True,
                    dropped_clauses=dropped,
                )
            )

    relationship_refs: list[CardEvidenceRef] = []
    for item in relationship_items:
        evidence_id = evidence_id_for_item(item)
        if not evidence_id:
            continue
        owner = _owner_subject_id(item)
        relationship_refs.append(
            CardEvidenceRef(
                role=CardEvidenceRole.RELATIONSHIP,
                evidence_id=evidence_id,
                source_id=str(item.get("source_id", "")).strip(),
                owner_subject_id=owner,
                direction="mentions_subject",
            )
        )

    if not identity_refs:
        return CardEvidencePackDecision(
            card_id=card_id,
            card_type=card_type,  # type: ignore[arg-type]
            subject_id=subject_id,
            subject_name=subject_name,
            sufficiency=CardEvidencePackSufficiency.INSUFFICIENT_IDENTITY_EVIDENCE,
            reason="no direct identity evidence for card subject",
            identity_evidence=[],
            relationship_evidence=relationship_refs,
            claim_views=[],
            provenance_ids=[],
        )

    return CardEvidencePackDecision(
        card_id=card_id,
        card_type=card_type,  # type: ignore[arg-type]
        subject_id=subject_id,
        subject_name=subject_name,
        sufficiency=CardEvidencePackSufficiency.OK,
        reason="",
        identity_evidence=identity_refs,
        relationship_evidence=relationship_refs,
        claim_views=claim_views,
        provenance_ids=provenance_ids,
    )


def pack_is_sufficient(pack: CardEvidencePackDecision) -> bool:
    return pack.sufficiency == CardEvidencePackSufficiency.OK


def build_card_evidence_pack_artifact(
    packs: Sequence[CardEvidencePackDecision],
) -> dict[str, Any]:
    """Serialize the versioned, fail-fast card-evidence-pack sidecar payload."""
    return CardEvidencePackArtifact(decisions=list(packs)).model_dump(mode="json")


def load_card_evidence_pack_artifact(
    data: dict[str, Any],
    *,
    artifact_name: str = "card_evidence_pack_decisions.json",
) -> CardEvidencePackArtifact:
    """Clean-break reader: accept exactly the current schema version, else fail with a diagnostic.

    Historic runs are regenerated when inspected — this is a contract check, not a migration path.
    """
    version = data.get("schema_version") if isinstance(data, dict) else None
    if version != CARD_EVIDENCE_PACK_SCHEMA_VERSION:
        raise ValueError(
            f"{artifact_name}: expected schema_version "
            f"{CARD_EVIDENCE_PACK_SCHEMA_VERSION!r} from producer 'draft_writer', got "
            f"{version!r}; regenerate this run's draft stage"
        )
    return CardEvidencePackArtifact.model_validate(data)
