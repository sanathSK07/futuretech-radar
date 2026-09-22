"""The labelled set: twenty documents a person reads and marks up by hand.

This is the yardstick extraction is measured against, and it has to be built by
a human before any model runs. If the labels come from a model, the evaluation
measures the model agreeing with itself and the precision number means nothing.

Two commands use this module. ``radar label export`` picks a stratified sample
and writes a worksheet with blanks. ``radar label check`` reads the worksheet
back and validates it — including running the same quote verification the
pipeline uses, because a hand-typed quote is exactly as likely to be wrong as a
generated one, and a labelled set with a mistyped quote silently penalises the
model for being right.
"""

from __future__ import annotations

import random
import textwrap
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from radar.core.models import Source, SourceDocument
from radar.core.types import ClaimType, EpistemicLabel
from radar.pipeline.contracts import ExtractedClaim
from radar.pipeline.grounding import verify_quote

DEFAULT_PER_DOMAIN = 4
DEFAULT_SEED = 20260921
"""A fixed seed so the sample is reproducible.

Rerunning the export must give the same twenty documents, or half a Saturday's
labelling belongs to a set that no longer exists.
"""


class LabelledClaim(BaseModel):
    """One claim a human found in a document."""

    model_config = ConfigDict(extra="forbid")

    quote: str
    text: str
    claim_type: ClaimType
    epistemic_label: EpistemicLabel


class LabelledDocument(BaseModel):
    """One document's labels, as typed into the worksheet."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    external_id: str = ""
    title: str = ""
    url: str = ""
    domains: list[str] = Field(default_factory=list)
    abstract: str = ""
    relevant: bool | None = Field(
        default=None, description="None means this document has not been labelled yet."
    )
    claims: list[LabelledClaim] = Field(default_factory=list)

    @property
    def is_labelled(self) -> bool:
        return self.relevant is not None


class LabelledSet(BaseModel):
    """A whole worksheet."""

    model_config = ConfigDict(extra="forbid")

    seed: int = DEFAULT_SEED
    generated_at: str = ""
    documents: list[LabelledDocument] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Problem:
    """Something wrong with a hand-written label."""

    external_id: str
    detail: str


@dataclass(frozen=True, slots=True)
class CheckReport:
    """What ``radar label check`` found."""

    total: int
    labelled: int
    relevant: int
    claims: int
    problems: list[Problem]

    @property
    def ok(self) -> bool:
        return not self.problems


def select_documents(
    session: Session, *, per_domain: int = DEFAULT_PER_DOMAIN, seed: int = DEFAULT_SEED
) -> list[SourceDocument]:
    """Pick a sample spread across domains, deterministically.

    Stratified rather than random over everything, because the corpus is not
    balanced: arXiv's robotics and AI categories produce far more documents per
    day than the quantum or energy ones, and an unstratified sample of twenty
    would be mostly robotics. The maturity model needs to be exercised across
    all six domains, which means the labelled set does too.
    """
    rows = session.execute(
        select(SourceDocument, Source.domains)
        .join(Source, SourceDocument.source_id == Source.id)
        .where(SourceDocument.abstract.is_not(None))
        .order_by(SourceDocument.external_id)
    ).all()

    by_domain: dict[str, list[SourceDocument]] = {}
    for document, domains in rows:
        for domain in domains or ["unassigned"]:
            by_domain.setdefault(domain, []).append(document)

    rng = random.Random(seed)  # noqa: S311 - sampling for review, not cryptography
    chosen: dict[UUID, SourceDocument] = {}
    for domain in sorted(by_domain):
        candidates = by_domain[domain]
        take = min(per_domain, len(candidates))
        for document in rng.sample(candidates, take):
            chosen.setdefault(document.id, document)

    return sorted(chosen.values(), key=lambda d: (d.source_id, d.external_id))


_INSTRUCTIONS = """\
# FutureTech Radar - labelled evaluation set
#
# Fill this in by hand. It is the yardstick the extraction pipeline is measured
# against, so nothing in it may come from a model - including from this one.
#
# For each document below:
#
#   relevant:  true if the document is about a technology this project tracks
#              and reports something that happened. false for surveys, position
#              papers, incremental benchmarks, and anything off-topic.
#
#   claims:    one entry per assertion worth storing. Leave empty if there are
#              none, which is a normal and common outcome.
#
#              quote            copy and paste EXACTLY from the abstract above.
#                               'radar label check' verifies it character for
#                               character after normalising typography.
#              text             the claim in one plain sentence, in your words.
#              claim_type       measured_result | demonstration | deployment |
#                               regulatory_event | funding_or_investment |
#                               self_reported_claim | expectation |
#                               expert_forecast | opinion
#              epistemic_label  observed_fact | source_expectation |
#                               expert_forecast
#
# A forecast (expectation, expert_forecast) can never be an observed_fact.
#
# Run 'radar label check <this file>' whenever you stop. It catches mistyped
# quotes, which would otherwise penalise the model for being right.
"""


def render_worksheet(documents: Sequence[SourceDocument], *, seed: int = DEFAULT_SEED) -> str:
    """Write the worksheet a person fills in.

    Hand-written YAML rather than CSV or JSON: it takes multi-line quotes
    without escaping, it survives comments, and a person editing it in any text
    editor can see what they are doing.
    """
    payload: dict[str, Any] = {
        "seed": seed,
        "generated_at": datetime.now(UTC).date().isoformat(),
        "documents": [
            {
                "id": str(document.id),
                "external_id": document.external_id,
                "title": document.title,
                "url": document.url,
                "domains": list(document.source.domains or []),
                "abstract": (document.abstract or "").strip(),
                "relevant": None,
                "claims": [],
            }
            for document in documents
        ],
    }
    body = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, width=88)
    return f"{_INSTRUCTIONS}\n{body}"


def parse_worksheet(text: str) -> LabelledSet:
    """Read a filled-in worksheet. Raises ValidationError on a malformed one."""
    data = yaml.safe_load(text) or {}
    return LabelledSet.model_validate(data)


def check_worksheet(session: Session, labelled: LabelledSet) -> CheckReport:
    """Validate hand-written labels against the documents they came from.

    Every quote is verified against the abstract stored in the database, not
    against the copy in the worksheet, so an edited worksheet cannot make a
    wrong quote look right.
    """
    problems: list[Problem] = []
    claims = 0
    relevant = 0

    for entry in labelled.documents:
        if not entry.is_labelled:
            continue
        if entry.relevant:
            relevant += 1

        document = session.get(SourceDocument, entry.id)
        if document is None:
            problems.append(
                Problem(entry.external_id, "no document with this id is in the database")
            )
            continue

        source_text = f"{document.title}\n{document.abstract or ''}"
        for index, claim in enumerate(entry.claims, start=1):
            claims += 1
            verification = verify_quote(claim.quote, source_text)
            if not verification.verified:
                problems.append(Problem(entry.external_id, f"claim {index}: {verification.reason}"))
                continue
            try:
                ExtractedClaim.model_validate(claim.model_dump())
            except ValidationError as exc:
                first = exc.errors()[0]
                problems.append(Problem(entry.external_id, f"claim {index}: {first['msg']}"))

    return CheckReport(
        total=len(labelled.documents),
        labelled=sum(1 for d in labelled.documents if d.is_labelled),
        relevant=relevant,
        claims=claims,
        problems=problems,
    )


def format_report(report: CheckReport) -> str:
    """A short human summary of a check."""
    lines = [
        f"{report.labelled}/{report.total} documents labelled"
        f"  ({report.relevant} relevant, {report.claims} claims written)",
    ]
    if report.problems:
        lines.append(f"\n{len(report.problems)} problem(s):")
        lines.extend(f"  {p.external_id}: {p.detail}" for p in report.problems)
        lines.append(
            "\n"
            + textwrap.fill(
                "A quote that does not verify is usually a paraphrase or a "
                "copy that picked up an edit. Copy it again from the abstract "
                "in the worksheet.",
                width=88,
                initial_indent="  ",
                subsequent_indent="  ",
            )
        )
    elif report.labelled:
        lines.append("\nEvery quote verifies against its source document.")
    return "\n".join(lines)
