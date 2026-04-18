from __future__ import annotations

import logging
import re
import time
from uuid import UUID

import requests
from sqlalchemy.orm import Session as DBSession

from config.model_registry import ModelConfig
from models.chat_schemas import ChatMessageResponse, ChatRole, ChatSession, ChatSessionResponse
from repositories.chat_repository import ChatRepository
from services.analyzer import AnalyzerService
from services.chat_context_builder import ChatContextBuilder

logger = logging.getLogger(__name__)

OLLAMA_URL = "http://ollama:11434/api/generate"
CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _session_to_response(session: ChatSession) -> ChatSessionResponse:
    return ChatSessionResponse(
        session_id=session.id,
        analysis_id=session.analysis_id,
        messages=[m.to_response() for m in session.messages],
    )


class ChatService:
    def __init__(
        self,
        context_builder: ChatContextBuilder,
        analyzer: AnalyzerService,
        model_name: str,
        model_config: ModelConfig,
    ):
        self.context_builder = context_builder
        self.analyzer = analyzer
        self.model_name = model_name
        self.model_config = model_config

    def create_session(
        self, db: DBSession, analysis_id: str, user_id: UUID | None = None,
    ) -> ChatSessionResponse:
        """Create chat session for existing analysis."""
        analysis = self.analyzer.get_result(analysis_id, db=db)
        if analysis is None:
            raise ValueError("Analysis not found")
        session = ChatRepository.create_session(db, analysis_id, user_id=user_id)
        logger.info("Chat session created: %s for analysis %s", session.id, analysis_id)
        return _session_to_response(session)

    def get_session(self, db: DBSession, session_id: UUID) -> ChatSessionResponse:
        """Return current chat session with history."""
        session = ChatRepository.get_session(db, session_id)
        return _session_to_response(session)

    def send_message(self, db: DBSession, session_id: UUID, content: str) -> ChatMessageResponse:
        """Store user message, generate assistant answer, and return it."""
        session = ChatRepository.get_session(db, session_id)
        analysis = self.analyzer.get_result(session.analysis_id, db=db)
        if analysis is None:
            raise ValueError("Analysis not found")

        safe_content = CONTROL_CHARS_RE.sub("", content)
        ChatRepository.add_message(db, session_id, ChatRole.USER, safe_content)
        logger.info("Chat question (%s): %s", session_id, safe_content[:50])

        history = ChatRepository.get_history(db, session_id)
        prompt = self.context_builder.build(analysis, history, safe_content)
        answer = self._call_llm(prompt)
        safe_answer = CONTROL_CHARS_RE.sub("", answer)
        msg = ChatRepository.add_message(db, session_id, ChatRole.ASSISTANT, safe_answer)
        return msg.to_response()

    def _call_llm(self, prompt: str) -> str:
        """Call Ollama generation API and return text answer."""
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self.model_config.temperature,
                "num_predict": self.model_config.max_output,
            },
        }
        started = time.monotonic()
        try:
            resp = requests.post(OLLAMA_URL, json=payload, timeout=180)
            resp.raise_for_status()
            body = resp.json()
            answer = (body.get("response") or "").strip()
            if not answer:
                raise RuntimeError("LLM returned empty response")
            return answer
        except requests.exceptions.ConnectionError as exc:
            logger.error("LLM unavailable: %s", exc)
            raise RuntimeError("LLM is unavailable") from exc
        except requests.exceptions.Timeout as exc:
            logger.error("LLM timeout: %s", exc)
            raise RuntimeError("LLM request timed out") from exc
        except Exception as exc:
            logger.error("LLM call failed: %s", exc)
            raise
        finally:
            elapsed = time.monotonic() - started
            logger.info("LLM call time: %.2fs", elapsed)
