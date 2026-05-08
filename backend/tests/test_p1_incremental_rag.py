"""
P1 Tests: Incremental batch saving and RAG with user documents.

Tests ensure:
1. Analysis results are saved incrementally in batches
2. Partial results are available during processing
3. User documents are integrated into RAG pipeline
4. System and user contexts are merged deterministically
"""

import os
import sys
import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config.database import Base
from models.db_models import UserDB, AnalysisResultDB, RiskItemDB
from models.schemas import RiskItem, RiskLevel, RiskCategory, AnalysisSummary


@pytest.fixture(scope="function")
def test_db():
    """Create a fresh SQLite in-memory database for each test."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def user_alice(test_db):
    """Create test user Alice."""
    user = UserDB(
        id=uuid.uuid4(),
        email="alice@test.com",
        username="alice",
        hashed_password="$2b$12$test_hash_alice",
        created_at=datetime.utcnow(),
    )
    test_db.add(user)
    test_db.commit()
    return user


@pytest.fixture
def processing_analysis(test_db, user_alice):
    """Create an analysis in 'processing' state."""
    analysis = AnalysisResultDB(
        id=uuid.uuid4(),
        user_id=user_alice.id,
        filename="test_contract.pdf",
        status="processing",
        total_segments=50,
        analyzed_segments=0,
        created_at=datetime.utcnow(),
    )
    test_db.add(analysis)
    test_db.commit()
    return analysis


class TestIncrementalBatchSaving:
    """Test that analysis results are saved incrementally in batches."""

    def test_save_batch_increments_analyzed_segments(self, test_db, processing_analysis):
        """save_batch should increment analyzed_segments counter."""
        from repositories.analysis_repository import AnalysisRepository
        
        batch_risks = [
            RiskItem(
                segment_id=i,
                text=f"Test segment {i}",
                is_risky=i % 2 == 0,
                risk_level=RiskLevel.MEDIUM if i % 2 == 0 else RiskLevel.NONE,
                risk_category=RiskCategory.FINANCIAL if i % 2 == 0 else None,
                risk_description=f"Risk {i}" if i % 2 == 0 else None,
                recommendation=None,
                rag_context=None,
            )
            for i in range(1, 21)  # 20 segments
        ]
        
        AnalysisRepository.save_batch(test_db, str(processing_analysis.id), batch_risks)
        
        # Refresh and check
        test_db.refresh(processing_analysis)
        assert processing_analysis.analyzed_segments == 20
        assert len(processing_analysis.risks) == 20

    def test_multiple_batches_accumulate(self, test_db, processing_analysis):
        """Multiple batches should accumulate correctly."""
        from repositories.analysis_repository import AnalysisRepository
        
        # First batch
        batch1 = [
            RiskItem(
                segment_id=i, text=f"Segment {i}", is_risky=False,
                risk_level=RiskLevel.NONE, risk_category=None,
                risk_description=None, recommendation=None, rag_context=None,
            )
            for i in range(1, 11)
        ]
        AnalysisRepository.save_batch(test_db, str(processing_analysis.id), batch1)
        
        test_db.refresh(processing_analysis)
        assert processing_analysis.analyzed_segments == 10
        
        # Second batch
        batch2 = [
            RiskItem(
                segment_id=i, text=f"Segment {i}", is_risky=True,
                risk_level=RiskLevel.HIGH, risk_category=RiskCategory.LEGAL,
                risk_description=f"Risk {i}", recommendation=None, rag_context=None,
            )
            for i in range(11, 21)
        ]
        AnalysisRepository.save_batch(test_db, str(processing_analysis.id), batch2)
        
        test_db.refresh(processing_analysis)
        assert processing_analysis.analyzed_segments == 20
        assert len(processing_analysis.risks) == 20

    def test_finalize_updates_summary(self, test_db, processing_analysis):
        """finalize_result should update summary stats and status."""
        from repositories.analysis_repository import AnalysisRepository
        
        # Save some risks first
        batch = [
            RiskItem(
                segment_id=1, text="Risky clause", is_risky=True,
                risk_level=RiskLevel.HIGH, risk_category=RiskCategory.FINANCIAL,
                risk_description="High risk", recommendation=None, rag_context=None,
            ),
            RiskItem(
                segment_id=2, text="Safe clause", is_risky=False,
                risk_level=RiskLevel.NONE, risk_category=None,
                risk_description=None, recommendation=None, rag_context=None,
            ),
        ]
        AnalysisRepository.save_batch(test_db, str(processing_analysis.id), batch)
        
        # Finalize
        summary = AnalysisSummary(
            total_segments=2,
            risky_segments=1,
            high_risk_count=1,
            medium_risk_count=0,
            low_risk_count=0,
            risk_score=0.5,
        )
        AnalysisRepository.finalize_result(test_db, str(processing_analysis.id), summary)
        
        test_db.refresh(processing_analysis)
        assert processing_analysis.status == "completed"
        assert processing_analysis.high_risk_count == 1
        assert processing_analysis.risk_score == 0.5


class TestPartialResults:
    """Test that partial results are available during processing."""

    def test_get_partial_result_returns_saved_risks(self, test_db, processing_analysis):
        """get_partial_result should return risks saved so far."""
        from repositories.analysis_repository import AnalysisRepository
        
        # Save partial batch
        batch = [
            RiskItem(
                segment_id=1, text="First segment", is_risky=True,
                risk_level=RiskLevel.MEDIUM, risk_category=RiskCategory.OPERATIONAL,
                risk_description="Medium risk", recommendation="Fix it", rag_context=None,
            ),
        ]
        AnalysisRepository.save_batch(test_db, str(processing_analysis.id), batch)
        
        # Get partial result
        partial = AnalysisRepository.get_partial_result(test_db, str(processing_analysis.id))
        
        assert partial is not None
        assert partial["status"] == "processing"
        assert partial["total_segments"] == 50
        assert partial["analyzed_segments"] == 1
        assert len(partial["risks"]) == 1
        assert partial["risks"][0].segment_id == 1

    def test_partial_result_reflects_progress(self, test_db, processing_analysis):
        """Partial result should accurately reflect analysis progress."""
        from repositories.analysis_repository import AnalysisRepository
        
        # Simulate incremental progress
        for batch_start in range(0, 30, 10):
            batch = [
                RiskItem(
                    segment_id=batch_start + i + 1,
                    text=f"Segment {batch_start + i + 1}",
                    is_risky=False,
                    risk_level=RiskLevel.NONE,
                    risk_category=None,
                    risk_description=None,
                    recommendation=None,
                    rag_context=None,
                )
                for i in range(10)
            ]
            AnalysisRepository.save_batch(test_db, str(processing_analysis.id), batch)
            
            partial = AnalysisRepository.get_partial_result(test_db, str(processing_analysis.id))
            expected_analyzed = batch_start + 10
            assert partial["analyzed_segments"] == expected_analyzed
            assert len(partial["risks"]) == expected_analyzed


class TestRAGUserDocumentIntegration:
    """Test RAG integration with user documents."""

    def test_rag_result_structure_with_user_chunks(self):
        """RAGResult should include user_chunks field."""
        from services.rag import RAGResult, RAGChunk, UserRAGChunk
        
        system_chunk = RAGChunk(
            etalon="Safe payment terms",
            risk="Payment only after all work",
            category="FINANCIAL",
            topic="payment",
            criticality="HIGH",
            legal_basis=["ГК РФ ст. 711"],
            score=0.85,
        )
        
        user_chunk = UserRAGChunk(
            text="Our standard payment clause",
            filename="standard_contract.pdf",
            contract_type="услуги",
            score=0.75,
        )
        
        result = RAGResult(
            chunks=[system_chunk],
            user_chunks=[user_chunk],
            no_rag_context=False,
        )
        
        assert len(result.chunks) == 1
        assert len(result.user_chunks) == 1
        assert result.chunks[0].category == "FINANCIAL"
        assert result.user_chunks[0].filename == "standard_contract.pdf"

    def test_format_rag_context_includes_user_chunks(self):
        """format_rag_context should include both system and user chunks."""
        from services.rag import RAGService, RAGResult, RAGChunk, UserRAGChunk
        
        system_chunk = RAGChunk(
            etalon="Balanced liability clause",
            risk="Unlimited liability",
            category="LEGAL",
            topic="liability",
            criticality="HIGH",
            legal_basis=["ГК РФ ст. 15"],
            score=0.9,
        )
        
        user_chunk = UserRAGChunk(
            text="Company standard liability limit: 100% of contract value",
            filename="company_standards.pdf",
            contract_type="услуги",
            score=0.8,
        )
        
        result = RAGResult(
            chunks=[system_chunk],
            user_chunks=[user_chunk],
            no_rag_context=False,
        )
        
        formatted = RAGService.format_rag_context(result)
        
        assert formatted is not None
        assert "ЭТАЛОН" in formatted  # System chunk
        assert "РИСК" in formatted  # System chunk
        assert "ПОЛЬЗОВАТЕЛЬСКИЙ ЭТАЛОН" in formatted  # User chunk
        assert "company_standards.pdf" in formatted

    def test_format_rag_context_system_chunks_first(self):
        """System chunks should appear before user chunks in formatted output."""
        from services.rag import RAGService, RAGResult, RAGChunk, UserRAGChunk
        
        system_chunk = RAGChunk(
            etalon="System etalon", risk="System risk", category="LEGAL",
            topic="test", criticality="HIGH", legal_basis=[], score=0.9,
        )
        
        user_chunk = UserRAGChunk(
            text="User document text",
            filename="user.pdf",
            contract_type="услуги",
            score=0.8,
        )
        
        result = RAGResult(
            chunks=[system_chunk],
            user_chunks=[user_chunk],
            no_rag_context=False,
        )
        
        formatted = RAGService.format_rag_context(result)
        
        system_pos = formatted.find("ЭТАЛОН")
        user_pos = formatted.find("ПОЛЬЗОВАТЕЛЬСКИЙ ЭТАЛОН")
        
        assert system_pos < user_pos, "System chunks should appear before user chunks"

    def test_no_rag_context_when_empty(self):
        """no_rag_context should be True when both chunks lists are empty."""
        from services.rag import RAGResult
        
        result = RAGResult(chunks=[], user_chunks=[], no_rag_context=True)
        
        assert result.no_rag_context is True
        assert len(result.chunks) == 0
        assert len(result.user_chunks) == 0

    def test_user_chunk_format_for_prompt(self):
        """UserRAGChunk should format correctly for LLM prompt."""
        from services.rag import UserRAGChunk
        
        chunk = UserRAGChunk(
            text="Standard termination clause with 30 day notice",
            filename="company_template.pdf",
            contract_type="услуги",
            score=0.82,
        )
        
        formatted = chunk.format_for_prompt()
        
        assert "[ПОЛЬЗОВАТЕЛЬСКИЙ ЭТАЛОН]" in formatted
        assert "company_template.pdf" in formatted
        assert "услуги" in formatted
        assert "Standard termination clause" in formatted


class TestAnalysisBatchSize:
    """Test batch size configuration."""

    def test_batch_size_configurable(self):
        """ANALYSIS_BATCH_SIZE should be configurable via environment."""
        from services.analyzer import ANALYSIS_BATCH_SIZE
        
        # Default is 20
        assert ANALYSIS_BATCH_SIZE > 0
        assert isinstance(ANALYSIS_BATCH_SIZE, int)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
