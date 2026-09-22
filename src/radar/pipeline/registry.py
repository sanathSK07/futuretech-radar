"""The source registry: sources.yaml, validated and synced into the database.

Sources are declared in a file reviewed through pull requests rather than edited
in a UI, because adding a source is a judgement about evidence quality (which
tier it belongs in, what its licence permits) that deserves a reviewer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog
import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from radar.core.models import Source
from radar.core.types import SourceKind, SourceTier

log = structlog.get_logger(__name__)

DEFAULT_REGISTRY_PATH = Path("sources.yaml")


class RateLimitSpec(BaseModel):
    """How gently to poll a source."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    requests_per_second: float = Field(default=1.0, gt=0, le=10)

    @property
    def min_interval_seconds(self) -> float:
        return 1.0 / self.requests_per_second


class SourceSpec(BaseModel):
    """One entry in sources.yaml."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1)
    kind: SourceKind
    tier: SourceTier
    params: dict[str, Any] = Field(default_factory=dict)
    schedule: str = "daily"
    licence: str | None = None
    domains: list[str] = Field(default_factory=list)
    rate_limit: RateLimitSpec = Field(default_factory=RateLimitSpec)
    active: bool = True
    note: str | None = None

    @field_validator("params")
    @classmethod
    def _require_params_for_kind(cls, value: dict[str, Any], info: Any) -> dict[str, Any]:
        kind = info.data.get("kind")
        if kind == SourceKind.ARXIV_CATEGORY and not value.get("category"):
            raise ValueError("an arxiv_category source needs params.category, e.g. 'cs.RO'")
        if kind == SourceKind.ARXIV_OAI and not value.get("set"):
            raise ValueError(
                "an arxiv_oai source needs params.set, a setSpec as ListSets reports it, "
                "e.g. 'cs:cs:RO' — the dotted category name 'cs.RO' is not a setSpec"
            )
        if kind == SourceKind.RSS and not value.get("url"):
            raise ValueError("an rss source needs params.url")
        return value


class Registry(BaseModel):
    """The whole sources.yaml file."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sources: list[SourceSpec]

    @field_validator("sources")
    @classmethod
    def _ids_unique(cls, value: list[SourceSpec]) -> list[SourceSpec]:
        seen: set[str] = set()
        for spec in value:
            if spec.id in seen:
                raise ValueError(f"duplicate source id: {spec.id}")
            seen.add(spec.id)
        return value

    @property
    def active_sources(self) -> list[SourceSpec]:
        return [s for s in self.sources if s.active]

    def get(self, source_id: str) -> SourceSpec:
        for spec in self.sources:
            if spec.id == source_id:
                return spec
        raise KeyError(f"no source with id {source_id!r} in the registry")


def load_registry(path: Path = DEFAULT_REGISTRY_PATH) -> Registry:
    """Read and validate sources.yaml.

    ``yaml.safe_load`` is used rather than ``load``: the file is trusted, but the
    unsafe loader can construct arbitrary Python objects and there is never a
    reason to allow that here.
    """
    if not path.exists():
        raise FileNotFoundError(f"source registry not found at {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a mapping with a 'sources' key")
    return Registry.model_validate(raw)


def sync_registry(session: Session, registry: Registry) -> tuple[int, int]:
    """Upsert the registry into the source table. Returns (created, updated).

    Rows are never deleted here: a source that is removed from the file is
    deactivated instead, because documents already reference it and their
    provenance must stay intact.
    """
    created = 0
    updated = 0
    spec_by_id = {spec.id: spec for spec in registry.sources}

    existing = {row.id: row for row in session.scalars(select(Source)).all()}

    for spec_id, spec in spec_by_id.items():
        row = existing.get(spec_id)
        if row is None:
            session.add(
                Source(
                    id=spec.id,
                    name=spec.name,
                    kind=spec.kind,
                    tier=spec.tier,
                    params=spec.params,
                    schedule=spec.schedule,
                    licence_note=spec.licence,
                    domains=list(spec.domains),
                    active=spec.active,
                )
            )
            created += 1
            continue

        changed = False
        for attr, value in (
            ("name", spec.name),
            ("kind", spec.kind),
            ("tier", spec.tier),
            ("params", spec.params),
            ("schedule", spec.schedule),
            ("licence_note", spec.licence),
            ("domains", list(spec.domains)),
            ("active", spec.active),
        ):
            if getattr(row, attr) != value:
                setattr(row, attr, value)
                changed = True
        if changed:
            updated += 1

    for row_id, row in existing.items():
        if row_id not in spec_by_id and row.active:
            log.info("source_deactivated", source_id=row_id, reason="absent from sources.yaml")
            row.active = False
            updated += 1

    session.flush()
    return created, updated
