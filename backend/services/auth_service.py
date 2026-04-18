"""
Authentication service — registration, login, password verification.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from config.security import hash_password, verify_password
from models.db_models import UserDB
from repositories.user_repository import UserRepository

logger = logging.getLogger(__name__)


class AuthService:

    @staticmethod
    def register(db: Session, email: str, username: str, password: str) -> UserDB:
        """Register a new user. Raises ValueError on conflict."""
        if UserRepository.get_by_email(db, email):
            raise ValueError("Пользователь с таким email уже существует")
        if UserRepository.get_by_username(db, username):
            raise ValueError("Имя пользователя уже занято")
        hashed = hash_password(password)
        return UserRepository.create_user(db, email, username, hashed)

    @staticmethod
    def authenticate(db: Session, email: str, password: str) -> UserDB:
        """Verify credentials. Raises ValueError on failure."""
        user = UserRepository.get_by_email(db, email)
        if user is None or not verify_password(password, user.hashed_password):
            raise ValueError("Неверный email или пароль")
        return user
