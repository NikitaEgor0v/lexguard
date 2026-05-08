"""Tests for analyzer.py _parse method."""

import json
import pytest

from models.schemas import RiskLevel
from services.analyzer import AnalyzerService


class TestParse:
    """Tests for _parse method."""

    def setup_method(self):
        self.analyzer = AnalyzerService.__new__(AnalyzerService)

    def test_parse_valid_json(self):
        """Valid JSON response is parsed correctly."""
        llm_response = json.dumps({
            "is_risky": True,
            "risk_level": "high",
            "risk_category": "правовой",
            "risk_description": "Расторжение без оплаты",
            "recommendation": "Добавить оплату",
        })

        result = self.analyzer._parse(llm_response, "Тестовый сегмент", 1, None)
        assert result.is_risky is True
        assert result.risk_level == RiskLevel.HIGH
        assert result.risk_description == "Расторжение без оплаты"

    def test_parse_json_with_markdown(self):
        """JSON wrapped in markdown code blocks is handled."""
        llm_response = """```json
{
    "is_risky": false,
    "risk_level": "none",
    "risk_category": null,
    "risk_description": null,
    "recommendation": null
}
```"""

        result = self.analyzer._parse(llm_response, "Тестовый сегмент", 1, None)
        assert result.is_risky is False
        assert result.risk_level == RiskLevel.NONE

    def test_parse_invalid_json_fallback(self):
        """Invalid JSON returns fallback RiskItem."""
        result = self.analyzer._parse("not json at all", "Тестовый сегмент", 1, None)
        assert result.is_risky is True
        assert result.risk_level == RiskLevel.LOW
        assert "Не удалось классифицировать" in result.risk_description

    def test_parse_preserves_rag_context(self):
        """RAG context is preserved in result."""
        llm_response = json.dumps({
            "is_risky": True,
            "risk_level": "medium",
            "risk_category": "финансовый",
            "risk_description": "Тест",
            "recommendation": "Тест",
        })
        rag = "Норма из базы знаний"

        result = self.analyzer._parse(llm_response, "Сегмент", 1, rag)
        assert result.rag_context == rag
