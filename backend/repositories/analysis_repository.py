"""
Repository for analysis results — CRUD operations over PostgreSQL.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from models.db_models import AnalysisResultDB, RiskItemDB
from models.schemas import (
    AnalysisResponse,
    AnalysisSummary,
    RiskItem,
    RiskLevel,
    RiskCategory,
)

logger = logging.getLogger(__name__)


class AnalysisRepository:
    """Persists and retrieves analysis results from PostgreSQL."""

    @staticmethod
    def save_result(
        db: Session,
        analysis_id: str,
        filename: str,
        summary: AnalysisSummary,
        risks: list[RiskItem],
        user_id: UUID | None = None,
    ) -> AnalysisResultDB:
        """Save a complete analysis (header + risks) in one transaction."""
        analysis = AnalysisResultDB(
            id=uuid.UUID(analysis_id),
            user_id=user_id,
            filename=filename,
            status="completed",
            total_segments=summary.total_segments,
            risky_segments=summary.risky_segments,
            high_risk_count=summary.high_risk_count,
            medium_risk_count=summary.medium_risk_count,
            low_risk_count=summary.low_risk_count,
            risk_score=summary.risk_score,
        )
        for risk in risks:
            analysis.risks.append(
                RiskItemDB(
                    segment_id=risk.segment_id,
                    text=risk.text,
                    is_risky=risk.is_risky,
                    risk_level=risk.risk_level.value,
                    risk_category=risk.risk_category.value if risk.risk_category else None,
                    risk_description=risk.risk_description,
                    recommendation=risk.recommendation,
                    rag_context=risk.rag_context,
                )
            )
        db.add(analysis)
        db.commit()
        db.refresh(analysis)
        logger.info("Analysis %s saved to DB (%d risks)", analysis_id, len(risks))
        return analysis

    @staticmethod
    def get_result(db: Session, analysis_id: str) -> Optional[AnalysisResponse]:
        """Load analysis by ID and convert to Pydantic response model."""
        try:
            uid = uuid.UUID(analysis_id)
        except ValueError:
            return None

        row: Optional[AnalysisResultDB] = db.get(AnalysisResultDB, uid)
        if row is None:
            return None

        return AnalysisRepository._row_to_response(row)

    @staticmethod
    def list_results(db: Session, user_id: UUID, limit: int = 20, offset: int = 0) -> list[dict]:
        """List analyses for a user with pagination (summary only, no risks)."""
        rows = (
            db.query(AnalysisResultDB)
            .filter(AnalysisResultDB.user_id == user_id)
            .order_by(AnalysisResultDB.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [
            {
                "analysis_id": str(r.id),
                "filename": r.filename,
                "status": r.status,
                "risk_score": r.risk_score,
                "total_segments": r.total_segments,
                "risky_segments": r.risky_segments,
                "high_risk_count": r.high_risk_count,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]

    @staticmethod
    def count_results(db: Session, user_id: UUID) -> int:
        return db.query(func.count(AnalysisResultDB.id)).filter(
            AnalysisResultDB.user_id == user_id
        ).scalar() or 0

    @staticmethod
    def _row_to_response(row: AnalysisResultDB) -> AnalysisResponse:
        risks = [
            RiskItem(
                segment_id=r.segment_id,
                text=r.text,
                is_risky=r.is_risky,
                risk_level=RiskLevel(r.risk_level),
                risk_category=RiskCategory(r.risk_category) if r.risk_category else None,
                risk_description=r.risk_description,
                recommendation=r.recommendation,
                rag_context=r.rag_context,
            )
            for r in row.risks
        ]
        summary = AnalysisSummary(
            total_segments=row.total_segments,
            risky_segments=row.risky_segments,
            high_risk_count=row.high_risk_count,
            medium_risk_count=row.medium_risk_count,
            low_risk_count=row.low_risk_count,
            risk_score=row.risk_score,
        )
        return AnalysisResponse(
            analysis_id=str(row.id),
            filename=row.filename,
            status=row.status,
            summary=summary,
            risks=risks,
        )
