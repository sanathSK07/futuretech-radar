"""The hand-labelled evaluation set: sampling, the worksheet, and checking it."""

from __future__ import annotations

import pytest
import yaml
from pydantic import ValidationError
from sqlalchemy.orm import Session
from tests.helpers import make_document, make_source

from radar.core.types import ClaimType, EpistemicLabel, SourceKind, SourceTier
from radar.pipeline.labelling import (
    check_worksheet,
    coverage,
    format_report,
    missing_domains,
    parse_worksheet,
    render_worksheet,
    select_documents,
)

pytestmark = pytest.mark.db

ABSTRACT = (
    "We present a bimanual system that folds unseen garments. On a held-out set "
    "of 30 items the policy achieved a 92% success rate."
)


def seed_corpus(session: Session) -> None:
    """Three domains, unevenly sized — the shape the real corpus has."""
    robotics = make_source(session, "arxiv-cs-ro", domains=["robotics"])
    quantum = make_source(
        session, "arxiv-quant-ph", domains=["quantum"], name="arXiv quant-ph", tier=SourceTier.T1
    )
    energy = make_source(
        session,
        "arxiv-physics-plasm",
        domains=["energy"],
        name="arXiv plasma physics",
        kind=SourceKind.ARXIV_CATEGORY,
    )
    for index in range(12):
        make_document(session, robotics, f"arXiv:2609.1{index:04d}", abstract=ABSTRACT)
    for index in range(3):
        make_document(session, quantum, f"arXiv:2609.2{index:04d}", abstract=ABSTRACT)
    for index in range(5):
        make_document(session, energy, f"arXiv:2609.3{index:04d}", abstract=ABSTRACT)


class TestSampling:
    def test_the_sample_is_spread_across_domains(self, session: Session) -> None:
        """An unstratified sample of an arXiv corpus is mostly robotics.

        Twelve robotics documents against three quantum ones is the real shape:
        sampling at random would leave whole domains unlabelled, and the
        maturity model has to be exercised in all of them.
        """
        seed_corpus(session)
        documents = select_documents(session, per_domain=2)
        domains = {d for doc in documents for d in doc.source.domains}
        assert domains == {"robotics", "quantum", "energy"}
        assert len(documents) == 6

    def test_one_document_cannot_fill_two_domain_quotas(self, session: Session) -> None:
        """The bug the first real export exposed.

        A source tagged [energy, semiconductors] used to put the same documents
        into both piles, so the worksheet reported two domains covered and
        contained one. The count a person reads has to be the count that was
        sampled.
        """
        both = make_source(
            session,
            "arxiv-cond-mat-mtrl-sci",
            domains=["energy", "semiconductors"],
            name="arXiv cond-mat.mtrl-sci",
        )
        for index in range(8):
            make_document(session, both, f"arXiv:2609.4{index:04d}", abstract=ABSTRACT)

        documents = select_documents(session, per_domain=4)
        assert len(documents) == 4
        assert coverage(documents) == {"energy": 4}

    def test_a_domain_with_no_documents_is_reported(self, session: Session) -> None:
        """Silence about an empty domain reads as coverage."""
        seed_corpus(session)
        make_source(session, "biorxiv-synbio", domains=["biotech"], name="bioRxiv")
        documents = select_documents(session, per_domain=2)
        assert missing_domains(session, documents) == ["biotech"]

    def test_a_thin_domain_contributes_what_it_has(self, session: Session) -> None:
        seed_corpus(session)
        documents = select_documents(session, per_domain=10)
        by_domain: dict[str, int] = {}
        for document in documents:
            for domain in document.source.domains:
                by_domain[domain] = by_domain.get(domain, 0) + 1
        assert by_domain == {"robotics": 10, "quantum": 3, "energy": 5}

    def test_the_same_seed_gives_the_same_documents(self, session: Session) -> None:
        """Rerunning the export must not invalidate a Saturday of labelling."""
        seed_corpus(session)
        first = [d.external_id for d in select_documents(session, per_domain=2, seed=7)]
        second = [d.external_id for d in select_documents(session, per_domain=2, seed=7)]
        assert first == second

    def test_a_different_seed_gives_a_different_sample(self, session: Session) -> None:
        seed_corpus(session)
        first = [d.external_id for d in select_documents(session, per_domain=3, seed=1)]
        second = [d.external_id for d in select_documents(session, per_domain=3, seed=2)]
        assert first != second

    def test_documents_without_an_abstract_are_skipped(self, session: Session) -> None:
        """There is nothing to quote from, so there is nothing to label."""
        source = make_source(session, "arxiv-cs-ro", domains=["robotics"])
        make_document(session, source, "arXiv:2609.90001", abstract=None)
        assert select_documents(session) == []


class TestWorksheet:
    def test_it_round_trips(self, session: Session) -> None:
        seed_corpus(session)
        documents = select_documents(session, per_domain=1)
        text = render_worksheet(documents)

        parsed = parse_worksheet(text)
        assert len(parsed.documents) == len(documents)
        assert all(entry.relevant is None for entry in parsed.documents)
        assert all(entry.abstract for entry in parsed.documents)

    def test_it_explains_itself(self, session: Session) -> None:
        """The worksheet is used alone, hours after it was generated."""
        seed_corpus(session)
        text = render_worksheet(select_documents(session, per_domain=1))
        assert "copy and paste EXACTLY" in text
        assert "measured_result" in text
        assert "observed_fact" in text

    def test_an_unknown_field_is_refused(self, session: Session) -> None:
        seed_corpus(session)
        data = yaml.safe_load(render_worksheet(select_documents(session, per_domain=1)))
        data["documents"][0]["priority"] = "high"
        with pytest.raises(ValidationError):
            parse_worksheet(yaml.safe_dump(data))


def fill_in(worksheet: str, **claim: object) -> str:
    """Label the first document in a worksheet, as a person would.

    The parameter is not called ``text`` because a claim has a ``text`` field,
    and ``fill_in(text, **claim)`` then collides on the keyword.
    """
    data = yaml.safe_load(worksheet)
    data["documents"][0]["relevant"] = True
    data["documents"][0]["claims"] = [claim] if claim else []
    return yaml.safe_dump(data)


A_GOOD_CLAIM = {
    "quote": "the policy achieved a 92% success rate",
    "text": "The system folded unseen garments with a 92% success rate.",
    "claim_type": ClaimType.MEASURED_RESULT.value,
    "epistemic_label": EpistemicLabel.OBSERVED_FACT.value,
}


class TestChecking:
    def test_a_correct_label_passes(self, session: Session) -> None:
        seed_corpus(session)
        text = render_worksheet(select_documents(session, per_domain=1))
        report = check_worksheet(session, parse_worksheet(fill_in(text, **A_GOOD_CLAIM)))
        assert report.ok
        assert report.claims == 1
        assert report.relevant == 1

    def test_a_mistyped_quote_is_caught(self, session: Session) -> None:
        """A human typo in the yardstick penalises the model for being right.

        This is the reason 'radar label check' exists at all: the labelled set
        is trusted absolutely by the evaluation, so it has to be verified as
        strictly as the model's output is.
        """
        seed_corpus(session)
        text = render_worksheet(select_documents(session, per_domain=1))
        claim = {**A_GOOD_CLAIM, "quote": "the policy achieved a 92% sucess rate"}
        report = check_worksheet(session, parse_worksheet(fill_in(text, **claim)))
        assert not report.ok
        assert "does not appear in the source" in report.problems[0].detail

    def test_a_paraphrase_is_caught(self, session: Session) -> None:
        seed_corpus(session)
        text = render_worksheet(select_documents(session, per_domain=1))
        claim = {**A_GOOD_CLAIM, "quote": "the system worked well on most of the garments"}
        report = check_worksheet(session, parse_worksheet(fill_in(text, **claim)))
        assert not report.ok

    def test_a_forecast_labelled_as_fact_is_caught(self, session: Session) -> None:
        seed_corpus(session)
        text = render_worksheet(select_documents(session, per_domain=1))
        claim = {**A_GOOD_CLAIM, "claim_type": ClaimType.EXPECTATION.value}
        report = check_worksheet(session, parse_worksheet(fill_in(text, **claim)))
        assert not report.ok
        assert "observed" in report.problems[0].detail

    def test_an_edited_abstract_cannot_make_a_wrong_quote_right(self, session: Session) -> None:
        """Quotes are checked against the database, not the worksheet's copy."""
        seed_corpus(session)
        text = render_worksheet(select_documents(session, per_domain=1))
        data = yaml.safe_load(text)
        data["documents"][0]["abstract"] = "the model achieved a 99% success rate"
        data["documents"][0]["relevant"] = True
        data["documents"][0]["claims"] = [
            {**A_GOOD_CLAIM, "quote": "the model achieved a 99% success rate"}
        ]
        report = check_worksheet(session, parse_worksheet(yaml.safe_dump(data)))
        assert not report.ok

    def test_an_unlabelled_document_is_counted_not_complained_about(self, session: Session) -> None:
        seed_corpus(session)
        text = render_worksheet(select_documents(session, per_domain=2))
        report = check_worksheet(session, parse_worksheet(fill_in(text, **A_GOOD_CLAIM)))
        assert report.ok
        assert report.labelled == 1
        assert report.total == 6

    def test_a_document_with_no_claims_is_a_valid_label(self, session: Session) -> None:
        """Most documents contain nothing worth storing. Saying so is a label."""
        seed_corpus(session)
        text = render_worksheet(select_documents(session, per_domain=1))
        report = check_worksheet(session, parse_worksheet(fill_in(text)))
        assert report.ok
        assert report.claims == 0

    def test_the_report_reads_like_something_a_person_can_act_on(self, session: Session) -> None:
        seed_corpus(session)
        text = render_worksheet(select_documents(session, per_domain=1))
        claim = {**A_GOOD_CLAIM, "quote": "a quote that is simply not in the document"}
        rendered = format_report(check_worksheet(session, parse_worksheet(fill_in(text, **claim))))
        assert "1 problem(s)" in rendered
        assert "Copy it again" in rendered
