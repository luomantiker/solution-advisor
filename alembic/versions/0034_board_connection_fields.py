"""Add direct board connection fields.

Revision ID: 0034_board_connection_fields
Revises: 0033_boards_and_binding_board
"""
from alembic import op
import sqlalchemy as sa


revision = "0034_board_connection_fields"
down_revision = "0033_boards_and_binding_board"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("boards") as batch:
        batch.add_column(sa.Column("ip_address", sa.String(length=45), nullable=True))
        batch.add_column(sa.Column("port", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("username", sa.String(length=120), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("boards") as batch:
        batch.drop_column("username")
        batch.drop_column("port")
        batch.drop_column("ip_address")
