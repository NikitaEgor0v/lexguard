"""
Общие фикстуры для тестового набора LexGuard.

Все тесты работают в изоляции от Docker-инфраструктуры:
- Qdrant/Ollama/Redis заменяются моками
- PostgreSQL заменяется SQLite in-memory
"""

import os
import sys
import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

# Убеждаемся, что backend/ — в sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.schemas import (
    AnalysisResponse,
    AnalysisSummary,
    RiskItem,
    RiskLevel,
    RiskCategory,
)
from models.chat_schemas import ChatMessage, ChatRole


# ── Фабрики данных ──

@pytest.fixture
def sample_analysis_response():
    """Минимальный AnalysisResponse для тестов."""
    def _factory(num_risks=10, analysis_id=None):
        aid = analysis_id or str(uuid.uuid4())
        risks = []
        levels = [RiskLevel.HIGH, RiskLevel.MEDIUM, RiskLevel.LOW, RiskLevel.NONE]
        cats = [
            RiskCategory.FINANCIAL, RiskCategory.LEGAL, RiskCategory.OPERATIONAL, 
            RiskCategory.INTELLECTUAL, RiskCategory.REPUTATIONAL
        ]
        for i in range(num_risks):
            level = levels[i % 4]
            is_risky = level != RiskLevel.NONE
            risks.append(RiskItem(
                segment_id=i + 1,
                text=f"Тестовый фрагмент договора #{i+1}. " * 5,
                is_risky=is_risky,
                risk_level=level,
                risk_category=cats[i % 5] if is_risky else None,
                risk_description=f"Описание риска #{i+1}" if is_risky else None,
                recommendation=f"Рекомендация #{i+1}" if is_risky else None,
                rag_context=f"Контекст RAG #{i+1}" if i < 5 else None,
            ))
        summary = AnalysisSummary(
            total_segments=num_risks,
            risky_segments=sum(1 for r in risks if r.is_risky),
            high_risk_count=sum(1 for r in risks if r.risk_level == RiskLevel.HIGH),
            medium_risk_count=sum(1 for r in risks if r.risk_level == RiskLevel.MEDIUM),
            low_risk_count=sum(1 for r in risks if r.risk_level == RiskLevel.LOW),
            risk_score=0.45,
        )
        return AnalysisResponse(
            analysis_id=aid, filename="test_contract.pdf",
            status="completed", summary=summary, risks=risks,
            executive_summary="Автоматическая сводка по рискам для теста."
        )
    return _factory


@pytest.fixture
def sample_chat_history():
    """Фабрика истории чат-сообщений."""
    def _factory(count=5, session_id=None):
        sid = session_id or uuid.uuid4()
        messages = []
        for i in range(count):
            role = ChatRole.USER if i % 2 == 0 else ChatRole.ASSISTANT
            messages.append(ChatMessage(
                id=uuid.uuid4(),
                session_id=sid,
                role=role,
                content=f"Тестовое сообщение #{i+1} длиной достаточной для проверки",
                created_at=datetime.utcnow(),
            ))
        return messages
    return _factory


@pytest.fixture
def mock_ollama_response():
    """Фабрика ответов Ollama."""
    def _factory(response_text='{"is_risky": true, "risk_level": "high", "risk_category": "финансовый", "risk_description": "тест", "recommendation": "тест"}', status_code=200):
        mock_resp = MagicMock()
        mock_resp.status_code = status_code
        mock_resp.json.return_value = {"response": response_text}
        mock_resp.text = response_text
        return mock_resp
    return _factory


@pytest.fixture
def long_contract_text():
    """Генерирует реалистичный длинный текст контракта."""
    clause = (
        "1.{n}. Исполнитель обязуется оказать Заказчику услуги по разработке "
        "программного обеспечения в соответствии с Техническим заданием "
        "(Приложение №1), являющимся неотъемлемой частью настоящего Договора. "
        "Стоимость услуг составляет {price} рублей, включая НДС. "
        "В случае нарушения сроков исполнения обязательств Исполнитель уплачивает "
        "неустойку в размере {penalty}% от стоимости невыполненных работ за каждый "
        "день просрочки, но не более {cap}% от общей стоимости Договора.\n\n"
    )
    return "\n\n".join(
        clause.format(n=i, price=100000 * i, penalty=0.1 * i, cap=10 + i)
        for i in range(1, 201)
    )
