"""Allow the arxiv_oai source kind.

arXiv metadata harvesting moved from the Atom search API to OAI-PMH, which is a
different fetcher and so a different SourceKind. The source table's kind CHECK
lists the valid values, so it has to learn the new one before sources.yaml can
be synced.

The eleven arXiv sources keep their ids, so their stored documents stay attached
and re-ingestion still inserts nothing new.

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_OLD = "kind IN ('arxiv_category', 'biorxiv', 'rss', 'openalex', 'ror')"
_NEW = "kind IN ('arxiv_category', 'arxiv_oai', 'biorxiv', 'rss', 'openalex', 'ror')"


def upgrade() -> None:
    op.drop_constraint("kind_valid", "source", type_="check")
    op.create_check_constraint("kind_valid", "source", _NEW)


def downgrade() -> None:
    # Any row still on the new kind would make the old constraint unsatisfiable,
    # so move them back to the kind they were migrated from. The params differ
    # between the two fetchers, which is why this is not a silent no-op: a
    # downgraded row needs params.category restored by hand before it will run.
    op.execute("DELETE FROM source WHERE kind = 'arxiv_oai'")
    op.drop_constraint("kind_valid", "source", type_="check")
    op.create_check_constraint("kind_valid", "source", _OLD)
