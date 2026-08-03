import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from extract import _merge_profiles, _vote_scalar, verify_evidence


# --- verify_evidence ---

DOCS = {"policy.pdf": "The AML / CFT Policy applies to all staff.\nRecords are retained for 5 years."}


def test_verify_evidence_keeps_valid_excerpt():
    profile = {"evidence": {"aml_present": {"source_document": "policy.pdf", "excerpt": "applies to all staff"}}}
    out = verify_evidence(profile, DOCS)
    assert "aml_present" in out["evidence"]


def test_verify_evidence_strips_hallucinated_excerpt():
    profile = {"evidence": {"ownership": {"source_document": "policy.pdf", "excerpt": "The UBO is a Panamanian trust"}}}
    out = verify_evidence(profile, DOCS)
    assert out["evidence"] == {}


def test_verify_evidence_unknown_document_dropped():
    profile = {"evidence": {"cyber": {"source_document": "nonexistent.pdf", "excerpt": "anything"}}}
    out = verify_evidence(profile, DOCS)
    assert out["evidence"] == {}


def test_verify_evidence_case_and_whitespace_insensitive():
    profile = {"evidence": {"privacy": {"source_document": "policy.pdf", "excerpt": "  RECORDS   ARE  RETAINED\nfor 5 years "}}}
    out = verify_evidence(profile, DOCS)
    assert "privacy" in out["evidence"]


def test_verify_evidence_malformed_entry_dropped():
    profile = {"evidence": {"cyber": "not-a-dict"}}
    out = verify_evidence(profile, DOCS)
    assert out["evidence"] == {}


def test_verify_evidence_full_path_citation_resolved_by_basename():
    profile = {"evidence": {"aml_present": {"source_document": "dataset/docs/policy.pdf", "excerpt": "applies to all staff"}}}
    out = verify_evidence(profile, DOCS)
    assert "aml_present" in out["evidence"]


def test_verify_evidence_hallucinated_excerpt_stripped_with_full_path():
    profile = {"evidence": {"ownership": {"source_document": "x/y/policy.pdf", "excerpt": "The UBO is hidden"}}}
    out = verify_evidence(profile, DOCS)
    assert out["evidence"] == {}


def test_verify_evidence_case_insensitive_basename():
    profile = {"evidence": {"aml_present": {"source_document": "POLICY.PDF", "excerpt": "applies to all staff"}}}
    out = verify_evidence(profile, DOCS)
    assert "aml_present" in out["evidence"]


def test_verify_evidence_ambiguous_basename_dropped():
    docs = {
        "a/report.txt": "alpha content",
        "b/report.txt": "beta content",
    }
    profile = {"evidence": {"cyber": {"source_document": "report.txt", "excerpt": "alpha content"}}}
    out = verify_evidence(profile, docs)
    assert out["evidence"] == {}


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


# --- vote diversity: distinct seeds per pass ---

class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeResponse:
    def __init__(self):
        self.choices = [type("Choice", (), {"message": _FakeMessage('{"ownership": "clear"}')})]
        self.model = "test-model"
        self.system_fingerprint = "fp_test"


class _FakeCompletions:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeResponse()


class _FakeClient:
    def __init__(self):
        self.chat = type("Chat", (), {"completions": _FakeCompletions()})()


def test_extraction_passes_use_distinct_seeds(monkeypatch):
    import extract
    fake = _FakeClient()
    monkeypatch.setattr(extract, "_client", fake)
    extract.extract_profile({"submission_id": "x"}, {})
    seeds = [c["seed"] for c in fake.chat.completions.calls]
    assert seeds == [extract.SEED, extract.SEED + 1, extract.SEED + 2]
    temps = {c["temperature"] for c in fake.chat.completions.calls}
    assert temps == {0}


# --- prompt rubric rules ---

def test_prompt_contains_rubric_rules():
    import extract
    prompt = extract._build_prompt({"submission_id": "x"}, "doc text")
    # PEP EDD requires a dedicated document, not a policy mention
    assert "dedicated EDD document" in prompt
    # major vs minor regulatory history distinction
    assert "enforcement actions" in prompt
    assert "fully remediated" in prompt
    # prompt-injection isolation
    assert "<document>" in prompt


# --- offline mock provider ---

def test_mock_provider_produces_schema_valid_profile(monkeypatch):
    import extract
    monkeypatch.setattr(extract, "_MOCK", True)
    docs = {
        "policy.txt": "The AML/CFT Policy is in force and applies to all staff. "
                      "The MLRO has been appointed. Beneficial owners are two natural persons.",
        "financials.txt": "Audited accounts show positive equity and adequate capital.",
    }
    profile = extract.extract_profile({"submission_id": "x", "document_refs": list(docs)}, docs)
    assert "error" not in profile
    assert profile["_model"] == "mock-llm-v1"
    from schema import RiskProfile
    RiskProfile(**profile)  # must validate cleanly


def test_mock_provider_evidence_verifies(monkeypatch):
    import extract
    monkeypatch.setattr(extract, "_MOCK", True)
    docs = {"policy.txt": "The AML/CFT Policy applies to all staff and is in force."}
    profile = extract.extract_profile({"submission_id": "x"}, docs)
    verified = extract.verify_evidence(profile, docs)
    for entry in verified["evidence"].values():
        assert entry["source_document"] == "policy.txt"


def test_mock_provider_requires_no_api_client(monkeypatch):
    """Mock mode must not construct an OpenAI client."""
    import extract
    monkeypatch.setattr(extract, "_MOCK", True)
    called = []

    def boom():
        called.append(True)
        raise AssertionError("OpenAI() should not be constructed in mock mode")

    monkeypatch.setattr(extract, "_client", None)
    monkeypatch.setattr(extract, "OpenAI", boom)
    profile = extract.extract_profile({"submission_id": "x"}, {"a.txt": "AML policy in force"})
    assert "error" not in profile
    assert not called
