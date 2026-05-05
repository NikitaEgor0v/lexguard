"""Add safe_redaction column to risk_items

Revision ID: 004_add_safe_redaction
Revises: 003_add_user_documents
Create Date: 2026-05-06
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "004_add_safe_redaction"
down_revision = "003_add_user_documents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("risk_items", sa.Column("safe_redaction", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("risk_items", "safe_redaction")
