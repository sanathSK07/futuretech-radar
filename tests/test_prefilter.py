"""The triage gate.

These tests encode the one thing the gate exists to do: let through documents
that assert something about the world, and hold back the method and theory papers
that make up most of an arXiv day. The expensive failure mode is the second kind
passing, so most of what is pinned here is rejection.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from radar.pipeline.prefilter import (
    MEASURED_QUANTITY,
    MIN_TEXT_CHARACTERS,
    Vocabulary,
    assess,
    load_vocabulary,
    searchable,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def vocabulary() -> Vocabulary:
    """The real shipped vocabulary. A fixture copy would drift from it."""
    return load_vocabulary(PROJECT_ROOT / "prefilter.yaml")


class TestTheShippedVocabulary:
    def test_it_loads_and_validates(self, vocabulary: Vocabulary) -> None:
        assert set(vocabulary.domains) == {
            "ai",
            "robotics",
            "quantum",
            "semiconductors",
            "energy",
            "biotech",
        }

    def test_every_mvp_domain_has_terms(self, vocabulary: Vocabulary) -> None:
        empty = [domain for domain, terms in vocabulary.domains.items() if not terms]
        assert empty == []

    def test_no_term_is_short_enough_to_match_by_accident(self, vocabulary: Vocabulary) -> None:
        """A two-character term matches half the corpus and tells you nothing.

        'dof' is the shortest deliberate one; anything shorter is a typo.
        """
        groups = list(vocabulary.domains.values()) + list(vocabulary.claim_signals.values())
        short = [term for terms in groups for term in terms if len(term) < 3]
        assert short == []

    def test_the_rule_version_follows_the_content(self, vocabulary: Vocabulary) -> None:
        """A hand-written version is one somebody forgets to change."""
        edited = Vocabulary(
            domains={**vocabulary.domains, "quantum": [*vocabulary.domains["quantum"], "magnon"]},
            claim_signals=vocabulary.claim_signals,
        )
        assert edited.rule_version != vocabulary.rule_version

    def test_the_rule_version_ignores_key_order(self, vocabulary: Vocabulary) -> None:
        """Reordering the file is not a rule change, and must not look like one."""
        reversed_domains = dict(reversed(list(vocabulary.domains.items())))
        assert (
            Vocabulary(
                domains=reversed_domains, claim_signals=vocabulary.claim_signals
            ).rule_version
            == vocabulary.rule_version
        )

    def test_an_unknown_key_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            Vocabulary.model_validate(
                {"domains": {"ai": ["agent"]}, "claim_signals": {"x": ["y"]}, "weights": {}}
            )


class TestRejection:
    """The cost case: what must NOT reach a model."""

    def test_a_method_paper_is_rejected(self, vocabulary: Vocabulary) -> None:
        verdict = assess(
            "A Unified Framework for Multi-Agent Policy Optimisation",
            "We propose a novel framework for policy optimisation in multi-agent "
            "settings. Our approach generalises several existing methods and we "
            "prove convergence under mild assumptions.",
            vocabulary,
        )
        assert not verdict
        assert "asserts nothing" in verdict.reason

    def test_a_theory_paper_is_rejected(self, vocabulary: Vocabulary) -> None:
        verdict = assess(
            "On the Complexity of Entanglement Distillation Protocols",
            "We study the asymptotic complexity of entanglement distillation and "
            "give an information-theoretic lower bound for a class of protocols.",
            vocabulary,
        )
        assert not verdict
        assert verdict.domains == ("quantum",)

    def test_outperforming_a_baseline_is_not_a_claim_signal(self, vocabulary: Vocabulary) -> None:
        """The vocabulary of a method paper, deliberately excluded.

        Beating a baseline is a fact about a leaderboard, not evidence that a
        capability exists in the world.
        """
        verdict = assess(
            "Improved Grasp Synthesis for Cluttered Scenes",
            "Our method outperforms prior work on grasp synthesis and shows "
            "strong results across a suite of simulated manipulation tasks.",
            vocabulary,
        )
        assert not verdict

    def test_a_claim_outside_every_tracked_domain_is_rejected(self, vocabulary: Vocabulary) -> None:
        verdict = assess(
            "A Record Harvest in the Loire Valley",
            "Growers reported the longest ripening season measured since records "
            "began, with ripening sustained for 40 days beyond the usual window.",
            vocabulary,
        )
        assert not verdict
        assert "no tracked-domain term" in verdict.reason

    def test_the_known_yield_false_positive_is_pinned_not_hidden(
        self, vocabulary: Vocabulary
    ) -> None:
        """A wine harvest passes the gate, and that is the accepted trade.

        "yield" is a core semiconductor metric and an agricultural one. Dropping
        it would lose every fab yield claim; keeping it costs one model call on
        the occasional farming article. The two errors are not symmetric — a
        false negative means evidence nobody ever looks at, and nothing in the
        system reports it — so the term stays and this test makes the cost
        visible rather than surprising. If such passes ever become frequent the
        fix is a narrower term, not a silent removal.
        """
        verdict = assess(
            "A Record Harvest in the Loire Valley",
            "Growers reported record yields, measured across 40 days of harvest.",
            vocabulary,
        )
        assert verdict
        assert verdict.matched_terms == ("yield",)


class TestPassing:
    def test_a_measured_demonstration_passes(self, vocabulary: Vocabulary) -> None:
        verdict = assess(
            "Logical Qubit Operation Below Threshold",
            "We demonstrate a logical qubit with a measured gate fidelity of "
            "99.7% and a coherence time sustained for 400 ms.",
            vocabulary,
        )
        assert verdict
        assert "quantum" in verdict.domains
        assert "demonstration" in verdict.signals
        assert "measurement" in verdict.signals

    def test_a_deployment_passes(self, vocabulary: Vocabulary) -> None:
        verdict = assess(
            "Grid-Scale Storage Installed in South Australia",
            "The battery system is now grid-connected and in service, with an "
            "energy density improvement over the previous installation.",
            vocabulary,
        )
        assert verdict
        assert "energy" in verdict.domains
        assert "deployment" in verdict.signals

    def test_a_regulatory_event_passes(self, vocabulary: Vocabulary) -> None:
        verdict = assess(
            "Base Editing Therapy Receives Clearance",
            "The base editing candidate was approved by the regulator following "
            "a clinical programme in 12 participants.",
            vocabulary,
        )
        assert verdict
        assert "biotech" in verdict.domains
        assert "regulatory" in verdict.signals

    def test_a_document_can_match_more_than_one_domain(self, vocabulary: Vocabulary) -> None:
        """Materials work is routinely both, and forcing one would lose the other."""
        verdict = assess(
            "A Superconducting Interconnect Fabricated at Wafer Scale",
            "We fabricated a superconducting interconnect on a 300 mm wafer and "
            "measured a record critical current.",
            vocabulary,
        )
        assert verdict
        assert set(verdict.domains) >= {"energy", "semiconductors"}


class TestThinDocuments:
    def test_a_very_short_document_is_passed_not_rejected(self, vocabulary: Vocabulary) -> None:
        """A thin feed entry is not evidence the paper asserts nothing.

        Rejecting on absence here would quietly drop press releases whose RSS
        summary is one line, which is exactly where deployment and regulatory
        claims live.
        """
        verdict = assess("New reactor online", None, vocabulary)
        assert len(searchable("New reactor online", None)) < MIN_TEXT_CHARACTERS
        assert verdict
        assert "too little text to judge" in verdict.reason

    def test_a_thin_document_reports_no_domains_rather_than_guessing(
        self, vocabulary: Vocabulary
    ) -> None:
        verdict = assess("New reactor online", None, vocabulary)
        assert verdict.domains == ()
        assert verdict.signals == ()


class TestMeasuredQuantity:
    @pytest.mark.parametrize(
        "text",
        [
            "a fidelity of 99.7%",
            "sustained for 400 s",
            "held for 1,000 seconds",
            "a 300 mm wafer",
            "reached 1.2e6 Hz",
            "delivered 20 MW",
            "a 12-fold improvement",
            "measured 5.5 T",
            "stored 250 Wh/kg of energy",
        ],
    )
    def test_it_finds_a_measurement(self, text: str) -> None:
        assert MEASURED_QUANTITY.search(text.lower()) is not None

    @pytest.mark.parametrize(
        "text",
        [
            "across 12 objects",
            "we review 40 papers",
            "with 3 authors",
            "figure 2 shows",
            "in 2026 the field",
            "section 4 describes",
        ],
    )
    def test_it_does_not_call_a_bare_count_a_measurement(self, text: str) -> None:
        """A count of things is not a measurement of anything."""
        assert MEASURED_QUANTITY.search(text.lower()) is None


class TestNormalisation:
    def test_matching_is_case_insensitive(self, vocabulary: Vocabulary) -> None:
        upper = assess(
            "LOGICAL QUBIT DEMONSTRATED AT 99.7% FIDELITY", "MEASURED OVER 400 MS.", vocabulary
        )
        assert upper

    def test_a_hyphenated_line_break_does_not_hide_a_term(self, vocabulary: Vocabulary) -> None:
        """Feeds wrap abstracts; 'qu-\\nbit' must still read as qubit."""
        assert "qubit" in searchable("A logical qu-\nbit", "demonstrated and measured at 400 ms")

    def test_a_title_alone_can_carry_a_claim(self, vocabulary: Vocabulary) -> None:
        """Newsroom feeds often put the whole claim in the headline."""
        assert assess("Fusion reactor sustained plasma for 400 s", None, vocabulary)

    def test_a_missing_abstract_is_not_an_error(self, vocabulary: Vocabulary) -> None:
        """No abstract is a thin document, not a rejectable one."""
        verdict = assess("A survey of methods for policy optimisation", None, vocabulary)
        assert not verdict
        assert verdict.rule_version


class TestFileHandling:
    def test_a_missing_file_says_where_it_looked(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="prefilter vocabulary not found"):
            load_vocabulary(tmp_path / "absent.yaml")

    def test_an_empty_file_is_rejected_rather_than_passing_everything(self, tmp_path: Path) -> None:
        """An empty vocabulary would gate nothing, silently costing full price."""
        path = tmp_path / "prefilter.yaml"
        path.write_text("", encoding="utf-8")
        with pytest.raises(ValueError):
            load_vocabulary(path)

    def test_a_vocabulary_with_no_claim_signals_is_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "prefilter.yaml"
        path.write_text(
            yaml.safe_dump({"domains": {"ai": ["agent"]}, "claim_signals": {}}), encoding="utf-8"
        )
        with pytest.raises(ValueError):
            load_vocabulary(path)
