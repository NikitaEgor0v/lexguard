"""
Service for managing user reference documents — vectorization and Qdrant storage.
"""

from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from models.db_models import UserDocumentDB
from models.document_schemas import UserDocumentResponse
from services.preprocessor import PreprocessorService

logger = logging.getLogger(__name__)

USER_DOCS_COLLECTION = "user_documents"
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50


class DocumentService:
    def __init__(self):
        self._preprocessor = PreprocessorService()
        self._encoder = None
        self._qdrant = None
        self._ready = False
        self._init_qdrant()

    def _init_qdrant(self):
        try:
            from sentence_transformers import SentenceTransformer
            from qdrant_client import QdrantClient
            from qdrant_client.models import Distance, VectorParams

            self._encoder = SentenceTransformer("intfloat/multilingual-e5-base")
            self._qdrant = QdrantClient(host="qdrant", port=6333)

            cols = [c.name for c in self._qdrant.get_collections().collections]
            if USER_DOCS_COLLECTION not in cols:
                self._qdrant.create_collection(
                    collection_name=USER_DOCS_COLLECTION,
                    vectors_config=VectorParams(size=768, distance=Distance.COSINE),
                )
            self._ready = True
            logger.info("DocumentService: Qdrant ready for user documents")
        except Exception as e:
            logger.error("DocumentService: Qdrant init failed: %s", e)
            self._ready = False

    def upload_document(
        self,
        db: Session,
        user_id: UUID,
        content: bytes,
        filename: str,
        contract_type: str = "иной",
        description: str = "",
    ) -> UserDocumentResponse:
        """Process, vectorize and store a user reference document."""
        if not self._ready:
            raise RuntimeError("Сервис документов недоступен")

        # Extract text
        text = ""
        if filename.lower().endswith(".pdf"):
            text = self._preprocessor._extract_pdf(content)
        else:
            text = self._preprocessor._extract_docx(content)

        text = self._preprocessor._clean_text(text)
        if not text.strip():
            raise ValueError("Документ пуст или нечитаем")

        # Chunk text
        chunks = self._chunk_text(text, CHUNK_SIZE, CHUNK_OVERLAP)
        if not chunks:
            raise ValueError("Не удалось извлечь фрагменты из документа")

        # Generate document ID
        doc_id = uuid4()

        # Vectorize and upsert into Qdrant
        from qdrant_client.models import PointStruct

        texts_for_encoding = [f"passage: {chunk}" for chunk in chunks]
        vectors = self._encoder.encode(texts_for_encoding, batch_size=32, show_progress_bar=False)

        points = [
            PointStruct(
                id=str(uuid4()),
                vector=vec.tolist(),
                payload={
                    "user_id": str(user_id),
                    "document_id": str(doc_id),
                    "contract_type": contract_type,
                    "chunk_text": chunk,
                    "filename": filename,
                },
            )
            for chunk, vec in zip(chunks, vectors)
        ]
        self._qdrant.upsert(collection_name=USER_DOCS_COLLECTION, points=points)

        # Save metadata to PostgreSQL
        doc = UserDocumentDB(
            id=doc_id,
            user_id=user_id,
            filename=filename,
            contract_type=contract_type,
            description=description or None,
            chunks_count=len(chunks),
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        logger.info("User document uploaded: %s (%d chunks) by user %s", filename, len(chunks), user_id)
        return UserDocumentResponse.model_validate(doc)

    def list_documents(self, db: Session, user_id: UUID) -> list[UserDocumentResponse]:
        """List all documents for a user."""
        rows = (
            db.query(UserDocumentDB)
            .filter(UserDocumentDB.user_id == user_id)
            .order_by(UserDocumentDB.created_at.desc())
            .all()
        )
        return [UserDocumentResponse.model_validate(r) for r in rows]

    def delete_document(self, db: Session, user_id: UUID, document_id: UUID) -> None:
        """Delete document from Qdrant and PostgreSQL."""
        doc = db.query(UserDocumentDB).filter(
            UserDocumentDB.id == document_id,
            UserDocumentDB.user_id == user_id,
        ).first()
        if doc is None:
            raise ValueError("Документ не найден")

        # Delete from Qdrant
        if self._ready:
            try:
                from qdrant_client.models import Filter, FieldCondition, MatchValue
                self._qdrant.delete(
                    collection_name=USER_DOCS_COLLECTION,
                    points_selector=Filter(
                        must=[
                            FieldCondition(key="document_id", match=MatchValue(value=str(document_id)))
                        ]
                    ),
                )
            except Exception as e:
                logger.error("Failed to delete from Qdrant: %s", e)

        # Delete from PostgreSQL
        db.delete(doc)
        db.commit()
        logger.info("User document deleted: %s by user %s", document_id, user_id)

    @staticmethod
    def _chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
        """Split text into overlapping chunks."""
        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            start += chunk_size - overlap
        return chunks

    def search_user_documents(
        self, segment: str, user_id: UUID, contract_type: str | None = None, top_k: int = 2,
    ) -> str | None:
        """Search user's custom documents in Qdrant."""
        if not self._ready or not self._encoder:
            return None

        try:
            from qdrant_client.models import Filter, FieldCondition, MatchValue

            must_conditions = [
                FieldCondition(key="user_id", match=MatchValue(value=str(user_id)))
            ]
            if contract_type and contract_type != "иной":
                must_conditions.append(
                    FieldCondition(key="contract_type", match=MatchValue(value=contract_type))
                )

            qv = self._encoder.encode(f"query: {segment}", show_progress_bar=False).tolist()
            results = self._qdrant.search(
                collection_name=USER_DOCS_COLLECTION,
                query_vector=qv,
                query_filter=Filter(must=must_conditions),
                limit=top_k,
                score_threshold=0.5,
            )
            if not results:
                return None

            parts = []
            for hit in results:
                p = hit.payload
                parts.append(
                    f"[Пользовательский эталон | {p.get('contract_type', '')}]\n"
                    f"Файл: {p.get('filename', '')}\n"
                    f"Фрагмент: {p.get('chunk_text', '')}"
                )
            return "\n\n".join(parts)
        except Exception as e:
            logger.error("User document search error: %s", e)
            return None
