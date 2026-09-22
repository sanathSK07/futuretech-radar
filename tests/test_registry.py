"""The source registry: validation, and syncing sources.yaml into the database."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from radar.core.models import Source
from radar.core.types import SourceKind, SourceTier
from radar.pipeline.registry import Registry, SourceSpec, load_registry, sync_registry

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def spec(**overrides: object) -> SourceSpec:
    values: dict[str, object] = {
        "id": "arxiv-cs-ro",
        "name": "arXiv cs.RO",
        "kind": SourceKind.ARXIV_CATEGORY,
        "tier": SourceTier.T1,
        "params": {"category": "cs.RO"},
        "domains": ["robotics"],
    }
    values.update(overrides)
    return SourceSpec.model_validate(values)


class TestSourceSpec:
    def test_an_arxiv_source_needs_a_category(self) -> None:
        with pytest.raises(ValidationError, match=r"params\.category"):
            spec(params={})

    def test_an_rss_source_needs_a_url(self) -> None:
        with pytest.raises(ValidationError, match=r"params\.url"):
            spec(kind=SourceKind.RSS, params={})

    def test_an_unknown_tier_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            spec(tier="T9")

    def test_an_unknown_field_is_rejected(self) -> None:
        """extra='forbid' turns a typo in sources.yaml into an error, not a silent no-op."""
        with pytest.raises(ValidationError):
            spec(tiers=SourceTier.T1)

    @pytest.mark.parametrize("bad_id", ["Has Capitals", "under_score", "-leading", "sp ace", ""])
    def test_ids_must_be_lowercase_slugs(self, bad_id: str) -> None:
        with pytest.raises(ValidationError):
            spec(id=bad_id)

    def test_the_rate_limit_becomes_an_interval(self) -> None:
        arxiv = spec(rate_limit={"requests_per_second": 0.333})
        assert 3.0 <= arxiv.rate_limit.min_interval_seconds <= 3.01

    def test_sources_default_to_active(self) -> None:
        assert spec().active is True


class TestRegistry:
    def test_duplicate_ids_are_rejected(self) -> None:
        with pytest.raises(ValidationError, match="duplicate source id"):
            Registry(sources=[spec(), spec()])

    def test_active_sources_excludes_inactive_ones(self) -> None:
        registry = Registry(sources=[spec(), spec(id="arxiv-cs-ai", active=False)])
        assert [s.id for s in registry.active_sources] == ["arxiv-cs-ro"]

    def test_get_raises_for_an_unknown_id(self) -> None:
        with pytest.raises(KeyError, match="no source with id"):
            Registry(sources=[spec()]).get("nope")


class TestTheShippedRegistryFile:
    """sources.yaml is part of the product; a broken one breaks every run."""

    def test_it_loads_and_validates(self) -> None:
        registry = load_registry(PROJECT_ROOT / "sources.yaml")
        assert len(registry.sources) > 10

    def test_every_active_source_has_a_fetcher_that_exists(self) -> None:
        registry = load_registry(PROJECT_ROOT / "sources.yaml")
        implemented = {SourceKind.ARXIV_CATEGORY, SourceKind.RSS, SourceKind.BIORXIV}
        unimplemented = [s.id for s in registry.active_sources if s.kind not in implemented]
        assert unimplemented == [], (
            f"these sources are active but have no fetcher yet: {unimplemented}. "
            "Mark them active: false until their fetcher lands."
        )

    def test_the_six_mvp_domains_are_all_covered(self) -> None:
        registry = load_registry(PROJECT_ROOT / "sources.yaml")
        covered = {domain for s in registry.active_sources for domain in s.domains}
        assert {"ai", "robotics", "quantum", "semiconductors", "energy", "biotech"} <= covered

    def test_every_source_declares_its_licence(self) -> None:
        registry = load_registry(PROJECT_ROOT / "sources.yaml")
        missing = [s.id for s in registry.sources if not s.licence]
        assert missing == []

    def test_arxiv_sources_honour_the_three_second_rule(self) -> None:
        """arXiv's terms of use: no more than one request every three seconds."""
        registry = load_registry(PROJECT_ROOT / "sources.yaml")
        for source in registry.sources:
            if source.kind == SourceKind.ARXIV_CATEGORY:
                assert source.rate_limit.min_interval_seconds >= 3.0, source.id


@pytest.mark.db
class TestSyncRegistry:
    def test_it_creates_missing_sources(self, session: Session) -> None:
        created, updated = sync_registry(session, Registry(sources=[spec()]))
        assert (created, updated) == (1, 0)
        row = session.get(Source, "arxiv-cs-ro")
        assert row is not None
        assert row.tier == SourceTier.T1

    def test_a_second_sync_changes_nothing(self, session: Session) -> None:
        registry = Registry(sources=[spec()])
        sync_registry(session, registry)
        created, updated = sync_registry(session, registry)
        assert (created, updated) == (0, 0)

    def test_an_edited_entry_is_updated_in_place(self, session: Session) -> None:
        sync_registry(session, Registry(sources=[spec()]))
        created, updated = sync_registry(
            session, Registry(sources=[spec(name="arXiv cs.RO (Robotics)", tier=SourceTier.T2)])
        )
        assert (created, updated) == (0, 1)
        row = session.get(Source, "arxiv-cs-ro")
        assert row is not None
        assert row.tier == SourceTier.T2
        assert row.name == "arXiv cs.RO (Robotics)"

    def test_a_removed_source_is_deactivated_not_deleted(self, session: Session) -> None:
        """Documents reference their source; deleting one would orphan provenance."""
        sync_registry(session, Registry(sources=[spec()]))
        created, _updated = sync_registry(session, Registry(sources=[spec(id="arxiv-cs-ai")]))
        assert created == 1
        old = session.get(Source, "arxiv-cs-ro")
        assert old is not None
        assert old.active is False

    def test_it_syncs_the_real_registry_file(self, session: Session) -> None:
        registry = load_registry(PROJECT_ROOT / "sources.yaml")
        created, _ = sync_registry(session, registry)
        assert created == len(registry.sources)
        stored = session.scalars(select(Source)).all()
        assert len(stored) == len(registry.sources)
