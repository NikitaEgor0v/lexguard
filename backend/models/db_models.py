"""
SQLAlchemy ORM models for LexGuard.

Tables:
  - users             — пользователи системы
  - analysis_results  — результаты анализа документов
  - risk_items        — отдельные риски, привязанные к анализу
  - chat_sessions     — чат-сессии по анализу
  - chat_messages     — сообщения в чат-сессиях
  - user_documents    — пользовательские эталонные документы
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Column, String, Text, Boolean, Integer, Float, DateTime, ForeignKey, Index,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from config.database import Base


# ── Users ──

class UserDB(Base):
    """Пользователь системы."""

    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(320), unique=True, nullable=False, index=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    hashed_password = Column(String(256), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    analyses = relationship("AnalysisResultDB", back_populates="user", lazy="select")
    documents = relationship("UserDocumentDB", back_populates="user", cascade="all, delete-orphan", lazy="select")


# ── Analysis ──

class AnalysisResultDB(Base):
    """Результат анализа документа."""

    __tablename__ = "analysis_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)  # nullable for backward compat
    filename = Column(String(512), nullable=False)
    status = Column(String(32), nullable=False, default="completed")

    # Summary fields (denormalized for fast reads)
    total_segments = Column(Integer, nullable=False, default=0)
    risky_segments = Column(Integer, nullable=False, default=0)
    high_risk_count = Column(Integer, nullable=False, default=0)
    medium_risk_count = Column(Integer, nullable=False, default=0)
    low_risk_count = Column(Integer, nullable=False, default=0)
    risk_score = Column(Float, nullable=False, default=0.0)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    user = relationship("UserDB", back_populates="analyses")
    risks = relationship(
        "RiskItemDB",
        back_populates="analysis",
        cascade="all, delete-orphan",
        order_by="RiskItemDB.segment_id",
        lazy="joined",
    )
    chat_sessions = relationship(
        "ChatSessionDB",
        back_populates="analysis",
        cascade="all, delete-orphan",
        lazy="select",
    )

    __table_args__ = (
        Index("ix_analysis_results_user_id", "user_id"),
    )


class RiskItemDB(Base):
    """Отдельный риск (сегмент документа) в рамках анализа."""

    __tablename__ = "risk_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_id = Column(
        UUID(as_uuid=True),
        ForeignKey("analysis_results.id", ondelete="CASCADE"),
        nullable=False,
    )
    segment_id = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    is_risky = Column(Boolean, nullable=False, default=False)
    risk_level = Column(String(16), nullable=False, default="none")
    risk_category = Column(String(64), nullable=True)
    risk_description = Column(Text, nullable=True)
    recommendation = Column(Text, nullable=True)
    rag_context = Column(Text, nullable=True)

    # Relationship
    analysis = relationship("AnalysisResultDB", back_populates="risks")

    __table_args__ = (
        Index("ix_risk_items_analysis_id", "analysis_id"),
    )


# ── Chat ──

class ChatSessionDB(Base):
    """Чат-сессия, привязанная к анализу."""

    __tablename__ = "chat_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_id = Column(
        UUID(as_uuid=True),
        ForeignKey("analysis_results.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    analysis = relationship("AnalysisResultDB", back_populates="chat_sessions")
    messages = relationship(
        "ChatMessageDB",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessageDB.created_at",
        lazy="joined",
    )

    __table_args__ = (
        Index("ix_chat_sessions_analysis_id", "analysis_id"),
        Index("ix_chat_sessions_user_id", "user_id"),
    )


class ChatMessageDB(Base):
    """Сообщение в чат-сессии."""

    __tablename__ = "chat_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    role = Column(String(16), nullable=False)  # "user" | "assistant"
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationship
    session = relationship("ChatSessionDB", back_populates="messages")

    __table_args__ = (
        Index("ix_chat_messages_session_id", "session_id"),
    )


# ── User Documents (Custom RAG) ──

class UserDocumentDB(Base):
    """Пользовательский эталонный документ для RAG."""

    __tablename__ = "user_documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    filename = Column(String(512), nullable=False)
    contract_type = Column(String(64), nullable=False, default="иной")
    description = Column(Text, nullable=True)
    chunks_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationship
    user = relationship("UserDB", back_populates="documents")

    __table_args__ = (
        Index("ix_user_documents_user_id", "user_id"),
    )
