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
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

import structlog

from radar.core.types import SourceKind
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
