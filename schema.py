from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Dict, List, Optional
from datetime import datetime
from enum import Enum


class AuthorizationLevel(str, Enum):
    APPROVE = "APPROVE"
    CONDITIONAL = "CONDITIONAL"
    DEFER = "DEFER"
    REJECT = "REJECT"


class ReviewStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    OVERRIDDEN = "OVERRIDDEN"


class ReviewerOverride(BaseModel):
    status: ReviewStatus
    reviewer_id: Optional[str] = None      # set when a human accepts or overrides
    reviewed_at: Optional[datetime] = None  # set when a human accepts or overrides
    override_level: Optional[AuthorizationLevel] = None  # set only when OVERRIDDEN
    notes: Optional[str] = None

    @model_validator(mode="after")
    def validate_review_constraints(self) -> "ReviewerOverride":
        if self.status in (ReviewStatus.ACCEPTED, ReviewStatus.OVERRIDDEN) and not self.reviewer_id:
            raise ValueError("reviewer_id is required when status is ACCEPTED or OVERRIDDEN")
        if self.status == ReviewStatus.OVERRIDDEN and self.override_level is None:
            raise ValueError("override_level is required when status is OVERRIDDEN")
        return self


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


class Evidence(BaseModel):
    """Source citation justifying one dimension classification."""
    source_document: str
    excerpt: str
    supporting_details: Optional[str] = None


class DeliveryStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class DeliveryInfo(BaseModel):
    """Outcome of the external review API delivery attempt."""
    status: DeliveryStatus
    detail: Optional[str] = None


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
    evidence: Dict[str, Evidence] = {}


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
    review: Optional[ReviewerOverride] = None
    delivery: Optional[DeliveryInfo] = None

    @field_validator("composite_score", mode="after")
    @classmethod
    def round_score(cls, v: float) -> float:
        return round(v, 2)
