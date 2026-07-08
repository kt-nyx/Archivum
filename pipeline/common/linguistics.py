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
      a participial caption has no finite verb spine. A verb whose dependency is ``amod``
      (attributive modifier — "fortified holdings") lands here too even when the sm model's
      morphology calls it finite: an adjectival modifier is not narration, and the mis-parse
      would otherwise inject phantom finite-past counts.
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


@lru_cache(maxsize=4096)
def _sentence_spans_cached(text: str) -> tuple[SentenceSpan, ...]:
    return tuple(
        SentenceSpan(start=sent.start_char, end=sent.end_char, text=sent.text)
        for sent in _analyze(text).sents
    )


def sentence_spans(text: str) -> list[SentenceSpan]:
    """Model-derived sentence boundaries, preserving source character offsets.

    Cached: Slice 8 routes every sentence-boundary consumer (lints, trims, claim extraction)
    through this, and the same snippet is segmented from several predicates per draft pass.
    """
    return list(_sentence_spans_cached(text))


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


@lru_cache(maxsize=4096)
def _support_tokens_cached(text: str) -> tuple[str, ...]:
    return tuple(
        token.text.lower() if token.pos_ in {"PROPN", "ADP"} else token.lemma_.lower()
        for token in _analyze(text)
        if (
            token.pos_ == "ADP"
            or (token.pos_ in _CONTENT_POS and not token.is_stop)
        )
    )


def support_tokens(text: str) -> list[str]:
    """Lowercased tokens for deterministic fallback retrieval/support scoring (Slice 8).

    Content words (NOUN/VERB/ADJ/ADV) are lemmatized so inflection ("gained"/"gain",
    "necromancers"/"necromancer") stops defeating overlap heuristics. Two classes stay as
    surface text on purpose:

    - **Proper nouns** — names are identifiers, never normalized (the module contract).
    - **Adpositions** — a closed grammatical class kept *un-stopworded* so exact location
      prepositions ("above", "beneath", "inside", "near") remain visible: a lemma-level
      score must never treat "built above Caer Darrow" and "built beneath Caer Darrow" as
      the same token set.

    Fallback ranking/support signal only — never a contradiction judge (that is Slice 15's
    assertion adjudicator).
    """
    return list(_support_tokens_cached(text))


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


def _conjunction_chain(token: Token) -> list[Token]:
    """The token plus every conjunction head above it ("recruit" → ["recruit", "spy"]).

    A conjoined verb shares its subject and modals with the head it is conjoined to
    ("they spy … and recruit …"), so imperative detection must look up the chain rather
    than only at the token's own children.
    """
    chain = [token]
    head = token
    while head.dep_ == "conj" and head.head is not head:
        head = head.head
        chain.append(head)
    return chain


def _is_imperative_clause_head(token: Token) -> bool:
    """Subjectless base-form verb clause — the grammatical shape of a quest directive.

    Excludes infinitival fragments ("to restore the land": a ``to`` particle attaches to the
    verb), any clause with an explicit subject, and any clause carrying a modal (imperatives
    never take modals — "Can be found in..." is a subjectless wiki fragment, not a directive).
    Subjects and modals are inherited through the conjunction chain, so "they spy … and
    recruit …" is finite narration, while "Aid X and slay Y" stays a two-verb directive.
    Covers the bare-auxiliary participle form ("Be warned") where the base-form verb is the
    auxiliary, not the clause head itself.
    """
    if token.pos_ not in {"VERB", "AUX"}:
        return False
    for clause in _conjunction_chain(token):
        children = list(clause.children)
        if any(child.dep_ in _SUBJECT_DEPS for child in children):
            return False
        if any(child.tag_ in {"TO", "MD"} for child in children):
            return False
    children = list(token.children)
    if token.tag_ == "VB":
        return True
    return any(child.dep_ in {"aux", "auxpass"} and child.tag_ == "VB" for child in children)


def _is_finite_clause(token: Token) -> bool:
    """The token heads a clause with a finite verb spine.

    Either the token itself is finite ("fell", "ends") or a finite auxiliary carries the
    clause's finiteness ("was founded", "is cast out") — passive/perfect predicates are
    participles, so finiteness must be read off the aux chain.
    """
    if _is_finite(token):
        return True
    return any(
        child.dep_ in {"aux", "auxpass"} and _is_finite(child) for child in token.children
    )


@lru_cache(maxsize=4096)
def finite_clause_count(text: str) -> int:
    """Number of finite clause predicates — distinct event/state predications (Slice 8).

    Counts verb/aux tokens that head a finite clause: main clauses, coordinated clauses,
    complement/adverbial/relative clauses. Auxiliaries riding another predicate and
    attributive participles ("fortified holdings") are not clause heads and never count.
    Non-finite material (infinitives, gerunds, participial adjuncts) predicates nothing on
    its own, so "begins healing the fields" is one predication, not two. This replaces the
    semicolon/word-count proxies in claim-extraction triage: a long single-event sentence
    counts 1; "the keep fell and later anchored the frontier" counts 2.
    """
    return sum(
        1
        for token in _analyze(text)
        if token.pos_ in {"VERB", "AUX"}
        and token.dep_ not in {"aux", "auxpass", "amod"}
        and _is_finite_clause(token)
    )


@dataclass(frozen=True)
class ActionRelation:
    """Agent→verb→patient roles for one action verb (general dependency grammar).

    Surface phrases only — the caller decides which verbs/names matter. Passive voice is
    normalized so ``X defeated Y`` and ``Y was defeated by X`` yield the same agent/patient
    split. A nominalized action ("his defeat at Andorhal") is *not* a verb and produces no
    relation, which is what lets callers treat backstory/origin nominalizations differently
    from a finite action.
    """

    verb_lemma: str
    agents: tuple[str, ...]
    patients: tuple[str, ...]


def _phrase_text(doc: Doc, token: Token) -> str:
    """Contiguous surface text of a token's subtree (its noun phrase)."""
    indexes = [descendant.i for descendant in token.subtree]
    return doc[min(indexes) : max(indexes) + 1].text


@lru_cache(maxsize=2048)
def _action_relations_cached(text: str) -> tuple[ActionRelation, ...]:
    doc = _analyze(text)
    relations: list[ActionRelation] = []
    for token in doc:
        if token.pos_ != "VERB":
            continue
        agents: list[str] = []
        patients: list[str] = []
        for child in token.children:
            dep = child.dep_
            if dep == "nsubj":
                agents.append(_phrase_text(doc, child))
            elif dep == "nsubjpass":
                patients.append(_phrase_text(doc, child))
            elif dep in {"dobj", "obj", "dative", "oprd"}:
                patients.append(_phrase_text(doc, child))
            elif dep == "agent":  # passive "by X": the object of the agent marker is the actor
                agents.extend(
                    _phrase_text(doc, grandchild)
                    for grandchild in child.children
                    if grandchild.dep_ == "pobj"
                )
        if not agents:
            # A conjoined verb shares the subject of the head it hangs off ("X hunted and
            # defeated Y"): climb the conjunction chain to inherit that subject/agent.
            head = token
            while head.dep_ == "conj" and head.head is not head and not agents:
                head = head.head
                for child in head.children:
                    if child.dep_ == "nsubj":
                        agents.append(_phrase_text(doc, child))
                    elif child.dep_ == "agent":
                        agents.extend(
                            _phrase_text(doc, grandchild)
                            for grandchild in child.children
                            if grandchild.dep_ == "pobj"
                        )
        if agents or patients:
            relations.append(
                ActionRelation(
                    verb_lemma=token.lemma_,
                    agents=tuple(agents),
                    patients=tuple(patients),
                )
            )
    return tuple(relations)


def action_relations(text: str) -> list[ActionRelation]:
    """Agent/patient relations for each finite action verb (subject-verb-object grammar).

    Reports grammatical roles only; no domain judgment about which verbs or names matter.
    """
    return list(_action_relations_cached(text))


# Adversative / concessive connectives — a closed grammatical class. Everything from the first
# such connective heading a clause is the reversal/result ("..., though it failed"); the leading
# clause is the assertion/intent.
_ADVERSATIVE_MARKERS = frozenset(
    {"though", "although", "but", "yet", "however", "whereas", "nevertheless", "nonetheless"}
)


@lru_cache(maxsize=2048)
def clause_before_adversative(text: str) -> str:
    """The leading clause up to the first adversative/concessive connective.

    A closed-class grammatical cut: "she pressed on, though it failed" -> "she pressed on".
    Returns the input unchanged when no adversative connective heads a clause. General grammar
    only — the caller decides what the trimmed clause means or is used for.
    """
    doc = _analyze(text)
    for token in doc:
        if token.lemma_.lower() in _ADVERSATIVE_MARKERS and token.dep_ in {"mark", "cc"}:
            return text[: token.idx].rstrip().rstrip(",;:").rstrip()
    return text


@lru_cache(maxsize=2048)
def _coordinated_clause_split_cached(text: str) -> tuple[str, ...]:
    doc = _analyze(text)
    sents = list(doc.sents)
    if len(sents) != 1:
        return ()
    sent = sents[0]
    root = sent.root
    if root.pos_ not in {"VERB", "AUX"} or not _is_finite_clause(root):
        return ()
    root_subjects = [child for child in root.children if child.dep_ in _SUBJECT_DEPS]
    if not root_subjects:
        return ()  # subjectless (imperative/fragment) — no standalone clauses to make
    conjuncts = [
        child
        for child in root.children
        if child.dep_ == "conj" and child.pos_ in {"VERB", "AUX"}
    ]
    if len(conjuncts) != 1:
        return ()  # zero or chained coordination — not the unambiguous two-clause shape
    conj = conjuncts[0]
    if not _is_finite_clause(conj):
        return ()  # shared-aux VP coordination ("was razed and rebuilt") stays whole
    conj_tokens = list(conj.subtree)
    boundary = min(token.i for token in conj_tokens)
    # Everything right of the boundary must belong to the second clause (or be the closing
    # punctuation, which attaches wherever the parser likes).
    conj_indexes = {token.i for token in conj_tokens}
    for token in doc[boundary : sent.end]:
        if token.i not in conj_indexes and token.pos_ != "PUNCT":
            return ()
    # The junction between the clauses must be an explicit coordinator (plus optional comma).
    # Asyndetic/semicolon joins are left whole for the LLM semantic splitter.
    junction_start = boundary
    saw_coordinator = False
    while junction_start > sent.start and doc[junction_start - 1].pos_ in {"CCONJ", "PUNCT"}:
        junction_start -= 1
        saw_coordinator = saw_coordinator or doc[junction_start].pos_ == "CCONJ"
    if not saw_coordinator or junction_start <= sent.start:
        return ()
    first_clause = doc[sent.start : junction_start].text.strip()
    if not first_clause:
        return ()
    second_tail = doc[boundary : sent.end].text.strip()
    conj_subjects = [child for child in conj.children if child.dep_ in _SUBJECT_DEPS]
    if conj_subjects:
        second_clause = second_tail
    else:
        # Shared subject: copy the first clause's subject phrase so the clause stands alone.
        if len(root_subjects) != 1:
            return ()
        subject_tokens = list(root_subjects[0].subtree)
        if any(token.i >= junction_start for token in subject_tokens):
            return ()  # parse placed subject material across the junction — not confident
        subject_text = doc[
            min(token.i for token in subject_tokens) : max(token.i for token in subject_tokens) + 1
        ].text.strip()
        if not subject_text:
            return ()
        second_clause = f"{subject_text} {second_tail}"
    # Named-entity preservation: a split must never lose a proper noun (only the junction's
    # coordinator/comma may be dropped, and those are never PROPN — this is a guard against
    # parse shapes we did not anticipate, per the Slice 8 contract).
    split_text = f"{first_clause} {second_clause}"
    for token in sent:
        if token.pos_ == "PROPN" and token.text not in split_text:
            return ()
    return (first_clause, second_clause)


def coordinated_finite_clause_split(text: str) -> list[str]:
    """Split one sentence of unambiguously coordinated finite clauses into clause texts.

    Returns ``[]`` unless every condition holds: a single sentence whose root heads a finite
    clause with a subject, exactly one finite verbal conjunct joined by an explicit
    coordinating conjunction, clean positional separation, and no proper noun lost by the
    split. The second clause either carries its own subject ("the wall fell and the town
    burned") or inherits a copy of the shared subject ("the keep fell ... and later anchored
    ..." → "The keep later anchored ..."). Anything the parser is less sure about — semicolon
    parataxis, shared-auxiliary VP coordination, chained conjuncts, imperatives — is left
    whole for the caller (the LLM semantic splitter owns the ambiguous cases).
    """
    return list(_coordinated_clause_split_cached(text))


@lru_cache(maxsize=4096)
def tense_profile(text: str) -> TenseProfile:
    """Bucket the text's verb spine by tense/finiteness and derive the tense scores.

    Cached: the draft lint gates (Slice 5) profile the same snippet from several predicates
    while ranking/filtering evidence pools, and the result is a small frozen dataclass.
    """
    doc = _analyze(text)
    past_finite_verbs: list[str] = []
    present_finite_verbs: list[str] = []
    past_auxiliaries: list[str] = []
    present_auxiliaries: list[str] = []
    past_participles: list[str] = []

    for token in doc:
        if token.pos_ == "VERB":
            # An attributive modifier ("fortified holdings", "ruined farms") functions as an
            # adjective regardless of its tense morphology; the sm model sometimes reports such
            # tokens as finite past, which would inject phantom narration counts.
            if _is_finite(token) and token.dep_ != "amod":
                if _tense(token) == "Past":
                    past_finite_verbs.append(token.text)
                elif _tense(token) == "Pres":
                    present_finite_verbs.append(token.text)
            elif _tense(token) == "Past" and (
                token.morph.get("VerbForm", []) == ["Part"] or token.dep_ == "amod"
            ):
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
