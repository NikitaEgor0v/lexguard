from fastapi import APIRouter, UploadFile, File, HTTPException
from starlette.concurrency import run_in_threadpool
from services.analyzer import AnalyzerService
from services.preprocessor import PreprocessorService
from models.schemas import AnalysisResponse, AnalysisStatus
import uuid
import logging

router = APIRouter()
analyzer = AnalyzerService()
preprocessor = PreprocessorService()
logger = logging.getLogger(__name__)
MAX_SEGMENTS_PER_DOCUMENT = 80


@router.post("/analyze", response_model=AnalysisResponse)
async def analyze_document(file: UploadFile = File(...)):
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
        # Анализ CPU-bound и блокирующий; запускаем в threadpool,
        # чтобы не блокировать обработку других HTTP-запросов.
        result = await run_in_threadpool(analyzer.analyze, segments, analysis_id, filename)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.exception("Unexpected analysis failure")
        raise HTTPException(status_code=500, detail=f"Ошибка анализа: {str(e)}")

    return result


@router.get("/analyze/{analysis_id}", response_model=AnalysisResponse)
def get_analysis(analysis_id: str):
    result = analyzer.get_result(analysis_id)
    if not result:
        raise HTTPException(status_code=404, detail="Анализ не найден")
    return result


@router.get("/status")
def system_status():
    return analyzer.check_model_status()
