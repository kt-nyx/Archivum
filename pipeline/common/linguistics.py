"""One home for deterministic English grammar analysis (generalization refactor Slice 4).

This module is the only place in the codebase that imports the NLP library. It wraps the
pinned spaCy pipeline (``spacy==3.8.13`` + ``en_core_web_sm`` 3.8.0, both pinned in
``pyproject.toml``) and exposes project-level plain-Python data structures instead of raw
library objects.

Design constraints (the Slice 4 contract):

- **Features only.** The wrapper reports grammar features (sentence boundaries, POS, lemmas,
  morphology, dependencies, tense/imperative signals). It never decides faction identity,
  location type, temporal scope, support/contradiction, or spoiler safety — those are domain
  judgments and live with wiki structure, the world registry, or LLM calls.
- **No fallback.** Failing to load the pinned model raises :class:`LinguisticsModelError`.
  The model is a standard dev/CI dependency; silently degrading to regex behaviour would let
  production and tests diverge invisibly.
- **Conservative with names.** Proper nouns and wiki identifiers stay as surface text unless
  the caller explicitly asks for lemmas (:func:`lemmatized_content_tokens` is that explicit
  ask, for retrieval/fallback scoring only — never for IDs, titles, or provenance strings).
- **Auditable.** Every helper returns deterministic plain values with enough feature detail
  to write decision records; :func:`describe` renders the full analysis for reviewers.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from spacy.language import Language
    from spacy.tokens import Doc, Token

_MODEL_NAME = "en_core_web_sm"
# NER is excluded: entity identity is domain semantics (world registry / LLM territory), and
# no wrapper helper reads entity annotations. Everything else (tok2vec, tagger, parser,
# attribute_ruler, lemmatizer) feeds the grammar features exposed here.
_EXCLUDED_PIPES = ("ner",)

_SUBJECT_DEPS = frozenset({"nsubj", "nsubjpass", "csubj", "csubjpass", "expl"})
_CONTENT_POS = frozenset({"NOUN", "PROPN", "VERB", "ADJ", "ADV"})


class LinguisticsModelError(RuntimeError):
    """The pinned NLP model is unavailable. There is deliberately no fallback path."""


@lru_cache(maxsize=1)
def _nlp() -> Language:
    try:
        import spacy
    except ImportError as exc:  # pragma: no cover - install-state failure, not logic
        raise LinguisticsModelError(
            "spacy is not installed; it is a pinned project dependency "
            "(pip install into the project venv per pyproject.toml)."
        ) from exc
    try:
        return spacy.load(_MODEL_NAME, exclude=list(_EXCLUDED_PIPES))
    except OSError as exc:  # pragma: no cover - install-state failure, not logic
        raise LinguisticsModelError(
            f"NLP model '{_MODEL_NAME}' is not installed. It is a pinned direct-URL "
            "dependency in pyproject.toml (GitHub release wheel); install it into the "
            "project venv. There is no regex fallback."
        ) from exc


def _analyze(text: str) -> Doc:
    return _nlp()(text)


def model_info() -> dict[str, str]:
    """Pinned-configuration metadata for smoke tests and diagnostics output."""
    nlp = _nlp()  # raises LinguisticsModelError first if the install is broken
    import spacy

    return {
        "spacy_version": spacy.__version__,
        "model_name": f"{nlp.meta['lang']}_{nlp.meta['name']}",
        "model_version": str(nlp.meta["version"]),
        "pipes": ",".join(nlp.pipe_names),
    }


@dataclass(frozen=True)
class SentenceSpan:
    """A sentence with its character offsets into the analyzed source text."""

    start: int
    end: int
    text: str


@dataclass(frozen=True)
class LinguisticToken:
    """Per-token grammar features. ``text`` + ``whitespace`` reconstruct the source."""

    text: str
    lemma: str
    pos: str
    tag: str
    dep: str
    morph: dict[str, str]
    whitespace: str


@dataclass(frozen=True)
class TenseProfile:
    """Verb-spine features of a text plus derived tense scores.

    Token lists hold surface forms (audit detail for decision records):

    - ``past_finite_verbs`` / ``present_finite_verbs`` — finite main verbs by tense.
    - ``past_auxiliaries`` / ``present_auxiliaries`` — finite auxiliaries/copulas by tense.
      Passive and perfect constructions ("was founded", "had been consumed") carry their
      past narration on the finite auxiliary, so these count toward the tense scores.
    - ``past_participles`` — past/perfect participles including adjectival uses ("ruined",
      "plague-scarred", "fallen"). Reported but **never** counted as finite past narration:
      a participial caption has no finite verb spine.
    - ``imperative_roots`` — clause heads of subjectless base-form verb clauses (quest-style
      directives: "Slay the necromancers", "Be warned"). Infinitival fragments introduced
      by "to" and modal-bearing fragments ("Can be found in...") are excluded.

    Derived scores:

    - ``past_count`` / ``present_count`` — finite verbs plus finite auxiliaries per tense.
    - ``past_dominant`` — more finite past than finite present spine.
    - ``present_framed`` — at least one finite present verb or present copula/auxiliary.
    - ``imperative_like`` — at least one imperative clause head.
    """

    past_finite_verbs: tuple[str, ...]
    present_finite_verbs: tuple[str, ...]
    past_auxiliaries: tuple[str, ...]
    present_auxiliaries: tuple[str, ...]
    past_participles: tuple[str, ...]
    imperative_roots: tuple[str, ...]
    past_count: int
    present_count: int
    past_dominant: bool
    present_framed: bool
    imperative_like: bool


def sentence_spans(text: str) -> list[SentenceSpan]:
    """Model-derived sentence boundaries, preserving source character offsets."""
    return [
        SentenceSpan(start=sent.start_char, end=sent.end_char, text=sent.text)
        for sent in _analyze(text).sents
    ]


def linguistic_tokens(text: str) -> list[LinguisticToken]:
    """Full per-token feature detail (text, lemma, POS, tag, dependency, morph, whitespace)."""
    return [
        LinguisticToken(
            text=token.text,
            lemma=token.lemma_,
            pos=token.pos_,
            tag=token.tag_,
            dep=token.dep_,
            morph=token.morph.to_dict(),
            whitespace=token.whitespace_,
        )
        for token in _analyze(text)
    ]


def lemmatized_content_tokens(text: str) -> list[str]:
    """Lowercased lemmas of content words (NOUN/PROPN/VERB/ADJ/ADV, minus stopwords).

    The explicit lemma ask for deterministic retrieval/fallback scoring. Never feed IDs,
    wiki titles, or provenance strings through this — those must stay surface text.
    """
    return [
        token.lemma_.lower()
        for token in _analyze(text)
        if token.pos_ in _CONTENT_POS and not token.is_stop
    ]


def _is_finite(token: Token) -> bool:
    return token.morph.get("VerbForm", []) == ["Fin"]


def _tense(token: Token) -> str:
    values = token.morph.get("Tense", [])
    return values[0] if values else ""


def _clause_heads(doc: Doc) -> list[Token]:
    """Sentence roots plus verbs conjoined to them ("Aid X **and slay** Y")."""
    heads = [sent.root for sent in doc.sents]
    frontier = list(heads)
    while frontier:
        head = frontier.pop()
        for child in head.children:
            if child.dep_ == "conj" and child.pos_ in {"VERB", "AUX"}:
                heads.append(child)
                frontier.append(child)
    return heads


def _is_imperative_clause_head(token: Token) -> bool:
    """Subjectless base-form verb clause — the grammatical shape of a quest directive.

    Excludes infinitival fragments ("to restore the land": a ``to`` particle attaches to the
    verb), any clause with an explicit subject, and any clause carrying a modal (imperatives
    never take modals — "Can be found in..." is a subjectless wiki fragment, not a directive).
    Covers the bare-auxiliary participle form ("Be warned") where the base-form verb is the
    auxiliary, not the clause head itself.
    """
    if token.pos_ not in {"VERB", "AUX"}:
        return False
    children = list(token.children)
    if any(child.dep_ in _SUBJECT_DEPS for child in children):
        return False
    if any(child.tag_ in {"TO", "MD"} for child in children):
        return False
    if token.tag_ == "VB":
        return True
    return any(child.dep_ in {"aux", "auxpass"} and child.tag_ == "VB" for child in children)


def tense_profile(text: str) -> TenseProfile:
    """Bucket the text's verb spine by tense/finiteness and derive the tense scores."""
    doc = _analyze(text)
    past_finite_verbs: list[str] = []
    present_finite_verbs: list[str] = []
    past_auxiliaries: list[str] = []
    present_auxiliaries: list[str] = []
    past_participles: list[str] = []

    for token in doc:
        if token.pos_ == "VERB":
            if _is_finite(token):
                if _tense(token) == "Past":
                    past_finite_verbs.append(token.text)
                elif _tense(token) == "Pres":
                    present_finite_verbs.append(token.text)
            elif token.morph.get("VerbForm", []) == ["Part"] and _tense(token) == "Past":
                past_participles.append(token.text)
        elif token.pos_ == "AUX" and _is_finite(token):
            if _tense(token) == "Past":
                past_auxiliaries.append(token.text)
            elif _tense(token) == "Pres":
                present_auxiliaries.append(token.text)

    imperative_roots = [
        head.text for head in _clause_heads(doc) if _is_imperative_clause_head(head)
    ]

    past_count = len(past_finite_verbs) + len(past_auxiliaries)
    present_count = len(present_finite_verbs) + len(present_auxiliaries)
    return TenseProfile(
        past_finite_verbs=tuple(past_finite_verbs),
        present_finite_verbs=tuple(present_finite_verbs),
        past_auxiliaries=tuple(past_auxiliaries),
        present_auxiliaries=tuple(present_auxiliaries),
        past_participles=tuple(past_participles),
        imperative_roots=tuple(imperative_roots),
        past_count=past_count,
        present_count=present_count,
        past_dominant=past_count > present_count,
        present_framed=present_count > 0,
        imperative_like=bool(imperative_roots),
    )


def describe(text: str) -> str:
    """Human-readable dump of the wrapper's full analysis, for reviewer diagnostics.

    Lets a reviewer inspect tense/parse disagreements (why a phrase was or wasn't counted)
    without stepping through the parser.
    """
    info = model_info()
    lines = [
        f"model: {info['model_name']} {info['model_version']} "
        f"(spacy {info['spacy_version']}; pipes: {info['pipes']})",
        "",
        "sentences:",
    ]
    for span in sentence_spans(text):
        lines.append(f"  [{span.start}:{span.end}] {span.text}")
    lines.extend(["", "tokens (text | lemma | pos | tag | dep | morph):"])
    for token in linguistic_tokens(text):
        morph = "|".join(f"{key}={value}" for key, value in sorted(token.morph.items()))
        lines.append(
            f"  {token.text} | {token.lemma} | {token.pos} | {token.tag} | {token.dep} | {morph}"
        )
    profile = tense_profile(text)
    lines.extend(
        [
            "",
            "tense profile:",
            f"  past_finite_verbs:     {list(profile.past_finite_verbs)}",
            f"  present_finite_verbs:  {list(profile.present_finite_verbs)}",
            f"  past_auxiliaries:      {list(profile.past_auxiliaries)}",
            f"  present_auxiliaries:   {list(profile.present_auxiliaries)}",
            f"  past_participles:      {list(profile.past_participles)}",
            f"  imperative_roots:      {list(profile.imperative_roots)}",
            f"  past_count={profile.past_count} present_count={profile.present_count} "
            f"past_dominant={profile.past_dominant} present_framed={profile.present_framed} "
            f"imperative_like={profile.imperative_like}",
            "",
            f"lemmatized_content_tokens: {lemmatized_content_tokens(text)}",
        ]
    )
    return "\n".join(lines)
