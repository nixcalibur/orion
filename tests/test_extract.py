import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from extract import _merge_profiles, _vote_scalar


# --- _vote_scalar ---

def test_vote_scalar_majority_wins():
    assert _vote_scalar("ownership", ["clear", "clear", "opaque"]) == "clear"


def test_vote_scalar_tie_fails_closed():
    # 3-way tie: clear (0), complex (2), opaque (3) → worst case wins
    assert _vote_scalar("ownership", ["clear", "complex", "opaque"]) == "opaque"


def test_vote_scalar_bool_majority():
    assert _vote_scalar("aml_present", [True, False, False]) is False
    assert _vote_scalar("has_criminal_flag", [False, False, True]) is False


def test_vote_scalar_ignores_none():
    assert _vote_scalar("cyber", [None, "weak", "weak"]) == "weak"
    assert _vote_scalar("cyber", [None, None, None]) is None


# --- _merge_profiles ---

def test_merge_profiles_single_passthrough():
    p = {"ownership": "clear"}
    assert _merge_profiles([p]) is p


def test_merge_profiles_votes_scalars():
    a = {"ownership": "clear", "aml_present": True, "missing_docs": ["x"], "evidence": {}}
    b = {"ownership": "opaque", "aml_present": True, "missing_docs": [], "evidence": {}}
    c = {"ownership": "clear", "aml_present": False, "missing_docs": ["y", "z"], "evidence": {}}
    merged = _merge_profiles([a, b, c])
    assert merged["ownership"] == "clear"
    assert merged["aml_present"] is True


def test_merge_profiles_lists_from_best_agreeing_run():
    a = {"ownership": "clear", "aml_present": True, "missing_docs": ["a-doc"], "evidence": {"x": 1}}
    b = {"ownership": "clear", "aml_present": True, "missing_docs": ["b-doc"], "evidence": {}}
    c = {"ownership": "opaque", "aml_present": False, "missing_docs": ["c-doc"], "evidence": {}}
    merged = _merge_profiles([a, b, c])
    # merged scalars: ownership=clear, aml=True → run a agrees fully, first maximal wins
    assert merged["missing_docs"] == ["a-doc"]
    assert merged["evidence"] == {"x": 1}
