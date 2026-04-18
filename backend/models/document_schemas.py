"""
Pydantic schemas for user documents (custom RAG).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class UploadDocumentRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    contract_type: str = Field(default="иной", max_length=64)
    description: str = Field(default="", max_length=500)


class UserDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    filename: str
    contract_type: str
    description: str | None
    chunks_count: int
    created_at: datetime
