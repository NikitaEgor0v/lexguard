from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from models.chat_schemas import ChatMessage, ChatRole, ChatSession


class ChatRepository:
    def __init__(self):
        self._sessions: dict[UUID, ChatSession] = {}

    def create_session(self, analysis_id: str) -> ChatSession:
        """Create a chat session for analysis result."""
        session = ChatSession(id=uuid4(), analysis_id=analysis_id, created_at=datetime.utcnow())
        self._sessions[session.id] = session
        return session

    def get_session(self, session_id: UUID) -> ChatSession:
        """Get session by id."""
        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError("Chat session not found")
        return session

    def add_message(self, session_id: UUID, role: ChatRole, content: str) -> ChatMessage:
        """Append message to existing session."""
        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError("Chat session not found")
        msg = ChatMessage(
            id=uuid4(),
            session_id=session_id,
            role=role,
            content=content,
            created_at=datetime.utcnow(),
        )
        session.messages.append(msg)
        return msg

    def get_history(self, session_id: UUID) -> list[ChatMessage]:
        """Return session message history."""
        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError("Chat session not found")
        return session.messages
