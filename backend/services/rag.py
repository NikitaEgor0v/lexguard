import hashlib
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from config.model_registry import (
    MIN_RELEVANCE_SCORE_DEFAULT,
    MAX_CHUNKS_PER_SEGMENT_DEFAULT,
)

logger = logging.getLogger(__name__)

NORMS_PATH = Path(__file__).parent.parent / "data" / "legal_norms.json"
COLLECTION_NAME = "legal_norms"
EMBEDDING_MODEL = "intfloat/multilingual-e5-base"
TOP_K = 6  # Retrieve more candidates for filtering (will be limited by model config)

# Minimum cosine similarity threshold. Chunks below this score are discarded.
# Configurable via environment variable for tuning.
# Default from model_registry.py (0.50 for better recall on server).
# Recommended range: 0.50-0.75 (lower = more recall, higher = more precision).
MIN_RELEVANCE_SCORE = float(os.getenv("MIN_RELEVANCE_SCORE", str(MIN_RELEVANCE_SCORE_DEFAULT)))
MAX_CHUNKS_PER_SEGMENT = int(os.getenv("MAX_CHUNKS_PER_SEGMENT", str(MAX_CHUNKS_PER_SEGMENT_DEFAULT)))

UNIVERSAL_CONTRACT_TYPES = ("все", "all", "any")
CONTRACT_TYPE_ALIASES = {
    "услуги": ("услуги", "software_development", "outsourcing"),
    "подряд": ("подряд", "software_development"),
    "поставка": ("поставка", "outsourcing"),
    "аренда": ("аренда",),
    "трудовой": ("трудовой",),
    "лицензионный": ("лицензионный", "software_development"),
    "нда": ("нда", "nda"),
    "агентский": ("агентский", "outsourcing"),
}


@dataclass
class RAGChunk:
    """Structured RAG chunk with explicit Etalon/Risk separation."""
    etalon: str  # Safe formulation (reference)
    risk: str  # Risky pattern to detect
    category: str
    topic: str
    criticality: str
    legal_basis: list[str]
    score: float
    
    def format_for_prompt(self) -> str:
        """Format chunk for LLM prompt with clear Etalon/Risk separation."""
        legal_text = "; ".join(self.legal_basis[:2]) if self.legal_basis else ""
        return (
            f"ЭТАЛОН (безопасная формулировка): {self.etalon}\n"
            f"РИСК (опасная формулировка): {self.risk}\n"
            f"КАТЕГОРИЯ: {self.category}\n"
            f"ОСНОВАНИЕ: {legal_text}"
        )
    
    def get_dedup_hash(self) -> str:
        """SHA256 hash of first 200 chars for deduplication."""
        text = (self.etalon + self.risk)[:200]
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class UserRAGChunk:
    """Structured user document chunk."""
    text: str
    filename: str
    contract_type: str
    score: float
    
    def format_for_prompt(self) -> str:
        """Format user chunk for LLM prompt."""
        return (
            f"[ПОЛЬЗОВАТЕЛЬСКИЙ ЭТАЛОН]\n"
            f"Файл: {self.filename}\n"
            f"Тип договора: {self.contract_type}\n"
            f"Текст: {self.text}"
        )


@dataclass
class RAGResult:
    """Result of RAG search with metadata."""
    chunks: list[RAGChunk]
    user_chunks: list[UserRAGChunk]  # User's custom document chunks
    no_rag_context: bool  # True if no relevant chunks found after filtering


class RAGService:
    def __init__(self):
        self._encoder = None
        self._client = None
        self._ready = False
        self._init()

    def _init(self):
        try:
            self._load_encoder()
            self._setup_qdrant()
            self._index_norms()
            self._ready = True
            logger.info("RAG готов")
        except Exception as e:
            logger.error(f"RAG fallback: {e}")
            self._ready = False

    def _load_encoder(self):
        from sentence_transformers import SentenceTransformer
        self._encoder = SentenceTransformer(EMBEDDING_MODEL)

    def _setup_qdrant(self):
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams
        self._client = QdrantClient(host="qdrant", port=6333)
        cols = [c.name for c in self._client.get_collections().collections]
        if COLLECTION_NAME not in cols:
            self._client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(size=768, distance=Distance.COSINE),
            )

    def _index_norms(self):
        from qdrant_client.models import PointStruct, Distance, VectorParams
        with open(NORMS_PATH, encoding="utf-8") as f:
            norms = json.load(f)
        count = self._client.count(COLLECTION_NAME).count
        if count != len(norms):
            logger.info("Пересоздание коллекции норм: было %d, стало %d", count, len(norms))
            self._client.recreate_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(size=768, distance=Distance.COSINE),
            )
        else:
            logger.info("Коллекция норм синхронизирована по количеству: %d", count)
        texts = [f"passage: {n['safe_norm']}" for n in norms]
        vectors = self._encoder.encode(texts, batch_size=32, show_progress_bar=False)
        points = [
            PointStruct(
                id=n["id"], vector=v.tolist(),
                payload={
                    "safe_norm": n["safe_norm"], "risk_category": n["risk_category"],
                    "contract_type": self._normalize_contract_type(n.get("contract_type")),
                    "criticality": str(n.get("criticality", "medium")).lower(),
                    "deception_patterns": n.get("deception_patterns", []),
                    "legal_basis": n.get("legal_basis", []),
                    "topic": n["topic"],
                    "risky_pattern": n.get("risky_pattern", ""),
                }
            )
            for n, v in zip(norms, vectors)
        ]
        self._client.upsert(collection_name=COLLECTION_NAME, points=points)
        logger.info(f"Проиндексировано {len(points)} норм")

    @staticmethod
    def _normalize_contract_type(value: str | None) -> str:
        return (value or "").strip().lower()

    def _resolve_filter_contract_types(self, contract_type: str) -> list[str]:
        normalized = self._normalize_contract_type(contract_type)
        if not normalized or normalized == "иной":
            return []

        resolved = set(CONTRACT_TYPE_ALIASES.get(normalized, (normalized,)))
        resolved.update(UNIVERSAL_CONTRACT_TYPES)
        return sorted(resolved)

    def search(
        self,
        query: str,
        contract_type: str = "иной",
        top_k: int | None = None,
        user_id: UUID | None = None,
        max_chars: int | None = None,
    ) -> RAGResult:
        """Поиск релевантных норм в базе Qdrant, включая пользовательские эталоны.

        P1: Now includes user document search when user_id is provided.
        System chunks and user chunks are merged with deterministic priority:
        - System chunks come first (higher authority)
        - User chunks follow (personal context)
        - Total chunks limited by MAX_CHUNKS_PER_SEGMENT

        Returns:
            RAGResult with structured chunks, user_chunks, and no_rag_context flag.
            If no_rag_context=True, model should classify based on text only.
        """
        if not self._ready or not self._encoder:
            return RAGResult(chunks=[], user_chunks=[], no_rag_context=True)

        effective_top_k = top_k if top_k is not None else TOP_K
        system_chunks: list[RAGChunk] = []
        user_chunks: list[UserRAGChunk] = []

        try:
            from qdrant_client.models import Filter, FieldCondition, MatchAny, MatchValue

            qv = self._encoder.encode(f"query: {query}", show_progress_bar=False).tolist()
            
            # ── Step 1: Search system legal norms ──
            filter_obj = None
            allowed_types = self._resolve_filter_contract_types(contract_type)
            if allowed_types:
                filter_obj = Filter(
                    must=[
                        FieldCondition(
                            key="contract_type",
                            match=MatchAny(any=allowed_types),
                        )
                    ]
                )

            results = self._client.search(
                collection_name=COLLECTION_NAME,
                query_vector=qv,
                query_filter=filter_obj,
                limit=effective_top_k,
            )

            for hit in results:
                logger.debug(
                    "RAG candidate score=%.3f topic='%s' segment='%s...'",
                    hit.score,
                    hit.payload.get("topic", "?"),
                    query[:50],
                )

            filtered_hits = [
                hit for hit in results
                if hit.score >= MIN_RELEVANCE_SCORE
            ]
            
            discarded_count = len(results) - len(filtered_hits)
            if discarded_count > 0:
                logger.info(
                    "RAG: discarded %d system chunks below threshold %.2f",
                    discarded_count, MIN_RELEVANCE_SCORE,
                )

            for hit in filtered_hits:
                p = hit.payload
                legal_basis = p.get("legal_basis") or []
                specific_legal = [
                    lb for lb in legal_basis
                    if lb not in (
                        "ГК РФ ст. 309", "ГК РФ ст. 310", "ГК РФ ст. 421",
                        "ГК РФ ст. 431", "ГК РФ ст. 432", "ГК РФ ст. 450", "ГК РФ ст. 452",
                    )
                ] if isinstance(legal_basis, list) else []
                
                system_chunks.append(RAGChunk(
                    etalon=p.get("safe_norm", ""),
                    risk=p.get("risky_pattern", ""),
                    category=str(p.get("risk_category", "")).upper(),
                    topic=p.get("topic", ""),
                    criticality=str(p.get("criticality", "medium")).upper(),
                    legal_basis=specific_legal,
                    score=hit.score,
                ))

            # Deduplicate system chunks
            seen_hashes: set[str] = set()
            deduplicated_system: list[RAGChunk] = []
            for chunk in system_chunks:
                h = chunk.get_dedup_hash()
                if h in seen_hashes:
                    continue
                seen_hashes.add(h)
                deduplicated_system.append(chunk)

            # ── Step 2: Search user documents (if user_id provided) ──
            if user_id is not None:
                user_chunks = self._search_user_documents(qv, user_id, contract_type)
                logger.info(
                    "RAG: found %d user chunks for user %s",
                    len(user_chunks), user_id,
                )

            # ── Step 3: Deterministic merge with limits ──
            # Priority: system chunks first (higher authority), then user chunks
            # Reserve at least 1 slot for user chunk if user has documents
            max_system = MAX_CHUNKS_PER_SEGMENT
            if user_chunks:
                max_system = max(1, MAX_CHUNKS_PER_SEGMENT - 1)  # Leave room for 1 user chunk
            
            final_system = deduplicated_system[:max_system]
            final_user = user_chunks[:(MAX_CHUNKS_PER_SEGMENT - len(final_system))]

            for chunk in final_system:
                logger.info(
                    "RAG: using system chunk score=%.3f category='%s' topic='%s'",
                    chunk.score, chunk.category, chunk.topic,
                )
            for chunk in final_user:
                logger.info(
                    "RAG: using user chunk score=%.3f file='%s'",
                    chunk.score, chunk.filename,
                )

            no_rag_context = len(final_system) == 0 and len(final_user) == 0
            if no_rag_context:
                logger.info("RAG: no_rag_context=True for segment '%s...'", query[:40])

            return RAGResult(
                chunks=final_system,
                user_chunks=final_user,
                no_rag_context=no_rag_context,
            )

        except Exception as e:
            logger.error(f"Qdrant error: {e}")
            fallback_text = self._fallback(query)
            if fallback_text:
                return RAGResult(
                    chunks=[RAGChunk(
                        etalon="",
                        risk=fallback_text,
                        category="ОБЩИЙ",
                        topic="fallback",
                        criticality="MEDIUM",
                        legal_basis=[],
                        score=0.0,
                    )],
                    user_chunks=[],
                    no_rag_context=False,
                )
            return RAGResult(chunks=[], user_chunks=[], no_rag_context=True)
    
    def _search_user_documents(
        self,
        query_vector: list[float],
        user_id: UUID,
        contract_type: str,
    ) -> list[UserRAGChunk]:
        """Search user's custom documents in Qdrant.
        
        P1: Integrated into main RAG pipeline for unified context.
        """
        try:
            from qdrant_client.models import Filter, FieldCondition, MatchValue

            must_conditions = [
                FieldCondition(key="user_id", match=MatchValue(value=str(user_id)))
            ]
            if contract_type and contract_type != "иной":
                must_conditions.append(
                    FieldCondition(key="contract_type", match=MatchValue(value=contract_type))
                )

            results = self._client.search(
                collection_name="user_documents",
                query_vector=query_vector,
                query_filter=Filter(must=must_conditions),
                limit=2,  # Max 2 user chunks per segment
            )

            user_chunks: list[UserRAGChunk] = []
            for hit in results:
                if hit.score < MIN_RELEVANCE_SCORE:
                    continue
                p = hit.payload
                user_chunks.append(UserRAGChunk(
                    text=p.get("chunk_text", ""),
                    filename=p.get("filename", ""),
                    contract_type=p.get("contract_type", "иной"),
                    score=hit.score,
                ))
            
            return user_chunks
        except Exception as e:
            logger.warning("User document search failed: %s", e)
            return []
    
    def search_legacy(
        self,
        query: str,
        contract_type: str = "иной",
        top_k: int | None = None,
        user_id: UUID | None = None,
        max_chars: int | None = None,
    ) -> str | None:
        """Legacy search returning formatted string for backward compatibility."""
        result = self.search(query, contract_type, top_k, user_id, max_chars)
        return self.format_rag_context(result, max_chars)
    
    @staticmethod
    def format_rag_context(result: RAGResult, max_chars: int | None = None) -> str | None:
        """Format RAGResult as string for LLM prompt.
        
        P1: Now includes both system chunks and user chunks.
        Order: system chunks first (higher authority), then user chunks.
        """
        if result.no_rag_context:
            return None
        
        if not result.chunks and not result.user_chunks:
            return None
        
        parts: list[str] = []
        
        # Add system chunks first (higher authority)
        for chunk in result.chunks:
            parts.append(chunk.format_for_prompt())
        
        # Add user chunks (personal context)
        for user_chunk in result.user_chunks:
            parts.append(user_chunk.format_for_prompt())
        
        if not parts:
            return None
        
        return RAGService._truncate_by_norm_boundaries(parts, max_chars)

    @staticmethod
    def _truncate_by_norm_boundaries(parts: list[str], max_chars: int | None) -> str:
        """Join norm parts, dropping trailing ones if total exceeds max_chars.

        Unlike naive [:max_chars] slicing, this never cuts a norm mid-sentence.
        """
        if max_chars is None or max_chars <= 0:
            return "\n\n".join(parts)

        result_parts: list[str] = []
        total_len = 0
        separator_len = 2  # len("\n\n")

        for part in parts:
            added_len = len(part) + (separator_len if result_parts else 0)
            if total_len + added_len > max_chars and result_parts:
                # Already have at least one norm; stop adding more
                break
            result_parts.append(part)
            total_len += added_len

        return "\n\n".join(result_parts)

    def _fallback(self, segment: str) -> str | None:
        kw = {
            "финансовый": ["штраф", "неустойка", "оплата", "стоимость", "компенсация"],
            "правовой": ["права", "лицензия", "суд", "расторжение"],
            "операционный": ["срок", "приёмка", "субподрядчик", "уведомление"],
            "репутационный": ["конфиденциальность", "разглашение"],
            "интеллектуальный": ["исключительные права", "интеллектуальная собственность"],
        }
        s = segment.lower()
        for cat, words in kw.items():
            if any(w in s for w in words):
                return f"[{cat.upper()}] Проверьте на соответствие стандартным нормам."
        return None

    def get_stats(self) -> dict:
        if not self._ready:
            return {"status": "fallback", "norms_count": 0}
        try:
            return {
                "status": "ready",
                "norms_count": self._client.count(COLLECTION_NAME).count,
                "model": EMBEDDING_MODEL,
                "min_relevance_score": MIN_RELEVANCE_SCORE,
                "max_chunks_per_segment": MAX_CHUNKS_PER_SEGMENT,
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}
