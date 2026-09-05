"""Add governed boards and optionally attach a ready board to a binding.

Revision ID: 0033_boards_and_binding_board
Revises: 0032_people_source
"""
from alembic import op
import sqlalchemy as sa

revision = "0033_boards_and_binding_board"
down_revision = "0032_people_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "boards",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("agent_id", sa.String(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("board_type", sa.String(length=120), nullable=False),
        sa.Column("connection_ref", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="UNVERIFIED"),
        sa.Column("last_test_at", sa.DateTime(), nullable=True),
        sa.Column("last_test_result", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("agent_id", "name", name="uq_board_agent_name"),
    )
    op.create_index("ix_boards_agent_id", "boards", ["agent_id"])
    op.create_index("ix_boards_status", "boards", ["status"])
    with op.batch_alter_table("platform_bindings") as batch:
        batch.add_column(sa.Column("board_id", sa.String(), nullable=True))
        batch.create_foreign_key("fk_platform_bindings_board_id", "boards", ["board_id"], ["id"])
        batch.create_index("ix_platform_bindings_board_id", ["board_id"])


def downgrade() -> None:
    with op.batch_alter_table("platform_bindings") as batch:
        batch.drop_index("ix_platform_bindings_board_id")
        batch.drop_constraint("fk_platform_bindings_board_id", type_="foreignkey")
        batch.drop_column("board_id")
    op.drop_index("ix_boards_status", table_name="boards")
    op.drop_index("ix_boards_agent_id", table_name="boards")
    op.drop_table("boards")
