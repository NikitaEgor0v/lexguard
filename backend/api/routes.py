from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from config.database import get_db
from config.security import get_current_user
from models.db_models import UserDB, AnalysisResultDB
from services.analyzer import AnalyzerService, MAX_SEGMENTS_PER_DOCUMENT
from services.preprocessor import PreprocessorService
from services.risk_grouping import group_analysis_risks
from models.schemas import AnalysisResponse, AnalysisStatus
import uuid
import logging
import json
import time
import os
import sys
import requests

router = APIRouter()
analyzer = AnalyzerService()
preprocessor = PreprocessorService()
logger = logging.getLogger(__name__)


def _verify_analysis_owner(
    db: Session,
    analysis_id: str,
    current_user: UserDB,
) -> AnalysisResultDB:
    """Verify that current user owns the analysis. Raises HTTPException if not.
    
    Returns the analysis row if found and owned by user.
    Raises 404 if analysis doesn't exist, 403 if owned by another user.
    """
    try:
        uid = uuid.UUID(analysis_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Анализ не найден")
    
    row = db.query(AnalysisResultDB).filter_by(id=uid).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Анализ не найден")
    
    if row.user_id is not None and row.user_id != current_user.id:
        logger.warning(
            "IDOR attempt: user %s tried to access analysis %s owned by %s",
            current_user.id, analysis_id, row.user_id
        )
        raise HTTPException(status_code=403, detail="Доступ запрещён")
    
    return row
DEBUG_LOG_PATH = "/tmp/lexguard-debug.log"
DEBUG_ENDPOINT = "http://127.0.0.1:7691/ingest/bcb6efda-9fe5-4ac7-b530-a243639a005e"
DEBUG_ENDPOINT_DOCKER_FALLBACK = "http://host.docker.internal:7691/ingest/bcb6efda-9fe5-4ac7-b530-a243639a005e"


def _debug_log(run_id: str, hypothesis_id: str, location: str, message: str, data: dict) -> None:
    payload = {
        "sessionId": "3d0ca5",
        "runId": run_id,
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
    }
    # #region agent log
    try:
        requests.post(
            DEBUG_ENDPOINT,
            json=payload,
            timeout=0.5,
            headers={"Content-Type": "application/json", "X-Debug-Session-Id": "3d0ca5"},
        )
    except Exception:
        try:
            requests.post(
                DEBUG_ENDPOINT_DOCKER_FALLBACK,
                json=payload,
                timeout=0.5,
                headers={"Content-Type": "application/json", "X-Debug-Session-Id": "3d0ca5"},
            )
        except Exception:
            pass
    try:
        os.makedirs(os.path.dirname(DEBUG_LOG_PATH), exist_ok=True)
        with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception as e:
        try:
            print(f"[debug-log-failed][routes]{e}", file=sys.stderr)
        except Exception:
            pass
    # #endregion


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

    # Configurable upper bound; 0 means unlimited.
    if MAX_SEGMENTS_PER_DOCUMENT > 0 and len(segments) > MAX_SEGMENTS_PER_DOCUMENT:
        raise HTTPException(
            status_code=422,
            detail=f"Документ слишком большой для анализа (сегментов: {len(segments)}, максимум: {MAX_SEGMENTS_PER_DOCUMENT})",
        )

    analysis_id = str(uuid.uuid4())
    try:
        from services.tasks import analyze_document_task
        uid_str = str(current_user.id) if current_user else None
        
        from models.db_models import AnalysisResultDB
        new_analysis = AnalysisResultDB(
            id=uuid.UUID(analysis_id),
            user_id=current_user.id if current_user else None,
            filename=filename,
            status="processing",
            total_segments=len(segments),
        )
        db.add(new_analysis)
        db.commit()
        
        # Submit to Celery
        task = analyze_document_task.delay(segments, analysis_id, filename, uid_str)
        logger.info("Sent analysis %s to Celery (Task ID: %s), segments: %d", analysis_id, task.id, len(segments))
        
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
    # P0 Security: Verify ownership before any other logic
    row = _verify_analysis_owner(db, analysis_id, current_user)
    
    _debug_log(
        "post-fix",
        "H1_H2",
        "backend/api/routes.py:get_analysis",
        "analysis lookup (owner verified)",
        {
            "analysis_id": analysis_id,
            "current_user_id": str(current_user.id) if current_user else None,
            "result_status": row.status,
        },
    )

    # If analysis is complete, return full result via repository
    if row.status == "completed":
        result = analyzer.get_result(analysis_id, db=db)
        if result:
            return result

    # If already marked failed in DB, return consistent error response
    if row.status == "failed":
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=200, content={
            "status": "failed",
            "analysis_id": analysis_id,
            "filename": row.filename,
            "message": "Процесс анализа неожиданно прерван. Попробуйте загрузить документ снова."
        })

    # Still processing — check Redis for progress & heartbeat
    import redis
    import time as _time
    from fastapi.responses import JSONResponse
    from services.analyzer import HEARTBEAT_TIMEOUT_SEC

    redis_url = os.getenv("REDIS_URL", "redis://lexguard_redis:6379/0")
    try:
        r = redis.from_url(redis_url)
        val = r.get(f"progress:{analysis_id}")
        progress_str = val.decode() if val else "0/1"
    except Exception:
        r = None
        progress_str = "0/1"

    # ── Heartbeat check: detect dead Celery workers ──
    heartbeat_stale = False
    if r is not None:
        try:
            hb_raw = r.get(f"heartbeat:{analysis_id}")
            if hb_raw is not None:
                last_beat = int(hb_raw.decode())
                if _time.time() - last_beat > HEARTBEAT_TIMEOUT_SEC:
                    heartbeat_stale = True
            else:
                # No heartbeat key at all — worker may not have started yet.
                # Only consider dead if enough time passed since DB creation.
                if row.status == "processing" and row.created_at:
                    from datetime import datetime, timezone
                    age_sec = (_time.time() - row.created_at.replace(tzinfo=timezone.utc).timestamp())
                    if age_sec > HEARTBEAT_TIMEOUT_SEC:
                        heartbeat_stale = True
        except Exception as hb_err:
            logger.warning("Heartbeat check failed for %s: %s", analysis_id, hb_err)

    if heartbeat_stale:
        # Mark as failed in DB so future requests don't re-check
        try:
            if row.status == "processing":
                row.status = "failed"
                db.commit()
                logger.warning("Analysis %s marked failed: heartbeat stale", analysis_id)
        except Exception as db_err:
            logger.error("Failed to mark analysis %s as failed: %s", analysis_id, db_err)

        # Clean up Redis keys
        try:
            r.delete(f"progress:{analysis_id}", f"heartbeat:{analysis_id}")
        except Exception:
            pass

        return JSONResponse(status_code=200, content={
            "status": "failed",
            "analysis_id": analysis_id,
            "filename": row.filename,
            "message": "Процесс анализа неожиданно прерван. Попробуйте загрузить документ снова."
        })

    # ── Normal processing response ──
    parts = progress_str.split("/")
    current = int(parts[0]) if len(parts) > 0 and parts[0].isdigit() else 0
    total = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
    pct = int(current / total * 100) if total > 0 else 0
    label = f"Анализ {current} из {total}" if current > 0 else "Инициализация LLM..."

    return JSONResponse(status_code=200, content={
        "status": "processing",
        "analysis_id": analysis_id,
        "filename": row.filename,
        "progress_percent": pct,
        "progress_label": label
    })


@router.get("/analyze/{analysis_id}/grouped")
def get_analysis_grouped(
    analysis_id: str,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    """Return grouped risk data.

    If the analysis is still processing, returns partial results (the risks
    that have been saved so far) with ``status: "processing"`` so the
    frontend can render them incrementally.
    """
    from repositories.analysis_repository import AnalysisRepository

    # P0 Security: Verify ownership before any other logic
    row = _verify_analysis_owner(db, analysis_id, current_user)
    
    _debug_log(
        "post-fix",
        "H2",
        "backend/api/routes.py:get_analysis_grouped",
        "grouped lookup (owner verified)",
        {
            "analysis_id": analysis_id,
            "current_user_id": str(current_user.id) if current_user else None,
            "result_status": row.status,
        },
    )

    if row.status == "completed":
        result = analyzer.get_result(analysis_id, db=db)
        if result:
            return group_analysis_risks(result)

    # ── Partial results while still processing ──
    partial = AnalysisRepository.get_partial_result(db, analysis_id)
    if partial is None:
        raise HTTPException(status_code=404, detail="Результат анализа не найден")

    # If we have no risks yet, return a minimal response
    if not partial["risks"]:
        return {
            "analysis_id": partial["analysis_id"],
            "filename": partial["filename"],
            "status": partial["status"],
            "total_segments": partial["total_segments"],
            "analyzed_segments": partial["analyzed_segments"],
            "summary": None,
            "executive_summary": None,
            "groups": [],
        }

    # Build a temporary AnalysisResponse to use the existing grouping logic
    from models.schemas import AnalysisSummary
    from services.executive_summary import build_executive_summary

    risks = partial["risks"]
    # is_risky=None (parse failure) treated as risky for stats
    risky = [r for r in risks if r.is_risky is True or r.is_risky is None]
    high = sum(1 for r in risks if r.risk_level.value == "high")
    medium = sum(1 for r in risks if r.risk_level.value == "medium")
    low = sum(1 for r in risks if r.risk_level.value == "low")
    total_so_far = len(risks)
    score = min(1.0, round((high * 1.0 + medium * 0.5 + low * 0.2) / max(total_so_far, 1), 2))

    temp_summary = AnalysisSummary(
        total_segments=partial["total_segments"],
        risky_segments=len(risky),
        high_risk_count=high,
        medium_risk_count=medium,
        low_risk_count=low,
        risk_score=score,
    )

    temp_response = AnalysisResponse(
        analysis_id=partial["analysis_id"],
        filename=partial["filename"],
        status=partial["status"],
        summary=temp_summary,
        executive_summary=None,  # Summary not ready until all segments are done
        risks=risks,
    )

    grouped = group_analysis_risks(temp_response)
    # Inject streaming metadata so frontend knows this is partial
    grouped["status"] = partial["status"]
    grouped["total_segments"] = partial["total_segments"]
    grouped["analyzed_segments"] = partial["analyzed_segments"]
    return grouped


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
