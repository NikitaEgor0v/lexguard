import json
import requests
import logging
import time
import os
from models.schemas import (
    AnalysisResponse, AnalysisSummary, RiskItem, RiskLevel, RiskCategory
)
from services.rag import RAGService

logger = logging.getLogger(__name__)

OLLAMA_URL = "http://ollama:11434/api/generate"
MODEL_NAME = os.getenv("OLLAMA_MODEL", "gemma2:2b")
REQUEST_TIMEOUT_SEC = 180
MAX_LLM_RETRIES = 2
MAX_SEGMENT_CHARS = 1200
MAX_RAG_CONTEXT_CHARS = 1200

SYSTEM_PROMPT = """Ты — система анализа юридических договоров для IT-компании.
Проанализируй фрагмент договора и верни ТОЛЬКО валидный JSON без пояснений и markdown.

Структура ответа:
{
  "is_risky": true или false,
  "risk_level": "high" или "medium" или "low" или "none",
  "risk_category": "финансовый" или "правовой" или "операционный" или "репутационный" или "интеллектуальный" или null,
  "risk_description": "краткое описание риска" или null,
  "recommendation": "конкретная рекомендация по исправлению" или null
}

Критерии:
- high: штраф по усмотрению, потеря прав на ПО, расторжение без компенсации, неограниченная ответственность
- medium: размытые сроки, неопределённые обязанности, несоразмерные санкции
- low: минорные неточности, избыточные требования без серьёзных последствий
- none: стандартная нейтральная юридически корректная формулировка"""


class AnalyzerService:
    def __init__(self):
        self.rag = RAGService()
        self._results: dict[str, AnalysisResponse] = {}

    def analyze(self, segments: list[str], analysis_id: str, filename: str = "document") -> AnalysisResponse:
        risks = []
        for i, segment in enumerate(segments):
            logger.info(f"Анализ {i+1}/{len(segments)}")
            rag_context = self.rag.search(segment)
            raw = self._call_llm(segment, rag_context)
            risks.append(self._parse(raw, segment, i + 1, rag_context))

        summary = self._summary(risks)
        response = AnalysisResponse(
            analysis_id=analysis_id, filename=filename,
            status="completed", summary=summary, risks=risks,
        )
        self._results[analysis_id] = response
        return response

    def _call_llm(self, segment: str, rag_context: str | None) -> str:
        segment_safe = segment[:MAX_SEGMENT_CHARS]
        rag_safe = rag_context[:MAX_RAG_CONTEXT_CHARS] if rag_context else None
        last_error = "Неизвестная ошибка"

        for attempt in range(MAX_LLM_RETRIES + 1):
            use_rag = bool(rag_safe) and attempt == 0
            if use_rag:
                user_prompt = (
                    f"Фрагмент договора:\n{segment_safe}\n\n"
                    f"Релевантные нормы из базы:\n{rag_safe}\n\n"
                    f"Проанализируй фрагмент с учётом норм."
                )
            else:
                user_prompt = f"Фрагмент договора:\n{segment_safe}"

            payload = {
                "model": MODEL_NAME,
                "prompt": f"{SYSTEM_PROMPT}\n\n{user_prompt}",
                "stream": False,
                # Меньший контекст снижает риск падения runner по памяти.
                "options": {"temperature": 0.0, "num_predict": 300, "num_ctx": 2048},
            }

            try:
                resp = requests.post(OLLAMA_URL, json=payload, timeout=REQUEST_TIMEOUT_SEC)
                if resp.status_code >= 400:
                    body = (resp.text or "").strip()[:300]
                    raise RuntimeError(f"Ollama HTTP {resp.status_code}: {body or 'empty response'}")
                answer = resp.json().get("response", "").strip()
                if not answer:
                    raise RuntimeError("Ollama вернул пустой ответ")
                return answer
            except requests.exceptions.ConnectionError:
                raise RuntimeError("Ollama недоступен")
            except requests.exceptions.Timeout:
                last_error = "Таймаут ответа Ollama"
            except Exception as e:
                last_error = str(e)
                logger.warning(f"LLM attempt {attempt + 1} failed: {e}")

            if attempt < MAX_LLM_RETRIES:
                time.sleep(1 + attempt)

        raise RuntimeError(f"Ошибка генерации в Ollama: {last_error}")

    def _parse(self, raw: str, segment: str, sid: int, rag: str | None) -> RiskItem:
        try:
            clean = raw.replace("```json", "").replace("```", "").strip()
            data = json.loads(clean)
            return RiskItem(
                segment_id=sid, text=segment,
                is_risky=bool(data.get("is_risky", False)),
                risk_level=RiskLevel(data.get("risk_level", "none")),
                risk_category=RiskCategory(data["risk_category"]) if data.get("risk_category") else None,
                risk_description=data.get("risk_description"),
                recommendation=data.get("recommendation"),
                rag_context=rag,
            )
        except Exception as e:
            logger.warning(f"Parse error segment {sid}: {e}")
            return RiskItem(
                segment_id=sid, text=segment, is_risky=True,
                risk_level=RiskLevel.LOW, risk_category=None,
                risk_description="Не удалось классифицировать — требует проверки",
                recommendation="Проверьте вручную", rag_context=rag,
            )

    def _summary(self, risks: list[RiskItem]) -> AnalysisSummary:
        risky = [r for r in risks if r.is_risky]
        high = sum(1 for r in risks if r.risk_level == RiskLevel.HIGH)
        medium = sum(1 for r in risks if r.risk_level == RiskLevel.MEDIUM)
        low = sum(1 for r in risks if r.risk_level == RiskLevel.LOW)
        score = min(1.0, round((high * 1.0 + medium * 0.5 + low * 0.2) / max(len(risks), 1), 2))
        return AnalysisSummary(
            total_segments=len(risks), risky_segments=len(risky),
            high_risk_count=high, medium_risk_count=medium,
            low_risk_count=low, risk_score=score,
        )

    def get_result(self, analysis_id: str) -> AnalysisResponse | None:
        return self._results.get(analysis_id)

    def check_model_status(self) -> dict:
        try:
            resp = requests.get("http://ollama:11434/api/tags", timeout=5)
            models = [m["name"] for m in resp.json().get("models", [])]
            model_base = MODEL_NAME.split(":")[0]
            return {
                "ollama": "running", "model": MODEL_NAME,
                "model_available": any(MODEL_NAME == m or model_base in m for m in models),
                "all_models": models,
                "rag": self.rag.get_stats(),
            }
        except Exception:
            return {"ollama": "not running", "model": MODEL_NAME, "model_available": False, "rag": self.rag.get_stats()}
