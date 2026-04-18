import json
import requests
import logging
import time
import os
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from config.model_registry import get_model_config
from models.schemas import (
    AnalysisResponse, AnalysisSummary, RiskItem, RiskLevel, RiskCategory
)
from repositories.analysis_repository import AnalysisRepository
from services.rag import RAGService

logger = logging.getLogger(__name__)

OLLAMA_URL = "http://ollama:11434/api/generate"
MODEL_NAME = os.getenv("LLM_MODEL", "gemma2:2b")
MODEL_CONFIG = get_model_config(MODEL_NAME)
REQUEST_TIMEOUT_SEC = 180
MAX_LLM_RETRIES = 2
MAX_SEGMENT_CHARS = 800
MAX_RAG_CONTEXT_CHARS = 800
MAX_CLASSIFY_PREVIEW_CHARS = 800
CONTRACT_TYPE_LABELS = frozenset({
    "услуги", "подряд", "поставка", "аренда", "трудовой",
    "лицензионный", "нда", "агентский", "иной",
})

CONTRACT_CLASSIFY_PROMPT = """Определи тип договора по фрагменту. Ответь ОДНИМ словом из списка, без пояснений и пунктуации:
услуги, подряд, поставка, аренда, трудовой, лицензионный, нда, агентский, иной

Текст:
"""

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

Правила уровня риска (классифицируй только по фактическому содержанию фрагмента):
- high: применяй, если в тексте есть хотя бы одно из: штраф, неустойка или иная денежная санкция без ограничения суммы или без верхнего предела; утрата прав на программное обеспечение или иные результаты работ без компенсации или без согласованного правопреемства; расторжение или прекращение без выплат контрагенту при отсутствии виновных действий с его стороны (если это прямо следует из формулировки); неограниченная ответственность или отсутствие пределов ответственности там, где закон или практика допускают ограничение.
- medium: применяй при существенной неопределённости или дисбалансе, не доходящем до high: сроки без измеримых критериев или без привязки к событиям; обязанности сформулированы так, что объём или критерий исполнения нельзя однозначно установить из текста; санкции заведомо несоразмерны предмету обязательства в пользу одной стороны; одна сторона вправе менять существенные условия в одностороннем порядке.
- low: применяй при незначительных огрехах формулировки или избыточных формальных требованиях, не создающих прямого денежного риска из самого текста.
- none: применяй, если формулировка нейтральна, сбалансирована и не содержит перечисленных признаков.

Дополнительные правила:
- Если между high и medium нет однозначности — выбирай high.
- Не приписывай фрагменту риски, которых в его тексте нет; не выдумывай факты и не ссылайся на условия, отсутствующие в данном фрагменте (если информации недостаточно — снижай уровень или используй none и is_risky=false)."""


class AnalyzerService:
    def __init__(self):
        self.rag = RAGService()

    def analyze(
        self,
        segments: list[str],
        analysis_id: str,
        filename: str = "document",
        db: Session | None = None,
        user_id: UUID | None = None,
    ) -> AnalysisResponse:
        import redis
        import os
        redis_url = os.getenv("REDIS_URL", "redis://lexguard_redis:6379/0")
        try:
            r = redis.from_url(redis_url)
        except Exception as e:
            logger.warning(f"No redis connection for progress: {e}")
            r = None

        contract_type = self._classify_contract_type(segments)
        risks = []
        total = len(segments)
        for i, segment in enumerate(segments):
            logger.info(f"Анализ {i+1}/{total}")
            if r is not None:
                try:
                    r.setex(f"progress:{analysis_id}", 3600, f"{i}/{total}")
                except Exception:
                    pass
            # Search both system norms and user's custom documents
            rag_context = self.rag.search(segment, contract_type=contract_type, user_id=user_id)
            raw = self._call_llm(segment, rag_context)
            risks.append(self._parse(raw, segment, i + 1, rag_context))

        if r is not None:
            try:
                r.setex(f"progress:{analysis_id}", 3600, f"{total}/{total}")
            except Exception:
                pass

        summary = self._summary(risks)
        response = AnalysisResponse(
            analysis_id=analysis_id, filename=filename,
            status="completed", summary=summary, risks=risks,
        )

        # Persist to PostgreSQL
        if db is not None:
            try:
                AnalysisRepository.save_result(db, analysis_id, filename, summary, risks, user_id=user_id)
            except Exception as e:
                logger.error("Failed to save analysis to DB: %s", e)

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
                "options": {
                    "temperature": MODEL_CONFIG.temperature,
                    "num_predict": MODEL_CONFIG.max_output,
                    "num_ctx": MODEL_CONFIG.context_window,
                },
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

    def _classify_contract_type(self, segments: list[str]) -> str:
        if not segments:
            return "иной"
        if len(segments) >= 2:
            preview = f"{segments[0]}\n\n{segments[1]}"[:MAX_CLASSIFY_PREVIEW_CHARS]
        else:
            preview = segments[0][:MAX_CLASSIFY_PREVIEW_CHARS]
        if not preview.strip():
            return "иной"
        payload = {
            "model": MODEL_NAME,
            "prompt": f"{CONTRACT_CLASSIFY_PROMPT}{preview}",
            "stream": False,
            "options": {
                "temperature": 0.0,
                "num_predict": 10,
                "num_ctx": 1024,
            },
        }
        try:
            resp = requests.post(OLLAMA_URL, json=payload, timeout=REQUEST_TIMEOUT_SEC)
            if resp.status_code >= 400:
                logger.warning("Классификация типа договора: HTTP %s", resp.status_code)
                return "иной"
            answer = (resp.json().get("response") or "").strip().lower()
            token = answer.split()[0] if answer else ""
            token = token.strip(".,;:!?\"'«»")
            if token in CONTRACT_TYPE_LABELS:
                return token
        except requests.exceptions.RequestException as e:
            logger.warning("Классификация типа договора: %s", e)
        except Exception as e:
            logger.warning("Классификация типа договора: %s", e)
        return "иной"

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

    def get_result(self, analysis_id: str, db: Session | None = None) -> AnalysisResponse | None:
        """Load analysis from PostgreSQL."""
        if db is not None:
            return AnalysisRepository.get_result(db, analysis_id)
        return None

    def check_model_status(self) -> dict:
        try:
            import os
            import requests
            base_url = os.getenv("OLLAMA_HOST", "http://lexguard-ollama:11434")
            resp = requests.get(f"{base_url}/api/tags", timeout=5)
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
