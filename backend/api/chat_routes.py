from __future__ import annotations

import logging
from functools import lru_cache
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from api.routes import analyzer
from config.model_registry import MODEL_NAME, get_model_config
from models.chat_schemas import (
    ChatMessageResponse,
    ChatSessionResponse,
    CreateSessionRequest,
    SendMessageRequest,
)
from repositories.chat_repository import ChatRepository
from services.chat_context_builder import ChatContextBuilder
from services.chat_service import ChatService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


@lru_cache
def get_chat_repository() -> ChatRepository:
    """Return singleton chat repository."""
    return ChatRepository()


@lru_cache
def get_context_builder() -> ChatContextBuilder:
    """Return singleton chat context builder."""
    return ChatContextBuilder(get_model_config(MODEL_NAME))


def get_chat_service(
    repository: ChatRepository = Depends(get_chat_repository),
    context_builder: ChatContextBuilder = Depends(get_context_builder),
) -> ChatService:
    """Construct chat service with injected dependencies."""
    return ChatService(
        repository=repository,
        context_builder=context_builder,
        analyzer=analyzer,
        model_name=MODEL_NAME,
        model_config=get_model_config(MODEL_NAME),
    )


@router.post("/session", response_model=ChatSessionResponse, status_code=status.HTTP_201_CREATED)
def create_chat_session(
    request: CreateSessionRequest,
    service: ChatService = Depends(get_chat_service),
) -> ChatSessionResponse:
    try:
        return service.create_session(request.analysis_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/session/{session_id}/message", response_model=ChatMessageResponse)
def send_chat_message(
    session_id: UUID,
    request: SendMessageRequest,
    service: ChatService = Depends(get_chat_service),
) -> ChatMessageResponse:
    try:
        return service.send_message(session_id, request.content)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/session/{session_id}", response_model=ChatSessionResponse)
def get_chat_session(
    session_id: UUID,
    service: ChatService = Depends(get_chat_service),
) -> ChatSessionResponse:
    try:
        return service.get_session(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
