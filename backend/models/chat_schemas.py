from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ChatRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"


class ChatMessageResponse(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    role: ChatRole
    content: str
    created_at: datetime


class ChatMessage(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    id: UUID
    session_id: UUID
    role: ChatRole
    content: str = Field(max_length=2000)
    created_at: datetime

    def to_response(self) -> ChatMessageResponse:
        """Convert internal message to API response model."""
        return ChatMessageResponse(role=self.role, content=self.content, created_at=self.created_at)


class ChatSession(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    id: UUID
    analysis_id: str
    messages: list[ChatMessage] = Field(default_factory=list)
    created_at: datetime


class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    analysis_id: str


class SendMessageRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    content: str = Field(min_length=1, max_length=2000)


class ChatSessionResponse(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    session_id: UUID
    analysis_id: str
    messages: list[ChatMessageResponse]
