"""Make Candidate creation for an agent/digest database-atomic."""
from alembic import op

revision = "0014_candidate_digest_unique"
down_revision = "0013_user_owned_assets"
branch_labels = depends_on = None

def upgrade():
    with op.batch_alter_table("platform_candidates") as batch:
        batch.create_unique_constraint("uq_platform_candidate_agent_digest", ["agent_id", "image_id"])

def downgrade(): raise RuntimeError("restore backup")
