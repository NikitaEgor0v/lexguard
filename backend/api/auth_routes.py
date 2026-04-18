"""
Authentication API endpoints — register, login, logout, current user.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session as DBSession

from config.database import get_db
from config.security import COOKIE_NAME, create_access_token, get_current_user
from models.db_models import UserDB
from models.user_schemas import LoginRequest, RegisterRequest, TokenMessage, UserResponse
from services.auth_service import AuthService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(
    request: RegisterRequest,
    response: Response,
    db: DBSession = Depends(get_db),
) -> UserResponse:
    """Register a new user and set auth cookie."""
    try:
        user = AuthService.register(db, request.email, request.username, request.password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    token = create_access_token(user.id)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=86400,  # 24h
    )
    return UserResponse.model_validate(user)


@router.post("/login", response_model=UserResponse)
def login(
    request: LoginRequest,
    response: Response,
    db: DBSession = Depends(get_db),
) -> UserResponse:
    """Authenticate and set auth cookie."""
    try:
        user = AuthService.authenticate(db, request.email, request.password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    token = create_access_token(user.id)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=86400,
    )
    return UserResponse.model_validate(user)


@router.post("/logout", response_model=TokenMessage)
def logout(response: Response) -> TokenMessage:
    """Clear auth cookie."""
    response.delete_cookie(key=COOKIE_NAME, path="/")
    return TokenMessage(message="Вы вышли из системы")


@router.get("/me", response_model=UserResponse)
def me(current_user: UserDB = Depends(get_current_user)) -> UserResponse:
    """Return current authenticated user."""
    return UserResponse.model_validate(current_user)
