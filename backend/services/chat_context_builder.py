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
        # Safely constrain history text to 2000 chars max
        if len(history_text) > 2000:
            history_text = "...\n" + history_text[-2000:]

        history_tokens = max(1, len(history_text) // 4) if history_text else 0
        available_tokens = max(200, self.model_config.safe_context - history_tokens)
        
        # 2. Hard caps on generated strings
        max_contract_chars = min(2000, max(400, available_tokens * 4))
        contract_text = self._build_contract_text(analysis)
        contract_excerpt = contract_text[:max_contract_chars]
        
        # Capping risks text to 1500 chars 
        risks_text = self._build_risks_text(analysis)[:1500]

        return (
            "Ты юридический ассистент системы LexGuard.\n"
            "Отвечай СТРОГО на русском языке, даже если вопрос задан на другом языке.\n"
            "Не переходи на английский и не смешивай языки.\n"
            "Используй только контекст договора и результатов анализа.\n"
            "Будь конкретным, ссылайся на фрагменты договора.\n"
            "Не выдумывай риски, которых нет в анализе.\n\n"
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
        for item in analysis.risks:
            if not item.is_risky:
                continue
            category = item.risk_category.value if item.risk_category else "без категории"
            description = item.risk_description or "описание отсутствует"
            lines.append(f"#{item.segment_id} [{item.risk_level.value}] {category}: {description}")
        return "\n".join(lines) if lines else "Риски не обнаружены."
