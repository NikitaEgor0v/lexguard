"""Add domain constraints for status, risk_level, role and unique segment_id

Revision ID: 007_constraints
Revises: 006_allow_null_is_risky
Create Date: 2026-05-08

P2 Security and Data Integrity:
- CHECK constraints for analysis_results.status (processing, completed, failed)
- CHECK constraints for risk_items.risk_level (high, medium, low, none)
- CHECK constraints for chat_messages.role (user, assistant)
- UNIQUE constraint on (analysis_id, segment_id) to prevent duplicate segments
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "007_constraints"
down_revision: Union[str, None] = "006_allow_null_is_risky"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── CHECK constraint for analysis_results.status ──
    op.execute("""
        ALTER TABLE analysis_results 
        ADD CONSTRAINT ck_analysis_results_status 
        CHECK (status IN ('processing', 'completed', 'failed'))
    """)
    
    # ── CHECK constraint for risk_items.risk_level ──
    op.execute("""
        ALTER TABLE risk_items 
        ADD CONSTRAINT ck_risk_items_risk_level 
        CHECK (risk_level IN ('high', 'medium', 'low', 'none'))
    """)
    
    # ── CHECK constraint for chat_messages.role ──
    op.execute("""
        ALTER TABLE chat_messages 
        ADD CONSTRAINT ck_chat_messages_role 
        CHECK (role IN ('user', 'assistant'))
    """)
    
    # ── UNIQUE constraint on (analysis_id, segment_id) ──
    # This prevents duplicate segments within the same analysis
    # First, clean up any potential duplicates (keep first occurrence)
    op.execute("""
        DELETE FROM risk_items a USING risk_items b
        WHERE a.id > b.id 
        AND a.analysis_id = b.analysis_id 
        AND a.segment_id = b.segment_id
    """)
    
    op.create_unique_constraint(
        "uq_risk_items_analysis_segment",
        "risk_items",
        ["analysis_id", "segment_id"]
    )


def downgrade() -> None:
    # Remove constraints in reverse order
    op.drop_constraint("uq_risk_items_analysis_segment", "risk_items", type_="unique")
    
    op.execute("ALTER TABLE chat_messages DROP CONSTRAINT ck_chat_messages_role")
    op.execute("ALTER TABLE risk_items DROP CONSTRAINT ck_risk_items_risk_level")
    op.execute("ALTER TABLE analysis_results DROP CONSTRAINT ck_analysis_results_status")
