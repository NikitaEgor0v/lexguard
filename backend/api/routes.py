from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from config.database import get_db
from config.security import get_current_user
from models.db_models import UserDB
from services.analyzer import AnalyzerService
from services.preprocessor import PreprocessorService
from services.risk_grouping import group_analysis_risks
from models.schemas import AnalysisResponse, AnalysisStatus
import uuid
import logging

router = APIRouter()
analyzer = AnalyzerService()
preprocessor = PreprocessorService()
logger = logging.getLogger(__name__)
MAX_SEGMENTS_PER_DOCUMENT = 80


@router.post("/analyze", response_model=AnalysisResponse)
async def analyze_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    """Загрузить договор (PDF/DOCX) и получить анализ рисков."""
    allowed_ext = (".pdf", ".docx")
    filename = file.filename or "document"
    if not any(filename.lower().endswith(e) for e in allowed_ext):
        raise HTTPException(status_code=400, detail="Поддерживаются только PDF и DOCX файлы")

    content = await file.read()
    if len(content) > 15 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Файл слишком большой (максимум 15 МБ)")

    try:
        segments = preprocessor.process(content, filename)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Ошибка обработки файла: {str(e)}")

    if not segments:
        raise HTTPException(status_code=422, detail="Документ пустой или нечитаемый")
    if len(segments) > MAX_SEGMENTS_PER_DOCUMENT:
        raise HTTPException(
            status_code=422,
            detail=f"Документ слишком большой для анализа (сегментов: {len(segments)}, максимум: {MAX_SEGMENTS_PER_DOCUMENT})",
        )

    analysis_id = str(uuid.uuid4())
    try:
        from services.tasks import analyze_document_task
        uid_str = str(current_user.id) if current_user else None
        
        # Submit to Celery
        task = analyze_document_task.delay(segments, analysis_id, filename, uid_str)
        logger.info("Sent analysis %s to Celery (Task ID: %s)", analysis_id, task.id)
        
    except Exception as e:
        logger.exception("Unexpected analysis start failure")
        raise HTTPException(status_code=500, detail=f"Ошибка запуска анализа: {str(e)}")

    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=202,
        content={
            "status": "processing",
            "analysis_id": analysis_id,
            "message": "Анализ запущен в фоновом режиме"
        }
    )

@router.get("/analyze/{analysis_id}")
def get_analysis(
    analysis_id: str,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    result = analyzer.get_result(analysis_id, db=db)
    if not result:
        import redis
        import os
        from fastapi.responses import JSONResponse
        
        redis_url = os.getenv("REDIS_URL", "redis://lexguard_redis:6379/0")
        try:
            r = redis.from_url(redis_url)
            val = r.get(f"progress:{analysis_id}")
            progress_str = val.decode() if val else "0/1"
        except Exception:
            progress_str = "0/1"
            
        parts = progress_str.split("/")
        current = int(parts[0]) if len(parts) > 0 and parts[0].isdigit() else 0
        total = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
        pct = int(current / total * 100) if total > 0 else 0
        label = f"Анализ {current} из {total}" if current > 0 else "Инициализация LLM..."
        
        return JSONResponse(status_code=200, content={
            "status": "processing", 
            "analysis_id": analysis_id,
            "progress_percent": pct,
            "progress_label": label
        })
    return result


@router.get("/analyze/{analysis_id}/grouped")
def get_analysis_grouped(
    analysis_id: str,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    result = analyzer.get_result(analysis_id, db=db)
    if not result:
        raise HTTPException(status_code=404, detail="Результат анализа не найден")
    return group_analysis_risks(result)


@router.get("/analyses")
def list_analyses(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    """List all analyses for current user with pagination."""
    from repositories.analysis_repository import AnalysisRepository
    items = AnalysisRepository.list_results(db, current_user.id, limit, offset)
    total = AnalysisRepository.count_results(db, current_user.id)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/status")
def system_status():
    return analyzer.check_model_status()
