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
    """Convert arxiv_oai sources back, rather than deleting them.

    The first version of this ran ``DELETE FROM source WHERE kind = 'arxiv_oai'``,
    which is wrong twice over. It destroys the sources — and with them, via
    cascade or refusal, every document ever fetched through them. And it simply
    fails: ``source_document.source_id`` references ``source.id``, so the delete
    raises a foreign key violation the moment any document exists.

    It passed CI regardless, because CI migrates a *bare* database where the
    delete matches no rows. It only surfaced on a workspace database with four
    documents in it. A downgrade tested only against an empty schema is not
    tested.

    So convert instead. A setSpec maps back to a dotted category by dropping its
    first segment and joining the rest with a dot, which is exactly how the
    eleven sources were migrated forward: ``cs:cs:RO`` to ``cs.RO``,
    ``physics:quant-ph`` to ``quant-ph``, ``physics:cond-mat:mtrl-sci`` to
    ``cond-mat.mtrl-sci``. Rows keep their ids, so documents stay attached.
    """
    op.execute(
        """
        UPDATE source
           SET kind = 'arxiv_category',
               params = jsonb_build_object(
                   'category',
                   array_to_string((string_to_array(params->>'set', ':'))[2:], '.')
               )
         WHERE kind = 'arxiv_oai'
           AND params ? 'set'
        """
    )
    # A row with no params.set cannot be converted, and leaving it would make the
    # old constraint unsatisfiable. Fail loudly rather than deleting someone's
    # source: the operator can decide what it should become.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM source WHERE kind = 'arxiv_oai') THEN
                RAISE EXCEPTION
                    'cannot downgrade: arxiv_oai source(s) have no params.set to '
                    'convert. Set params.category and kind by hand, then retry.';
            END IF;
        END $$
        """
    )
    op.drop_constraint("kind_valid", "source", type_="check")
    op.create_check_constraint("kind_valid", "source", _OLD)
