import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from pydantic import ValidationError
from schema import (
    ReviewerOverride,
    ReviewStatus,
    AuthorizationLevel,
    RiskProfile,
)


# --- ReviewerOverride validators ---

def test_pending_requires_no_reviewer():
    r = ReviewerOverride(status=ReviewStatus.PENDING)
    assert r.reviewer_id is None
    assert r.override_level is None


def test_accepted_requires_reviewer_id():
    with pytest.raises(ValidationError, match="reviewer_id is required"):
        ReviewerOverride(status=ReviewStatus.ACCEPTED)


def test_overridden_requires_reviewer_id():
    with pytest.raises(ValidationError, match="reviewer_id is required"):
        ReviewerOverride(
            status=ReviewStatus.OVERRIDDEN,
            override_level=AuthorizationLevel.CONDITIONAL,
        )


def test_overridden_requires_override_level():
    with pytest.raises(ValidationError, match="override_level is required"):
        ReviewerOverride(
            status=ReviewStatus.OVERRIDDEN,
            reviewer_id="rev-001",
        )


def test_overridden_valid_with_all_fields():
    r = ReviewerOverride(
        status=ReviewStatus.OVERRIDDEN,
        reviewer_id="rev-001",
        override_level=AuthorizationLevel.CONDITIONAL,
    )
    assert r.override_level == AuthorizationLevel.CONDITIONAL


def test_accepted_valid_with_reviewer_id():
    r = ReviewerOverride(status=ReviewStatus.ACCEPTED, reviewer_id="rev-002")
    assert r.reviewer_id == "rev-002"
    assert r.override_level is None


# --- RiskProfile enum validation ---

VALID_PROFILE = dict(
    ownership="clear",
    aml_present=True,
    regulatory_history="clean",
    cyber="strong",
    financial_health="healthy",
    privacy="compliant",
    has_pep=False,
    has_criminal_flag=False,
)


def test_risk_profile_valid():
    p = RiskProfile(**VALID_PROFILE)
    assert p.ownership.value == "clear"


def test_risk_profile_invalid_ownership():
    with pytest.raises(ValidationError):
        RiskProfile(**{**VALID_PROFILE, "ownership": "totally_clear"})


def test_risk_profile_invalid_regulatory_history():
    with pytest.raises(ValidationError):
        RiskProfile(**{**VALID_PROFILE, "regulatory_history": "spotless"})


def test_risk_profile_invalid_cyber():
    with pytest.raises(ValidationError):
        RiskProfile(**{**VALID_PROFILE, "cyber": "bulletproof"})


def test_risk_profile_invalid_financial_health():
    with pytest.raises(ValidationError):
        RiskProfile(**{**VALID_PROFILE, "financial_health": "fine"})


def test_risk_profile_invalid_privacy():
    with pytest.raises(ValidationError):
        RiskProfile(**{**VALID_PROFILE, "privacy": "ok"})


def test_risk_profile_defaults_empty_lists():
    p = RiskProfile(**VALID_PROFILE)
    assert p.missing_docs == []
    assert p.activities_verified == []
    assert p.activities_undeclared == []
    assert p.key_findings == []
