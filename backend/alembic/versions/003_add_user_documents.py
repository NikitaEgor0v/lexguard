"""add user documents table

Revision ID: 003_add_user_documents
Revises: 002_add_users
Create Date: 2026-04-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = "003_add_user_documents"
down_revision: Union[str, None] = "002_add_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- user_documents ---
    op.create_table(
        "user_documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("contract_type", sa.String(64), nullable=False, server_default="иной"),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("chunks_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_user_documents_user_id", "user_documents", ["user_id"])


def downgrade() -> None:
    op.drop_table("user_documents")
