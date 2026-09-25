"""Stage one: does this document plausibly assert something, judged from its title.

ADR-0008 explains why this is a model call and not a keyword gate. The short
version is that the question is about register, and register is not a vocabulary:
"we demonstrate that X implies Y" and "we demonstrated a working X" share their
vocabulary and mean opposite things. A term list matched the first on 971 of 1,525
passes and called it evidence.

The economics are the reason it reads titles rather than abstracts, and the reason
it reads many titles per call.

ADR-0008 costed this at 30 input tokens per document and was wrong by more than an
order of magnitude, because it counted the title and forgot the system prompt is
resent on every request. Measured with `radar triage estimate`: the system prompt
is 488 tokens and a title is about 12, so the instructions are **97% of input
tokens**. One call per document works out at roughly $21/month for stage one alone
— the entire project budget.

Prompt caching does not rescue it. Haiku 4.5 will not cache a prefix under 4,096
tokens and returns no error when asked to, so a `cache_control` marker on a
488-token prompt would have paid list price while looking like a saving; and
caching does not combine usefully with the Batch API, where an entry expires
before the request that would read it. Both verified against the published docs on
2026-09-25.

So titles are sent in chunks. One system prompt amortised across fifty titles
takes the instruction overhead from 488 tokens per document to about 10, which is
roughly $2/month. The price is a correctness risk — a misread chunk corrupts fifty
verdicts instead of one — so every title is numbered, every verdict must carry its
number back, and a chunk whose verdicts do not line up exactly is split and
retried rather than trusted. See ``parse_verdicts``.

Two asymmetries shape the prompt.

**Recall over precision.** A wrong NO deletes a piece of evidence and nothing in
the system will ever report it. A wrong YES costs one stage-two call, roughly a
hundredth of a cent. The prompt says so explicitly, because a model told only
"be accurate" will balance the errors evenly and that is the wrong balance.

**Newsroom register is not academic register.** The gate this replaces rejected a
government funding announcement and a product launch for containing no academic
vocabulary. Those are the M4-and-above evidence classes the whole framework is
built around, so the prompt names them as examples of YES.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

import structlog
from pydantic import ValidationError

from radar.core.types import SourceKind
from radar.pipeline.contracts import TriageDecision
from radar.pipeline.llm import HAIKU, ModelClient, ModelRequest, Usage

log = structlog.get_logger(__name__)

DEFAULT_CHUNK_SIZE = 50
"""Titles per request.

Fifty amortises a 488-token system prompt down to about 10 tokens per document,
which is where the curve flattens: 100 saves another 5 tokens each and doubles
what a single misread response costs. Not tuned beyond that — if the misalignment
rate measured on real runs is zero, raising it is cheap to try.
"""

TOKENS_PER_VERDICT = 8
"""Output budget per title: its number, a separator, a word, a newline.

Eight rather than four because the number now has to come back too, and a ceiling
that truncates the last verdict of a chunk turns a cost saving into a silent
alignment failure.
"""

YES = "YES"
NO = "NO"

STAGE_ONE_SYSTEM = f"""\
You screen titles for a technology-intelligence pipeline. You will be given a \
numbered list of titles. For each one, decide whether that document might contain \
a claim about something that actually exists, works, shipped, was measured, or was \
permitted — as opposed to a method, a proposal, a proof, a survey, or a framework.

Reply with one line per title, in the form `<number>: {YES}` or `<number>: {NO}`. \
Reply for every number you were given, in the same order, and write nothing else \
— no preamble, no explanation, no blank lines.

Answer {YES} when the title suggests any of:
- a working system, device, prototype or facility that was built or operated
- a measured result about a real artefact (a fidelity, a duration, a yield, a \
density, a throughput)
- a deployment, installation, commercial launch, product release or customer \
availability
- a regulatory decision, approval, clearance, certification or licence filing
- public funding, procurement or investment in building something specific
- a record or first-of-its-kind achievement

Answer {NO} when the title suggests the document is primarily:
- a new method, model, framework, architecture or algorithm offered as a \
contribution
- a proof, bound, complexity result or theoretical analysis
- a survey, review, position paper, benchmark suite or dataset release
- a simulation or purely computational study with no physical artefact

Two things to hold onto.

First, the word "demonstrate" is ambiguous and you must read past it. In academic \
writing "we demonstrate that X" usually means "we prove X", which is {NO}. \
"We demonstrated a 400-second plasma" means a thing was operated, which is {YES}.

Second, many titles come from newsrooms, government press offices and company \
blogs rather than from journals. They carry no academic vocabulary at all and are \
often the most important documents in the corpus. A funding announcement, a \
product launch or a regulatory clearance is {YES} even when the title reads like \
marketing.

When you are unsure, answer {YES}. A wrong {YES} costs one cheap follow-up call. \
A wrong {NO} deletes a piece of evidence permanently and nobody finds out."""


def prompt_version(system: str = STAGE_ONE_SYSTEM) -> str:
    """A short content hash of the prompt.

    Derived rather than written down, for the same reason the prefilter's
    vocabulary version was: a hand-maintained version is one somebody forgets to
    change, and then an eval comparing two prompts silently compares one prompt
    with itself.
    """
    return hashlib.sha256(system.encode("utf-8")).hexdigest()[:12]


class MisalignedChunkError(ValueError):
    """The verdicts did not line up with the titles that were sent.

    Never absorbed. A chunk whose numbers are missing, duplicated or invented
    cannot be partially trusted: the failure mode is a verdict attached to the
    wrong document, which then propagates as a claim about the wrong paper. The
    caller splits and retries instead.
    """


class UnreadableVerdictError(ValueError):
    """A verdict line was not YES or NO.

    Deliberately an error rather than a default. Treating an unparseable answer
    as NO would silently starve the pipeline — the failure would look like a
    quiet day rather than a broken prompt — and treating it as YES would hide a
    prompt regression behind a larger bill.
    """


def render_chunk(titles: list[str]) -> str:
    """Number the titles, one per line.

    Newlines inside a title would break the one-line-per-title contract, so they
    are collapsed. Titles arrive from feeds that hard-wrap them.
    """
    return "\n".join(
        f"{index}: {' '.join(title.split())}" for index, title in enumerate(titles, start=1)
    )


def parse_verdicts(text: str, expected: int) -> list[bool]:
    """Read one chunk's verdicts, or refuse the whole chunk.

    Every number from 1 to ``expected`` must appear exactly once. Anything else —
    a missing line, a duplicate, a number nobody asked about, a stray sentence —
    raises rather than returning a shorter list, because a short list silently
    shifts every verdict after the gap onto the wrong document.
    """
    verdicts: dict[int, bool] = {}
    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        number, separator, answer = line.partition(":")
        if not separator or not number.strip().isdigit():
            raise MisalignedChunkError(f"expected lines like '3: {YES}', got {line[:60]!r}")
        index = int(number.strip())
        cleaned = answer.strip().strip(".").upper()
        if cleaned not in {YES, NO}:
            raise UnreadableVerdictError(
                f"line {index}: expected {YES} or {NO}, got {answer.strip()[:40]!r}. "
                "Not treated as a rejection, because a broken prompt would then "
                "look like a quiet day."
            )
        if index in verdicts:
            raise MisalignedChunkError(f"number {index} answered more than once")
        verdicts[index] = cleaned == YES

    wanted = set(range(1, expected + 1))
    got = set(verdicts)
    if got != wanted:
        raise MisalignedChunkError(
            f"sent {expected} titles and got {len(got)} usable verdicts; "
            f"missing {sorted(wanted - got)}, unexpected {sorted(got - wanted)}"
        )
    return [verdicts[index] for index in range(1, expected + 1)]


@dataclass(frozen=True, slots=True)
class Candidate:
    """A document waiting to be screened."""

    document_id: str
    title: str
    source_id: str
    source_kind: SourceKind


@dataclass(frozen=True, slots=True)
class Screen:
    """One stage-one outcome."""

    document_id: str
    passed: bool
    reason: str
    prompt_version: str
    screened: bool = True
    """False when the document skipped the model entirely — see needs_screening."""

    def __bool__(self) -> bool:
        return self.passed


def needs_screening(candidate: Candidate) -> bool:
    """Whether this document should cost a stage-one call at all.

    Only the bulk preprint feeds do. On the day this was measured, 2,738 of 2,751
    documents came from arXiv and 13 from newsrooms and preprint APIs — half a
    percent. Screening those thirteen saves a fraction of a cent and risks losing
    the deployment and regulatory claims that arXiv structurally cannot carry,
    which is the exact mistake ADR-0008 records.
    """
    return candidate.source_kind in {SourceKind.ARXIV_OAI, SourceKind.ARXIV_CATEGORY}


def build_request(titles: list[str], *, model: str = HAIKU) -> ModelRequest:
    """The request for one chunk of titles."""
    return ModelRequest(
        model=model,
        system=STAGE_ONE_SYSTEM,
        prompt=render_chunk(titles),
        max_tokens=len(titles) * TOKENS_PER_VERDICT + 16,
    )


def _judge(
    client: ModelClient,
    titles: list[str],
    *,
    model: str,
    usage: Usage | None,
) -> list[bool]:
    """Judge one chunk, halving and retrying if the verdicts do not line up.

    Recursion bottoms out at a single title, where a misalignment is a genuine
    parse failure rather than a counting one and is allowed to propagate. This
    turns the one real risk of batching — fifty verdicts riding on one response —
    into at worst a handful of extra calls.
    """
    response = client.complete(build_request(titles, model=model))
    if usage is not None:
        usage.record(response)

    try:
        return parse_verdicts(response.text, len(titles))
    except MisalignedChunkError:
        if len(titles) == 1:
            raise
        middle = len(titles) // 2
        log.warning("stage_one_chunk_misaligned", size=len(titles), retrying_as=middle)
        return _judge(client, titles[:middle], model=model, usage=usage) + _judge(
            client, titles[middle:], model=model, usage=usage
        )


def screen(
    client: ModelClient,
    candidates: Iterable[Candidate],
    *,
    model: str = HAIKU,
    usage: Usage | None = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> Iterator[Screen]:
    """Screen each candidate, yielding one outcome per document in input order.

    Documents that do not need screening are yielded as passes without a model
    call, so the caller gets one result per input and never has to track which
    ones were skipped.
    """
    version = prompt_version()
    pending: list[Candidate] = []

    def flush() -> Iterator[Screen]:
        if not pending:
            return
        verdicts = _judge(client, [c.title for c in pending], model=model, usage=usage)
        for item, passed in zip(pending, verdicts, strict=True):
            yield Screen(
                document_id=item.document_id,
                passed=passed,
                reason=f"model said {YES if passed else NO}",
                prompt_version=version,
            )
        pending.clear()

    for candidate in candidates:
        if not needs_screening(candidate):
            # Order matters: anything already queued was seen first.
            yield from flush()
            yield Screen(
                document_id=candidate.document_id,
                passed=True,
                reason=f"not screened: {candidate.source_kind} goes straight to stage two",
                prompt_version=version,
                screened=False,
            )
            continue
        pending.append(candidate)
        if len(pending) >= chunk_size:
            yield from flush()

    yield from flush()


def estimate_tokens(text: str) -> int:
    """A rough token count for planning, without an API call.

    Four characters per token is the usual English approximation and it is only
    that. It exists so a dry run can print a cost before a key is configured;
    the moment a real run happens, ``Usage`` carries measured counts and this
    number should be ignored in favour of them.
    """
    return max(1, len(text) // 4)


# --------------------------------------------------------------------- stage two ---

STAGE_TWO_MAX_TOKENS = 400
"""Room for a decision object and no more.

Generous next to the four tokens stage one needs, and still a ceiling: a model
that starts writing an essay in ``reason`` gets truncated, and truncated JSON
fails validation loudly rather than being stored as a short explanation.
"""

STAGE_TWO_DOMAINS = ("ai", "robotics", "quantum", "semiconductors", "energy", "biotech")
"""The six MVP domains, as slugs.

Hardcoded rather than read from the database on purpose: the prompt is versioned
by its content hash, and a prompt whose text depends on a table would change
version whenever someone added a row, silently invalidating every eval
comparison. A seventh domain is a deliberate prompt edit, not a data change.
"""

STAGE_TWO_SYSTEM = f"""\
You triage documents for a technology-intelligence platform that tracks emerging \
technology across six domains: {", ".join(STAGE_TWO_DOMAINS)}.

You are given one document's title and abstract. Decide whether it is worth \
extracting claims from, and reply with a single JSON object and nothing else.

The object has exactly these fields:
- "relevant": true or false
- "confidence": "high", "medium" or "low"
- "reason": one sentence a human curator can read and disagree with
- "domains": a list of slugs from the six above; [] if none apply
- "technology_mentions": a list of strings

A document is relevant when it reports something about the state of a technology \
in the world: a capability that was built or measured, a system deployed or sold, \
a regulatory decision, a funding commitment to build something specific, or a \
result that changes what is known to be achievable.

A document is not relevant when its contribution is a method, a model, an \
architecture, a proof, a survey, a benchmark or a dataset, even when the subject \
matter is squarely in one of the six domains. Most of what arrives is this.

Three rules about "technology_mentions", and they matter more than the rest.

Copy strings that appear in the text. Do not translate a phrase into the \
canonical name of the technology you believe it refers to, do not expand an \
acronym the document did not expand, and do not add a company, product or \
technology the document does not name. If the abstract says "a 16-DoF hand", the \
mention is "16-DoF hand". Resolving mentions to tracked technologies happens in \
code, from these strings, and it cannot recover from an invented one.

An empty list is a correct answer. A document can be relevant and name no \
specific technology.

Never add a field that is not in the list above, and never omit one.

On "confidence": "high" means the title and abstract say plainly what happened. \
"medium" means you are reading between the lines. "low" means the abstract is too \
vague to tell, in which case set "relevant" to true anyway — a cheap extraction \
that finds nothing costs far less than a discarded document nobody revisits."""


TRIAGE_DECISION_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["relevant", "confidence", "reason", "domains", "technology_mentions"],
    "properties": {
        "relevant": {"type": "boolean"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "reason": {"type": "string", "maxLength": 400},
        "domains": {
            "type": "array",
            "items": {"type": "string", "enum": list(STAGE_TWO_DOMAINS)},
        },
        "technology_mentions": {"type": "array", "items": {"type": "string"}},
    },
}
"""The same shape ``TriageDecision`` enforces, in the form the API accepts.

Deliberately duplicated rather than generated from the Pydantic model. A
generated schema tracks the model automatically, which sounds better until the
model gains a field with a default: the schema then starts *requiring* something
the prompt never mentions, and every call fails. Two explicit definitions that a
test compares is the safer arrangement — see
``test_the_schema_and_the_contract_agree``.

The contract is still validated in Python after the call. A schema the API
honours makes malformed output impossible; a schema it silently ignores, which is
what an unverified feature might do, would otherwise leave nothing checking.
"""


def stage_two_version(system: str = STAGE_TWO_SYSTEM) -> str:
    """Content hash of the stage-two prompt."""
    return hashlib.sha256(system.encode("utf-8")).hexdigest()[:12]


def render_document(title: str, abstract: str | None) -> str:
    """The user turn for stage two.

    Labelled rather than concatenated, so a title that ends without punctuation
    cannot read as the first sentence of the abstract.
    """
    body = " ".join((abstract or "").split()) or "(no abstract available)"
    return f"TITLE: {' '.join(title.split())}\n\nABSTRACT: {body}"


def build_stage_two_request(
    title: str,
    abstract: str | None,
    *,
    model: str = HAIKU,
    constrain_schema: bool = True,
) -> ModelRequest:
    """One triage request.

    ``constrain_schema`` is on by default and can be turned off in one place if
    the API turns out not to honour ``output_config.format`` for this model —
    which is unverified as of 2026-09-25. Validation does not depend on it.
    """
    return ModelRequest(
        model=model,
        system=STAGE_TWO_SYSTEM,
        prompt=render_document(title, abstract),
        max_tokens=STAGE_TWO_MAX_TOKENS,
        json_schema=TRIAGE_DECISION_SCHEMA if constrain_schema else None,
    )


class TriageParseError(ValueError):
    """The model's stage-two output was not a usable TriageDecision.

    Recorded against the document rather than retried blindly. A prompt that has
    drifted fails on nearly everything, and a run that quietly retried each one
    three times would spend triple the budget discovering that.
    """


def parse_decision(text: str) -> TriageDecision:
    """Validate one stage-two response against the contract.

    Tolerates a fenced code block, because models wrap JSON in one often enough
    that refusing would trade a real failure for a formatting quibble. Tolerates
    nothing else: the contract forbids extra fields, so a model that invents one
    fails here with the offending key named, which is the whole point of
    ``extra="forbid"``.
    """
    body = text.strip()
    if body.startswith("```"):
        lines = body.splitlines()
        body = "\n".join(lines[1:-1] if lines[-1].strip().startswith("```") else lines[1:])
        body = body.strip()

    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise TriageParseError(f"not JSON: {body[:120]!r}") from exc

    try:
        return TriageDecision.model_validate(payload)
    except ValidationError as exc:
        raise TriageParseError(f"does not satisfy the triage contract: {exc}") from exc


@dataclass(frozen=True, slots=True)
class Triaged:
    """One stage-two outcome, with the prompt that produced it."""

    document_id: str
    decision: TriageDecision
    prompt_version: str

    def __bool__(self) -> bool:
        return self.decision.relevant


def triage_document(
    client: ModelClient,
    *,
    document_id: str,
    title: str,
    abstract: str | None,
    model: str = HAIKU,
    usage: Usage | None = None,
    constrain_schema: bool = True,
) -> Triaged:
    """Triage one document against the full contract."""
    response = client.complete(
        build_stage_two_request(title, abstract, model=model, constrain_schema=constrain_schema)
    )
    if usage is not None:
        usage.record(response)

    if response.truncated:
        raise TriageParseError(
            f"the response hit the {STAGE_TWO_MAX_TOKENS}-token ceiling and is "
            "incomplete. Raise STAGE_TWO_MAX_TOKENS rather than parsing the "
            "fragment; a truncated decision is not a cautious decision."
        )

    return Triaged(
        document_id=document_id,
        decision=parse_decision(response.text),
        prompt_version=stage_two_version(),
    )
