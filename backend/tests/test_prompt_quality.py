"""Tests for prompt quality fixes in analyzer.py.

Covers:
  1. _validate_safe_redaction — rejects verbatim copies, near-identical texts,
     and redactions for non-risky segments.
  2. _parse — post-processing wires through validation correctly.
"""

import json
import pytest

from models.schemas import RiskLevel
from services.analyzer import AnalyzerService


class TestValidateSafeRedaction:
    """Tests for the _validate_safe_redaction static method."""

    def test_none_input_returns_none(self):
        result = AnalyzerService._validate_safe_redaction(
            None, "some segment", True, RiskLevel.HIGH,
        )
        assert result is None

    def test_empty_string_returns_none(self):
        result = AnalyzerService._validate_safe_redaction(
            "", "some segment", True, RiskLevel.HIGH,
        )
        assert result is None

    def test_non_risky_segment_returns_none(self):
        """safe_redaction should be discarded for non-risky segments."""
        result = AnalyzerService._validate_safe_redaction(
            "Новая формулировка пункта", "old text", False, RiskLevel.NONE,
        )
        assert result is None

    def test_low_risk_returns_none(self):
        """safe_redaction should be discarded for low-risk segments."""
        result = AnalyzerService._validate_safe_redaction(
            "Новая формулировка пункта", "old text", True, RiskLevel.LOW,
        )
        assert result is None

    def test_identical_text_returns_none(self):
        """Model copied the original — should be rejected."""
        original = "Заказчик вправе расторгнуть договор в любой момент без оплаты."
        result = AnalyzerService._validate_safe_redaction(
            original, original, True, RiskLevel.HIGH,
        )
        assert result is None

    def test_identical_text_different_whitespace_returns_none(self):
        """Whitespace-normalized match should still be rejected."""
        original = "Заказчик  вправе   расторгнуть\n  договор."
        redaction = "Заказчик вправе расторгнуть договор."
        result = AnalyzerService._validate_safe_redaction(
            redaction, original, True, RiskLevel.HIGH,
        )
        assert result is None

    def test_valid_redaction_is_kept(self):
        """A genuinely different redaction should be preserved."""
        original = "Заказчик вправе расторгнуть договор без оплаты фактически выполненных работ."
        redaction = (
            "Заказчик вправе расторгнуть договор с обязательной оплатой "
            "фактически выполненных работ и возмещением расходов Исполнителя."
        )
        result = AnalyzerService._validate_safe_redaction(
            redaction, original, True, RiskLevel.HIGH,
        )
        assert result == redaction

    def test_high_similarity_returns_none(self):
        """If redaction has >85% similarity to original via SequenceMatcher, reject."""
        original = "Исполнитель вправе расторгнуть договор только с письменного согласия Заказчика."
        # Very minor change — just added "после получения" — still too similar
        redaction = "Исполнитель вправе расторгнуть договор только после получения согласия Заказчика."
        result = AnalyzerService._validate_safe_redaction(
            redaction, original, True, RiskLevel.MEDIUM,
        )
        assert result is None

    def test_medium_risk_valid_redaction_kept(self):
        """Medium risk with valid redaction should be kept."""
        original = "Срок выполнения работ определяется Заказчиком."
        redaction = (
            "Срок выполнения работ определяется по взаимному согласию сторон "
            "и фиксируется в календарном плане."
        )
        result = AnalyzerService._validate_safe_redaction(
            redaction, original, True, RiskLevel.MEDIUM,
        )
        assert result == redaction


class TestParsePostProcessing:
    """Integration tests: _parse must wire through safe_redaction validation."""

    def setup_method(self):
        # Patch RAG to skip Qdrant initialization
        self.analyzer = AnalyzerService.__new__(AnalyzerService)

    def test_parse_rejects_verbatim_safe_redaction(self):
        """If LLM returns safe_redaction identical to original, _parse sets it to None."""
        original_segment = "Заказчик вправе расторгнуть договор без оплаты."
        llm_response = json.dumps({
            "is_risky": True,
            "risk_level": "high",
            "risk_category": "правовой",
            "risk_description": "Расторжение без оплаты",
            "recommendation": "Добавить оплату",
            # Model just copied the original
            "safe_redaction": original_segment,
        })

        result = self.analyzer._parse(llm_response, original_segment, 1, None)
        assert result.is_risky is True
        assert result.safe_redaction is None  # Must be rejected

    def test_parse_keeps_valid_safe_redaction(self):
        """Valid safe_redaction that differs from original is kept."""
        original_segment = "Заказчик вправе расторгнуть договор без оплаты."
        llm_response = json.dumps({
            "is_risky": True,
            "risk_level": "high",
            "risk_category": "правовой",
            "risk_description": "Расторжение без оплаты",
            "recommendation": "Добавить оплату",
            "safe_redaction": "Заказчик вправе расторгнуть договор с оплатой фактически выполненных работ.",
        })

        result = self.analyzer._parse(llm_response, original_segment, 1, None)
        assert result.is_risky is True
        assert result.safe_redaction is not None
        assert "с оплатой" in result.safe_redaction

    def test_parse_nullifies_safe_redaction_for_none_risk(self):
        """safe_redaction for none-risk should be nullified even if LLM returns it."""
        original = "Стоимость услуг составляет 100 000 рублей."
        llm_response = json.dumps({
            "is_risky": False,
            "risk_level": "none",
            "risk_category": None,
            "risk_description": None,
            "recommendation": None,
            # Model erroneously provided safe_redaction for a safe segment
            "safe_redaction": "Какой-то текст",
        })

        result = self.analyzer._parse(llm_response, original, 1, None)
        assert result.is_risky is False
        assert result.safe_redaction is None
