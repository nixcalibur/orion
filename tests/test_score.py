import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from score import score_profile, get_authorization_level, MAX_RAW_SCORE, DIMENSION_SCORES


# --- MAX_RAW_SCORE derivation ---

def test_max_raw_score_equals_sum_of_dimension_maxes():
    expected = sum(max(v.values()) for v in DIMENSION_SCORES.values())
    assert MAX_RAW_SCORE == expected


# --- score_profile paths ---

CLEAN_PROFILE = {
    "ownership": "clear",
    "aml_present": True,
    "regulatory_history": "clean",
    "cyber": "strong",
    "financial_health": "healthy",
    "privacy": "compliant",
    "has_pep": False,
    "has_criminal_flag": False,
    "missing_docs": [],
}


def test_score_profile_approve_path():
    dim_scores, composite = score_profile(CLEAN_PROFILE)
    assert composite == 0.0
    assert all(v == 0 for k, v in dim_scores.items() if k != "missing_docs")


def test_score_profile_conditional_path():
    profile = {**CLEAN_PROFILE, "financial_health": "marginal", "privacy": "partial"}
    _, composite = score_profile(profile)
    # raw = 0.5 + 0.5 = 1.0 → composite = (1.0 / MAX_RAW_SCORE) * 10
    assert 0.0 < composite < 4.5


def test_score_profile_defer_path():
    profile = {
        **CLEAN_PROFILE,
        "ownership": "complex",
        "financial_health": "stressed",
        "privacy": "partial",
        "has_pep": True,
    }
    _, composite = score_profile(profile)
    assert 2.0 <= composite < 9.0


def test_score_profile_reject_path():
    profile = {
        **CLEAN_PROFILE,
        "ownership": "opaque",
        "aml_present": False,
        "regulatory_history": "major_issues",
        "has_criminal_flag": True,
    }
    _, composite = score_profile(profile)
    assert composite >= 4.5


def test_score_profile_missing_doc_penalty():
    profile = {**CLEAN_PROFILE, "missing_docs": ["AML policy", "UBO declaration"]}
    dim_scores, composite = score_profile(profile)
    assert dim_scores["missing_docs"] == 1.0  # 2 * 0.5
    assert composite > 0.0


def test_score_profile_composite_clamped_at_10():
    worst = {
        "ownership": "opaque",
        "aml_present": False,
        "regulatory_history": "major_issues",
        "cyber": "weak",
        "financial_health": "distressed",
        "privacy": "non_compliant",
        "has_pep": True,
        "has_criminal_flag": True,
        "missing_docs": ["doc"] * 100,
    }
    _, composite = score_profile(worst)
    assert composite == 10.0


def test_score_profile_unknown_value_scores_worst_case():
    profile = {**CLEAN_PROFILE, "ownership": "unknown_value"}
    dim_scores, _ = score_profile(profile)
    assert dim_scores["ownership"] == max(DIMENSION_SCORES["ownership"].values())


# --- get_authorization_level thresholds ---

def test_auth_level_approve():
    assert get_authorization_level(0.0) == "APPROVE"
    assert get_authorization_level(1.99) == "APPROVE"


def test_auth_level_conditional():
    assert get_authorization_level(2.0) == "CONDITIONAL"
    assert get_authorization_level(4.49) == "CONDITIONAL"


def test_auth_level_defer():
    assert get_authorization_level(4.5) == "DEFER"
    assert get_authorization_level(8.99) == "DEFER"


def test_auth_level_reject_by_score():
    assert get_authorization_level(9.0) == "REJECT"
    assert get_authorization_level(10.0) == "REJECT"


def test_auth_level_criminal_flag_hard_override():
    profile = {**CLEAN_PROFILE, "has_criminal_flag": True}
    assert get_authorization_level(0.0, profile) == "REJECT"


def test_auth_level_major_regulatory_hard_override():
    profile = {**CLEAN_PROFILE, "regulatory_history": "major_issues"}
    assert get_authorization_level(0.0, profile) == "REJECT"


def test_auth_level_no_profile_uses_score_only():
    assert get_authorization_level(1.0, None) == "APPROVE"
    assert get_authorization_level(1.0, {}) == "APPROVE"
