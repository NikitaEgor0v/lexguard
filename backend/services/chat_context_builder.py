from __future__ import annotations

from config.model_registry import ModelConfig
from models.chat_schemas import ChatMessage
from models.schemas import AnalysisResponse


class ChatContextBuilder:
    def __init__(self, model_config: ModelConfig):
        self.model_config = model_config

    def build(self, analysis: AnalysisResponse, history: list[ChatMessage], question: str) -> str:
        """Build prompt with analysis, history, and user question securely within context bounds."""
        # 1. Sliding window: keep only the last 6 messages
        recent_history = history[-6:]
        history_text = "\n".join(
            f"{msg.role}: {msg.content}" for msg in recent_history
        )
        # Safely constrain history text to 1000 chars max
        if len(history_text) > 1000:
            history_text = "...\n" + history_text[-1000:]

        history_tokens = max(1, len(history_text) // 4) if history_text else 0
        available_tokens = max(200, self.model_config.safe_context - history_tokens)
        
        # 2. Hard caps on generated strings (Tighter for heavy cyrillic load)
        max_contract_chars = min(1200, max(400, available_tokens * 3))
        contract_text = self._build_contract_text(analysis)
        contract_excerpt = contract_text[:max_contract_chars]
        
        # Capping risks text - increased to accommodate risk numbers and previews
        risks_text = self._build_risks_text(analysis)[:2000]

        return (
            "Ты юридический ассистент системы LexGuard.\n"
            "Отвечай СТРОГО на русском языке, даже если вопрос задан на другом языке.\n"
            "Не переходи на английский и не смешивай языки.\n\n"
            "Твои возможности:\n"
            "- Отвечать на вопросы о договоре и результатах анализа\n"
            "- Генерировать исправленные формулировки пунктов договора\n"
            "- Предлагать альтернативные варианты текста, соответствующие законодательству РФ\n"
            "- Объяснять риски и давать рекомендации по их устранению\n"
            "- Помогать с любыми юридическими вопросами в контексте договора\n\n"
            "Правила:\n"
            "- При генерации текста пунктов опирайся на нормы ГК РФ и лучшие практики\n"
            "- При ответе на вопросы о рисках используй результаты анализа\n"
            "- Будь конкретным, ссылайся на фрагменты договора где уместно\n"
            "- Не выдумывай риски, которых нет в анализе\n"
            "- Если просят сгенерировать текст — генерируй готовый к использованию текст\n"
            "- Когда пользователь говорит 'риск №N' или 'N-й риск', он имеет в виду риск из списка ниже с номером N\n\n"
            f"ID анализа: {analysis.analysis_id}\n"
            f"Файл: {analysis.filename}\n\n"
            f"Фрагменты договора:\n{contract_excerpt}\n\n"
            f"Выявленные риски (сокращенно):\n{risks_text}\n\n"
            f"История диалога (последние сообщения):\n{history_text or '(пусто)'}\n\n"
            f"Вопрос пользователя:\n{question}\n"
        )

    def _build_contract_text(self, analysis: AnalysisResponse) -> str:
        parts: list[str] = []
        for item in analysis.risks:
            text = item.text.strip()
            if text:
                parts.append(text)
        return "\n\n".join(parts)

    def _build_risks_text(self, analysis: AnalysisResponse) -> str:
        lines: list[str] = []
        risk_number = 0
        for item in analysis.risks:
            # Skip only explicitly non-risky items
            if item.is_risky is False:
                continue
            risk_number += 1
            category = item.risk_category.value if item.risk_category else "без категории"
            description = item.risk_description or "описание отсутствует"
            # Include both display number and segment reference for clarity
            text_preview = item.text[:100].strip() if item.text else ""
            lines.append(
                f"Риск №{risk_number} (сегмент {item.segment_id}) [{item.risk_level.value}] "
                f"{category}: {description}\n  Текст: \"{text_preview}...\""
            )
        return "\n".join(lines) if lines else "Риски не обнаружены."
