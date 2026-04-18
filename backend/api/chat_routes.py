from __future__ import annotations

import logging
from functools import lru_cache
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session as DBSession

from api.routes import analyzer
from config.database import get_db
from config.model_registry import MODEL_NAME, get_model_config
from config.security import get_current_user
from models.chat_schemas import (
    ChatMessageResponse,
    ChatSessionResponse,
    CreateSessionRequest,
    SendMessageRequest,
)
from models.db_models import UserDB
from services.chat_context_builder import ChatContextBuilder
from services.chat_service import ChatService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


@lru_cache
def get_context_builder() -> ChatContextBuilder:
    """Return singleton chat context builder."""
    return ChatContextBuilder(get_model_config(MODEL_NAME))


def get_chat_service(
    context_builder: ChatContextBuilder = Depends(get_context_builder),
) -> ChatService:
    """Construct chat service with injected dependencies."""
    return ChatService(
        context_builder=context_builder,
        analyzer=analyzer,
        model_name=MODEL_NAME,
        model_config=get_model_config(MODEL_NAME),
    )


@router.post("/session", response_model=ChatSessionResponse, status_code=status.HTTP_201_CREATED)
def create_chat_session(
    request: CreateSessionRequest,
    db: DBSession = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
) -> ChatSessionResponse:
    try:
        return service.create_session(db, request.analysis_id, user_id=current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/session/{session_id}/message", response_model=ChatMessageResponse)
def send_chat_message(
    session_id: UUID,
    request: SendMessageRequest,
    db: DBSession = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
) -> ChatMessageResponse:
    try:
        return service.send_message(db, session_id, request.content)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/session/{session_id}", response_model=ChatSessionResponse)
def get_chat_session(
    session_id: UUID,
    db: DBSession = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
) -> ChatSessionResponse:
    try:
        return service.get_session(db, session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/sessions")
def list_chat_sessions(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: DBSession = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    """List all chat sessions for current user with pagination."""
    from repositories.chat_repository import ChatRepository
    items = ChatRepository.list_sessions(db, current_user.id, limit, offset)
    total = ChatRepository.count_sessions(db, current_user.id)
    return {"items": items, "total": total, "limit": limit, "offset": offset}
