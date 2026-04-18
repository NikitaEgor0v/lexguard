"""
Repository for chat sessions and messages — PostgreSQL-backed.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import func
from sqlalchemy.orm import Session

from models.chat_schemas import (
    ChatMessage,
    ChatRole,
    ChatSession,
)
from models.db_models import ChatMessageDB, ChatSessionDB

logger = logging.getLogger(__name__)


class ChatRepository:
    """Manages chat sessions and messages in PostgreSQL."""

    @staticmethod
    def create_session(db: Session, analysis_id: str, user_id: UUID | None = None) -> ChatSession:
        """Create a new chat session or return an existing one for an analysis result."""
        import uuid as _uuid
        an_id = _uuid.UUID(analysis_id)
        
        query = db.query(ChatSessionDB).filter(ChatSessionDB.analysis_id == an_id)
        if user_id:
            query = query.filter(ChatSessionDB.user_id == user_id)
        existing = query.first()
        
        if existing:
            logger.info("Retrieved existing chat session: %s for analysis %s", existing.id, analysis_id)
            messages = [
                ChatMessage(
                    id=m.id,
                    session_id=m.session_id,
                    role=ChatRole(m.role),
                    content=m.content,
                    created_at=m.created_at,
                )
                for m in existing.messages
            ]
            return ChatSession(
                id=existing.id,
                analysis_id=str(existing.analysis_id),
                messages=messages,
                created_at=existing.created_at,
            )

        row = ChatSessionDB(
            id=uuid4(),
            analysis_id=an_id,
            user_id=user_id,
            created_at=datetime.utcnow(),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        logger.info("Chat session created: %s for analysis %s", row.id, analysis_id)
        return ChatSession(
            id=row.id,
            analysis_id=str(row.analysis_id),
            messages=[],
            created_at=row.created_at,
        )

    @staticmethod
    def get_session(db: Session, session_id: UUID) -> ChatSession:
        """Get session by id with all messages."""
        row: Optional[ChatSessionDB] = db.get(ChatSessionDB, session_id)
        if row is None:
            raise ValueError("Chat session not found")
        messages = [
            ChatMessage(
                id=m.id,
                session_id=m.session_id,
                role=ChatRole(m.role),
                content=m.content,
                created_at=m.created_at,
            )
            for m in row.messages
        ]
        return ChatSession(
            id=row.id,
            analysis_id=str(row.analysis_id),
            messages=messages,
            created_at=row.created_at,
        )

    @staticmethod
    def add_message(
        db: Session,
        session_id: UUID,
        role: ChatRole,
        content: str,
    ) -> ChatMessage:
        """Append message to existing session."""
        row: Optional[ChatSessionDB] = db.get(ChatSessionDB, session_id)
        if row is None:
            raise ValueError("Chat session not found")

        msg = ChatMessageDB(
            id=uuid4(),
            session_id=session_id,
            role=role.value if isinstance(role, ChatRole) else role,
            content=content,
            created_at=datetime.utcnow(),
        )
        db.add(msg)
        db.commit()
        db.refresh(msg)

        return ChatMessage(
            id=msg.id,
            session_id=msg.session_id,
            role=ChatRole(msg.role),
            content=msg.content,
            created_at=msg.created_at,
        )

    @staticmethod
    def get_history(db: Session, session_id: UUID) -> list[ChatMessage]:
        """Return session message history."""
        row: Optional[ChatSessionDB] = db.get(ChatSessionDB, session_id)
        if row is None:
            raise ValueError("Chat session not found")
        return [
            ChatMessage(
                id=m.id,
                session_id=m.session_id,
                role=ChatRole(m.role),
                content=m.content,
                created_at=m.created_at,
            )
            for m in row.messages
        ]

    @staticmethod
    def list_sessions(db: Session, user_id: UUID, limit: int = 20, offset: int = 0) -> list[dict]:
        """List chat sessions for a user with pagination."""
        rows = (
            db.query(ChatSessionDB)
            .filter(ChatSessionDB.user_id == user_id)
            .order_by(ChatSessionDB.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [
            {
                "session_id": str(r.id),
                "analysis_id": str(r.analysis_id),
                "messages_count": len(r.messages),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]

    @staticmethod
    def count_sessions(db: Session, user_id: UUID) -> int:
        return db.query(func.count(ChatSessionDB.id)).filter(
            ChatSessionDB.user_id == user_id
        ).scalar() or 0
