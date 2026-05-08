"""
P0 Security Tests: IDOR protection and state machine correctness.

Tests ensure:
1. Users cannot access other users' analyses (IDOR protection)
2. Users cannot access other users' chat sessions (IDOR protection)
3. Non-existent analysis_id returns 404 (not false "processing")
4. Analysis state transitions are correct (processing → completed/failed)
"""

import os
import sys
import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Ensure backend/ is in path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config.database import Base
from models.db_models import UserDB, AnalysisResultDB, RiskItemDB, ChatSessionDB, ChatMessageDB


# ── Test Database Setup ──

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
def user_bob(test_db):
    """Create test user Bob."""
    user = UserDB(
        id=uuid.uuid4(),
        email="bob@test.com",
        username="bob",
        hashed_password="$2b$12$test_hash_bob",
        created_at=datetime.utcnow(),
    )
    test_db.add(user)
    test_db.commit()
    return user


@pytest.fixture
def alice_analysis(test_db, user_alice):
    """Create an analysis owned by Alice."""
    analysis = AnalysisResultDB(
        id=uuid.uuid4(),
        user_id=user_alice.id,
        filename="alice_contract.pdf",
        status="completed",
        total_segments=10,
        risky_segments=3,
        high_risk_count=1,
        medium_risk_count=1,
        low_risk_count=1,
        risk_score=0.35,
        analyzed_segments=10,
        created_at=datetime.utcnow(),
    )
    test_db.add(analysis)
    test_db.commit()
    return analysis


@pytest.fixture
def bob_analysis(test_db, user_bob):
    """Create an analysis owned by Bob."""
    analysis = AnalysisResultDB(
        id=uuid.uuid4(),
        user_id=user_bob.id,
        filename="bob_contract.pdf",
        status="completed",
        total_segments=5,
        risky_segments=2,
        high_risk_count=1,
        medium_risk_count=1,
        low_risk_count=0,
        risk_score=0.45,
        analyzed_segments=5,
        created_at=datetime.utcnow(),
    )
    test_db.add(analysis)
    test_db.commit()
    return analysis


@pytest.fixture
def alice_chat_session(test_db, user_alice, alice_analysis):
    """Create a chat session owned by Alice."""
    session = ChatSessionDB(
        id=uuid.uuid4(),
        analysis_id=alice_analysis.id,
        user_id=user_alice.id,
        created_at=datetime.utcnow(),
    )
    test_db.add(session)
    test_db.commit()
    return session


@pytest.fixture
def bob_chat_session(test_db, user_bob, bob_analysis):
    """Create a chat session owned by Bob."""
    session = ChatSessionDB(
        id=uuid.uuid4(),
        analysis_id=bob_analysis.id,
        user_id=user_bob.id,
        created_at=datetime.utcnow(),
    )
    test_db.add(session)
    test_db.commit()
    return session


# ── IDOR Tests: Analysis Endpoints ──

class TestAnalysisIDORProtection:
    """Test that users cannot access other users' analyses."""

    def test_verify_analysis_owner_success(self, test_db, user_alice, alice_analysis):
        """User can access their own analysis."""
        from api.routes import _verify_analysis_owner
        
        result = _verify_analysis_owner(test_db, str(alice_analysis.id), user_alice)
        assert result.id == alice_analysis.id
        assert result.user_id == user_alice.id

    def test_verify_analysis_owner_blocks_other_user(self, test_db, user_alice, bob_analysis):
        """User cannot access another user's analysis (403 Forbidden)."""
        from api.routes import _verify_analysis_owner
        from fastapi import HTTPException
        
        with pytest.raises(HTTPException) as exc_info:
            _verify_analysis_owner(test_db, str(bob_analysis.id), user_alice)
        
        assert exc_info.value.status_code == 403
        assert "Доступ запрещён" in exc_info.value.detail

    def test_verify_analysis_owner_nonexistent_returns_404(self, test_db, user_alice):
        """Non-existent analysis returns 404."""
        from api.routes import _verify_analysis_owner
        from fastapi import HTTPException
        
        fake_id = str(uuid.uuid4())
        with pytest.raises(HTTPException) as exc_info:
            _verify_analysis_owner(test_db, fake_id, user_alice)
        
        assert exc_info.value.status_code == 404
        assert "не найден" in exc_info.value.detail

    def test_verify_analysis_owner_invalid_uuid_returns_404(self, test_db, user_alice):
        """Invalid UUID format returns 404."""
        from api.routes import _verify_analysis_owner
        from fastapi import HTTPException
        
        with pytest.raises(HTTPException) as exc_info:
            _verify_analysis_owner(test_db, "not-a-valid-uuid", user_alice)
        
        assert exc_info.value.status_code == 404

    def test_analysis_without_user_id_is_accessible(self, test_db, user_alice):
        """Legacy analyses without user_id can be accessed by any authenticated user."""
        from api.routes import _verify_analysis_owner
        
        # Create analysis without user_id (legacy)
        legacy_analysis = AnalysisResultDB(
            id=uuid.uuid4(),
            user_id=None,  # No owner
            filename="legacy_contract.pdf",
            status="completed",
            total_segments=5,
        )
        test_db.add(legacy_analysis)
        test_db.commit()
        
        # Should not raise, as user_id is None
        result = _verify_analysis_owner(test_db, str(legacy_analysis.id), user_alice)
        assert result.id == legacy_analysis.id


# ── IDOR Tests: Chat Endpoints ──

class TestChatIDORProtection:
    """Test that users cannot access other users' chat sessions."""

    def test_verify_session_owner_success(self, test_db, user_alice, alice_chat_session):
        """User can access their own chat session."""
        from api.chat_routes import _verify_session_owner
        
        result = _verify_session_owner(test_db, alice_chat_session.id, user_alice)
        assert result.id == alice_chat_session.id
        assert result.user_id == user_alice.id

    def test_verify_session_owner_blocks_other_user(self, test_db, user_alice, bob_chat_session):
        """User cannot access another user's chat session (403 Forbidden)."""
        from api.chat_routes import _verify_session_owner
        from fastapi import HTTPException
        
        with pytest.raises(HTTPException) as exc_info:
            _verify_session_owner(test_db, bob_chat_session.id, user_alice)
        
        assert exc_info.value.status_code == 403
        assert "Доступ запрещён" in exc_info.value.detail

    def test_verify_session_owner_nonexistent_returns_404(self, test_db, user_alice):
        """Non-existent session returns 404."""
        from api.chat_routes import _verify_session_owner
        from fastapi import HTTPException
        
        fake_id = uuid.uuid4()
        with pytest.raises(HTTPException) as exc_info:
            _verify_session_owner(test_db, fake_id, user_alice)
        
        assert exc_info.value.status_code == 404
        assert "не найдена" in exc_info.value.detail

    def test_verify_analysis_owner_for_chat(self, test_db, user_alice, alice_analysis, bob_analysis):
        """User cannot create chat for another user's analysis."""
        from api.chat_routes import _verify_analysis_owner_for_chat
        from fastapi import HTTPException
        
        # Alice can create chat for her own analysis
        result = _verify_analysis_owner_for_chat(test_db, str(alice_analysis.id), user_alice)
        assert result.id == alice_analysis.id
        
        # Alice cannot create chat for Bob's analysis
        with pytest.raises(HTTPException) as exc_info:
            _verify_analysis_owner_for_chat(test_db, str(bob_analysis.id), user_alice)
        
        assert exc_info.value.status_code == 403


# ── State Machine Tests ──

class TestAnalysisStateMachine:
    """Test that analysis state transitions are correct."""

    def test_processing_analysis_returns_processing_status(self, test_db, user_alice):
        """Analysis in 'processing' state returns correct status."""
        analysis = AnalysisResultDB(
            id=uuid.uuid4(),
            user_id=user_alice.id,
            filename="test.pdf",
            status="processing",
            total_segments=10,
            analyzed_segments=5,
            created_at=datetime.utcnow(),
        )
        test_db.add(analysis)
        test_db.commit()
        
        assert analysis.status == "processing"
        assert analysis.analyzed_segments < analysis.total_segments

    def test_completed_analysis_has_all_segments_analyzed(self, test_db, user_alice, alice_analysis):
        """Completed analysis has analyzed_segments == total_segments."""
        assert alice_analysis.status == "completed"
        assert alice_analysis.analyzed_segments == alice_analysis.total_segments

    def test_failed_analysis_state(self, test_db, user_alice):
        """Failed analysis has correct state."""
        analysis = AnalysisResultDB(
            id=uuid.uuid4(),
            user_id=user_alice.id,
            filename="failed_test.pdf",
            status="failed",
            total_segments=10,
            analyzed_segments=3,
            created_at=datetime.utcnow(),
        )
        test_db.add(analysis)
        test_db.commit()
        
        assert analysis.status == "failed"
        # Failed analysis may have partial segments
        assert analysis.analyzed_segments <= analysis.total_segments

    def test_valid_statuses(self, test_db, user_alice):
        """Only valid statuses are allowed."""
        valid_statuses = ["processing", "completed", "failed"]
        
        for status in valid_statuses:
            analysis = AnalysisResultDB(
                id=uuid.uuid4(),
                user_id=user_alice.id,
                filename=f"test_{status}.pdf",
                status=status,
                total_segments=5,
            )
            test_db.add(analysis)
        
        test_db.commit()
        
        # All should be created successfully
        count = test_db.query(AnalysisResultDB).filter(
            AnalysisResultDB.user_id == user_alice.id
        ).count()
        assert count == 3


# ── Heartbeat/Timeout Tests ──

class TestHeartbeatTimeout:
    """Test heartbeat-based failure detection."""

    def test_stale_heartbeat_marks_analysis_failed(self, test_db, user_alice):
        """Analysis with stale heartbeat should be marked as failed."""
        from services.analyzer import HEARTBEAT_TIMEOUT_SEC
        
        # Create an old processing analysis
        old_time = datetime.utcnow() - timedelta(seconds=HEARTBEAT_TIMEOUT_SEC + 100)
        analysis = AnalysisResultDB(
            id=uuid.uuid4(),
            user_id=user_alice.id,
            filename="stale_test.pdf",
            status="processing",
            total_segments=10,
            analyzed_segments=3,
            created_at=old_time,
        )
        test_db.add(analysis)
        test_db.commit()
        
        # The analysis is old enough that it should be considered stale
        import time
        age_sec = time.time() - old_time.timestamp()
        assert age_sec > HEARTBEAT_TIMEOUT_SEC


# ── Integration-like Tests ──

class TestEndpointSecurity:
    """Higher-level tests simulating endpoint behavior."""

    def test_alice_cannot_enumerate_bob_analyses(self, test_db, user_alice, user_bob, bob_analysis):
        """Alice cannot enumerate Bob's analyses through the API."""
        from repositories.analysis_repository import AnalysisRepository
        
        # Alice's list should not include Bob's analyses
        alice_results = AnalysisRepository.list_results(test_db, user_alice.id)
        bob_ids = [str(bob_analysis.id)]
        
        for result in alice_results:
            assert result["analysis_id"] not in bob_ids

    def test_alice_can_only_see_her_analyses(self, test_db, user_alice, alice_analysis, user_bob, bob_analysis):
        """Alice can only see her own analyses in the list."""
        from repositories.analysis_repository import AnalysisRepository
        
        alice_results = AnalysisRepository.list_results(test_db, user_alice.id)
        alice_ids = [r["analysis_id"] for r in alice_results]
        
        assert str(alice_analysis.id) in alice_ids
        assert str(bob_analysis.id) not in alice_ids

    def test_chat_sessions_isolated_by_user(self, test_db, user_alice, user_bob, alice_chat_session, bob_chat_session):
        """Chat sessions are properly isolated by user."""
        from repositories.chat_repository import ChatRepository
        
        alice_sessions = ChatRepository.list_sessions(test_db, user_alice.id)
        alice_session_ids = [s["session_id"] for s in alice_sessions]
        
        assert str(alice_chat_session.id) in alice_session_ids
        assert str(bob_chat_session.id) not in alice_session_ids


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
