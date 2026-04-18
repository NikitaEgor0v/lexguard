"""add users table and auth relationships

Revision ID: 002_add_users
Revises: 001_initial
Create Date: 2026-04-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = "002_add_users"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- users ---
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("hashed_password", sa.String(256), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    # --- add user_id to analysis_results ---
    op.add_column("analysis_results", sa.Column("user_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_analysis_results_user_id_users",
        "analysis_results",
        "users",
        ["user_id"],
        ["id"],
    )
    op.create_index("ix_analysis_results_user_id", "analysis_results", ["user_id"])

    # --- add user_id to chat_sessions ---
    op.add_column("chat_sessions", sa.Column("user_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_chat_sessions_user_id_users",
        "chat_sessions",
        "users",
        ["user_id"],
        ["id"],
    )
    op.create_index("ix_chat_sessions_user_id", "chat_sessions", ["user_id"])


def downgrade() -> None:
    # --- chat_sessions ---
    op.drop_index("ix_chat_sessions_user_id", table_name="chat_sessions")
    op.drop_constraint("fk_chat_sessions_user_id_users", "chat_sessions", type_="foreignkey")
    op.drop_column("chat_sessions", "user_id")

    # --- analysis_results ---
    op.drop_index("ix_analysis_results_user_id", table_name="analysis_results")
    op.drop_constraint("fk_analysis_results_user_id_users", "analysis_results", type_="foreignkey")
    op.drop_column("analysis_results", "user_id")

    # --- users ---
    op.drop_table("users")
