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
from services.executive_summary import build_executive_summary

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
        uid = uuid.UUID(analysis_id)
        analysis = db.query(AnalysisResultDB).filter_by(id=uid).first()
        if not analysis:
            analysis = AnalysisResultDB(id=uid, user_id=user_id)
            db.add(analysis)

        analysis.filename = filename
        analysis.status = "completed"
        analysis.total_segments = summary.total_segments
        analysis.risky_segments = summary.risky_segments
        analysis.high_risk_count = summary.high_risk_count
        analysis.medium_risk_count = summary.medium_risk_count
        analysis.low_risk_count = summary.low_risk_count
        analysis.risk_score = summary.risk_score
        analysis.analyzed_segments = summary.total_segments
        
        analysis.risks.clear()

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
                    safe_redaction=risk.safe_redaction,
                )
            )
        db.commit()
        db.refresh(analysis)
        logger.info("Analysis %s saved to DB (%d risks)", analysis_id, len(risks))
        return analysis

    @staticmethod
    def save_batch(
        db: Session,
        analysis_id: str,
        batch_risks: list[RiskItem],
    ) -> None:
        """Incrementally save a batch of analyzed segments to DB.

        Appends new RiskItemDB rows and bumps ``analyzed_segments`` counter
        so the frontend can start reading partial data immediately.
        """
        uid = uuid.UUID(analysis_id)
        analysis = db.query(AnalysisResultDB).filter_by(id=uid).first()
        if not analysis:
            logger.error("save_batch: analysis %s not found in DB", analysis_id)
            return

        for risk in batch_risks:
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
                    safe_redaction=risk.safe_redaction,
                )
            )

        analysis.analyzed_segments = (analysis.analyzed_segments or 0) + len(batch_risks)
        db.commit()
        logger.info(
            "Batch saved for %s: +%d risks (total saved: %d/%d)",
            analysis_id, len(batch_risks),
            analysis.analyzed_segments, analysis.total_segments,
        )

    @staticmethod
    def finalize_result(
        db: Session,
        analysis_id: str,
        summary: AnalysisSummary,
    ) -> None:
        """Mark analysis as completed and write final summary stats.

        Called after all batches have been saved — updates denormalized
        counters and flips status to ``completed``.
        """
        uid = uuid.UUID(analysis_id)
        analysis = db.query(AnalysisResultDB).filter_by(id=uid).first()
        if not analysis:
            logger.error("finalize_result: analysis %s not found in DB", analysis_id)
            return

        analysis.status = "completed"
        analysis.total_segments = summary.total_segments
        analysis.risky_segments = summary.risky_segments
        analysis.high_risk_count = summary.high_risk_count
        analysis.medium_risk_count = summary.medium_risk_count
        analysis.low_risk_count = summary.low_risk_count
        analysis.risk_score = summary.risk_score
        analysis.analyzed_segments = summary.total_segments
        db.commit()
        logger.info("Analysis %s finalized (score=%.2f)", analysis_id, summary.risk_score)

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
    def get_partial_result(db: Session, analysis_id: str) -> Optional[dict]:
        """Return partially analyzed risks (for streaming to frontend).

        Returns a dict with risks collected so far and progress metadata.
        Used while analysis is still ``processing``.
        """
        try:
            uid = uuid.UUID(analysis_id)
        except ValueError:
            return None

        row: Optional[AnalysisResultDB] = db.get(AnalysisResultDB, uid)
        if row is None:
            return None

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
                safe_redaction=r.safe_redaction,
            )
            for r in sorted(row.risks, key=lambda x: x.segment_id)
        ]

        return {
            "analysis_id": str(row.id),
            "filename": row.filename,
            "status": row.status,
            "total_segments": row.total_segments or 0,
            "analyzed_segments": row.analyzed_segments or 0,
            "risks": risks,
        }

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
                safe_redaction=r.safe_redaction,
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
            executive_summary=build_executive_summary(summary, risks),
            risks=risks,
        )
