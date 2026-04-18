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
    """
    logger.info("Starting background analysis for %s (chunks: %d)", analysis_id, len(segments))
    
    analyzer = AnalyzerService()
    db: Session = SessionLocal()
    
    try:
        import uuid
        uid = uuid.UUID(user_id_str) if user_id_str else None
        
        # This will save the result to the DB inside analyzer.analyze(...)
        analyzer.analyze(segments, analysis_id, filename, db=db, user_id=uid)
        logger.info("Analysis task %s completed successfully", analysis_id)
        
        return {"status": "completed", "analysis_id": analysis_id}
    except Exception as e:
        logger.exception("Analysis task %s failed", analysis_id)
        # We could also track failures in the DB if we added a status field to AnalysisResultDB
        # Right now we rely on the client noticing a timeout or checking Celery results
        raise e
    finally:
        db.close()
