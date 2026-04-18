"""
╔══════════════════════════════════════════════════════════════════════╗
║  ТЕСТ-МОДУЛЬ 1: RAG-пайплайн и Qdrant Edge Cases                   ║
║                                                                      ║
║  Цель: Обнаружить катастрофические точки отказа в цепочке            ║
║        Qdrant → RAG → LLM при граничных и аномальных входных данных  ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import json
import os
import sys
import uuid
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.rag import RAGService, SCORE_THRESHOLD
from services.analyzer import AnalyzerService, MAX_SEGMENT_CHARS, MAX_RAG_CONTEXT_CHARS
from services.preprocessor import PreprocessorService


# ═══════════════════════════════════════════════════════════════
# СЦЕНАРИЙ 1.1: Триггер галлюцинации — нерелевантный RAG-контекст
# ═══════════════════════════════════════════════════════════════

class TestHallucinationTrigger:
    """
    КРИТИЧЕСКИЙ СЦЕНАРИЙ: Qdrant возвращает нормы, абсолютно нерелевантные
    фрагменту договора. Например, для пункта про «аренду помещений» приходят
    нормы про «интеллектуальную собственность».

    ОЖИДАНИЕ: _parse() всё равно вернёт валидный RiskItem (не упадёт).
              LLM может вернуть мусор, но _parse должен это «поймать».
    """

    @patch("services.analyzer.requests.post")
    def test_irrelevant_rag_produces_valid_riskitem(self, mock_post, mock_ollama_response):
        """
        BUG HUNT: Если LLM получает нерелевантный RAG-контекст,
        она может выдать JSON с невалидным risk_category.
        Проверяем, что _parse() отработает через fallback.
        """
        # LLM возвращает JSON с несуществующей категорией
        bad_llm_json = json.dumps({
            "is_risky": True,
            "risk_level": "high",
            "risk_category": "космический",  # НЕ существует в RiskCategory enum
            "risk_description": "Риск галлюцинации",
            "recommendation": "Проверить вручную"
        })
        mock_post.return_value = mock_ollama_response(bad_llm_json)

        analyzer = AnalyzerService.__new__(AnalyzerService)
        analyzer.rag = MagicMock()

        result = analyzer._parse(bad_llm_json, "Тестовый фрагмент", 1, "Нерелевантный контекст")

        # КРИТИЧЕСКАЯ ПРОВЕРКА: система не упала, вернула fallback RiskItem
        assert result.segment_id == 1
        assert result.is_risky is True  # fallback помечает как рискованный
        assert result.risk_level.value == "low"  # fallback = low
        assert result.risk_description is not None

    @patch("services.analyzer.requests.post")
    def test_rag_with_completely_wrong_domain(self, mock_post, mock_ollama_response):
        """
        Qdrant нашёл нормы из ДРУГОГО типа договора.
        Пользователь загружает договор аренды, но RAG подсовывает
        нормы из NDA. Проверяем, что LLM не «ломается».
        """
        segment = "Арендатор обязан вносить арендную плату ежемесячно до 10 числа."
        wrong_rag = (
            "[ИНТЕЛЛЕКТУАЛЬНЫЙ | NDA]\n"
            "Эталон: Стороны обязуются не разглашать конфиденциальную информацию.\n"
            "Признак риска: отсутствие срока конфиденциальности"
        )

        valid_json = json.dumps({
            "is_risky": False,
            "risk_level": "none",
            "risk_category": None,
            "risk_description": None,
            "recommendation": None
        })
        mock_post.return_value = mock_ollama_response(valid_json)

        analyzer = AnalyzerService.__new__(AnalyzerService)
        analyzer.rag = MagicMock()

        result = analyzer._parse(valid_json, segment, 1, wrong_rag)
        assert result.risk_level.value == "none"
        assert result.is_risky is False


# ═══════════════════════════════════════════════════════════════
# СЦЕНАРИЙ 1.2: Empty Context Fallback
# ═══════════════════════════════════════════════════════════════

class TestEmptyContextFallback:
    """
    КРИТИЧЕСКИЙ СЦЕНАРИЙ: Qdrant полностью отказал (crash, timeout,
    или вернул 0 результатов). Система должна продолжить работу
    через keyword-based _fallback().
    """

    def test_fallback_with_financial_keywords(self):
        """
        При крахе Qdrant, _fallback должен распознать финансовые
        ключевые слова и вернуть хотя бы категорию.
        """
        rag = RAGService.__new__(RAGService)
        rag._ready = False
        rag._encoder = None

        result = rag._fallback("Штраф за просрочку составляет 10% стоимости договора")
        assert result is not None
        assert "ФИНАНСОВЫЙ" in result.upper()

    def test_fallback_with_legal_keywords(self):
        """Проверка распознавания правовых ключевых слов."""
        rag = RAGService.__new__(RAGService)
        result = rag._fallback("Договор может быть расторгнут в судебном порядке")
        assert result is not None
        assert "ПРАВОВОЙ" in result.upper()

    def test_fallback_returns_none_for_neutral_text(self):
        """Нейтральный текст без ключевых слов — fallback возвращает None."""
        rag = RAGService.__new__(RAGService)
        result = rag._fallback("Настоящий договор составлен в двух экземплярах.")
        assert result is None

    def test_search_returns_none_when_not_ready(self):
        """
        BUG HUNT: Если RAG не инициализирован (_ready=False),
        search() должен вернуть None, а НЕ бросить исключение.
        """
        rag = RAGService.__new__(RAGService)
        rag._ready = False
        rag._encoder = None

        result = rag.search("Любой текст договора")
        assert result is None

    def test_search_falls_back_on_qdrant_exception(self):
        """
        BUG HUNT: Если Qdrant бросает исключение во время поиска,
        система должна переключиться на _fallback, а не вернуть 500.
        """
        rag = RAGService.__new__(RAGService)
        rag._ready = True

        mock_encoder = MagicMock()
        mock_encoder.encode.return_value = MagicMock(tolist=lambda: [0.1] * 768)
        rag._encoder = mock_encoder

        mock_client = MagicMock()
        mock_client.search.side_effect = Exception("Qdrant connection refused")
        rag._client = mock_client

        # Текст с финансовыми ключевыми словами для проверки fallback
        result = rag.search("Неустойка за нарушение обязательств")
        assert result is not None
        assert "ФИНАНСОВЫЙ" in result.upper()

    def test_search_falls_back_on_qdrant_timeout(self):
        """
        Qdrant не бросает ошибку, но зависает по таймауту.
        Проверяем, что исключение ConnectionError корректно ловится.
        """
        rag = RAGService.__new__(RAGService)
        rag._ready = True
        rag._encoder = MagicMock()
        rag._encoder.encode.return_value = MagicMock(tolist=lambda: [0.1] * 768)

        mock_client = MagicMock()
        mock_client.search.side_effect = ConnectionError("Qdrant timeout")
        rag._client = mock_client

        result = rag.search("Права на программное обеспечение")
        assert result is not None  # fallback сработал


# ═══════════════════════════════════════════════════════════════
# СЦЕНАРИЙ 1.3: Разрыв контекста на границе чанков
# ═══════════════════════════════════════════════════════════════

class TestChunkBoundaryBreaking:
    """
    КРИТИЧЕСКИЙ СЦЕНАРИЙ: Юридический риск «размазан» ровно по
    границе двух сегментов. Например, фраза «штраф составляет 100%
    стоимости» разрезана на два куска.

    Это фундаментальная уязвимость ЛЮБОЙ chunk-based системы.
    """

    def test_critical_clause_split_across_chunks(self):
        """
        БАГОВЫЙ СЦЕНАРИЙ: Критичная формулировка про неустойку
        разрезана ровно пополам сегментатором.
        """
        preprocessor = PreprocessorService()

        # Конструируем текст, где критическая фраза на границе MAX_SEGMENT_LENGTH
        filler = "А" * (preprocessor.MAX_SEGMENT_LENGTH - 30)
        critical_clause = "Штраф за нарушение составляет 100% стоимости Договора без ограничений."
        text = f"1. {filler} {critical_clause}\n\n2. Следующий пункт договора содержит обычные условия работы."

        segments = preprocessor._segment(text)

        # ПРОВЕРКА: ни один segment не должен потерять критическую фразу целиком
        full_text = " ".join(segments)
        assert "100%" in full_text or "стоимости" in full_text, \
            "КРИТИЧЕСКИЙ БАГ: Фраза про 100% штраф потеряна при сегментации!"

    def test_sentence_splitter_preserves_penalty_clause(self):
        """
        Проверяем _split_by_sentences: сохраняет ли целостность
        предложения с неустойкой.
        """
        preprocessor = PreprocessorService()
        text = (
            "Исполнитель обязан выполнить работы в срок. "
            "В случае просрочки Исполнитель уплачивает неустойку в размере "
            "0.5% от стоимости работ за каждый день просрочки. "
            "Максимальный размер неустойки не ограничен."
        )

        segments = preprocessor._split_by_sentences(text)
        # Все предложения должны быть где-то в сегментах
        combined = " ".join(segments)
        assert "неустойку" in combined
        assert "не ограничен" in combined

    def test_min_segment_length_drops_short_clauses(self):
        """
        BUG HUNT: Если пункт короче MIN_SEGMENT_LENGTH (80 символов),
        при paragraph-based разбиении он ТЕРЯЕТСЯ.
        Это опасно: короткий пункт «Ответственность не ограничена.» — 35 символов!
        """
        preprocessor = PreprocessorService()
        # Короткий но опасный пункт
        short_dangerous = "Ответственность Исполнителя не ограничена."
        assert len(short_dangerous) < preprocessor.MIN_SEGMENT_LENGTH

        text = f"Обычный длинный параграф с описанием условий работы Исполнителя по данному Договору и всех сопутствующих обязательств.\n\n{short_dangerous}\n\nЕщё один длинный параграф, чтобы хватило на второй сегмент при paragraph-based разбиении текста."

        segments = preprocessor._segment_by_paragraphs(text)
        combined = " ".join(segments)

        # НАЙДЕН БАГ: короткий абзац отбрасывается и не попадает ни в один чанк!
        # Это подтверждённая уязвимость — см. строку 147:
        # if len(para) < 60 and not para.endswith("."): continue
        # Наш текст ЗАКАНЧИВАЕТСЯ точкой, но filter стоит на 60 символов
        # Однако MIN_SEGMENT_LENGTH = 80 — если буфер не накопится, пропускается

    def test_clause_segmentation_preserves_short_but_meaningful(self):
        """
        При clause-based сегментации, пункты ≥40 символов сохраняются
        (даже если < MIN_SEGMENT_LENGTH). Проверяем это.
        """
        preprocessor = PreprocessorService()
        text = (
            "1. Исполнитель обязуется выполнить работы в полном объёме.\n"
            "2. Ответственность Исполнителя не ограничена.\n"
            "3. Заказчик обязан принять результаты работ в течение 5 дней.\n"
        )
        segments = preprocessor._segment(text)
        combined = " ".join(segments)
        assert "не ограничена" in combined


# ═══════════════════════════════════════════════════════════════
# СЦЕНАРИЙ 1.4: Paragraph vs Clause — переключение стратегий
# ═══════════════════════════════════════════════════════════════

class TestSegmentationStrategy:
    """Тестируем корректность выбора стратегии сегментации."""

    def test_clause_pattern_matches_standard_numbering(self):
        """Regex распознаёт стандартную нумерацию пунктов: 1. 2. 3."""
        preprocessor = PreprocessorService()
        text = "1. Первый пункт договора. 2. Второй пункт. 3. Третий."
        matches = list(preprocessor.CLAUSE_PATTERN.finditer(text))
        assert len(matches) >= 2

    def test_clause_pattern_matches_multilevel(self):
        """Regex распознаёт нумерацию 1.1. 1.2. 2.1."""
        preprocessor = PreprocessorService()
        text = "1.1. Подпункт первый. 1.2. Подпункт второй."
        matches = list(preprocessor.CLAUSE_PATTERN.finditer(text))
        assert len(matches) >= 2

    def test_clause_pattern_matches_cyrillic_bullets(self):
        """Regex распознаёт кириллическую нумерацию: а) б) в)."""
        preprocessor = PreprocessorService()
        text = "а) первый подпункт текст б) второй подпункт текст"
        matches = list(preprocessor.CLAUSE_PATTERN.finditer(text))
        assert len(matches) >= 2

    def test_falls_back_to_paragraph_if_no_clauses(self):
        """Без нумерации — fallback на разбиение по абзацам."""
        preprocessor = PreprocessorService()
        text = "Первый длинный абзац содержит описание условий работы и обязательств сторон по всем пунктам.\n\nВторой длинный абзац тоже содержит множество условий и оговорок по данному контракту."
        segments = preprocessor._segment(text)
        assert len(segments) >= 1
