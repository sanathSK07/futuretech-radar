"""ORM models for schema v0.

Importing this package registers every model on ``Base.metadata``, which is what
Alembic's autogenerate compares against the live database.
"""

from radar.core.models.analysis_run import AnalysisRun
from radar.core.models.base import Base
from radar.core.models.claim import Claim
from radar.core.models.development import (
    Development,
    DevelopmentOrganization,
    DevelopmentTechnology,
)
from radar.core.models.domain import Domain
from radar.core.models.fetch_run import FetchRun
from radar.core.models.organization import Organization
from radar.core.models.review import ReviewAction, ReviewTask
from radar.core.models.source import Source
from radar.core.models.source_document import SourceDocument
from radar.core.models.technology import Technology, TechnologyAlias

__all__ = [
    "AnalysisRun",
    "Base",
    "Claim",
    "Development",
    "DevelopmentOrganization",
    "DevelopmentTechnology",
    "Domain",
    "FetchRun",
    "Organization",
    "ReviewAction",
    "ReviewTask",
    "Source",
    "SourceDocument",
    "Technology",
    "TechnologyAlias",
]
