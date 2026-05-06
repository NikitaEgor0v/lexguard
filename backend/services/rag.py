import json
import logging
from pathlib import Path
from uuid import UUID

logger = logging.getLogger(__name__)

NORMS_PATH = Path(__file__).parent.parent / "data" / "legal_norms.json"
COLLECTION_NAME = "legal_norms"
EMBEDDING_MODEL = "intfloat/multilingual-e5-base"
TOP_K = 2
SCORE_THRESHOLD = 0.55
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
    ) -> str | None:
        """Поиск релевантных норм в базе Qdrant, включая пользовательские эталоны.

        Args:
            top_k: Number of norms to retrieve (defaults to module-level TOP_K).
            max_chars: Soft limit on total context length; truncation happens
                       at norm boundaries so no norm is ever cut mid-text.
        """
        if not self._ready or not self._encoder:
            return None

        effective_top_k = top_k if top_k is not None else TOP_K

        try:
            # 1. Search standard legal norms
            from qdrant_client.models import Filter, FieldCondition, MatchAny

            qv = self._encoder.encode(f"query: {query}", show_progress_bar=False).tolist()
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
                score_threshold=SCORE_THRESHOLD,
            )

            parts: list[str] = []

            # 2. Add custom user documents if user_id is provided
            if user_id:
                from services.document_service import DocumentService
                doc_service = DocumentService()
                user_context = doc_service.search_user_documents(
                    segment=query, user_id=user_id, contract_type=contract_type, top_k=2
                )
                if user_context:
                    parts.append(user_context)

            # 3. Add standard legal norms — compact format to fit small context windows
            for hit in results:
                p = hit.payload
                criticality = str(p.get("criticality", "medium")).upper()
                deception_patterns = p.get("deception_patterns") or []
                legal_basis = p.get("legal_basis") or []
                # Concise deception text — only first 2 patterns to save space
                deception_text = ""
                if isinstance(deception_patterns, list) and deception_patterns:
                    deception_text = " Уловки: " + "; ".join(str(x) for x in deception_patterns[:2])
                # Concise legal basis — only first 2 specific references (skip generic ГК 309/310/421)
                specific_legal = [lb for lb in legal_basis if lb not in (
                    "ГК РФ ст. 309", "ГК РФ ст. 310", "ГК РФ ст. 421",
                    "ГК РФ ст. 431", "ГК РФ ст. 432", "ГК РФ ст. 450", "ГК РФ ст. 452",
                )] if isinstance(legal_basis, list) else []
                legal_text = ""
                if specific_legal:
                    legal_text = " Основание: " + "; ".join(str(x) for x in specific_legal[:2])
                parts.append(
                    f"[{p.get('risk_category', '?').upper()} | {p.get('topic', '?')} | {criticality}] "
                    f"Эталон: {p.get('safe_norm', '')} "
                    f"Риск: {p.get('risky_pattern', '')}"
                    f"{deception_text}"
                    f"{legal_text}"
                )

            if not parts:
                return None

            # Smart truncation: drop trailing norms that don't fit, never cut mid-norm
            return self._truncate_by_norm_boundaries(parts, max_chars)
        except Exception as e:
            logger.error(f"Qdrant error: {e}")
            return self._fallback(query)

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
            return {"status": "ready", "norms_count": self._client.count(COLLECTION_NAME).count, "model": EMBEDDING_MODEL}
        except Exception as e:
            return {"status": "error", "error": str(e)}
