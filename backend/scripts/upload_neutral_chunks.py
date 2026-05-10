#!/usr/bin/env python3
"""
Upload neutral safe chunks to Qdrant to reduce false positives.

These chunks represent standard, balanced contract formulations that should
outcompete risky RAG context when a neutral segment is being analyzed.

Usage:
  # From inside the backend Docker container:
  python scripts/upload_neutral_chunks.py

  # Or from host via docker exec:
  docker exec -it lexguard-backend python scripts/upload_neutral_chunks.py

The script:
  1. Loads neutral chunks from data/neutral_safe_chunks.json
  2. Builds embeddings using the SAME model and format as _index_norms()
     (i.e. "passage: {safe_norm} {risky_pattern}")
  3. Upserts points into the existing "legal_norms" Qdrant collection
  4. Does NOT recreate the collection — only adds/updates the 6 new points

After running, restart the backend so that _index_norms() picks up the new
total count and does NOT trigger a full recreation.
Alternatively, add the chunks to legal_norms.json directly (see --merge flag).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Paths relative to this script
SCRIPT_DIR = Path(__file__).parent
BACKEND_DIR = SCRIPT_DIR.parent
DATA_DIR = BACKEND_DIR / "data"
NEUTRAL_CHUNKS_PATH = DATA_DIR / "neutral_safe_chunks.json"
LEGAL_NORMS_PATH = DATA_DIR / "legal_norms.json"

# Must match rag.py exactly
COLLECTION_NAME = "legal_norms"
EMBEDDING_MODEL = "intfloat/multilingual-e5-base"
QDRANT_HOST = "qdrant"
QDRANT_PORT = 6333


def load_neutral_chunks() -> list[dict]:
    """Load neutral chunk definitions from JSON file."""
    with open(NEUTRAL_CHUNKS_PATH, encoding="utf-8") as f:
        chunks = json.load(f)
    logger.info("Loaded %d neutral chunks from %s", len(chunks), NEUTRAL_CHUNKS_PATH.name)
    return chunks


def normalize_contract_type(value: str | None) -> str:
    """Mirror RAGService._normalize_contract_type()."""
    return (value or "").strip().lower()


def build_embedding_texts(chunks: list[dict]) -> list[str]:
    """Build embedding input texts in the same format as rag.py _index_norms().

    Format: "passage: {safe_norm} {risky_pattern}"
    This is critical — the embedding must be built from the same fields
    so that cosine similarity is comparable to existing norms.
    """
    texts = []
    for chunk in chunks:
        text = f"passage: {chunk['safe_norm']} {chunk.get('risky_pattern', '')}"
        texts.append(text)
        logger.debug("Embedding text: %s", text[:100])
    return texts


def upload_to_qdrant(chunks: list[dict], dry_run: bool = False) -> None:
    """Encode chunks and upsert into Qdrant collection."""
    from sentence_transformers import SentenceTransformer
    from qdrant_client import QdrantClient
    from qdrant_client.models import PointStruct

    # Load encoder (same model as rag.py)
    logger.info("Loading embedding model: %s", EMBEDDING_MODEL)
    encoder = SentenceTransformer(EMBEDDING_MODEL)

    # Build embedding texts (same format as _index_norms)
    texts = build_embedding_texts(chunks)
    logger.info("Encoding %d texts...", len(texts))
    vectors = encoder.encode(texts, batch_size=32, show_progress_bar=True)

    # Build Qdrant points (same payload structure as _index_norms)
    points = []
    for chunk, vector in zip(chunks, vectors):
        point = PointStruct(
            id=chunk["id"],
            vector=vector.tolist(),
            payload={
                "safe_norm": chunk["safe_norm"],
                "risk_category": chunk["risk_category"],
                "contract_type": normalize_contract_type(chunk.get("contract_type")),
                "criticality": str(chunk.get("criticality", "medium")).lower(),
                "deception_patterns": chunk.get("deception_patterns", []),
                "legal_basis": chunk.get("legal_basis", []),
                "topic": chunk["topic"],
                "risky_pattern": chunk.get("risky_pattern", ""),
            },
        )
        points.append(point)
        logger.info(
            "  Point id=%d topic='%s' contract_type='%s'",
            chunk["id"], chunk["topic"], chunk.get("contract_type", "все"),
        )

    if dry_run:
        logger.info("DRY RUN: would upsert %d points. Skipping.", len(points))
        return

    # Connect to Qdrant and upsert
    logger.info("Connecting to Qdrant at %s:%d", QDRANT_HOST, QDRANT_PORT)
    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

    # Verify collection exists
    collections = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME not in collections:
        logger.error(
            "Collection '%s' not found! Available: %s",
            COLLECTION_NAME, collections,
        )
        sys.exit(1)

    current_count = client.count(COLLECTION_NAME).count
    logger.info("Current collection count: %d", current_count)

    # Upsert (will add or update points by ID)
    client.upsert(collection_name=COLLECTION_NAME, points=points)

    new_count = client.count(COLLECTION_NAME).count
    logger.info(
        "Upsert complete. Collection count: %d -> %d (+%d)",
        current_count, new_count, new_count - current_count,
    )


def merge_into_legal_norms(chunks: list[dict]) -> None:
    """Merge neutral chunks into the main legal_norms.json file.

    This ensures that when _index_norms() runs on next restart,
    it will include these chunks and the count check will pass.
    """
    with open(LEGAL_NORMS_PATH, encoding="utf-8") as f:
        norms = json.load(f)

    existing_ids = {n["id"] for n in norms}
    added = 0
    updated = 0

    for chunk in chunks:
        if chunk["id"] in existing_ids:
            # Update existing entry
            for i, n in enumerate(norms):
                if n["id"] == chunk["id"]:
                    norms[i] = chunk
                    updated += 1
                    break
        else:
            norms.append(chunk)
            added += 1

    with open(LEGAL_NORMS_PATH, "w", encoding="utf-8") as f:
        json.dump(norms, f, ensure_ascii=False, indent=2)

    logger.info(
        "Merged into %s: %d added, %d updated. Total: %d norms.",
        LEGAL_NORMS_PATH.name, added, updated, len(norms),
    )


def main():
    parser = argparse.ArgumentParser(
        description="Upload neutral safe chunks to Qdrant (reduce false positives)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be uploaded without actually upserting",
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help="Also merge chunks into legal_norms.json for persistence across restarts",
    )
    parser.add_argument(
        "--merge-only",
        action="store_true",
        help="Only merge into legal_norms.json, don't upload to Qdrant directly",
    )
    args = parser.parse_args()

    chunks = load_neutral_chunks()

    if not chunks:
        logger.warning("No chunks to upload")
        return

    logger.info("=" * 60)
    logger.info("Neutral Safe Chunks Upload")
    logger.info("=" * 60)

    for chunk in chunks:
        logger.info(
            "  [%d] %s — %s (criticality=%s)",
            chunk["id"], chunk["topic"],
            chunk.get("contract_type", "все"), chunk.get("criticality", "?"),
        )

    if args.merge_only:
        merge_into_legal_norms(chunks)
        logger.info(
            "Done! Restart the backend for changes to take effect "
            "(the _index_norms() will re-index all norms including the new ones)."
        )
        return

    upload_to_qdrant(chunks, dry_run=args.dry_run)

    if args.merge:
        merge_into_legal_norms(chunks)
        logger.info(
            "Chunks uploaded AND merged. On next restart, "
            "_index_norms() will see the correct count."
        )
    else:
        logger.warning(
            "Chunks uploaded to Qdrant but NOT merged into legal_norms.json. "
            "On next restart, _index_norms() will see a count mismatch and "
            "RECREATE the collection (losing these chunks). "
            "Run with --merge to persist, or manually add to legal_norms.json."
        )


if __name__ == "__main__":
    main()
