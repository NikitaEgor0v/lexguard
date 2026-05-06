"""Add analyzed_segments column to analysis_results for incremental processing

Revision ID: 005_add_analyzed_segments
Revises: 004_add_safe_redaction
Create Date: 2026-05-06
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "005_add_analyzed_segments"
down_revision = "004_add_safe_redaction"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "analysis_results",
        sa.Column("analyzed_segments", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("analysis_results", "analyzed_segments")
