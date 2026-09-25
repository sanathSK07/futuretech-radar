"""The model boundary.

No test here has an API key or makes a network call, and none ever should: the
whole point of the protocol is that prompt construction, parsing and cost
arithmetic are testable for free. What is pinned is mostly the cost maths, because
it is the thing that decides whether this project stays inside its budget and the
thing nobody notices is wrong until an invoice arrives.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from radar.pipeline.llm import (
    BATCH_DISCOUNT,
    HAIKU,
    PRICES,
    SONNET,
    MissingApiKeyError,
    ModelClient,
    ModelRequest,
    ModelResponse,
    ScriptedClient,
    Usage,
)


def response(*, model: str = HAIKU, in_tokens: int = 1000, out_tokens: int = 100) -> ModelResponse:
    return ModelResponse(text="YES", model=model, input_tokens=in_tokens, output_tokens=out_tokens)


class TestThePriceTable:
    def test_every_model_the_pipeline_names_has_a_price(self) -> None:
        assert set(PRICES) >= {HAIKU, SONNET}

    def test_every_price_says_where_it_came_from(self) -> None:
        """An unsourced price cannot be checked when it goes stale."""
        assert all(price.source for price in PRICES.values())
        assert all("read 2026" in price.source for price in PRICES.values())

    def test_output_costs_more_than_input(self) -> None:
        """Sanity check on the table itself, and the reason stage one returns
        one token: output is the expensive half."""
        for price in PRICES.values():
            assert price.output_per_mtok > price.input_per_mtok


class TestCostArithmetic:
    def test_a_known_quantity_costs_what_the_table_says(self) -> None:
        """One million in, one million out, at Haiku's $1/$5, is $6."""
        usage = Usage()
        usage.record(response(in_tokens=1_000_000, out_tokens=1_000_000))
        assert usage.estimated_cost_usd == Decimal("6")

    def test_batch_halves_it(self) -> None:
        usage = Usage(batch=True)
        usage.record(response(in_tokens=1_000_000, out_tokens=1_000_000))
        assert usage.estimated_cost_usd == Decimal("6") * BATCH_DISCOUNT

    def test_sonnet_is_priced_separately(self) -> None:
        usage = Usage()
        usage.record(response(model=SONNET, in_tokens=1_000_000, out_tokens=1_000_000))
        assert usage.estimated_cost_usd == Decimal("12")

    def test_fractions_of_a_cent_are_not_rounded_away(self) -> None:
        """The failure this guards against: per-document costs are tiny, and
        rounding each one to two decimals makes a real total come out at zero.
        """
        usage = Usage(batch=True)
        for _ in range(1000):
            usage.record(response(in_tokens=30, out_tokens=3))
        assert usage.estimated_cost_usd > 0
        assert usage.calls == 1000

    def test_totals_accumulate_across_calls(self) -> None:
        usage = Usage()
        usage.record(response(in_tokens=100, out_tokens=10))
        usage.record(response(in_tokens=200, out_tokens=20))
        assert (usage.input_tokens, usage.output_tokens, usage.calls) == (300, 30, 2)


class TestUnknownModels:
    def test_an_unpriced_model_is_counted_but_not_costed(self) -> None:
        usage = Usage()
        usage.record(response(model="claude-something-unreleased", in_tokens=500, out_tokens=50))
        assert usage.input_tokens == 500
        assert usage.estimated_cost_usd == Decimal("0")

    def test_and_the_gap_is_reported_rather_than_hidden(self) -> None:
        """Silently costing zero for an unknown model is how a budget check
        passes while the invoice does not."""
        usage = Usage()
        usage.record(response(model="claude-something-unreleased"))
        assert not usage.fully_priced
        assert "not in the price table" in usage.summary()
        assert "claude-something-unreleased" in usage.summary()

    def test_a_fully_priced_run_says_nothing_about_gaps(self) -> None:
        usage = Usage()
        usage.record(response())
        assert usage.fully_priced
        assert "price table" not in usage.summary()


class TestTruncation:
    def test_hitting_the_token_ceiling_is_named(self) -> None:
        """A truncated JSON body fails schema validation in a way that looks
        like a bad prompt; the real fix is a larger max_tokens."""
        assert ModelResponse(
            text="{partial", model=HAIKU, input_tokens=10, output_tokens=4, stop_reason="max_tokens"
        ).truncated

    def test_a_normal_stop_is_not_truncation(self) -> None:
        assert not ModelResponse(
            text="NO", model=HAIKU, input_tokens=10, output_tokens=1, stop_reason="end_turn"
        ).truncated


class TestScriptedClient:
    def test_it_satisfies_the_protocol(self) -> None:
        assert isinstance(ScriptedClient(), ModelClient)

    def test_it_answers_in_order(self) -> None:
        client = ScriptedClient.answering("YES", "NO", "YES")
        request = ModelRequest(model=HAIKU, system="s", prompt="p", max_tokens=4)
        assert [client.complete(request).text for _ in range(3)] == ["YES", "NO", "YES"]

    def test_it_records_what_it_was_asked(self) -> None:
        """Prompt construction is most of what there is to get wrong, and this
        is how it gets asserted on without spending anything."""
        client = ScriptedClient.answering("YES")
        client.complete(ModelRequest(model=HAIKU, system="judge", prompt="a title", max_tokens=4))
        assert client.requests[0].system == "judge"
        assert client.requests[0].prompt == "a title"
        assert client.requests[0].max_tokens == 4

    def test_running_out_raises_rather_than_repeating(self) -> None:
        """A client that looped would make an off-by-one in batching look like a
        model that keeps agreeing with itself."""
        client = ScriptedClient.answering("YES")
        request = ModelRequest(model=HAIKU, system="s", prompt="p", max_tokens=4)
        client.complete(request)
        with pytest.raises(AssertionError, match="ran out of responses"):
            client.complete(request)

    def test_a_scripted_failure_is_raised(self) -> None:
        client = ScriptedClient(responses=[RuntimeError("overloaded")])
        with pytest.raises(RuntimeError, match="overloaded"):
            client.complete(ModelRequest(model=HAIKU, system="s", prompt="p", max_tokens=4))

    def test_its_token_counts_are_not_zero(self) -> None:
        """Zero counts would make every cost assertion pass by multiplying by
        nothing."""
        client = ScriptedClient.answering("a plausible answer of some length")
        got = client.complete(ModelRequest(model=HAIKU, system="s", prompt="p", max_tokens=16))
        assert got.input_tokens > 0
        assert got.output_tokens > 0


class TestRequestDefaults:
    def test_there_is_no_temperature_field(self) -> None:
        """The SDK does not accept one, so carrying it would be a false promise.

        An earlier version of this module had temperature=0.0 and a docstring
        claiming determinism for the eval. The SDK (1.8.0) has no such
        parameter — it is absent from MessageCreateParams — so the field would
        have been dropped on the floor while reading like a guarantee. The eval
        has to live with sampling noise or sample more than once; that is
        recorded as debt rather than papered over here.
        """
        assert not hasattr(
            ModelRequest(model=HAIKU, system="s", prompt="p", max_tokens=4), "temperature"
        )

    def test_a_json_schema_is_optional_and_off_by_default(self) -> None:
        assert ModelRequest(model=HAIKU, system="s", prompt="p", max_tokens=4).json_schema is None

    def test_max_tokens_has_no_default(self) -> None:
        """Stage one wants four and extraction wants two thousand; the
        difference is the whole argument of ADR-0008, so it is stated at the
        call site."""
        with pytest.raises(TypeError):
            ModelRequest(model=HAIKU, system="s", prompt="p")  # type: ignore[call-arg]


class TestMissingCredentials:
    def test_a_missing_key_says_how_to_set_it(self) -> None:
        from radar.pipeline.llm import AnthropicClient

        with pytest.raises(MissingApiKeyError, match="make secret"):
            AnthropicClient(api_key=None)

    def test_an_empty_string_counts_as_missing(self) -> None:
        """An unset variable read through os.environ.get arrives as '' often
        enough that treating it as a key would fail at the API instead of here.
        """
        from radar.pipeline.llm import AnthropicClient

        with pytest.raises(MissingApiKeyError):
            AnthropicClient(api_key="")
