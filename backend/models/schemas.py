from pydantic import BaseModel
from typing import Optional
from enum import Enum


class RiskLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


class RiskCategory(str, Enum):
    FINANCIAL = "финансовый"
    LEGAL = "правовой"
    OPERATIONAL = "операционный"
    REPUTATIONAL = "репутационный"
    INTELLECTUAL = "интеллектуальный"


class RiskItem(BaseModel):
    segment_id: int
    text: str
    is_risky: bool
    risk_level: RiskLevel
    risk_category: Optional[RiskCategory] = None
    risk_description: Optional[str] = None
    recommendation: Optional[str] = None
    rag_context: Optional[str] = None


class AnalysisSummary(BaseModel):
    total_segments: int
    risky_segments: int
    high_risk_count: int
    medium_risk_count: int
    low_risk_count: int
    risk_score: float


class AnalysisResponse(BaseModel):
    analysis_id: str
    filename: str
    status: str = "completed"
    summary: AnalysisSummary
    risks: list[RiskItem]


class AnalysisStatus(BaseModel):
    analysis_id: str
    status: str
    progress: Optional[int] = None
    result: Optional[AnalysisResponse] = None
