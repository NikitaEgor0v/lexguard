"""Allow NULL for is_risky column (parse failures)

Revision ID: 006_allow_null_is_risky
Revises: 005_add_analyzed_segments
Create Date: 2026-05-07

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '006_allow_null_is_risky'
down_revision = '005_add_analyzed_segments'
branch_labels = None
depends_on = None


def upgrade():
    """Allow is_risky to be NULL (indicates parse failure requiring manual review)."""
    op.alter_column(
        'risk_items',
        'is_risky',
        existing_type=sa.Boolean(),
        nullable=True,
        existing_nullable=False,
    )


def downgrade():
    """Revert is_risky to NOT NULL (set NULL values to FALSE before migration)."""
    # Set all NULL values to False before making the column NOT NULL
    op.execute("UPDATE risk_items SET is_risky = FALSE WHERE is_risky IS NULL")
    
    op.alter_column(
        'risk_items',
        'is_risky',
        existing_type=sa.Boolean(),
        nullable=False,
        existing_nullable=True,
    )
