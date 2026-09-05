"""Archive Candidates while retaining their collaboration audit chain."""
from alembic import op
import sqlalchemy as sa

revision = "0015_candidate_archive"
down_revision = "0014_candidate_digest_unique"
branch_labels = depends_on = None

def upgrade():
    with op.batch_alter_table("platform_candidates") as batch:
        batch.drop_constraint("uq_platform_candidate_agent_digest", type_="unique")
        batch.add_column(sa.Column("archived_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("archived_by", sa.String(), nullable=True))
        batch.add_column(sa.Column("archive_reason", sa.String(), nullable=True))
    op.create_index("ix_platform_candidates_archived_at", "platform_candidates", ["archived_at"])
    op.create_index("uq_platform_candidate_active_agent_digest", "platform_candidates", ["agent_id", "image_id"], unique=True,
                    postgresql_where=sa.text("archived_at IS NULL"), sqlite_where=sa.text("archived_at IS NULL"))

def downgrade(): raise RuntimeError("restore backup")
