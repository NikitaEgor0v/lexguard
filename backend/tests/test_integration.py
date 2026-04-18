"""
╔══════════════════════════════════════════════════════════════════════╗
║  ТЕСТ-МОДУЛЬ 3: Integration Tests — E2E цепочки                    ║
║                                                                      ║
║  Цель: Тестировать взаимодействие между компонентами:               ║
║        Frontend polling → API → Celery → Analyzer → Qdrant → LLM   ║
║        ChatService → ChatContextBuilder → LLM → Repository          ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import json
import os
import sys
import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.analyzer import AnalyzerService
from services.chat_context_builder import ChatContextBuilder
from services.chat_service import ChatService
from services.preprocessor import PreprocessorService
from config.model_registry import get_model_config
from models.schemas import RiskLevel, AnalysisResponse


# ═══════════════════════════════════════════════════════════════
# СЦЕНАРИЙ 3.1: Полная цепочка analyze → _parse → summary
# ═══════════════════════════════════════════════════════════════

class TestFullAnalysisPipeline:
    """
    Интеграционный тест полного пайплайна:
    segments → classify → (RAG + LLM) * N → parse → summary → save
    """

    @patch("services.analyzer.requests.post")
    def test_happy_path_3_segments(self, mock_post):
        """
        Минимальный happy path: 3 сегмента, LLM возвращает валидный JSON.
        Все компоненты работают в связке.
        """
        responses = [
            # Первый вызов: classify_contract_type
            MagicMock(status_code=200, json=lambda: {"response": "услуги"}),
            # Три сегмента:
            MagicMock(status_code=200, json=lambda: {"response": json.dumps({
                "is_risky": True, "risk_level": "high",
                "risk_category": "финансовый",
                "risk_description": "Штраф без лимита",
                "recommendation": "Установить cap"
            })}),
            MagicMock(status_code=200, json=lambda: {"response": json.dumps({
                "is_risky": False, "risk_level": "none",
                "risk_category": None, "risk_description": None,
                "recommendation": None
            })}),
            MagicMock(status_code=200, json=lambda: {"response": json.dumps({
                "is_risky": True, "risk_level": "medium",
                "risk_category": "операционный",
                "risk_description": "Нечёткие сроки",
                "recommendation": "Указать конкретные даты"
            })}),
        ]
        mock_post.side_effect = responses

        analyzer = AnalyzerService.__new__(AnalyzerService)
        analyzer.rag = MagicMock()
        analyzer.rag.search.return_value = "Тестовый RAG контекст"

        with patch("redis.from_url", side_effect=Exception("no redis in test")):
            result = analyzer.analyze(
                segments=["Фрагмент 1", "Фрагмент 2", "Фрагмент 3"],
                analysis_id="test-123",
                filename="test.pdf",
                db=None,
                user_id=None,
            )

        assert result.status == "completed"
        assert result.analysis_id == "test-123"
        assert len(result.risks) == 3
        assert result.summary.total_segments == 3
        assert result.summary.high_risk_count == 1
        assert result.summary.medium_risk_count == 1
        assert result.summary.risky_segments == 2
        assert result.summary.risk_score > 0

    @patch("services.analyzer.requests.post")
    def test_mixed_valid_and_invalid_llm_responses(self, mock_post):
        """
        СЦЕНАРИЙ СМЕШАННЫХ ОТВЕТОВ:
        - Сегмент 1: LLM возвращает валидный JSON
        - Сегмент 2: LLM возвращает мусор → fallback
        - Сегмент 3: LLM возвращает markdown-wrapped JSON
        
        Все 3 должны быть обработаны без падения.
        """
        responses = [
            MagicMock(status_code=200, json=lambda: {"response": "иной"}),
            # Сегмент 1: ок
            MagicMock(status_code=200, json=lambda: {"response": '{"is_risky": false, "risk_level": "none", "risk_category": null, "risk_description": null, "recommendation": null}'}),
            # Сегмент 2: мусор
            MagicMock(status_code=200, json=lambda: {"response": "Этот фрагмент безопасен, рисков нет."}),
            # Сегмент 3: markdown
            MagicMock(status_code=200, json=lambda: {"response": '```json\n{"is_risky": true, "risk_level": "high", "risk_category": "финансовый", "risk_description": "тест", "recommendation": "тест"}\n```'}),
        ]
        mock_post.side_effect = responses

        analyzer = AnalyzerService.__new__(AnalyzerService)
        analyzer.rag = MagicMock()
        analyzer.rag.search.return_value = None

        with patch("redis.from_url", side_effect=Exception("skip")):
            result = analyzer.analyze(
                ["Сегмент 1", "Сегмент 2", "Сегмент 3"],
                "test-mixed", "test.pdf",
            )

        assert len(result.risks) == 3
        # Сегмент 2 (мусор) → fallback → is_risky=True, level=low
        assert result.risks[1].is_risky is True
        assert result.risks[1].risk_level == RiskLevel.LOW


# ═══════════════════════════════════════════════════════════════
# СЦЕНАРИЙ 3.2: Chat Service — контекстное окно при длинной истории
# ═══════════════════════════════════════════════════════════════

class TestChatContextIntegration:
    """
    Тестируем взаимодействие ChatService ↔ ChatContextBuilder ↔ LLM
    при нарастающей истории диалога.
    """

    def test_context_builder_with_growing_history(self, sample_analysis_response, sample_chat_history):
        """
        Каждое новое сообщение увеличивает историю. После 50 сообщений
        промпт может взорвать контекстное окно gemma2:2b.
        """
        config = get_model_config("gemma2:2b")
        builder = ChatContextBuilder(config)
        analysis = sample_analysis_response(num_risks=10)

        sizes = []
        for msg_count in [1, 5, 10, 20, 50]:
            history = sample_chat_history(count=msg_count)
            prompt = builder.build(analysis, history, "Как исправить риск #1?")
            sizes.append((msg_count, len(prompt), len(prompt) // 4))

        print("\n[АУДИТ] Рост промпта с историей:")
        for msgs, chars, tokens in sizes:
            status = "⚠️ DANGER" if tokens > config.context_window else "✅ OK"
            print(f"  {msgs:3d} сообщений → {chars:6d} симв. ≈ {tokens:5d} токенов {status}")

        # Проверяем, что при 50 сообщениях промпт не превысил лимит
        _, _, last_tokens = sizes[-1]
        if last_tokens > config.context_window:
            pytest.fail(
                f"УЯЗВИМОСТЬ: при 50 сообщениях в истории промпт = {last_tokens} токенов, "
                f"но context_window = {config.context_window}. ChatService не обрезает историю!"
            )

    def test_risks_text_not_truncated(self, sample_analysis_response):
        """
        BUG HUNT: _build_risks_text() НЕ обрезается вообще.
        При 100+ рисках это может перевесить контекст.
        """
        config = get_model_config("gemma2:2b")
        builder = ChatContextBuilder(config)
        analysis = sample_analysis_response(num_risks=100)

        risks_text = builder._build_risks_text(analysis)
        estimated_tokens = len(risks_text) // 4

        print(f"\n[АУДИТ] risks_text при 100 рисках: {len(risks_text)} символов ≈ {estimated_tokens} токенов")

        if estimated_tokens > config.safe_context:
            print(f"  ⚠️ НАЙДЕН БАГ: risks_text ({estimated_tokens} токенов) > safe_context ({config.safe_context})")


# ═══════════════════════════════════════════════════════════════
# СЦЕНАРИЙ 3.3: Preprocessor → Analyzer Integration
# ═══════════════════════════════════════════════════════════════

class TestPreprocessorAnalyzerIntegration:
    """
    Тестируем, что сегментатор производит чанки, которые
    не ломают Analyzer.
    """

    def test_all_segments_within_max_chars(self):
        """
        Каждый сегмент из PreprocessorService должен быть ≤ MAX_SEGMENT_LENGTH.
        Иначе _call_llm обрежет текст, потеряв конец фрагмента.
        """
        preprocessor = PreprocessorService()

        text = "\n\n".join([
            f"{i}. " + "Тестовый текст для проверки сегментации. " * 50
            for i in range(1, 20)
        ])

        segments = preprocessor._segment(text)

        for i, seg in enumerate(segments):
            assert len(seg) <= preprocessor.MAX_SEGMENT_LENGTH + 50, \
                f"Сегмент {i+1} ({len(seg)} символов) > MAX ({preprocessor.MAX_SEGMENT_LENGTH})!"

    @patch("services.analyzer.requests.post")
    def test_empty_segments_list_handled(self, mock_post):
        """
        BUG HUNT: Если preprocessor вернул пустой список сегментов,
        analyze() не должен падать.
        """
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"response": "иной"}
        )

        analyzer = AnalyzerService.__new__(AnalyzerService)
        analyzer.rag = MagicMock()

        with patch("redis.from_url", side_effect=Exception("skip")):
            result = analyzer.analyze([], "test-empty", "test.pdf")

        assert result.status == "completed"
        assert len(result.risks) == 0
        assert result.summary.total_segments == 0
        assert result.summary.risk_score == 0.0


# ═══════════════════════════════════════════════════════════════
# СЦЕНАРИЙ 3.4: Redis Progress Tracking Integration
# ═══════════════════════════════════════════════════════════════

class TestRedisProgressIntegration:
    """
    Тестируем интеграцию прогресс-трекера через Redis.
    """

    @patch("services.analyzer.requests.post")
    def test_progress_updates_in_redis(self, mock_post):
        """
        Каждый сегмент должен обновлять ключ progress:{analysis_id}
        в Redis с текущим прогрессом.
        """
        responses = [
            MagicMock(status_code=200, json=lambda: {"response": "иной"}),
        ]
        for _ in range(3):
            responses.append(MagicMock(status_code=200, json=lambda: {"response": '{"is_risky": false, "risk_level": "none", "risk_category": null, "risk_description": null, "recommendation": null}'}))
        mock_post.side_effect = responses

        mock_redis_client = MagicMock()

        analyzer = AnalyzerService.__new__(AnalyzerService)
        analyzer.rag = MagicMock()
        analyzer.rag.search.return_value = None

        with patch("redis.from_url", return_value=mock_redis_client):

            analyzer.analyze(
                ["Сегмент 1", "Сегмент 2", "Сегмент 3"],
                "progress-test", "test.pdf",
            )

        # Проверяем вызовы setex: 3 обновления (0/3, 1/3, 2/3) + финальное (3/3)
        setex_calls = mock_redis_client.setex.call_args_list
        assert len(setex_calls) >= 3

        # Последний вызов = 3/3
        last_call_args = setex_calls[-1]
        assert "3/3" in str(last_call_args)


# ═══════════════════════════════════════════════════════════════
# СЦЕНАРИЙ 3.5: Risk Score Calculation Edge Cases
# ═══════════════════════════════════════════════════════════════

class TestRiskScoreCalculation:
    """Тестируем формулу risk_score."""

    def test_score_capped_at_1(self):
        """Даже при 100% high-рисков, score ≤ 1.0."""
        from models.schemas import RiskItem, RiskLevel
        analyzer = AnalyzerService.__new__(AnalyzerService)
        risks = [
            RiskItem(segment_id=i, text="T", is_risky=True, risk_level=RiskLevel.HIGH)
            for i in range(10)
        ]
        summary = analyzer._summary(risks)
        assert summary.risk_score <= 1.0

    def test_score_zero_for_no_risks(self):
        """Нет рисков → score = 0."""
        from models.schemas import RiskItem, RiskLevel
        analyzer = AnalyzerService.__new__(AnalyzerService)
        risks = [
            RiskItem(segment_id=i, text="T", is_risky=False, risk_level=RiskLevel.NONE)
            for i in range(5)
        ]
        summary = analyzer._summary(risks)
        assert summary.risk_score == 0.0

    def test_score_division_by_zero_empty_risks(self):
        """Пустой список рисков → не должно быть ZeroDivisionError."""
        analyzer = AnalyzerService.__new__(AnalyzerService)
        summary = analyzer._summary([])
        assert summary.risk_score == 0.0
        assert summary.total_segments == 0
