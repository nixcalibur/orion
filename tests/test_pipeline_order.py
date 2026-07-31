"""Regression: main validates RiskProfile only after verify_evidence."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from extract import verify_evidence
from schema import RiskProfile


# Minimal valid profile fields (mirrors what RiskProfile requires).
_BASE = {
    "ownership": "clear",
    "aml_present": True,
    "regulatory_history": "clean",
    "cyber": "adequate",
    "financial_health": "healthy",
    "privacy": "compliant",
    "has_pep": False,
    "has_criminal_flag": False,
}


def test_pipeline_order_strips_hallucinated_evidence_before_riskprofile():
    """Same order as main.run_pipeline: verify_evidence → RiskProfile(**profile)."""
    docs = {"policy.txt": "AML policy applies to all staff."}
    raw = {
        **_BASE,
        "evidence": {
            "aml_present": {
                "source_document": "policy.txt",
                "excerpt": "AML policy applies to all staff",
            },
            "ownership": {
                "source_document": "policy.txt",
                "excerpt": "UBO is a Panamanian trust shell",  # hallucinated
            },
        },
    }
    verified = verify_evidence(raw, docs)
    risk = RiskProfile(**verified)
    assert "aml_present" in risk.evidence
    assert "ownership" not in risk.evidence
