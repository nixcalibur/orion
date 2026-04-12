from pydantic import BaseModel, Field, validator
from typing import Dict, List, Optional
from datetime import datetime
from enum import Enum


class AuthorizationLevel(str, Enum):
    APPROVE = "APPROVE"
    CONDITIONAL = "CONDITIONAL"
    DEFER = "DEFER"
    REJECT = "REJECT"


class OwnershipType(str, Enum):
    clear = "clear"
    complex = "complex"
    opaque = "opaque"


class RegulatoryHistory(str, Enum):
    clean = "clean"
    minor_issues = "minor_issues"
    major_issues = "major_issues"


class CyberRating(str, Enum):
    strong = "strong"
    adequate = "adequate"
    weak = "weak"
    inadequate = "inadequate"


class FinancialHealth(str, Enum):
    healthy = "healthy"
    marginal = "marginal"
    stressed = "stressed"
    distressed = "distressed"


class PrivacyRating(str, Enum):
    compliant = "compliant"
    partial = "partial"
    non_compliant = "non_compliant"


class RiskProfile(BaseModel):
    ownership: OwnershipType
    aml_present: bool
    regulatory_history: RegulatoryHistory
    cyber: CyberRating
    financial_health: FinancialHealth
    privacy: PrivacyRating
    has_pep: bool
    has_criminal_flag: bool
    missing_docs: List[str] = []
    activities_verified: List[str] = []
    activities_undeclared: List[str] = []
    key_findings: List[str] = []


class AssessmentResult(BaseModel):
    submission_id: str
    applicant_name: Optional[str]
    assessed_at: datetime
    authorization_level: AuthorizationLevel
    composite_score: float = Field(..., ge=0.0, le=10.0)
    dimension_scores: Dict[str, float]
    risk_profile: RiskProfile
    declared_activities: List[str] = []
    activities_verified: List[str] = []
    activities_undeclared: List[str] = []
    followup_questions: List[str] = []
    key_findings: List[str] = []

    @validator("composite_score")
    def round_score(cls, v):
        return round(v, 2)
