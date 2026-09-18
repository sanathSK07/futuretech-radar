"""Quote verification and the extraction contracts.

These are the tests for the promise the whole project rests on: that a claim in
this database is supported by words that actually appear in the source. Most of
them are attempts to get something ungrounded past the check.
"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from radar.core.types import ClaimType, DateBasis, EpistemicLabel
from radar.pipeline.contracts import ExtractedClaim, ExtractionResult, TriageDecision
from radar.pipeline.grounding import (
    MAX_QUOTE_CHARACTERS,
    normalise,
    quote_contains,
    verify_quote,
)

ABSTRACT = (
    "We present a bimanual manipulation system that folds unseen articles of "
    "clothing. On a held-out set of 30 garments the policy achieved a 92% "
    "success rate, and we demonstrate continuous operation for 4 hours without "
    "human intervention. Code and checkpoints are released."
)


class TestNormalisation:
    def test_typographic_quotes_match_ascii_ones(self) -> None:
        assert normalise("the “best” result") == normalise('the "best" result')

    def test_dashes_of_every_width_are_the_same_dash(self) -> None:
        assert normalise("state–of–the—art") == normalise("state-of-the-art")

    def test_a_hyphenated_line_break_is_rejoined(self) -> None:
        """A PDF that wraps 'quantum' as 'quan-\\ntum' is still the word quantum."""
        assert normalise("quan-\ntum advantage") == "quantum advantage"

    def test_whitespace_runs_collapse(self) -> None:
        assert normalise("two\n\n  spaces\ttabbed") == "two spaces tabbed"

    def test_non_breaking_spaces_become_spaces(self) -> None:
        assert normalise("99.9 %") == "99.9 %"

    def test_case_is_preserved(self) -> None:
        """Lowercasing would make the check kinder and less true."""
        assert normalise("US policy") != normalise("us policy")


class TestQuoteVerification:
    def test_a_quote_lifted_from_the_source_verifies(self) -> None:
        result = verify_quote("the policy achieved a 92% success rate", ABSTRACT)
        assert result.verified
        assert result.offset is not None
        assert ABSTRACT[result.offset : result.offset + 10].startswith("the policy")

    def test_an_invented_quote_is_refused(self) -> None:
        """The whole point: a plausible sentence that is not in the document."""
        result = verify_quote("the policy achieved a 99% success rate on unseen garments", ABSTRACT)
        assert not result.verified
        assert result.reason == "the quote does not appear in the source document"

    def test_a_quote_differing_only_in_typography_still_verifies(self) -> None:
        result = verify_quote("continuous operation for 4 hours", ABSTRACT)
        assert result.verified

    def test_a_quote_reflowed_across_lines_still_verifies(self) -> None:
        result = verify_quote("held-out set of\n     30 garments", ABSTRACT)
        assert result.verified

    def test_a_trivially_short_quote_is_refused(self) -> None:
        """Without a floor, a model returning 'the' would verify every time.

        The metric would then read 100% exactly when the extraction supported
        nothing at all.
        """
        result = verify_quote("the", ABSTRACT)
        assert not result.verified
        assert "at least" in str(result.reason)

    def test_a_quote_that_is_really_the_whole_document_is_refused(self) -> None:
        long_source = "x" * (MAX_QUOTE_CHARACTERS + 100)
        result = verify_quote(long_source, long_source)
        assert not result.verified
        assert "excerpt" in str(result.reason)

    def test_an_empty_quote_is_refused(self) -> None:
        assert not verify_quote("   ", ABSTRACT)

    def test_a_document_with_no_text_verifies_nothing(self) -> None:
        result = verify_quote("a perfectly reasonable quote about robots", "")
        assert not result.verified
        assert "no text" in str(result.reason)

    def test_the_result_is_falsy_when_it_failed(self) -> None:
        assert not verify_quote("not in here at all, nowhere to be seen", ABSTRACT)
        assert verify_quote("Code and checkpoints are released", ABSTRACT)


class TestMetricGrounding:
    def test_a_value_in_the_quote_is_found(self) -> None:
        assert quote_contains("achieved a 92% success rate", "92%")

    def test_spacing_around_a_unit_does_not_matter(self) -> None:
        assert quote_contains("fidelity of 99.9 %", "99.9%")

    def test_a_value_absent_from_the_quote_is_not_found(self) -> None:
        assert not quote_contains("achieved a 92% success rate", "94%")


def a_claim(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "text": "The system folded unseen garments with a 92% success rate.",
        "quote": "the policy achieved a 92% success rate",
        "claim_type": ClaimType.MEASURED_RESULT,
        "epistemic_label": EpistemicLabel.OBSERVED_FACT,
    }
    payload.update(overrides)
    return payload


class TestExtractionContract:
    def test_a_well_formed_claim_validates(self) -> None:
        claim = ExtractedClaim.model_validate(
            a_claim(metrics=[{"name": "success rate", "value": "92%"}])
        )
        assert claim.metrics[0].value == "92%"

    def test_a_metric_missing_from_the_quote_is_refused(self) -> None:
        """A model that knows the real figure may not supply it from memory."""
        with pytest.raises(ValidationError, match="do not appear in the quote"):
            ExtractedClaim.model_validate(
                a_claim(metrics=[{"name": "success rate", "value": "94%"}])
            )

    def test_an_invented_field_is_refused(self) -> None:
        """Drift between prompt and contract should be loud, not silent."""
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            ExtractedClaim.model_validate(a_claim(confidence_score=0.87))

    def test_a_date_without_a_basis_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="date_basis"):
            ExtractedClaim.model_validate(a_claim(date_referenced=date(2026, 4, 1)))

    def test_a_date_with_a_basis_validates(self) -> None:
        claim = ExtractedClaim.model_validate(
            a_claim(
                date_referenced=date(2026, 4, 1),
                date_basis=DateBasis.DOCUMENT_METADATA,
            )
        )
        assert claim.date_basis == DateBasis.DOCUMENT_METADATA

    @pytest.mark.parametrize("claim_type", [ClaimType.EXPECTATION, ClaimType.EXPERT_FORECAST])
    def test_a_forecast_cannot_be_an_observed_fact(self, claim_type: ClaimType) -> None:
        with pytest.raises(ValidationError, match="has not been observed"):
            ExtractedClaim.model_validate(
                a_claim(claim_type=claim_type, epistemic_label=EpistemicLabel.OBSERVED_FACT)
            )

    def test_a_paraphrase_too_short_to_be_a_quote_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="at least 24 characters"):
            ExtractedClaim.model_validate(a_claim(quote="it worked"))

    def test_an_unknown_claim_type_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            ExtractedClaim.model_validate(a_claim(claim_type="breakthrough"))

    def test_an_empty_extraction_is_a_valid_outcome(self) -> None:
        """Most documents contain no claim worth storing. That is not an error."""
        result = ExtractionResult.model_validate(
            {"claims": [], "no_claims_reason": "A survey paper with no new results."}
        )
        assert result.claims == []


class TestTriageContract:
    def test_a_decision_validates(self) -> None:
        decision = TriageDecision.model_validate(
            {
                "relevant": True,
                "confidence": "high",
                "reason": "Reports a manipulation policy evaluated on unseen garments.",
                "domains": ["robotics"],
                "technology_mentions": ["bimanual manipulation"],
            }
        )
        assert decision.relevant is True

    def test_an_unknown_confidence_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="high, medium or low"):
            TriageDecision.model_validate(
                {"relevant": True, "confidence": "very high", "reason": "x"}
            )

    def test_a_score_instead_of_a_decision_is_refused(self) -> None:
        """No relevance score: a tuned threshold nobody can explain is worse."""
        with pytest.raises(ValidationError):
            TriageDecision.model_validate(
                {"relevant": True, "confidence": "high", "reason": "x", "score": 0.91}
            )
