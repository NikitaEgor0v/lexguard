import logging
from typing import Optional

from celery import shared_task
from sqlalchemy.orm import Session

from config.celery_app import celery_app
from config.database import SessionLocal
from services.analyzer import AnalyzerService

logger = logging.getLogger(__name__)


@shared_task(bind=True, name="analyze_document_task")
def analyze_document_task(self, segments: list[str], analysis_id: str, filename: str, user_id_str: Optional[str] = None):
    """
    Background Celery task that performs document risk analysis.
    Creates its own DB session since it runs out of HTTP request context.

    Processing happens in batches — each batch is saved to the DB
    immediately so the frontend can start rendering partial results.
    """
    logger.info("Starting background analysis for %s (chunks: %d)", analysis_id, len(segments))
    
    analyzer = AnalyzerService()
    db: Session = SessionLocal()
    
    try:
        import uuid
        uid = uuid.UUID(user_id_str) if user_id_str else None
        
        # This will save batches incrementally and finalize at the end
        analyzer.analyze(segments, analysis_id, filename, db=db, user_id=uid)
        logger.info("Analysis task %s completed successfully", analysis_id)
        
        # Clean up heartbeat key on success
        try:
            import redis
            import os
            redis_url = os.getenv("REDIS_URL", "redis://lexguard_redis:6379/0")
            r = redis.from_url(redis_url)
            r.delete(f"heartbeat:{analysis_id}")
        except Exception:
            pass
        
        return {"status": "completed", "analysis_id": analysis_id}
    except Exception as e:
        logger.exception("Analysis task %s failed", analysis_id)
        # Mark the existing record as failed (it was created by the route handler)
        try:
            from models.db_models import AnalysisResultDB
            import uuid as _uuid
            row = db.query(AnalysisResultDB).filter_by(id=_uuid.UUID(analysis_id)).first()
            if row:
                row.status = "failed"
                db.commit()
            else:
                # Should not happen, but just in case
                uid = _uuid.UUID(user_id_str) if user_id_str else None
                failed_analysis = AnalysisResultDB(
                    id=_uuid.UUID(analysis_id),
                    user_id=uid,
                    filename=filename,
                    status="failed",
                    total_segments=len(segments),
                    risky_segments=0,
                    high_risk_count=0,
                    medium_risk_count=0,
                    low_risk_count=0,
                    risk_score=0.0,
                )
                db.add(failed_analysis)
                db.commit()
        except Exception as db_err:
            logger.error("Failed to save error state to DB: %s", db_err)
            
        try:
            import redis
            import os
            redis_url = os.getenv("REDIS_URL", "redis://lexguard_redis:6379/0")
            r = redis.from_url(redis_url)
            r.setex(f"progress:{analysis_id}", 3600, "error")
            r.delete(f"heartbeat:{analysis_id}")
        except Exception as redis_err:
            logger.error("Failed to update redis: %s", redis_err)

        raise e
    finally:
        db.close()
