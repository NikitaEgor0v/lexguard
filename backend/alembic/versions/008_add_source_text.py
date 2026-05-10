"""Add source_text column to user_documents

Revision ID: 008_add_source_text
Revises: 007_constraints
Create Date: 2026-05-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "008_add_source_text"
down_revision: Union[str, None] = "007_constraints"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("user_documents", sa.Column("source_text", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("user_documents", "source_text")
