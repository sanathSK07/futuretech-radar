"""The model boundary.

Everything that talks to a model goes through ``ModelClient``. There are three
reasons it is a protocol rather than direct SDK calls at the call sites.

**Tests must not spend money.** ``ScriptedClient`` answers from a list and
records what it was asked, so prompt construction, response parsing, retry
behaviour and cost arithmetic are all testable at zero cost and zero latency.
The suite has no API key and must never need one.

**Cost has to be visible before it is incurred.** Every response carries its
token counts, and ``Usage`` turns those into an estimate from a price table with
a source and a date on it. A pipeline that cannot say what a run cost cannot be
kept inside a $20/month budget.

**The eval script needs to replay.** Phase 3 compares prompt versions against
the hand-labelled set. That means the same interface, fed recorded responses.

Prices here are for *estimates*. The invoice is authoritative and prices change;
see the note on PRICES.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

import structlog

log = structlog.get_logger(__name__)

HAIKU = "claude-haiku-4-5"
SONNET = "claude-sonnet-5"


@dataclass(frozen=True, slots=True)
class Price:
    """What a model costs per million tokens, and where that came from."""

    input_per_mtok: Decimal
    output_per_mtok: Decimal
    source: str


_PRICE_SOURCE = "platform.claude.com/docs/en/about-claude/pricing, read 2026-09-25"

PRICES: dict[str, Price] = {
    HAIKU: Price(Decimal("1.00"), Decimal("5.00"), _PRICE_SOURCE),
    SONNET: Price(Decimal("2.00"), Decimal("10.00"), _PRICE_SOURCE),
}
"""Published list prices per million tokens.

Deliberately a table with a source string rather than constants in the code. A
bare 0.000001 multiplier somewhere in a cost function is unauditable, and when
prices change — they have twice in this model family — nobody can tell whether
the number was ever right.

These are estimates for planning. They do not know about prompt caching, the
long-context surcharge, or anything negotiated, and they will drift. Treat a
disagreement with the invoice as this table being stale, not the invoice.
"""

BATCH_DISCOUNT = Decimal("0.5")
"""The Batch API's published discount on both input and output tokens.

Triage and extraction are nightly batch work with no user waiting, which is
exactly what it is for, so the pipeline should never pay list price.
"""


class ModelError(RuntimeError):
    """A model call failed in a way the caller has to handle."""


class MissingApiKeyError(ModelError):
    """No API key is configured.

    Its own type because the fix is a one-line change to .env rather than
    anything in the code, and a generic failure buries that.
    """


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """One call, fully specified.

    ``max_tokens`` has no default. Stage-one triage wants roughly four and
    extraction wants two thousand, and the cost difference between them is the
    entire argument of ADR-0008 — so it is stated at every call site rather than
    inherited from a default somebody has to go and look up.
    """

    model: str
    system: str
    prompt: str
    max_tokens: int
    stop_sequences: tuple[str, ...] = ()
    json_schema: dict[str, Any] | None = None
    """When set, sent as ``output_config.format`` so the model is constrained to
    this JSON schema rather than merely asked for it.

    Worth preferring over prompt-level instructions wherever a stage has a
    contract, because a shape the API refuses to emit cannot become a
    ``schema_error`` three layers down. Unverified against the live API as of
    2026-09-25; the first real extraction run is the check.
    """

    # There is deliberately no temperature field. This SDK (1.8.0) does not
    # accept one — it is absent from MessageCreateParams and from the documented
    # Messages parameters — and a field that silently never reaches the API is
    # worse than no field, because it reads like a guarantee.
    #
    # The cost is real and belongs in the open: without temperature=0 the eval
    # cannot assume a prompt change is the only thing that moved between two
    # runs. Phase 3 therefore has to either sample each document more than once
    # or state the noise it is living with. Recorded in PROJECT-STATUS as debt.


@dataclass(frozen=True, slots=True)
class ModelResponse:
    """What came back, with what it cost to get it."""

    text: str
    model: str
    input_tokens: int
    output_tokens: int
    stop_reason: str | None = None

    @property
    def truncated(self) -> bool:
        """True when the model ran out of room mid-answer.

        Worth a named property because a truncated JSON body fails schema
        validation in a way that looks like a bad prompt, and the real fix is a
        larger ``max_tokens``.
        """
        return self.stop_reason == "max_tokens"


@runtime_checkable
class ModelClient(Protocol):
    """Anything that can answer a ModelRequest."""

    def complete(self, request: ModelRequest) -> ModelResponse:
        """Send one request and return one response, or raise ModelError."""
        ...


@dataclass
class Usage:
    """Running token and cost totals for a pipeline stage."""

    batch: bool = False
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    unpriced_models: set[str] = field(default_factory=set)
    _cost: Decimal = field(default=Decimal("0"))

    def record(self, response: ModelResponse) -> None:
        self.calls += 1
        self.input_tokens += response.input_tokens
        self.output_tokens += response.output_tokens

        price = PRICES.get(response.model)
        if price is None:
            # Counted but not priced, and said out loud. Silently costing zero
            # for an unknown model is how a budget check passes while the bill
            # does not.
            self.unpriced_models.add(response.model)
            log.warning("model_not_in_price_table", model=response.model)
            return

        discount = BATCH_DISCOUNT if self.batch else Decimal("1")
        million = Decimal("1000000")
        self._cost += discount * (
            price.input_per_mtok * Decimal(response.input_tokens) / million
            + price.output_per_mtok * Decimal(response.output_tokens) / million
        )

    @property
    def estimated_cost_usd(self) -> Decimal:
        """The estimate, unrounded.

        Not rounded to cents here: a per-document cost is fractions of a cent and
        rounding each one to two places turns a real total into zero. Round at
        the point of display.
        """
        return self._cost

    @property
    def fully_priced(self) -> bool:
        """False when any call used a model missing from the price table."""
        return not self.unpriced_models

    def summary(self) -> str:
        rate = "batch" if self.batch else "list"
        line = (
            f"{self.calls} calls, {self.input_tokens:,} in / {self.output_tokens:,} out, "
            f"~${self.estimated_cost_usd:.4f} at {rate} rates"
        )
        if not self.fully_priced:
            line += f" (EXCLUDES {', '.join(sorted(self.unpriced_models))}: not in the price table)"
        return line


@dataclass
class ScriptedClient:
    """A ModelClient that answers from a list. For tests and evals only.

    Lives in the package rather than in the test tree so that mypy --strict
    checks it and the eval script can import it. It holds no credentials and
    performs no I/O.

    Raises rather than repeating its last answer when the script runs out: a
    client that silently loops would make an off-by-one in batching look like a
    model that keeps agreeing with itself.
    """

    responses: list[ModelResponse | Exception] = field(default_factory=list)
    requests: list[ModelRequest] = field(default_factory=list)

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError(
                f"ScriptedClient ran out of responses on call {len(self.requests)}; "
                "the script is shorter than the number of calls under test"
            )
        answer = self.responses.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    @classmethod
    def answering(cls, *texts: str, model: str = HAIKU) -> ScriptedClient:
        """Build a client that returns these strings in order.

        Token counts are the rough shape of the real thing rather than zero, so
        a test that asserts on cost is exercising the arithmetic instead of
        multiplying by nothing.
        """
        return cls(
            responses=[
                ModelResponse(
                    text=text,
                    model=model,
                    input_tokens=max(1, len(text) // 4 + 20),
                    output_tokens=max(1, len(text) // 4),
                    stop_reason="end_turn",
                )
                for text in texts
            ]
        )


class AnthropicClient:
    """The real client.

    Wraps the official SDK rather than calling the HTTP API directly. The
    project's own ``SafeHttpClient`` is deliberately not used here: its job is
    guarding against hostile third-party hosts — SSRF checks, byte caps,
    redirect re-validation — and none of that applies to a known first-party
    endpoint, while the SDK does handle the parts that matter here (typed
    errors, overload retries, and the Batch API this pipeline will move to).

    The import is inside ``__init__`` so that the rest of the module, and every
    test using ScriptedClient, works whether or not the SDK is installed.
    """

    def __init__(self, api_key: str | None, *, timeout_seconds: float = 120.0) -> None:
        if not api_key:
            raise MissingApiKeyError(
                "RADAR_ANTHROPIC_API_KEY is not set. Add it with "
                "'make secret k=RADAR_ANTHROPIC_API_KEY', which reads it from a "
                "hidden prompt rather than a shell argument."
            )
        try:
            from anthropic import Anthropic
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise ModelError("the 'anthropic' package is not installed; run 'make setup'") from exc

        self._client = Anthropic(api_key=api_key, timeout=timeout_seconds)

    def complete(self, request: ModelRequest) -> ModelResponse:
        from anthropic import APIError

        # Optional parameters are added only when set. Passing None where the
        # SDK expects its own sentinel is a type error, not a no-op.
        extra: dict[str, Any] = {}
        if request.stop_sequences:
            extra["stop_sequences"] = list(request.stop_sequences)
        if request.json_schema is not None:
            extra["output_config"] = {
                "format": {"type": "json_schema", "schema": request.json_schema}
            }

        try:
            message: Any = self._client.messages.create(
                model=request.model,
                system=request.system,
                messages=[{"role": "user", "content": request.prompt}],
                max_tokens=request.max_tokens,
                **extra,
            )
        except APIError as exc:
            raise ModelError(f"{request.model} call failed: {exc}") from exc

        text = "".join(
            block.text for block in message.content if getattr(block, "type", None) == "text"
        )
        return ModelResponse(
            text=text,
            model=message.model,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            stop_reason=message.stop_reason,
        )
