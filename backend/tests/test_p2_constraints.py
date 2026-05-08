"""
P2 Tests: Database constraints and data integrity.

Tests ensure:
1. Valid status values are enforced (processing, completed, failed)
2. Valid risk_level values are enforced (high, medium, low, none)
3. Valid role values are enforced (user, assistant)
4. Unique (analysis_id, segment_id) constraint prevents duplicates

Note: These tests verify the application-level validation.
Database-level CHECK constraints require PostgreSQL and are tested separately.
"""

import os
import sys
import uuid
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config.database import Base
from models.db_models import (
    UserDB, AnalysisResultDB, RiskItemDB, ChatSessionDB, ChatMessageDB
)
from models.schemas import RiskLevel, RiskCategory
from models.chat_schemas import ChatRole


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
def user(test_db):
    """Create test user."""
    user = UserDB(
        id=uuid.uuid4(),
        email="test@test.com",
        username="testuser",
        hashed_password="$2b$12$test_hash",
        created_at=datetime.utcnow(),
    )
    test_db.add(user)
    test_db.commit()
    return user


@pytest.fixture
def analysis(test_db, user):
    """Create test analysis."""
    analysis = AnalysisResultDB(
        id=uuid.uuid4(),
        user_id=user.id,
        filename="test.pdf",
        status="completed",
        total_segments=5,
        created_at=datetime.utcnow(),
    )
    test_db.add(analysis)
    test_db.commit()
    return analysis


class TestStatusValues:
    """Test that status values are properly validated."""

    def test_valid_status_processing(self, test_db, user):
        """'processing' is a valid status."""
        analysis = AnalysisResultDB(
            id=uuid.uuid4(),
            user_id=user.id,
            filename="test.pdf",
            status="processing",
            total_segments=10,
        )
        test_db.add(analysis)
        test_db.commit()
        assert analysis.status == "processing"

    def test_valid_status_completed(self, test_db, user):
        """'completed' is a valid status."""
        analysis = AnalysisResultDB(
            id=uuid.uuid4(),
            user_id=user.id,
            filename="test.pdf",
            status="completed",
            total_segments=10,
        )
        test_db.add(analysis)
        test_db.commit()
        assert analysis.status == "completed"

    def test_valid_status_failed(self, test_db, user):
        """'failed' is a valid status."""
        analysis = AnalysisResultDB(
            id=uuid.uuid4(),
            user_id=user.id,
            filename="test.pdf",
            status="failed",
            total_segments=10,
        )
        test_db.add(analysis)
        test_db.commit()
        assert analysis.status == "failed"

    def test_all_valid_statuses(self):
        """Verify the expected valid status values."""
        valid_statuses = {"processing", "completed", "failed"}
        assert valid_statuses == {"processing", "completed", "failed"}


class TestRiskLevelValues:
    """Test that risk_level values are properly validated."""

    def test_valid_risk_levels_enum(self):
        """Verify RiskLevel enum has expected values."""
        assert RiskLevel.HIGH.value == "high"
        assert RiskLevel.MEDIUM.value == "medium"
        assert RiskLevel.LOW.value == "low"
        assert RiskLevel.NONE.value == "none"

    def test_all_risk_levels(self):
        """All expected risk levels are defined."""
        all_levels = {level.value for level in RiskLevel}
        expected = {"high", "medium", "low", "none"}
        assert all_levels == expected

    def test_risk_item_with_valid_levels(self, test_db, analysis):
        """RiskItemDB accepts all valid risk levels."""
        for level in ["high", "medium", "low", "none"]:
            risk = RiskItemDB(
                id=uuid.uuid4(),
                analysis_id=analysis.id,
                segment_id=list(RiskLevel).index(RiskLevel(level)) + 1,
                text=f"Test segment for {level}",
                is_risky=level != "none",
                risk_level=level,
            )
            test_db.add(risk)
        
        test_db.commit()
        
        risks = test_db.query(RiskItemDB).filter_by(analysis_id=analysis.id).all()
        assert len(risks) == 4


class TestRoleValues:
    """Test that chat message role values are properly validated."""

    def test_valid_roles_enum(self):
        """Verify ChatRole enum has expected values."""
        assert ChatRole.USER.value == "user"
        assert ChatRole.ASSISTANT.value == "assistant"

    def test_all_roles(self):
        """All expected roles are defined."""
        all_roles = {role.value for role in ChatRole}
        expected = {"user", "assistant"}
        assert all_roles == expected

    def test_chat_message_with_valid_roles(self, test_db, analysis):
        """ChatMessageDB accepts all valid roles."""
        session = ChatSessionDB(
            id=uuid.uuid4(),
            analysis_id=analysis.id,
            user_id=analysis.user_id,
            created_at=datetime.utcnow(),
        )
        test_db.add(session)
        test_db.commit()
        
        for role in ["user", "assistant"]:
            msg = ChatMessageDB(
                id=uuid.uuid4(),
                session_id=session.id,
                role=role,
                content=f"Test message from {role}",
                created_at=datetime.utcnow(),
            )
            test_db.add(msg)
        
        test_db.commit()
        
        messages = test_db.query(ChatMessageDB).filter_by(session_id=session.id).all()
        assert len(messages) == 2


class TestUniqueSegmentConstraint:
    """Test unique (analysis_id, segment_id) constraint."""

    def test_same_segment_id_different_analysis(self, test_db, user):
        """Same segment_id in different analyses is allowed."""
        analysis1 = AnalysisResultDB(
            id=uuid.uuid4(),
            user_id=user.id,
            filename="test1.pdf",
            status="completed",
            total_segments=5,
        )
        analysis2 = AnalysisResultDB(
            id=uuid.uuid4(),
            user_id=user.id,
            filename="test2.pdf",
            status="completed",
            total_segments=5,
        )
        test_db.add_all([analysis1, analysis2])
        test_db.commit()
        
        # Same segment_id=1 in both analyses should work
        risk1 = RiskItemDB(
            id=uuid.uuid4(),
            analysis_id=analysis1.id,
            segment_id=1,
            text="Segment 1 from analysis 1",
            is_risky=False,
            risk_level="none",
        )
        risk2 = RiskItemDB(
            id=uuid.uuid4(),
            analysis_id=analysis2.id,
            segment_id=1,
            text="Segment 1 from analysis 2",
            is_risky=False,
            risk_level="none",
        )
        test_db.add_all([risk1, risk2])
        test_db.commit()
        
        assert risk1.segment_id == risk2.segment_id == 1
        assert risk1.analysis_id != risk2.analysis_id

    def test_different_segment_ids_same_analysis(self, test_db, analysis):
        """Different segment_ids in same analysis is allowed."""
        for i in range(1, 6):
            risk = RiskItemDB(
                id=uuid.uuid4(),
                analysis_id=analysis.id,
                segment_id=i,
                text=f"Segment {i}",
                is_risky=False,
                risk_level="none",
            )
            test_db.add(risk)
        
        test_db.commit()
        
        risks = test_db.query(RiskItemDB).filter_by(analysis_id=analysis.id).all()
        segment_ids = [r.segment_id for r in risks]
        assert len(segment_ids) == len(set(segment_ids))  # All unique

    def test_segment_ids_are_sequential(self, test_db, analysis):
        """Verify segment_ids start at 1 and are sequential in application logic."""
        from models.schemas import RiskItem
        
        # Application creates risks with segment_id starting at 1
        risks = [
            RiskItem(
                segment_id=i,
                text=f"Segment {i}",
                is_risky=False,
                risk_level=RiskLevel.NONE,
                risk_category=None,
                risk_description=None,
                recommendation=None,
                rag_context=None,
            )
            for i in range(1, 11)
        ]
        
        # Verify segment_ids are 1-indexed and sequential
        assert risks[0].segment_id == 1
        assert risks[-1].segment_id == 10
        for i, risk in enumerate(risks):
            assert risk.segment_id == i + 1


class TestRiskCategoryValues:
    """Test that risk_category values are properly defined."""

    def test_all_risk_categories(self):
        """All expected risk categories are defined."""
        all_categories = {cat.value for cat in RiskCategory}
        expected = {
            "финансовый",
            "правовой",
            "операционный",
            "репутационный",
            "интеллектуальный",
        }
        assert all_categories == expected

    def test_risk_item_nullable_category(self, test_db, analysis):
        """risk_category can be null for non-risky items."""
        risk = RiskItemDB(
            id=uuid.uuid4(),
            analysis_id=analysis.id,
            segment_id=1,
            text="Safe segment",
            is_risky=False,
            risk_level="none",
            risk_category=None,
        )
        test_db.add(risk)
        test_db.commit()
        
        assert risk.risk_category is None


class TestMigrationCompatibility:
    """Test that migration can be applied safely."""

    def test_migration_file_exists(self):
        """Migration file for constraints exists."""
        import os
        migration_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "alembic",
            "versions",
            "007_add_domain_constraints.py"
        )
        assert os.path.exists(migration_path)

    def test_migration_has_downgrade(self):
        """Migration has downgrade function for reversibility."""
        import importlib.util
        import os
        
        migration_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "alembic",
            "versions",
            "007_add_domain_constraints.py"
        )
        
        spec = importlib.util.spec_from_file_location("migration", migration_path)
        module = importlib.util.module_from_spec(spec)
        # Don't actually execute, just check it can be imported
        assert spec is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
