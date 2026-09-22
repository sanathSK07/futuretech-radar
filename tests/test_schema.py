"""Schema v0 behaviour, exercised against a migrated PostgreSQL database.

These tests encode the guarantees later sprints depend on: re-running an
ingestion must not duplicate rows, duplicate content must be recordable rather
than rejected, and full-text and vector search must actually work.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import func, select, text
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session
from tests.helpers import make_document, make_source

from radar.core.models import (
    AnalysisRun,
    Claim,
    Development,
    DevelopmentOrganization,
    Domain,
    FetchRun,
    Organization,
    Source,
    SourceDocument,
    Technology,
    TechnologyAlias,
)
from radar.core.types import (
    AnalysisStage,
    AnalysisStatus,
    ClaimStatus,
    ClaimType,
    DateBasis,
    DevelopmentKind,
    DocumentLifecycle,
    EntityStatus,
    EpistemicLabel,
    FetchStatus,
    OrganizationRole,
    SourceKind,
    SourceTier,
)

pytestmark = pytest.mark.db


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TestSource:
    def test_round_trips(self, session: Session) -> None:
        make_source(session)
        loaded = session.get(Source, "arxiv-cs-ro")
        assert loaded is not None
        assert loaded.tier == SourceTier.T1
        assert loaded.params == {"category": "cs.RO"}
        assert loaded.domains == ["robotics"]
        assert loaded.active is True
        assert loaded.schedule == "daily"

    def test_rejects_an_invalid_tier(self, session: Session) -> None:
        session.add(
            Source(id="bad", name="Bad", kind=SourceKind.RSS, tier="T9")  # type: ignore[arg-type]
        )
        with pytest.raises(IntegrityError, match="tier_valid"):
            session.flush()

    def test_rejects_an_unknown_kind(self, session: Session) -> None:
        session.add(
            Source(id="bad", name="Bad", kind="scrape", tier=SourceTier.T3)  # type: ignore[arg-type]
        )
        with pytest.raises(IntegrityError, match="kind_valid"):
            session.flush()


class TestFetchRun:
    def test_records_a_successful_poll(self, session: Session) -> None:
        source = make_source(session)
        run = FetchRun(
            source_id=source.id,
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            status=FetchStatus.OK,
            fetched_count=30,
            new_count=4,
        )
        session.add(run)
        session.flush()
        assert isinstance(run.id, uuid.UUID)
        assert run.source.id == source.id

    def test_rejects_more_new_than_fetched(self, session: Session) -> None:
        source = make_source(session)
        session.add(
            FetchRun(
                source_id=source.id,
                started_at=datetime.now(UTC),
                status=FetchStatus.OK,
                fetched_count=2,
                new_count=5,
            )
        )
        with pytest.raises(IntegrityError, match="new_not_above_fetched"):
            session.flush()

    def test_rejects_negative_counts(self, session: Session) -> None:
        source = make_source(session)
        session.add(
            FetchRun(
                source_id=source.id,
                started_at=datetime.now(UTC),
                status=FetchStatus.ERROR,
                fetched_count=-1,
            )
        )
        with pytest.raises(IntegrityError, match="counts_non_negative"):
            session.flush()


class TestSourceDocumentIdempotency:
    def test_same_source_and_external_id_cannot_be_inserted_twice(self, session: Session) -> None:
        """The guarantee Task 3 rests on: re-running a day's fetch inserts nothing new."""
        source = make_source(session)
        make_document(session, source, "arXiv:2609.00001")
        session.add(
            SourceDocument(
                source_id=source.id,
                external_id="arXiv:2609.00001",
                url="https://arxiv.org/abs/2609.00001v2",
                title="Same paper, fetched again",
                retrieved_at=datetime.now(UTC),
                content_hash="different-hash",
            )
        )
        with pytest.raises(IntegrityError, match="uq_source_document_source_id_external_id"):
            session.flush()

    def test_the_same_external_id_from_a_different_source_is_allowed(
        self, session: Session
    ) -> None:
        arxiv = make_source(session, "arxiv-cs-ro")
        news = make_source(session, "mit-news", kind=SourceKind.RSS, tier=SourceTier.T2)
        make_document(session, arxiv, "shared-id")
        make_document(session, news, "shared-id")
        count = session.scalar(
            select(func.count())
            .select_from(SourceDocument)
            .where(SourceDocument.external_id == "shared-id")
        )
        assert count == 2

    def test_identical_content_from_two_sources_is_recorded_not_rejected(
        self, session: Session
    ) -> None:
        """A syndicated press release must become a duplicate row, not an error."""
        wire = make_source(session, "eurekalert", kind=SourceKind.RSS, tier=SourceTier.T2)
        uni = make_source(session, "mit-news", kind=SourceKind.RSS, tier=SourceTier.T2)
        original = make_document(session, wire, "wire-1", content_hash="identical")
        copy = make_document(
            session,
            uni,
            "uni-1",
            content_hash="identical",
            lifecycle=DocumentLifecycle.DUPLICATE,
            duplicate_of=original.id,
        )
        session.flush()
        assert copy.duplicate_target is not None
        assert copy.duplicate_target.id == original.id


class TestSourceDocumentConstraints:
    def test_a_document_cannot_duplicate_itself(self, session: Session) -> None:
        source = make_source(session)
        document = make_document(session, source)
        document.duplicate_of = document.id
        document.lifecycle = DocumentLifecycle.DUPLICATE
        with pytest.raises(IntegrityError, match="duplicate_not_self"):
            session.flush()

    def test_duplicate_lifecycle_requires_a_target(self, session: Session) -> None:
        source = make_source(session)
        document = make_document(session, source)
        document.lifecycle = DocumentLifecycle.DUPLICATE
        with pytest.raises(IntegrityError, match="duplicate_has_target"):
            session.flush()

    def test_rejects_an_unknown_lifecycle(self, session: Session) -> None:
        source = make_source(session)
        document = make_document(session, source)
        document.lifecycle = "archived"  # type: ignore[assignment]
        with pytest.raises(IntegrityError, match="lifecycle_valid"):
            session.flush()

    def test_rejects_an_invalid_tier_override(self, session: Session) -> None:
        source = make_source(session)
        document = make_document(session, source)
        document.tier_override = "T7"  # type: ignore[assignment]
        with pytest.raises(IntegrityError, match="tier_override_valid"):
            session.flush()

    def test_a_source_with_documents_cannot_be_deleted(self, session: Session) -> None:
        """Documents are evidence; deleting a source must not silently orphan them."""
        source = make_source(session)
        make_document(session, source)
        session.delete(source)
        with pytest.raises(IntegrityError):
            session.flush()


class TestEffectiveTier:
    def test_defaults_to_the_source_tier(self, session: Session) -> None:
        source = make_source(session, tier=SourceTier.T2)
        document = make_document(session, source)
        assert document.effective_tier == SourceTier.T2

    def test_a_reviewer_override_wins(self, session: Session) -> None:
        source = make_source(session, tier=SourceTier.T3)
        document = make_document(session, source, tier_override=SourceTier.T1)
        assert document.effective_tier == SourceTier.T1


class TestSearch:
    def test_the_search_vector_is_generated_from_title_and_abstract(self, session: Session) -> None:
        source = make_source(session)
        document = make_document(session, source)
        session.flush()
        session.refresh(document)
        assert document.search_tsv
        # tsvector stores stemmed lexemes, so "laundry" is indexed as "laundri";
        # match through a tsquery rather than asserting on the raw string.
        assert "laundri" in document.search_tsv
        matched = session.scalar(
            select(func.count())
            .select_from(SourceDocument)
            .where(
                SourceDocument.id == document.id,
                SourceDocument.search_tsv.op("@@")(func.websearch_to_tsquery("english", "laundry")),
            )
        )
        assert matched == 1

    def test_full_text_search_finds_a_document(self, session: Session) -> None:
        source = make_source(session)
        make_document(session, source)
        make_document(
            session,
            source,
            "arXiv:2609.00002",
            title="Superconducting magnet reaches 20 tesla",
            abstract="A high-temperature superconducting magnet for compact fusion.",
        )
        hits = session.scalars(
            select(SourceDocument).where(
                SourceDocument.search_tsv.op("@@")(func.websearch_to_tsquery("english", "fusion"))
            )
        ).all()
        assert len(hits) == 1
        assert "magnet" in hits[0].title

    def test_the_search_vector_follows_an_edit(self, session: Session) -> None:
        source = make_source(session)
        document = make_document(session, source)
        document.title = "Quantum error correction below threshold"
        session.flush()
        session.refresh(document)
        assert "quantum" in document.search_tsv
        assert "dexter" not in document.search_tsv  # the old title is gone


class TestEmbeddings:
    def test_an_embedding_round_trips(self, session: Session) -> None:
        source = make_source(session)
        vector = [0.1] * 384
        document = make_document(session, source, embedding=vector)
        session.flush()
        session.refresh(document)
        assert document.embedding is not None
        assert len(document.embedding) == 384

    def test_a_wrong_sized_embedding_is_rejected(self, session: Session) -> None:
        source = make_source(session)
        # Built inline rather than via the helper, which flushes: the failure has
        # to happen inside the raises block.
        session.add(
            SourceDocument(
                source_id=source.id,
                external_id="wrong-size",
                url="https://example.org/1",
                title="Wrong sized embedding",
                retrieved_at=datetime.now(UTC),
                content_hash="h",
                embedding=[0.1] * 16,
            )
        )
        with pytest.raises(DataError, match="expected 384 dimensions"):
            session.flush()

    def test_cosine_distance_orders_nearest_first(self, session: Session) -> None:
        """The query shape deduplication and semantic search will both use."""
        source = make_source(session)
        query = [1.0] + [0.0] * 383
        near = [0.99, 0.01] + [0.0] * 382
        far = [0.0] * 383 + [1.0]
        make_document(session, source, "near", embedding=near)
        make_document(session, source, "far", embedding=far)
        session.flush()

        ordered = session.scalars(
            select(SourceDocument)
            .where(SourceDocument.embedding.is_not(None))
            .order_by(SourceDocument.embedding.cosine_distance(query))
        ).all()
        assert [d.external_id for d in ordered] == ["near", "far"]


class TestMigrationState:
    def test_the_database_is_at_the_migration_head(self, session: Session) -> None:
        """Compare against the migration directory, not a literal revision.

        A hardcoded revision fails on every migration for the wrong reason, and
        the fix is always to edit the literal — which trains you to edit it
        without reading it. Asking the script directory for its head keeps the
        real assertion: the fixture ran every migration there is.
        """
        config = Config(str(PROJECT_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
        head = ScriptDirectory.from_config(config).get_current_head()
        revision = session.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert revision == head

    def test_pgvector_is_installed(self, session: Session) -> None:
        installed = session.execute(
            text("SELECT count(*) FROM pg_extension WHERE extname = 'vector'")
        ).scalar_one()
        assert installed == 1


def make_analysis_run(session: Session, **kwargs: object) -> AnalysisRun:
    defaults: dict[str, object] = {
        "stage": AnalysisStage.EXTRACT,
        "model_id": "claude-haiku-4-5",
        "prompt_version": "0f1e2d3",
        "input_ids": [],
        "status": AnalysisStatus.OK,
    }
    defaults.update(kwargs)
    run = AnalysisRun(**defaults)
    session.add(run)
    session.flush()
    return run


def make_claim(
    session: Session, document: SourceDocument, run: AnalysisRun, **kwargs: object
) -> Claim:
    defaults: dict[str, object] = {
        "document_id": document.id,
        "text": "A robot hand folded laundry autonomously in a live demonstration.",
        "quote": "a robot hand folding laundry autonomously",
        "quote_verified": True,
        "claim_type": ClaimType.DEMONSTRATION,
        "epistemic_label": EpistemicLabel.OBSERVED_FACT,
        "analysis_run_id": run.id,
    }
    defaults.update(kwargs)
    claim = Claim(**defaults)
    session.add(claim)
    session.flush()
    return claim


class TestClaimGrounding:
    """The three grounding rules that the database itself enforces."""

    def test_a_claim_round_trips_with_its_evidence(self, session: Session) -> None:
        source = make_source(session)
        document = make_document(session, source)
        run = make_analysis_run(session)
        metrics = [{"name": "success_rate", "value": 92, "unit": "%"}]
        claim = make_claim(session, document, run, metrics=metrics)

        loaded = session.get(Claim, claim.id)
        assert loaded is not None
        assert loaded.status == ClaimStatus.PROPOSED
        assert loaded.document.title == document.title
        assert loaded.metrics == metrics
        assert loaded.conflicts_with == []

    def test_an_unverified_quote_cannot_be_stored(self, session: Session) -> None:
        """The pipeline drops ungrounded claims; the database refuses them.

        Two independent guards, because this is the rule that keeps invented
        facts out. A backfill script that skips the pipeline still cannot write
        one.
        """
        source = make_source(session)
        document = make_document(session, source)
        run = make_analysis_run(session)
        with pytest.raises(IntegrityError, match="quote_must_be_verified"):
            make_claim(session, document, run, quote_verified=False)

    def test_an_empty_quote_is_refused(self, session: Session) -> None:
        source = make_source(session)
        document = make_document(session, source)
        run = make_analysis_run(session)
        with pytest.raises(IntegrityError, match="quote_not_empty"):
            make_claim(session, document, run, quote="")

    def test_a_date_without_a_basis_is_refused(self, session: Session) -> None:
        source = make_source(session)
        document = make_document(session, source)
        run = make_analysis_run(session)
        with pytest.raises(IntegrityError, match="date_has_basis"):
            make_claim(session, document, run, date_referenced=date(2026, 3, 1))

    def test_a_date_with_a_basis_is_accepted(self, session: Session) -> None:
        source = make_source(session)
        document = make_document(session, source)
        run = make_analysis_run(session)
        claim = make_claim(
            session,
            document,
            run,
            date_referenced=date(2026, 3, 1),
            date_basis=DateBasis.DOCUMENT_METADATA,
        )
        assert claim.date_basis == DateBasis.DOCUMENT_METADATA

    @pytest.mark.parametrize("claim_type", [ClaimType.EXPECTATION, ClaimType.EXPERT_FORECAST])
    def test_a_forecast_cannot_be_labelled_an_observed_fact(
        self, session: Session, claim_type: ClaimType
    ) -> None:
        """The rule the brief cared most about, enforced in the schema.

        'Never present speculation as fact' is a prompt instruction anywhere
        else. Here it is a constraint: a claim typed as a forecast and labelled
        as observed fact cannot exist in this database.
        """
        source = make_source(session)
        document = make_document(session, source)
        run = make_analysis_run(session)
        with pytest.raises(IntegrityError, match="forecast_is_not_observed_fact"):
            make_claim(
                session,
                document,
                run,
                claim_type=claim_type,
                epistemic_label=EpistemicLabel.OBSERVED_FACT,
            )

    def test_a_forecast_with_the_right_label_is_accepted(self, session: Session) -> None:
        source = make_source(session)
        document = make_document(session, source)
        run = make_analysis_run(session)
        claim = make_claim(
            session,
            document,
            run,
            claim_type=ClaimType.EXPECTATION,
            epistemic_label=EpistemicLabel.SOURCE_EXPECTATION,
            text="The company expects first power by 2027.",
            quote="we expect first power by 2027",
        )
        assert claim.claim_type == ClaimType.EXPECTATION

    def test_an_unknown_claim_type_is_refused(self, session: Session) -> None:
        source = make_source(session)
        document = make_document(session, source)
        run = make_analysis_run(session)
        with pytest.raises(IntegrityError, match="claim_type_valid"):
            make_claim(session, document, run, claim_type="breakthrough")  # type: ignore[arg-type]

    def test_a_claim_cannot_outlive_its_analysis_run(self, session: Session) -> None:
        """RESTRICT, not CASCADE: deleting the run would orphan the provenance.

        A claim whose run is gone cannot answer "which model said this, from
        which prompt", which is the whole point of storing it.
        """
        source = make_source(session)
        document = make_document(session, source)
        run = make_analysis_run(session)
        make_claim(session, document, run)
        session.delete(run)
        with pytest.raises(IntegrityError, match="fk_claim_analysis_run_id_analysis_run"):
            session.flush()

    def test_claims_are_full_text_searchable(self, session: Session) -> None:
        source = make_source(session)
        document = make_document(session, source)
        run = make_analysis_run(session)
        make_claim(session, document, run)
        found = session.execute(
            select(func.count())
            .select_from(Claim)
            .where(Claim.search_tsv.op("@@")(func.plainto_tsquery("english", "laundry")))
        ).scalar_one()
        assert found == 1


class TestCuratedEntities:
    def test_a_technology_needs_a_domain_and_a_scope_note(self, session: Session) -> None:
        session.add(Domain(id="robotics", name="Robotics and humanoids"))
        session.flush()
        technology = Technology(
            slug="general-purpose-manipulation",
            name="General-purpose manipulation",
            domain_id="robotics",
            scope_note=(
                "Autonomous manipulation in unstructured environments. Excludes teleoperation."
            ),
        )
        session.add(technology)
        session.flush()
        assert technology.status == EntityStatus.PROPOSED
        assert technology.featured is False

    def test_a_merged_technology_must_say_what_it_merged_into(self, session: Session) -> None:
        session.add(Domain(id="robotics", name="Robotics"))
        session.flush()
        session.add(
            Technology(
                slug="humanoids",
                name="Humanoids",
                domain_id="robotics",
                scope_note="Bipedal general-purpose robots.",
                status=EntityStatus.MERGED,
            )
        )
        with pytest.raises(IntegrityError, match="merged_has_target"):
            session.flush()

    def test_an_alias_resolves_a_surface_form(self, session: Session) -> None:
        session.add(Domain(id="quantum", name="Quantum computing"))
        session.flush()
        technology = Technology(
            slug="below-threshold-error-correction",
            name="Below-threshold error correction",
            domain_id="quantum",
            scope_note="Logical error rate below the physical error rate as the code scales.",
        )
        technology.aliases.append(TechnologyAlias(alias="surface code below threshold"))
        session.add(technology)
        session.flush()

        resolved = session.execute(
            select(TechnologyAlias.technology_id).where(
                TechnologyAlias.alias == "surface code below threshold"
            )
        ).scalar_one()
        assert resolved == technology.id

    def test_an_organisation_may_have_no_ror_id(self, session: Session) -> None:
        """Startups are absent from ROR and are still real developers."""
        session.add_all(
            [
                Organization(name="A stealth robotics startup"),
                Organization(name="Another one"),
            ]
        )
        session.flush()  # two NULL ror_ids do not collide

    def test_two_organisations_cannot_share_a_ror_id(self, session: Session) -> None:
        session.add_all(
            [
                Organization(name="York University", ror_id="https://ror.org/05fq50484"),
                Organization(name="York U", ror_id="https://ror.org/05fq50484"),
            ]
        )
        with pytest.raises(IntegrityError, match="ror_id"):
            session.flush()

    def test_one_organisation_can_hold_two_roles_in_a_development(self, session: Session) -> None:
        """A national lab that both funds and evaluates is not developer-controlled evidence.

        Collapsing the two roles into one row would lose exactly the distinction
        the maturity model uses to cap a stage at M3.
        """
        org = Organization(name="A national laboratory")
        development = Development(
            slug="fusion-net-gain-shot",
            title="Net energy gain shot",
            kind=DevelopmentKind.DEMONSTRATION,
        )
        session.add_all([org, development])
        session.flush()
        session.add_all(
            [
                DevelopmentOrganization(
                    development_id=development.id,
                    organization_id=org.id,
                    role=OrganizationRole.FUNDER,
                ),
                DevelopmentOrganization(
                    development_id=development.id,
                    organization_id=org.id,
                    role=OrganizationRole.EVALUATOR,
                ),
            ]
        )
        session.flush()
        roles = session.execute(
            select(func.count()).select_from(DevelopmentOrganization)
        ).scalar_one()
        assert roles == 2

    def test_a_development_date_needs_a_basis(self, session: Session) -> None:
        session.add(
            Development(
                slug="a-demo",
                title="A demo",
                kind=DevelopmentKind.DEMONSTRATION,
                occurred_on=date(2026, 5, 1),
            )
        )
        with pytest.raises(IntegrityError, match="occurred_has_basis"):
            session.flush()


class TestAnalysisRun:
    def test_it_records_what_a_call_cost(self, session: Session) -> None:
        run = make_analysis_run(
            session,
            tokens_in=12000,
            tokens_out=800,
            cost_usd=Decimal("0.014400"),
            duration_ms=2310,
            records_written=7,
            ungrounded_claims=2,
        )
        loaded = session.get(AnalysisRun, run.id)
        assert loaded is not None
        assert loaded.cost_usd == Decimal("0.014400")
        assert loaded.ungrounded_claims == 2

    def test_a_negative_cost_is_refused(self, session: Session) -> None:
        with pytest.raises(IntegrityError, match="cost_not_negative"):
            make_analysis_run(session, cost_usd=Decimal("-1"))

    def test_an_unknown_stage_is_refused(self, session: Session) -> None:
        with pytest.raises(IntegrityError, match="stage_valid"):
            make_analysis_run(session, stage="vibes")  # type: ignore[arg-type]
