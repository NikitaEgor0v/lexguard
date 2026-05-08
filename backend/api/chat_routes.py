from __future__ import annotations

import logging
from functools import lru_cache
from uuid import UUID
import json
import time
import os
import sys
import requests

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
from models.db_models import UserDB, ChatSessionDB, AnalysisResultDB
from services.chat_context_builder import ChatContextBuilder
from services.chat_service import ChatService

logger = logging.getLogger(__name__)


def _verify_session_owner(
    db: DBSession,
    session_id: UUID,
    current_user: UserDB,
) -> ChatSessionDB:
    """Verify that current user owns the chat session. Raises HTTPException if not.
    
    Returns the session row if found and owned by user.
    Raises 404 if session doesn't exist, 403 if owned by another user.
    """
    row = db.get(ChatSessionDB, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Чат-сессия не найдена")
    
    if row.user_id is not None and row.user_id != current_user.id:
        logger.warning(
            "IDOR attempt: user %s tried to access chat session %s owned by %s",
            current_user.id, session_id, row.user_id
        )
        raise HTTPException(status_code=403, detail="Доступ запрещён")
    
    return row


def _verify_analysis_owner_for_chat(
    db: DBSession,
    analysis_id: str,
    current_user: UserDB,
) -> AnalysisResultDB:
    """Verify that current user owns the analysis before creating chat session."""
    import uuid as _uuid
    try:
        uid = _uuid.UUID(analysis_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Анализ не найден")
    
    row = db.query(AnalysisResultDB).filter_by(id=uid).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Анализ не найден")
    
    if row.user_id is not None and row.user_id != current_user.id:
        logger.warning(
            "IDOR attempt: user %s tried to create chat for analysis %s owned by %s",
            current_user.id, analysis_id, row.user_id
        )
        raise HTTPException(status_code=403, detail="Доступ запрещён")
    
    return row
DEBUG_LOG_PATH = "/Users/nikitaegorov/Мои проекты/lexguard/.cursor/debug-3d0ca5.log"
DEBUG_ENDPOINT = "http://127.0.0.1:7691/ingest/bcb6efda-9fe5-4ac7-b530-a243639a005e"
DEBUG_ENDPOINT_DOCKER_FALLBACK = "http://host.docker.internal:7691/ingest/bcb6efda-9fe5-4ac7-b530-a243639a005e"


def _debug_log(run_id: str, hypothesis_id: str, location: str, message: str, data: dict) -> None:
    payload = {
        "sessionId": "3d0ca5",
        "runId": run_id,
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
    }
    # #region agent log
    try:
        requests.post(
            DEBUG_ENDPOINT,
            json=payload,
            timeout=0.5,
            headers={"Content-Type": "application/json", "X-Debug-Session-Id": "3d0ca5"},
        )
    except Exception:
        try:
            requests.post(
                DEBUG_ENDPOINT_DOCKER_FALLBACK,
                json=payload,
                timeout=0.5,
                headers={"Content-Type": "application/json", "X-Debug-Session-Id": "3d0ca5"},
            )
        except Exception:
            pass
    try:
        os.makedirs(os.path.dirname(DEBUG_LOG_PATH), exist_ok=True)
        with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception as e:
        try:
            print(f"[debug-log-failed][chat_routes]{e}", file=sys.stderr)
        except Exception:
            pass
    # #endregion

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
    # P0 Security: Verify analysis ownership before creating chat session
    _verify_analysis_owner_for_chat(db, request.analysis_id, current_user)
    
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
    # P0 Security: Verify session ownership before sending message
    session_row = _verify_session_owner(db, session_id, current_user)
    
    _debug_log(
        "post-fix",
        "H3",
        "backend/api/chat_routes.py:send_chat_message",
        "chat message (owner verified)",
        {
            "session_id": str(session_id),
            "current_user_id": str(current_user.id) if current_user else None,
            "session_owner_id": str(session_row.user_id) if session_row.user_id else None,
        },
    )
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
    # P0 Security: Verify session ownership before reading
    session_row = _verify_session_owner(db, session_id, current_user)
    
    _debug_log(
        "post-fix",
        "H3",
        "backend/api/chat_routes.py:get_chat_session",
        "chat read (owner verified)",
        {
            "session_id": str(session_id),
            "current_user_id": str(current_user.id) if current_user else None,
            "session_owner_id": str(session_row.user_id) if session_row.user_id else None,
        },
    )
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
