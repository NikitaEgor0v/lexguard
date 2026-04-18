"""
User documents API — upload, list, delete reference documents for custom RAG.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session as DBSession

from config.database import get_db
from config.security import get_current_user
from models.db_models import UserDB
from models.document_schemas import UserDocumentResponse
from services.document_service import DocumentService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])


@lru_cache
def get_document_service() -> DocumentService:
    return DocumentService()


@router.post("/upload", response_model=UserDocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    contract_type: str = Form("иной"),
    description: str = Form(""),
    db: DBSession = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
    service: DocumentService = Depends(get_document_service),
) -> UserDocumentResponse:
    """Upload a reference document for custom RAG."""
    allowed_ext = (".pdf", ".docx")
    filename = file.filename or "document"
    if not any(filename.lower().endswith(e) for e in allowed_ext):
        raise HTTPException(status_code=400, detail="Поддерживаются только PDF и DOCX файлы")

    content = await file.read()
    if len(content) > 15 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Файл слишком большой (максимум 15 МБ)")

    try:
        return service.upload_document(
            db, current_user.id, content, filename, contract_type, description,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("", response_model=list[UserDocumentResponse])
def list_documents(
    db: DBSession = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
    service: DocumentService = Depends(get_document_service),
) -> list[UserDocumentResponse]:
    """List all reference documents for current user."""
    return service.list_documents(db, current_user.id)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: UUID,
    db: DBSession = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
    service: DocumentService = Depends(get_document_service),
):
    """Delete a reference document."""
    try:
        service.delete_document(db, current_user.id, document_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
