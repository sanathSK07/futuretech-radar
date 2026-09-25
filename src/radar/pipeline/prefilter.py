"""The triage gate: which stored documents are ever shown to a model.

Why this exists
---------------
The first live OAI-PMH harvest stored 2,239 documents in one day. Sending all of
them through a model daily is the largest avoidable cost in the project, and
most of it buys nothing: the first hand-labelling export found every sampled
arXiv document was a method or theory paper with no capability claim in it.

So a deterministic gate runs first. It is not a classifier and it does not
replace triage — the model still decides relevance. The gate decides only
whether a document is worth *asking* about.

What this is not
----------------
Not a score with a threshold. A number invites a tuned cutoff nobody can
explain, and the brief forbids inventing precision. A document passes or it does
not, and the reason is recorded in words.

Not a filter at ingest. Every document is stored whichever way the gate votes.
Discarding before storage would mean a bad rule silently erases evidence with no
way to discover it later; a recorded rejection can be re-run when the rules
improve, and counted when they are wrong.

Not a list of technology names. Naming specific technologies in the vocabulary
would make the gate blind to anything new, which is the opposite of a radar's
job. See the comment at the top of prefilter.yaml.

How it decides
--------------
Both conditions must hold:

1. the text mentions a term from at least one tracked domain, and
2. the text carries a claim signal — a demonstration, deployment, regulatory
   event, record, or a measured quantity.

Condition 2 does the work. "quantum" appears in thousands of papers a month
that assert nothing about the world.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import structlog
import yaml
from pydantic import BaseModel, ConfigDict, Field

from radar.pipeline.grounding import normalise

log = structlog.get_logger(__name__)

DEFAULT_VOCABULARY_PATH = Path("prefilter.yaml")

_UNITS = (
    # Explicit rather than a general \w+ after the number: a general pattern
    # matches "3 papers" and "12 objects", which measure nothing. Both the
    # symbol and the spelled-out form are listed, because feeds carry both.
    r"seconds?|secs?|minutes?|min|hours?|hrs?|days?|weeks?|months?|years?"
    r"|milliseconds?|microseconds?|nanoseconds?|picoseconds?"
    r"|ms|us|\u00b5s|ns|ps|fs|s"
    r"|kelvin|teslas?|mk|k|t"
    r"|nanomet(?:re|er)s?|micromet(?:re|er)s?|millimet(?:re|er)s?"
    r"|centimet(?:re|er)s?|kilomet(?:re|er)s?|met(?:re|er)s?"
    r"|nm|um|\u00b5m|mm|cm|km|m"
    r"|[kmgt]?hz"
    r"|[kmgt]?wh?|mah"
    r"|[km]?j|[kmg]?ev"
    r"|bytes?|bits?|[kmgtp]b"
    r"|qubits?|cores?|flops?|tops?"
    r"|grams?|kg|mg|ug|\u00b5g|g"
    r"|lit(?:re|er)s?|ml|l"
    r"|moles?|mol"
    r"|[kmg]?pa|bar|atm|psi"
    r"|db|fps|rpm"
    r"|fold|x"
)

MEASURED_QUANTITY = re.compile(
    # A number — thousands separators, decimals and exponents allowed — then a
    # unit. Case-insensitive because the text this reads has been lowercased,
    # and a case-sensitive pattern silently matched nothing at all: the first
    # version of this found zero measurements and no test caught it until the
    # parametrised cases went in.
    r"(?<![\w.])\d+(?:[.,]\d{3})*(?:\.\d+)?(?:[eE][-+]?\d+)?"
    # "%" needs its own branch. A trailing \b after it never matches, because
    # neither "%" nor the space beside it is a word character — which is how
    # "99.7%", the most common measurement in the corpus, went undetected.
    r"(?:\s?%|[-\s]?(?:" + _UNITS + r")\b)",
    re.IGNORECASE,
)
"""A measured quantity is the strongest claim signal there is, and no term list
finds it. "achieved 99.7% fidelity" and "sustained for 400 s" are assertions
about the world whatever verbs surround them."""

MIN_TEXT_CHARACTERS = 40
"""Below this there is nothing to judge. A title with no abstract is not
evidence that the paper says nothing — it is evidence the feed was thin — so a
document this short is passed rather than rejected, and the reason says why."""


class Vocabulary(BaseModel):
    """prefilter.yaml, validated."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    domains: dict[str, list[str]] = Field(min_length=1)
    claim_signals: dict[str, list[str]] = Field(min_length=1)

    @property
    def rule_version(self) -> str:
        """A short content hash, so the version cannot drift from the rules.

        Set by hand, a version number is a version number somebody forgets to
        change after editing the terms — and then a re-run silently claims to be
        the old rules.
        """
        payload = yaml.safe_dump(
            {"domains": self.domains, "claim_signals": self.claim_signals}, sort_keys=True
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True, slots=True)
class Verdict:
    """One gate decision, with everything needed to argue with it."""

    passed: bool
    reason: str
    rule_version: str
    domains: tuple[str, ...] = ()
    signals: tuple[str, ...] = ()
    matched_terms: tuple[str, ...] = field(default=())

    def __bool__(self) -> bool:
        return self.passed


def load_vocabulary(path: Path | str = DEFAULT_VOCABULARY_PATH) -> Vocabulary:
    """Read and validate the vocabulary file."""
    resolved = Path(path)
    if not resolved.exists():
        raise FileNotFoundError(f"prefilter vocabulary not found at {resolved}")
    raw = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
    return Vocabulary.model_validate(raw)


@lru_cache(maxsize=8)
def _lowered(terms: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(term.lower() for term in terms)


def _matches(haystack: str, terms: list[str]) -> list[str]:
    return [term for term in _lowered(tuple(terms)) if term in haystack]


def searchable(title: str, abstract: str | None) -> str:
    """The text the gate reads: title and abstract, normalised and lowercased.

    Lowercased here and nowhere else in the project. Quote verification
    deliberately preserves case because a recapitalised quote has been edited;
    this is a keyword sweep, where "Qubit" and "qubit" are the same word.
    """
    return normalise(f"{title}\n{abstract or ''}").lower()


def assess(title: str, abstract: str | None, vocabulary: Vocabulary) -> Verdict:
    """Decide whether one document is worth asking a model about."""
    version = vocabulary.rule_version
    text = searchable(title, abstract)

    if len(text) < MIN_TEXT_CHARACTERS:
        return Verdict(
            passed=True,
            reason=(
                "too little text to judge (under "
                f"{MIN_TEXT_CHARACTERS} characters); passed rather than rejected "
                "so a thin feed entry is not mistaken for an empty paper"
            ),
            rule_version=version,
        )

    domains: list[str] = []
    terms: list[str] = []
    for domain, domain_terms in sorted(vocabulary.domains.items()):
        found = _matches(text, domain_terms)
        if found:
            domains.append(domain)
            terms.extend(found)

    signals: list[str] = []
    for signal, signal_terms in sorted(vocabulary.claim_signals.items()):
        if _matches(text, signal_terms):
            signals.append(signal)
    if MEASURED_QUANTITY.search(text):
        signals.append("measurement")

    if not domains and not signals:
        reason = "no tracked-domain term and no claim signal"
    elif not domains:
        reason = f"claim signal ({', '.join(signals)}) but no tracked-domain term"
    elif not signals:
        reason = (
            f"mentions {', '.join(domains)} but asserts nothing: no demonstration, "
            "deployment, regulatory event, record or measured quantity"
        )
    else:
        reason = f"{', '.join(domains)} + {', '.join(signals)}"

    return Verdict(
        passed=bool(domains and signals),
        reason=reason,
        rule_version=version,
        domains=tuple(domains),
        signals=tuple(signals),
        matched_terms=tuple(sorted(set(terms))),
    )
