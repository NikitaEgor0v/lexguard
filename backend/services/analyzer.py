import json
import requests
import logging
import time
import os
from typing import Callable, Optional
from uuid import UUID

from sqlalchemy.orm import Session

import re
from difflib import SequenceMatcher
from config.model_registry import get_model_config
from models.schemas import (
    AnalysisResponse, AnalysisSummary, RiskItem, RiskLevel, RiskCategory
)
from repositories.analysis_repository import AnalysisRepository
from services.executive_summary import build_executive_summary
from services.rag import RAGService, RAGResult

# Patterns for neutral segments that should always be is_risky: false
# These patterns match segments that contain ONLY these elements and nothing else substantive
NEUTRAL_SEGMENT_PATTERNS = [
    # Only price/amount with currency
    r"^[\s\d\W]*(стоимост|цен|сумм|оплат)[\w\s]*[\d\s]+\s*(рубл|руб\.|₽|тыс\.|млн|р\.|долл|\$|евро|EUR|USD)[\w\s.,]*$",
    # Only requisites (INN, KPP, OGRN, bank details, addresses)
    r"^[\s\S]*(инн|кпп|огрн|бик|р/с|к/с|банк|адрес|юридическ|почтов|место\s*нахождения)[\s\S]*$",
    # Only number of copies and signatures
    r"^[\s\S]*(экземпляр|подпис|печат|договор\s*составлен|от\s*заказчика|от\s*исполнителя)[\s\S]*$",
    # Only validity date
    r"^[\s\S]*(вступает\s*в\s*силу|действует\s*(до|с)|срок\s*действия)[\s\S]*$",
    # User added patterns
    r"\d+\s*календарных\s*дней",
    r"составляет\s+[\d\s]+(рубл|руб)",
    r"по одному для каждой из сторон",
    r"равную юридическую силу",
]

def is_neutral_segment(text: str) -> bool:
    """Check if segment is neutral (only contains price, requisites, signatures etc.)."""
    text_lower = text.lower().strip()
    
    for pattern in NEUTRAL_SEGMENT_PATTERNS:
        if re.search(pattern, text_lower):
            return True
            
    # Quick check for neutral keywords without risk keywords
    neutral_keywords = [
        "инн", "кпп", "огрн", "бик", "р/с", "к/с", "банк",
        "экземпляр", "подпис", "печат",
        "юридический адрес", "почтовый адрес", "место нахождения",
    ]
    risk_keywords = [
        "штраф", "неустойк", "ответственност", "расторж", "односторонн",
        "отказ", "без компенсац", "без ограничен", "немедленн", "любой момент",
        "по усмотрению", "без объяснен", "без причин", "без возврат",
    ]
    
    has_neutral = any(kw in text_lower for kw in neutral_keywords)
    has_risk = any(kw in text_lower for kw in risk_keywords)
    
    # If has neutral keywords and no risk keywords, and length is short — likely neutral
    if has_neutral and not has_risk and len(text) < 300:
        return True
    
    # Check if segment is ONLY a price
    price_pattern = r"(стоимость|цена|сумма|оплата).{0,30}[\d\s]+(рубл|руб|₽|тыс|р\.)"
    if re.search(price_pattern, text_lower) and len(text) < 200:
        # Check it doesn't have substantive clauses
        substantive_markers = ["если", "при", "в случае", "обязан", "вправе", "должен"]
        if not any(m in text_lower for m in substantive_markers):
            return True
    
    return False

logger = logging.getLogger(__name__)

MODEL_NAME = os.getenv("LLM_MODEL", "gemma2:2b")
MODEL_CONFIG = get_model_config(MODEL_NAME)

# Adaptive limits from model config (scale with model capacity)
MAX_SEGMENT_CHARS = MODEL_CONFIG.max_segment_chars
MAX_RAG_CONTEXT_CHARS = MODEL_CONFIG.max_rag_chars
MAX_RAG_NORMS = MODEL_CONFIG.max_rag_norms

# Timeouts scaled for larger models (llama3.1:8b needs longer cold start)
REQUEST_TIMEOUT_SEC = int(os.getenv("LLM_REQUEST_TIMEOUT", "300"))
HEARTBEAT_TIMEOUT_SEC = int(os.getenv("LLM_HEARTBEAT_TIMEOUT", "600"))
MAX_LLM_RETRIES = 2
MAX_CLASSIFY_PREVIEW_CHARS = 1500

# Batch size for incremental saving (segments are saved to DB in batches)
ANALYSIS_BATCH_SIZE = int(os.getenv("ANALYSIS_BATCH_SIZE", "20"))

# Ollama endpoint (unified across services)
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434") + "/api/generate"
MAX_SEGMENTS_PER_DOCUMENT = int(os.getenv("MAX_SEGMENTS_PER_DOCUMENT", "500"))
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
  "recommendation": "конкретная рекомендация по исправлению" или null,
  "safe_redaction": "безопасная переформулировка текста" или null
}

=== КРИТИЧЕСКОЕ ПРАВИЛО: СРАВНЕНИЕ С ЭТАЛОНОМ И РИСКОМ ===

RAG-контекст (если есть) структурирован следующим образом:
- ЭТАЛОН (безопасная формулировка): [текст эталона]
- РИСК (опасная формулировка): [текст риска]
- КАТЕГОРИЯ: [категория]
- ОСНОВАНИЕ: [статьи]

АЛГОРИТМ ПРИНЯТИЯ РЕШЕНИЯ:

1. Сравни текст сегмента с полем ЭТАЛОН:
   - Если текст по смыслу СООТВЕТСТВУЕТ ЭТАЛОНУ → is_risky: false, risk_level: none
   - Примеры эталонных формулировок: "права переходят после оплаты", "аванс 50%", 
     "возврат пропорционально выполненным работам", "уведомление за 14 дней"

2. Сравни текст сегмента с полем РИСК:
   - Если текст по смыслу СООТВЕТСТВУЕТ РИСКУ → is_risky: true
   - Примеры рисковых формулировок: "оплата только после всех работ", 
     "неустойка без ограничений", "одностороннее расторжение без компенсации"

3. Само по себе наличие RAG-контекста НЕ ОЗНАЧАЕТ наличие риска!
   RAG показывает тему — решение принимается по ТЕКСТУ фрагмента.

ПРИМЕРЫ ПРАВИЛЬНОЙ КЛАССИФИКАЦИИ:

Фрагмент: "Права на результат переходят Заказчику после полной оплаты"
ЭТАЛОН: "Права переходят после полной оплаты и подписания акта"
→ is_risky: false (текст соответствует эталону)

Фрагмент: "Оплата в два этапа: 50% аванс, 50% после подписания акта"
ЭТАЛОН: "Авансовый платёж 50%, окончательный после акта"
→ is_risky: false (текст соответствует эталону, есть аванс)

Фрагмент: "Оплата производится после выполнения всех работ в полном объёме"
РИСК: "оплата только после всех работ, без промежуточных платежей"
→ is_risky: true, risk_level: medium (текст соответствует риску)

=== НЕЙТРАЛЬНЫЕ СЕГМЕНТЫ (ВСЕГДА is_risky: false БЕЗ ОБРАЩЕНИЯ К RAG) ===

Следующие типы сегментов классифицируй как is_risky: false НЕМЕДЛЕННО:

1. СУММА ДОГОВОРА — только число и валюта:
   "Стоимость услуг составляет 100 000 рублей", "180 000 руб.", "цена 50 000"
   → is_risky: false, risk_level: none

2. РЕКВИЗИТЫ СТОРОН:
   ИНН, КПП, ОГРН, банковские реквизиты, юридический адрес, фактический адрес
   → is_risky: false, risk_level: none

3. ПОДПИСИ И ЭКЗЕМПЛЯРЫ:
   "Договор составлен в двух экземплярах", подписи сторон, печати, должности
   → is_risky: false, risk_level: none

4. ДАТА ВСТУПЛЕНИЯ В СИЛУ:
   "Договор вступает в силу с момента подписания", "действует до 31.12.2026"
   → is_risky: false, risk_level: none

5. ФОРС-МАЖОР С ОБЪЕКТИВНЫМ КРИТЕРИЕМ:
   "Форс-мажор подтверждается справкой компетентного органа (ТПП)"
   → is_risky: false, risk_level: none

6. ДОПСОГЛАШЕНИЯ ОБЕИМИ СТОРОНАМИ:
   "Изменения вносятся по соглашению сторон путём подписания дополнительных соглашений"
   → is_risky: false, risk_level: none (это ЗАЩИТА, не риск)

=== ПРАВИЛА УРОВНЯ РИСКА ===
- high: штраф/неустойка без лимита; утрата прав без компенсации; расторжение без выплат при отсутствии вины; неограниченная ответственность
- medium: сроки без критериев; неопределённые обязанности; несоразмерные санкции; одностороннее изменение условий
- low: незначительные огрехи формулировки без прямого денежного риска
- none: нейтральная, сбалансированная формулировка или нейтральный сегмент

=== ПРАВИЛА SAFE_REDACTION ===
Если is_risky: true И risk_level: high, ОБЯЗАТЕЛЬНО предложи safe_redaction:
- Содержит ТОЛЬКО новую безопасную формулировку (готовый текст для замены)
- НЕ содержит исходный опасный текст даже частично
- НЕ начинается со слов из оригинала
- НЕ содержит пояснений — только текст замены
- Для low/medium/none — safe_redaction: null

ПРИМЕР safe_redaction для пункта о расторжении:
Оригинал: "При расторжении Заказчик оплачивает 100% стоимости"
safe_redaction: "При досрочном расторжении договора Заказчик оплачивает фактически выполненный объём работ и подтверждённые расходы Исполнителя на дату расторжения."

=== ДОПОЛНИТЕЛЬНЫЕ ПРАВИЛА ===
- Не приписывай фрагменту риски, которых в его тексте нет
- Если сомневаешься между риском и безопасностью — проверь, похож ли текст на ЭТАЛОН
- При недостатке информации или отсутствии RAG-контекста — используй none и is_risky: false
- Если RAG-контекст не предоставлен — анализируй только по тексту сегмента"""


class AnalyzerService:
    def __init__(self):
        self.rag = RAGService()

    @staticmethod
    def _update_heartbeat(redis_conn, analysis_id: str) -> None:
        """Refresh heartbeat timestamp for long-running analysis."""
        if redis_conn is None:
            return
        try:
            redis_conn.setex(f"heartbeat:{analysis_id}", 3600, str(int(time.time())))
        except Exception:
            pass

    def analyze(
        self,
        segments: list[str],
        analysis_id: str,
        filename: str = "document",
        db: Session | None = None,
        user_id: UUID | None = None,
    ) -> AnalysisResponse:
        """Analyze document segments and save results incrementally in batches.
        
        Segments are processed one by one (sequential for GPU efficiency) but
        results are saved to DB in batches of ANALYSIS_BATCH_SIZE. This allows
        the frontend to start rendering partial results immediately.
        """
        import redis
        import os
        redis_url = os.getenv("REDIS_URL", "redis://lexguard_redis:6379/0")
        try:
            r = redis.from_url(redis_url)
        except Exception as e:
            logger.warning(f"No redis connection for progress: {e}")
            r = None

        self._update_heartbeat(r, analysis_id)

        contract_type = self._classify_contract_type(segments)
        all_risks: list[RiskItem] = []
        batch_risks: list[RiskItem] = []
        total = len(segments)
        
        for i, segment in enumerate(segments):
            logger.info(f"Анализ {i+1}/{total}")
            self._update_heartbeat(r, analysis_id)
            if r is not None:
                try:
                    r.setex(f"progress:{analysis_id}", 3600, f"{i}/{total}")
                except Exception:
                    pass
            
            # Early exit for neutral segments (price, requisites, signatures)
            if is_neutral_segment(segment):
                logger.info(f"Segment {i+1} classified as NEUTRAL (early exit)")
                risk_item = RiskItem(
                    segment_id=i + 1,
                    text=segment,
                    is_risky=False,
                    risk_level=RiskLevel.NONE,
                    risk_category=None,
                    risk_description=None,
                    recommendation=None,
                    rag_context=None,
                    safe_redaction=None,
                )
                all_risks.append(risk_item)
                batch_risks.append(risk_item)
                self._update_heartbeat(r, analysis_id)
            else:
                # Get structured RAG result with model-specific limits
                rag_result = self.rag.search(
                    segment,
                    contract_type=contract_type,
                    user_id=user_id,
                    top_k=MAX_RAG_NORMS,
                    max_chars=MAX_RAG_CONTEXT_CHARS,
                )
                rag_context_str = RAGService.format_rag_context(rag_result, MAX_RAG_CONTEXT_CHARS)
                
                raw = self._call_llm(
                    segment,
                    rag_result,
                    heartbeat_callback=lambda: self._update_heartbeat(r, analysis_id),
                )
                risk_item = self._parse(raw, segment, i + 1, rag_context_str)
                all_risks.append(risk_item)
                batch_risks.append(risk_item)
                self._update_heartbeat(r, analysis_id)
            
            # P1: Incremental batch saving — save to DB every ANALYSIS_BATCH_SIZE segments
            if len(batch_risks) >= ANALYSIS_BATCH_SIZE:
                if db is not None:
                    try:
                        AnalysisRepository.save_batch(db, analysis_id, batch_risks)
                        logger.info(
                            "Batch saved: %d risks for analysis %s (total: %d/%d)",
                            len(batch_risks), analysis_id, len(all_risks), total
                        )
                    except Exception as e:
                        logger.error("Failed to save batch to DB: %s", e)
                batch_risks = []  # Reset batch buffer

        # Save any remaining risks in the final batch
        if batch_risks and db is not None:
            try:
                AnalysisRepository.save_batch(db, analysis_id, batch_risks)
                logger.info(
                    "Final batch saved: %d risks for analysis %s",
                    len(batch_risks), analysis_id
                )
            except Exception as e:
                logger.error("Failed to save final batch to DB: %s", e)

        if r is not None:
            try:
                r.setex(f"progress:{analysis_id}", 3600, f"{total}/{total}")
            except Exception:
                pass

        # Calculate final summary and executive summary
        summary = self._summary(all_risks)
        executive_summary = build_executive_summary(summary, all_risks)
        
        # P1: Finalize analysis — update status and summary stats
        if db is not None:
            try:
                AnalysisRepository.finalize_result(db, analysis_id, summary)
                logger.info("Analysis %s finalized", analysis_id)
            except Exception as e:
                logger.error("Failed to finalize analysis in DB: %s", e)

        return AnalysisResponse(
            analysis_id=analysis_id, filename=filename,
            status="completed",
            summary=summary,
            executive_summary=executive_summary,
            risks=all_risks,
        )

    def _call_llm(
        self,
        segment: str,
        rag_result: RAGResult,
        heartbeat_callback: Callable[[], None] | None = None,
    ) -> str:
        segment_safe = segment[:MAX_SEGMENT_CHARS]
        last_error = "Неизвестная ошибка"
        
        # Format RAG context (already limited in search call)
        rag_context_str = RAGService.format_rag_context(rag_result)

        for attempt in range(MAX_LLM_RETRIES + 1):
            use_rag = bool(rag_context_str) and attempt == 0 and not rag_result.no_rag_context
            
            if use_rag:
                user_prompt = (
                    f"Фрагмент договора:\n{segment_safe}\n\n"
                    f"RAG-КОНТЕКСТ (релевантные нормы из базы):\n{rag_context_str}\n\n"
                    f"Сравни текст фрагмента с полями ЭТАЛОН и РИСК. "
                    f"Если текст ближе к ЭТАЛОН — верни is_risky: false. "
                    f"Если текст ближе к РИСК — верни is_risky: true с описанием."
                )
            else:
                # no_rag_context=True or retry without RAG
                user_prompt = (
                    f"Фрагмент договора:\n{segment_safe}\n\n"
                    f"RAG-контекст не найден. Классифицируй сегмент только по его тексту. "
                    f"Для нейтральных сегментов (суммы, реквизиты, подписи) верни is_risky: false."
                )

            payload = {
                "model": MODEL_NAME,
                "prompt": f"{SYSTEM_PROMPT}\n\n{user_prompt}",
                "stream": False,
                "options": {
                    "temperature": MODEL_CONFIG.temperature,
                    "num_predict": MODEL_CONFIG.max_output,
                    "num_ctx": MODEL_CONFIG.context_window,
                },
            }

            try:
                if heartbeat_callback:
                    heartbeat_callback()
                resp = requests.post(OLLAMA_URL, json=payload, timeout=REQUEST_TIMEOUT_SEC)
                if resp.status_code >= 400:
                    body = (resp.text or "").strip()[:300]
                    raise RuntimeError(f"Ollama HTTP {resp.status_code}: {body or 'empty response'}")
                answer = resp.json().get("response", "").strip()
                if not answer:
                    raise RuntimeError("Ollama вернул пустой ответ")
                if heartbeat_callback:
                    heartbeat_callback()
                return answer
            except requests.exceptions.ConnectionError:
                raise RuntimeError("Ollama недоступен")
            except requests.exceptions.Timeout:
                last_error = "Таймаут ответа Ollama"
            except Exception as e:
                last_error = str(e)
                logger.warning(f"LLM attempt {attempt + 1} failed: {e}")
            finally:
                if heartbeat_callback:
                    heartbeat_callback()

            if attempt < MAX_LLM_RETRIES:
                time.sleep(1 + attempt)

        raise RuntimeError(f"Ошибка генерации в Ollama: {last_error}")

    def _classify_contract_type(self, segments: list[str]) -> str:
        if not segments:
            return "иной"
        
        full_text = "\n\n".join(segments)
        if len(full_text) > 4500:
            preview = full_text[:1000] + "\n...\n" + full_text[3000:4500]
        else:
            preview = full_text[:MAX_CLASSIFY_PREVIEW_CHARS]
            
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
            # 1. Robust JSON extraction: look for the first '{' and last '}'
            # This handles cases where models include chatty text around the JSON block.
            match = re.search(r'(\{.*\})', raw, re.DOTALL)
            if match:
                clean = match.group(1).strip()
            else:
                # Fallback to the original logic if no braces found
                clean = raw.replace("```json", "").replace("```", "").strip()
            
            data = json.loads(clean)
            
            is_risky = bool(data.get("is_risky", False))
            risk_level = RiskLevel(data.get("risk_level", "none"))
            safe_redaction = data.get("safe_redaction")
            
            # Validate safe_redaction: only for high risk, must not contain original text
            if safe_redaction and is_risky and risk_level in (RiskLevel.HIGH, RiskLevel.MEDIUM):
                safe_redaction = self._validate_safe_redaction(safe_redaction, segment)
            else:
                safe_redaction = None
            
            return RiskItem(
                segment_id=sid, text=segment,
                is_risky=is_risky,
                risk_level=risk_level,
                risk_category=RiskCategory(data["risk_category"]) if data.get("risk_category") else None,
                risk_description=data.get("risk_description"),
                recommendation=data.get("recommendation"),
                rag_context=rag,
                safe_redaction=safe_redaction,
            )
        except Exception as e:
            logger.error(
                "Parse error segment %d: %s. Raw LLM response: %s",
                sid, str(e), raw[:1000]
            )
            return RiskItem(
                segment_id=sid, text=segment, is_risky=True,
                risk_level=RiskLevel.LOW, risk_category=None,
                risk_description="Ошибка обработки ответа ИИ — требует ручной проверки",
                recommendation="Проверьте фрагмент вручную (ИИ вернул невалидный формат)", 
                rag_context=rag,
            )
    
    def _validate_safe_redaction(self, safe_redaction: str, original_segment: str) -> str | None:
        """Validate that safe_redaction doesn't contain dangerous original text."""
        if not safe_redaction or not safe_redaction.strip():
            return None
        
        safe_redaction = safe_redaction.strip()
        original_lower = original_segment.lower()
        safe_lower = safe_redaction.lower()
        
        DANGEROUS_PHRASES = [
            "штраф",
            "неустойк",
            "односторонн",
            "без компенсац",
            "без объяснен",
            "без причин",
            "любой момент",
            "немедленн",
            "по усмотрению"
        ]
        
        # Check if safe_redaction starts with dangerous phrase
        for phrase in DANGEROUS_PHRASES:
            if safe_lower.startswith(phrase):
                logger.warning(f"safe_redaction starts with dangerous phrase: {phrase}, rejecting")
                return None
        
        # Check for high overlap with SequenceMatcher instead of sets
        similarity = SequenceMatcher(None, safe_lower, original_lower).ratio()
        if similarity > 0.85:
            logger.warning(f"safe_redaction has >85% similarity with original (score: {similarity:.2f}), rejecting")
            return None
        
        return safe_redaction

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
            base_url = os.getenv("OLLAMA_URL", "http://ollama:11434")
            resp = requests.get(f"{base_url}/api/tags", timeout=10)
            models = [m["name"] for m in resp.json().get("models", [])]
            model_base = MODEL_NAME.split(":")[0]
            return {
                "ollama": "running",
                "model": MODEL_NAME,
                "model_available": any(MODEL_NAME == m or model_base in m for m in models),
                "all_models": models,
                "model_config": {
                    "max_segment_chars": MAX_SEGMENT_CHARS,
                    "max_rag_chars": MAX_RAG_CONTEXT_CHARS,
                    "max_rag_norms": MAX_RAG_NORMS,
                    "request_timeout": REQUEST_TIMEOUT_SEC,
                    "heartbeat_timeout": HEARTBEAT_TIMEOUT_SEC,
                },
                "rag": self.rag.get_stats(),
            }
        except Exception as e:
            logger.warning(f"Ollama status check failed: {e}")
            return {
                "ollama": "not running",
                "model": MODEL_NAME,
                "model_available": False,
                "rag": self.rag.get_stats(),
            }
