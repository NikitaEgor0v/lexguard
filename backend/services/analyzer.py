import json
import re
import requests
import logging
import time
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from config.model_registry import get_model_config
from models.schemas import (
    AnalysisResponse, AnalysisSummary, RiskItem, RiskLevel, RiskCategory
)
from repositories.analysis_repository import AnalysisRepository
from services.executive_summary import build_executive_summary
from services.rag import RAGService

logger = logging.getLogger(__name__)

# Setup dedicated logger for raw LLM responses (debugging JSON parse issues)
llm_raw_logger = logging.getLogger("llm_raw")
llm_raw_logger.setLevel(logging.DEBUG)
if not llm_raw_logger.handlers:
    raw_handler = logging.FileHandler("llm_raw.log", encoding="utf-8")
    raw_handler.setFormatter(logging.Formatter("%(asctime)s [SEG %(message)s]"))
    llm_raw_logger.addHandler(raw_handler)

OLLAMA_URL = "http://ollama:11434/api/generate"
MODEL_NAME = os.getenv("LLM_MODEL", "gemma2:2b")
MODEL_CONFIG = get_model_config(MODEL_NAME)
REQUEST_TIMEOUT_SEC = 180
MAX_LLM_RETRIES = 2
# Heartbeat timeout must exceed REQUEST_TIMEOUT_SEC to avoid false "dead" reports
# when Ollama is processing a complex segment.
HEARTBEAT_TIMEOUT_SEC = 300
HEARTBEAT_TTL_SEC = 3600
MAX_CLASSIFY_PREVIEW_CHARS = 800
# Number of parallel LLM workers. Must match Ollama's OLLAMA_NUM_PARALLEL setting.
# Too high a value will OOM the GPU/RAM; 3 is a safe default for 8-16 GB VRAM.
LLM_MAX_WORKERS = int(os.getenv("LLM_MAX_WORKERS", "3"))
# Maximum segments in one processing batch.  After each batch the results are
# saved to PostgreSQL so the frontend can start rendering them immediately.
BATCH_SIZE = int(os.getenv("ANALYSIS_BATCH_SIZE", "20"))
# Hard ceiling on segments accepted for analysis (0 = unlimited).
MAX_SEGMENTS_PER_DOCUMENT = int(os.getenv("MAX_SEGMENTS_PER_DOCUMENT", "500"))
CONTRACT_TYPE_LABELS = frozenset({
    "услуги", "подряд", "поставка", "аренда", "трудовой",
    "лицензионный", "нда", "агентский", "иной",
})

CONTRACT_CLASSIFY_PROMPT = """Это выдержки из начала и середины документа. Определи тип договора по фрагментам. Ответь ОДНИМ словом из списка, без пояснений и пунктуации:
услуги, подряд, поставка, аренда, трудовой, лицензионный, нда, агентский, иной

Текст:
"""

# ── Compact system prompt for small models (gemma2:2b, <8B params) ──
SYSTEM_PROMPT_COMPACT = """Ты — юридический анализатор для IT-контрактов. Верни ТОЛЬКО JSON.
{"is_risky":bool,"risk_level":"high"|"medium"|"low"|"none","risk_category":"финансовый"|"правовой"|"операционный"|"репутационный"|"интеллектуальный"|null,"risk_description":string|null,"recommendation":string|null,"safe_redaction":string|null}

Уровни риска:
- high: неустойка/штраф без лимита; утрата прав на ПО без компенсации; расторжение без выплат невиновному; неограниченная ответственность; одностороннее изменение цены без формулы; подсудность в пользу одной стороны.
- medium: сроки без критериев; неопределённый объём обязательств; несоразмерные санкции; одностороннее изменение условий; ссылка на приложение без текста; отсутствие претензионного порядка.
- low: мелкие огрехи формулировки без денежного риска.
- none: нейтральный, сбалансированный текст.

КРИТИЧЕСКОЕ ПРАВИЛО — АНТИ-КОНТАМИНАЦИЯ:
- risk_description ДОЛЖЕН описывать риск из ТЕКСТА ФРАГМЕНТА, а НЕ из справочных норм.
- ЗАПРЕЩЕНО копировать risk_description из RAG-контекста, если этот риск НЕ присутствует в тексте фрагмента.
- Пример ошибки: RAG содержит "расторжение без оплаты", но текст про "полную ответственность" — НЕ пиши про расторжение!
- Если в тексте фрагмента НЕТ ключевых слов риска — верни is_risky: false.
- Если текст описывает НОРМАЛЬНОЕ условие (например, "оплата за выполненную работу") — верни is_risky: false.

safe_redaction (ТОЛЬКО для high/medium):
- Верни ТОЛЬКО ФИНАЛЬНЫЙ безопасный текст пункта.
- НЕ начинай с опасной формулировки. НЕ копируй оригинал в начало.
- Результат — готовый текст для вставки в договор.
- Для low/none — null.

Важно: при сомнении между high и medium — ставь high. Не выдумывай риски."""

# ── Full system prompt for large models (gemma3:12b+) ──
SYSTEM_PROMPT_FULL = """Ты — система анализа юридических договоров для IT-компании.
Проанализируй фрагмент договора и верни ТОЛЬКО валидный JSON без пояснений и markdown.

Структура ответа:
{
  "is_risky": true или false,
  "risk_level": "high" или "medium" или "low" или "none",
  "risk_category": "финансовый" или "правовой" или "операционный" или "репутационный" или "интеллектуальный" или null,
  "risk_description": "краткое описание риска" или null,
  "recommendation": "конкретная рекомендация по исправлению" или null,
  "safe_redaction": "НОВЫЙ текст пункта, заменяющий опасную формулировку" или null
}

═══ КРИТИЧЕСКОЕ ПРАВИЛО: АНТИ-КОНТАМИНАЦИЯ ═══
risk_description ДОЛЖЕН описывать риск из ТЕКСТА ФРАГМЕНТА, а НЕ из справочных норм.
- ЗАПРЕЩЕНО копировать risk_description из RAG-контекста, если этот риск НЕ присутствует в тексте.
- Пример ошибки: RAG содержит "расторжение без оплаты", но текст про "полную ответственность" — НЕ пиши про расторжение!
- Пример ошибки: текст "Заказчик оплачивает фактически выполненный объём работ" — это БЕЗОПАСНО, не риск.
- Если в тексте фрагмента НЕТ ключевых слов риска — верни is_risky: false.
- Если текст описывает НОРМАЛЬНОЕ условие (оплата за выполненное, возврат аванса за невыполненное) — верни is_risky: false.

Правила уровня риска:
- high: применяй, если В ТЕКСТЕ ФРАГМЕНТА есть хотя бы одно из:
  * штраф, неустойка или иная денежная санкция без ограничения суммы или без верхнего предела
  * утрата прав на программное обеспечение или иные результаты работ без компенсации
  * расторжение или прекращение без выплат контрагенту при отсутствии виновных действий
  * неограниченная ответственность или отсутствие пределов ответственности ("полная ответственность", "без ограничения суммой")
  * одностороннее изменение цены или объёма работ без формулы и без согласия другой стороны
  * полная передача исключительных прав без отдельного вознаграждения
  * подсудность только по месту нахождения одной стороны
- medium: применяй при существенной неопределённости или дисбалансе, не доходящем до high:
  * сроки без измеримых критериев или без привязки к событиям
  * обязанности сформулированы так, что объём или критерий исполнения нельзя установить из текста
  * санкции заведомо несоразмерны предмету обязательства в пользу одной стороны
  * одна сторона вправе менять существенные условия в одностороннем порядке
  * ссылки на приложения/документы, текст которых не представлен
  * отсутствие обязательного претензионного порядка
- low: незначительные огрехи формулировки или избыточные формальные требования, не создающие прямого денежного риска.
- none: формулировка нейтральна, сбалансирована и не содержит перечисленных признаков.

═══ ПРАВИЛА ДЛЯ safe_redaction ═══
Для high/medium рисков — предложи ЗАМЕНУ:
- Верни ТОЛЬКО ФИНАЛЬНЫЙ безопасный текст пункта.
- НЕ начинай с опасной формулировки. НЕ копируй оригинал в начало.
- Текст должен быть готов для вставки в договор вместо исходного пункта.
- Для low/none — верни null.

Дополнительные правила:
- Если между high и medium нет однозначности — выбирай high.
- Не выдумывай риски, которых нет в тексте фрагмента.
- Если фрагмент обрезан или ссылается на условия вне контекста — отметь как medium."""


def _get_system_prompt() -> str:
    """Select system prompt variant based on model capacity."""
    if MODEL_CONFIG.use_compact_prompt:
        return SYSTEM_PROMPT_COMPACT
    return SYSTEM_PROMPT_FULL


class AnalyzerService:
    def __init__(self):
        self.rag = RAGService()

    @staticmethod
    def _update_heartbeat(r, analysis_id: str):
        """Write current timestamp to heartbeat:{analysis_id} in Redis."""
        if r is None:
            return
        try:
            r.setex(f"heartbeat:{analysis_id}", HEARTBEAT_TTL_SEC, str(int(time.time())))
        except Exception:
            pass

    # ── helpers to split segment list into batches ──

    @staticmethod
    def _make_batches(segments: list[str], batch_size: int) -> list[list[tuple[int, str]]]:
        """Split segments into batches of ``batch_size``.

        Returns a list of batches, where each batch is a list of
        ``(global_index, segment_text)`` tuples so we can track segment_id.
        """
        batches: list[list[tuple[int, str]]] = []
        for start in range(0, len(segments), batch_size):
            batch = [
                (i, segments[i])
                for i in range(start, min(start + batch_size, len(segments)))
            ]
            batches.append(batch)
        return batches

    def analyze(
        self,
        segments: list[str],
        analysis_id: str,
        filename: str = "document",
        db: Session | None = None,
        user_id: UUID | None = None,
    ) -> AnalysisResponse:
        import redis as _redis

        redis_url = os.getenv("REDIS_URL", "redis://lexguard_redis:6379/0")
        try:
            r = _redis.from_url(redis_url)
        except Exception as e:
            logger.warning(f"No redis connection for progress: {e}")
            r = None

        # Initial heartbeat — marks the start of analysis
        self._update_heartbeat(r, analysis_id)

        contract_type = self._classify_contract_type(segments)
        total = len(segments)

        # Atomic counter key for thread-safe progress tracking.
        # Threads call INCR on this key; the readable progress:{analysis_id}
        # is updated from the counter after each increment.
        progress_counter_key = f"progress_counter:{analysis_id}"
        if r is not None:
            try:
                r.set(progress_counter_key, 0, ex=3600)
                r.setex(f"progress:{analysis_id}", 3600, f"0/{total}")
            except Exception:
                pass

        # ── Batch processing ──
        # Split into batches of BATCH_SIZE.  Each batch is analysed in
        # parallel via ThreadPool and then *immediately* saved to DB so the
        # frontend can render partial results.
        batches = self._make_batches(segments, BATCH_SIZE)
        all_risks: list[RiskItem] = [None] * total  # pre-allocate to maintain order

        workers = min(LLM_MAX_WORKERS, total)
        logger.info(
            "Пакетный анализ: %d сегментов, %d пакетов по %d, %d потоков (LLM_MAX_WORKERS=%d)",
            total, len(batches), BATCH_SIZE, workers, LLM_MAX_WORKERS,
        )

        for batch_idx, batch in enumerate(batches):
            logger.info("── Пакет %d/%d (сегменты %d-%d) ──",
                        batch_idx + 1, len(batches),
                        batch[0][0] + 1, batch[-1][0] + 1)

            batch_risks: list[RiskItem] = [None] * len(batch)

            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {
                    pool.submit(
                        self._analyze_single_segment,
                        segment=seg_text,
                        segment_index=seg_idx,
                        total=total,
                        contract_type=contract_type,
                        user_id=user_id,
                        redis_conn=r,
                        analysis_id=analysis_id,
                        progress_counter_key=progress_counter_key,
                    ): local_pos
                    for local_pos, (seg_idx, seg_text) in enumerate(batch)
                }

                for future in as_completed(futures):
                    local_pos = futures[future]
                    seg_idx = batch[local_pos][0]
                    seg_text = batch[local_pos][1]
                    try:
                        risk_item = future.result()
                        batch_risks[local_pos] = risk_item
                        all_risks[seg_idx] = risk_item
                    except Exception as exc:
                        logger.error("Segment %d raised exception: %s", seg_idx + 1, exc)
                        fallback = RiskItem(
                            segment_id=seg_idx + 1,
                            text=seg_text,
                            is_risky=None,  # Changed from True to avoid false positives
                            risk_level=RiskLevel.NONE,
                            risk_category=None,
                            risk_description="Ошибка при параллельной обработке — требует проверки",
                            recommendation="Проверьте вручную",
                            rag_context=None,
                            safe_redaction=None,
                        )
                        batch_risks[local_pos] = fallback
                        all_risks[seg_idx] = fallback

            # ── Incremental save: persist this batch to DB immediately ──
            if db is not None:
                try:
                    AnalysisRepository.save_batch(db, analysis_id, batch_risks)
                except Exception as e:
                    logger.error("Failed to save batch %d to DB: %s", batch_idx + 1, e)

        # Final progress update
        if r is not None:
            try:
                r.setex(f"progress:{analysis_id}", 3600, f"{total}/{total}")
                r.delete(progress_counter_key)
            except Exception:
                pass

        summary = self._summary(all_risks)
        executive_summary = build_executive_summary(summary, all_risks)
        response = AnalysisResponse(
            analysis_id=analysis_id, filename=filename,
            status="completed",
            summary=summary,
            executive_summary=executive_summary,
            risks=all_risks,
        )

        # Finalize: update summary stats and set status to completed
        if db is not None:
            try:
                AnalysisRepository.finalize_result(db, analysis_id, summary)
            except Exception as e:
                logger.error("Failed to finalize analysis in DB: %s", e)

        return response

    def _analyze_single_segment(
        self,
        segment: str,
        segment_index: int,
        total: int,
        contract_type: str,
        user_id: UUID | None,
        redis_conn,
        analysis_id: str,
        progress_counter_key: str,
    ) -> RiskItem:
        """Process one segment: 2-step pipeline (classifier → analyzer). Thread-safe."""
        segment_id = segment_index + 1
        logger.info("Анализ %d/%d", segment_id, total)

        # Heartbeat before LLM calls
        self._update_heartbeat(redis_conn, analysis_id)

        # ── STEP 1: Classifier (YES/NO only, no RAG, temperature=0.0) ──
        is_risky_likely = self._classify_risk(segment)
        
        if not is_risky_likely:
            # Segment is neutral — skip full analysis
            return RiskItem(
                segment_id=segment_id, text=segment,
                is_risky=False, risk_level=RiskLevel.NONE,
                risk_category=None, risk_description=None,
                recommendation=None, rag_context=None, safe_redaction=None,
            )

        # ── STEP 2: Full analyzer (with RAG context, format="json") ──
        rag_context = self.rag.search(
            segment,
            contract_type=contract_type,
            user_id=user_id,
            top_k=MODEL_CONFIG.max_rag_norms,
            max_chars=MODEL_CONFIG.max_rag_chars,
        )
        raw = self._call_llm_analyzer(segment, rag_context, segment_id)

        # Heartbeat after LLM calls
        self._update_heartbeat(redis_conn, analysis_id)

        # Atomic progress update
        if redis_conn is not None:
            try:
                done = redis_conn.incr(progress_counter_key)
                redis_conn.setex(f"progress:{analysis_id}", 3600, f"{done}/{total}")
            except Exception:
                pass

        return self._parse(raw, segment, segment_id, rag_context)

    def _classify_risk(self, segment: str) -> bool:
        """Step 1: Binary classifier (YES/NO). No RAG, temperature=0.0.
        
        Returns True if segment likely contains risk, False otherwise.
        """
        classifier_prompt = """Содержит ли этот фрагмент договора юридический риск для IT-компании?

Риски:
- Штраф/неустойка без лимита или несоразмерная
- Неограниченная ответственность ("полная ответственность", "без ограничения суммой", "включая упущенную выгоду")
- Утрата прав на ПО без компенсации
- Одностороннее изменение цены/условий
- Расторжение без оплаты выполненного
- Подсудность только по месту одной стороны
- Отсутствие претензионного порядка

Ответь ТОЛЬКО "YES" или "NO", без пояснений.

Фрагмент:
"""
        payload = {
            "model": MODEL_NAME,
            "prompt": f"{classifier_prompt}{segment}",
            "stream": False,
            "options": {
                "temperature": 0.0,
                "num_predict": 5,
                "num_ctx": 2048,
            },
        }

        try:
            resp = requests.post(OLLAMA_URL, json=payload, timeout=REQUEST_TIMEOUT_SEC)
            if resp.status_code >= 400:
                logger.warning("Classifier HTTP %s — defaulting to YES", resp.status_code)
                return True
            answer = resp.json().get("response", "").strip().upper()
            # Log classifier decision
            logger.debug("Classifier answer: %s", answer)
            return "YES" in answer
        except Exception as e:
            logger.warning("Classifier failed: %s — defaulting to YES", e)
            return True  # On failure, err on the side of caution

    def _call_llm_analyzer(self, segment: str, rag_context: str | None, segment_id: int) -> str:
        """Step 2: Full analyzer with RAG context. Uses format='json' for reliable parsing.
        
        Preprocessing now handles truncation — no need to cut segment here.
        """
        system_prompt = _get_system_prompt()
        last_error = "Неизвестная ошибка"

        for attempt in range(MAX_LLM_RETRIES + 1):
            use_rag = bool(rag_context) and attempt == 0
            if use_rag:
                user_prompt = (
                    f"Фрагмент договора:\n{segment}\n\n"
                    f"Справочные нормы:\n{rag_context}"
                )
            else:
                user_prompt = f"Фрагмент договора:\n{segment}"

            payload = {
                "model": MODEL_NAME,
                "prompt": f"{system_prompt}\n\n{user_prompt}",
                "stream": False,
                "format": "json",  # Ollama JSON mode for reliable output
                "options": {
                    "temperature": 0.1,
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
                
                # Log raw LLM response for debugging
                llm_raw_logger.debug(f"{segment_id}] {answer[:500]}")
                
                return answer
            except requests.exceptions.ConnectionError:
                raise RuntimeError("Ollama недоступен")
            except requests.exceptions.Timeout:
                last_error = "Таймаут ответа Ollama"
            except Exception as e:
                last_error = str(e)
                logger.warning(f"LLM analyzer attempt {attempt + 1} failed: {e}")

            if attempt < MAX_LLM_RETRIES:
                time.sleep(1 + attempt)

        raise RuntimeError(f"Ошибка генерации в Ollama: {last_error}")

    def _classify_contract_type(self, segments: list[str]) -> str:
        if not segments:
            return "иной"
        from services.preprocessor import PreprocessorService
        full_text = "\n\n".join(segments)
        preview = PreprocessorService.extract_smart_classification_preview(full_text)
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
        """Parse LLM response with robust error handling.
        
        Uses regex to extract JSON from conversational text.
        Returns is_risky=None (not True) on parse failure to avoid false positives.
        """
        try:
            # Step 1: Extract JSON using regex (handles conversational text around JSON)
            json_match = re.search(r'\{.*\}', raw, re.DOTALL)
            if not json_match:
                raise ValueError("No JSON object found in LLM response")
            
            clean = json_match.group(0)
            
            # Step 2: Try parsing
            try:
                data = json.loads(clean)
            except json.JSONDecodeError as e:
                # Step 3: Try fixing trailing comma (common LLM error)
                # Example: {"key": "value",} → {"key": "value"}
                clean_fixed = re.sub(r',(\s*[}\]])', r'\1', clean)
                data = json.loads(clean_fixed)  # Raises if still invalid

            is_risky = bool(data.get("is_risky", False))
            risk_level = RiskLevel(data.get("risk_level", "none"))
            risk_description = data.get("risk_description")
            safe_redaction = data.get("safe_redaction")

            # Post-processing: validate that risk_description relates to segment text
            is_risky, risk_level, risk_description = self._validate_risk_relevance(
                is_risky, risk_level, risk_description, segment, rag,
            )

            # Post-processing validation for safe_redaction
            safe_redaction = self._validate_safe_redaction(
                safe_redaction, segment, is_risky, risk_level,
            )

            return RiskItem(
                segment_id=sid, text=segment,
                is_risky=is_risky,
                risk_level=risk_level,
                risk_category=RiskCategory(data["risk_category"]) if data.get("risk_category") else None,
                risk_description=risk_description,
                recommendation=data.get("recommendation"),
                rag_context=rag,
                safe_redaction=safe_redaction,
            )
        except Exception as e:
            logger.warning(f"Parse error segment {sid}: {e} | Raw: {raw[:200]}")
            # Return is_risky=None (not True!) to avoid false positives
            # Frontend should treat None as "needs manual review"
            return RiskItem(
                segment_id=sid, text=segment,
                is_risky=None,  # Changed from True to None
                risk_level=RiskLevel.NONE,
                risk_category=None,
                risk_description="Не удалось классифицировать — требует проверки",
                recommendation="Проверьте вручную",
                rag_context=rag,
                safe_redaction=None,
            )

    # Keywords that indicate specific risks — used for anti-contamination validation
    RISK_KEYWORDS = {
        "расторжение": ["расторж", "прекращ", "прекратить"],
        "неустойка": ["неустойк", "штраф", "пени", "просрочк"],
        "ответственность": ["ответственност", "убыт", "возмещ", "компенсац"],
        "права": ["исключительн", "прав", "лицензи"],
        "подсудность": ["суд", "подсудност", "юрисдикц", "претензионн"],
    }
    
    # Safe patterns that should NOT be marked as risky
    SAFE_PATTERNS = [
        "оплачивает фактически выполненный",
        "возвращает аванс в части",
        "оплата за выполненные работы",
        "в соответствии с техническим заданием",
        "по одному для каждой из сторон",
        "равную юридическую силу",
        "после полной оплаты",  # standard IP transfer condition
        "после подписания акта приёмки",  # standard delivery condition
    ]

    @classmethod
    def _validate_risk_relevance(
        cls,
        is_risky: bool,
        risk_level: RiskLevel,
        risk_description: str | None,
        segment: str,
        rag_context: str | None,
    ) -> tuple[bool, RiskLevel, str | None]:
        """Post-process to validate that risk_description relates to segment text.
        
        If segment contains safe patterns or no risk keywords at all,
        downgrade to is_risky=False.
        """
        if not is_risky or not risk_description:
            return is_risky, risk_level, risk_description
        
        segment_lower = segment.lower()
        
        # Check if segment contains safe pattern — if so, it's NOT risky
        for safe_pattern in cls.SAFE_PATTERNS:
            if safe_pattern in segment_lower:
                logger.warning(
                    "Segment contains safe pattern '%s' — downgrading to non-risky",
                    safe_pattern,
                )
                return False, RiskLevel.NONE, None
        
        # Check if segment contains ANY risk keywords
        # If no risk keywords found in segment, it's likely a false positive from RAG
        segment_has_risk_keywords = False
        for risk_type, keywords in cls.RISK_KEYWORDS.items():
            if any(kw in segment_lower for kw in keywords):
                segment_has_risk_keywords = True
                break
        
        if not segment_has_risk_keywords:
            logger.warning(
                "Segment lacks any risk keywords — downgrading to non-risky"
            )
            return False, RiskLevel.NONE, None
        
        return is_risky, risk_level, risk_description

    # Dangerous phrases that should not appear in safe_redaction
    DANGEROUS_PHRASES = [
        "без оплаты",
        "без выплат",
        "без компенсации",
        "без ограничения",
        "неограниченную ответственность",
        "полную ответственность",
        "включая упущенную выгоду",
        "в одностороннем порядке",
        "по своему усмотрению",
    ]

    @classmethod
    def _validate_safe_redaction(
        cls,
        safe_redaction: str | None,
        original_segment: str,
        is_risky: bool | None,
        risk_level: RiskLevel,
    ) -> str | None:
        """Post-process safe_redaction to catch common LLM failure modes.

        Returns None if the redaction is invalid:
        - Provided for non-risky or low-risk segments
        - Identical or near-identical to the original (model copied instead of rewriting)
        - High sequence similarity (>85%) detected via SequenceMatcher
        - Starts with dangerous phrase from original (model reproduced risk at beginning)
        """
        if not safe_redaction:
            return None

        # safe_redaction should only exist for high/medium risks
        if is_risky is False or risk_level in (RiskLevel.LOW, RiskLevel.NONE):
            return None

        # Normalize whitespace for comparison
        redaction_normalized = " ".join(safe_redaction.split()).strip().lower()
        original_normalized = " ".join(original_segment.split()).strip().lower()

        # If the model just copied the original text verbatim — reject
        if redaction_normalized == original_normalized:
            logger.warning(
                "safe_redaction is identical to original segment — discarding"
            )
            return None

        # Use SequenceMatcher for accurate similarity — catches partial copies,
        # truncations, and minor rephrasing that preserves the dangerous text.
        from difflib import SequenceMatcher
        similarity = SequenceMatcher(
            None, redaction_normalized, original_normalized
        ).ratio()

        if similarity > 0.85:
            logger.warning(
                "safe_redaction too similar to original (%.0f%%) — discarding",
                similarity * 100,
            )
            return None

        # Check if safe_redaction starts with dangerous phrase from original
        # This catches cases like: "Заказчик вправе расторгнуть без оплаты... [safe text]"
        first_sentence = redaction_normalized.split(".")[0] if "." in redaction_normalized else redaction_normalized[:100]
        
        for phrase in cls.DANGEROUS_PHRASES:
            if phrase in first_sentence and phrase in original_normalized:
                logger.warning(
                    "safe_redaction starts with dangerous phrase '%s' — discarding",
                    phrase,
                )
                return None

        return safe_redaction

    def _summary(self, risks: list[RiskItem]) -> AnalysisSummary:
        # is_risky can be None (parse failure) — treat as risky for stats
        risky = [r for r in risks if r.is_risky is True or r.is_risky is None]
        high = sum(1 for r in risks if r.risk_level == RiskLevel.HIGH)
        medium = sum(1 for r in risks if r.risk_level == RiskLevel.MEDIUM)
        low = sum(1 for r in risks if r.risk_level == RiskLevel.LOW)
        # Используем "эффективное количество сегментов" для знаменателя (не более 40),
        # чтобы риск не размывался в очень длинных документах.
        effective_total = max(min(len(risks), 40), 1)
        score = min(1.0, round((high * 1.0 + medium * 0.4 + low * 0.1) / effective_total, 2))
        
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
