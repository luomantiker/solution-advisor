"""Record Candidate creator for deletion authorization and audit."""
from alembic import op
import sqlalchemy as sa

revision = "0010_candidate_creator"
down_revision = "0009_host_images"
branch_labels = depends_on = None


def upgrade():
    with op.batch_alter_table("platform_candidates") as batch:
        batch.add_column(sa.Column("created_by", sa.String(), nullable=False, server_default="admin"))


def downgrade():
    raise RuntimeError("restore backup")
