"""
Repository for user CRUD operations.
"""

from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from models.db_models import UserDB

logger = logging.getLogger(__name__)


class UserRepository:

    @staticmethod
    def create_user(db: Session, email: str, username: str, hashed_password: str) -> UserDB:
        user = UserDB(email=email.lower(), username=username, hashed_password=hashed_password)
        db.add(user)
        db.commit()
        db.refresh(user)
        logger.info("User created: %s (%s)", username, email)
        return user

    @staticmethod
    def get_by_email(db: Session, email: str) -> Optional[UserDB]:
        return db.query(UserDB).filter(UserDB.email == email.lower()).first()

    @staticmethod
    def get_by_username(db: Session, username: str) -> Optional[UserDB]:
        return db.query(UserDB).filter(UserDB.username == username).first()

    @staticmethod
    def get_by_id(db: Session, user_id: UUID) -> Optional[UserDB]:
        return db.get(UserDB, user_id)
