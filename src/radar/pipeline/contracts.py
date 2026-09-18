"""What a model is allowed to return.

Every model call in this pipeline produces JSON that must satisfy one of these
schemas before anything is written. The schemas are not documentation of what
the model usually does — they are the boundary. Output that does not fit is
recorded as ``schema_error`` on the analysis run and discarded.

Two habits run through all of them:

``extra="forbid"`` — a model that invents a field is telling us the prompt and
the contract have drifted apart, and silently dropping the field would hide
that. Better a loud failure on twenty documents than a quiet one on twenty
thousand.

Validation mirrors the database CHECK constraints rather than trusting them. The
database is the last line; failing here gives a diagnosable error with the
offending value in it, instead of an IntegrityError three layers down.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator

from radar.core.types import ClaimType, DateBasis, EpistemicLabel
from radar.pipeline.grounding import MAX_QUOTE_CHARACTERS, MIN_QUOTE_CHARACTERS, quote_contains

FORECAST_TYPES = frozenset({ClaimType.EXPECTATION, ClaimType.EXPERT_FORECAST})


class Metric(BaseModel):
    """One measured quantity pulled out of a claim."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, description="What was measured, e.g. 'gate fidelity'.")
    value: str = Field(
        min_length=1,
        description=(
            "The value exactly as written in the quote, kept as text. A number "
            "parsed into a float loses '>99.9' and '~3x', and those distinctions "
            "are the difference between a result and a rounding."
        ),
    )
    unit: str | None = Field(default=None, description="Unit as written, if any.")


class Mention(BaseModel):
    """An entity as the model found it, before any resolution.

    ``surface`` is the string in the document. Turning it into an entity is
    deterministic lookup elsewhere (docs/04 rule G.3.2) — the model never
    decides that two names are the same organisation, and never invents an
    identifier.
    """

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(description="organization | technology | product | person | place")
    surface: str = Field(min_length=1, description="The mention exactly as it appears.")


class ExtractedClaim(BaseModel):
    """One assertion with the quote that supports it.

    The validators below enforce, on the model's output, the rules the database
    enforces on the row: a date needs a basis, a forecast is not an observed
    fact, and every number in a metric must appear in the quote. The last one is
    the interesting one — it is how a model that knows the real figure from
    training is stopped from supplying it when the document does not.
    """

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, description="The claim as one plain sentence.")
    quote: str = Field(
        min_length=MIN_QUOTE_CHARACTERS,
        max_length=MAX_QUOTE_CHARACTERS,
        description="Verbatim from the document. Copied, never paraphrased.",
    )
    claim_type: ClaimType
    epistemic_label: EpistemicLabel
    date_referenced: date | None = None
    date_basis: DateBasis | None = None
    metrics: list[Metric] = Field(default_factory=list)
    subjects: list[Mention] = Field(default_factory=list)

    @model_validator(mode="after")
    def _a_date_needs_a_basis(self) -> ExtractedClaim:
        if self.date_referenced is not None and self.date_basis is None:
            raise ValueError(
                "date_referenced was given without date_basis; a date must say "
                "whether it came from document metadata or from the quoted text"
            )
        return self

    @model_validator(mode="after")
    def _a_forecast_is_not_an_observed_fact(self) -> ExtractedClaim:
        if (
            self.claim_type in FORECAST_TYPES
            and self.epistemic_label == EpistemicLabel.OBSERVED_FACT
        ):
            raise ValueError(
                f"claim_type {self.claim_type.value} cannot carry the "
                "observed_fact label: a forecast has not been observed"
            )
        return self

    @model_validator(mode="after")
    def _metrics_must_be_in_the_quote(self) -> ExtractedClaim:
        missing = [m.value for m in self.metrics if not quote_contains(self.quote, m.value)]
        if missing:
            raise ValueError(
                f"metric values {missing} do not appear in the quote; a number "
                "the document does not state cannot be attributed to it"
            )
        return self


class ExtractionResult(BaseModel):
    """Everything one extraction call returns for one document."""

    model_config = ConfigDict(extra="forbid")

    claims: list[ExtractedClaim] = Field(
        default_factory=list,
        description="May be empty. A document with no extractable claim is a normal outcome.",
    )
    no_claims_reason: str | None = Field(
        default=None,
        description=(
            "Why nothing was extracted, when nothing was. Requested so that an "
            "empty result is distinguishable from a confused one."
        ),
    )


class TriageDecision(BaseModel):
    """Whether a document is worth extracting from.

    Triage exists to keep cost proportionate: most of what arrives in a daily
    arXiv sweep is not about a tracked technology, and running full extraction
    over all of it would spend most of the budget on documents that produce
    nothing.

    ``relevant`` is deliberately a boolean with a separate ``confidence``, not a
    score with a threshold. A number invites a tuned cutoff that nobody can
    explain; a decision with a stated confidence can be audited by reading it.
    """

    model_config = ConfigDict(extra="forbid")

    relevant: bool
    confidence: str = Field(description="high | medium | low")
    reason: str = Field(
        min_length=1, max_length=400, description="One sentence, readable by a curator."
    )
    domains: list[str] = Field(
        default_factory=list, description="Domain slugs this document appears to belong to."
    )
    technology_mentions: list[str] = Field(
        default_factory=list,
        description="Surface strings only. Resolution to tracked technologies happens in code.",
    )

    @model_validator(mode="after")
    def _confidence_is_one_of_three(self) -> TriageDecision:
        if self.confidence not in {"high", "medium", "low"}:
            raise ValueError(f"confidence must be high, medium or low; got {self.confidence!r}")
        return self
