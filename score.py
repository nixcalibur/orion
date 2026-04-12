DIMENSION_SCORES = {
    "ownership":          {"clear": 0, "complex": 2,   "opaque": 3},
    "aml_present":        {True: 0,    False: 3},
    "regulatory_history": {"clean": 0, "minor_issues": 1, "major_issues": 3},
    "cyber":              {"strong": 0, "adequate": 0, "weak": 0.5, "inadequate": 0.5},
    "financial_health":   {"healthy": 0, "marginal": 0.5, "stressed": 1, "distressed": 1},
    "privacy":            {"compliant": 0, "partial": 0.5, "non_compliant": 1},
    "has_pep":            {False: 0, True: 1},
    "has_criminal_flag":  {False: 0, True: 4},
}

MISSING_DOC_PENALTY = 0.5
MAX_RAW_SCORE = 10.0  # calibrated against labeled dataset


def score_profile(profile):
    dim_scores = {}
    raw = 0

    for dim, weights in DIMENSION_SCORES.items():
        value = profile.get(dim)
        s = weights.get(value, 0)
        dim_scores[dim] = s
        raw += s

    missing_penalty = len(profile.get("missing_docs", [])) * MISSING_DOC_PENALTY
    dim_scores["missing_docs"] = round(missing_penalty, 2)
    raw += missing_penalty

    # Normalize to 0–10 scale
    composite = round(min((raw / MAX_RAW_SCORE) * 10, 10.0), 2)

    return dim_scores, composite


def get_authorization_level(composite, profile=None):
    # Hard rules override score for clear-cut cases
    if profile:
        if profile.get("has_criminal_flag"):
            return "REJECT"
        if profile.get("regulatory_history") == "major_issues":
            return "REJECT"

    if composite >= 9.0:
        return "REJECT"
    elif composite >= 4.5:
        return "DEFER"
    elif composite >= 2.0:
        return "CONDITIONAL"
    else:
        return "APPROVE"


def generate_followup_questions(profile, submission):
    questions = []
    # Track topics already covered to avoid duplicates
    covered = set()

    if not profile.get("aml_present"):
        questions.append(
            "A complete AML/CFT policy document is required. Please submit the full policy including procedures, risk assessment, and MLRO appointment."
        )
        covered.add("aml")

    if profile.get("ownership") == "opaque":
        questions.append(
            "Beneficial ownership is unresolved. Please provide full UBO disclosure including trust beneficiary identities and supporting documentation."
        )
        covered.add("ownership")
    elif profile.get("ownership") == "complex":
        questions.append(
            "The ownership structure is multi-layered. Please provide a complete group structure chart and UBO declarations for all entities above 25% threshold."
        )
        covered.add("ownership")

    if profile.get("has_pep"):
        questions.append(
            "One or more key personnel are politically exposed persons (PEPs). Enhanced due diligence evidence including source of wealth documentation is required."
        )
        covered.add("pep")

    if profile.get("has_criminal_flag"):
        questions.append(
            "A criminal history or sanctions flag has been identified. Please provide full details and any relevant court or regulatory outcomes."
        )
        covered.add("criminal")

    if profile.get("regulatory_history") == "minor_issues":
        questions.append(
            "Past regulatory issues have been noted. Please provide details of the findings, remediation steps taken, and confirmation of resolution."
        )
        covered.add("regulatory")
    elif profile.get("regulatory_history") == "major_issues":
        questions.append(
            "Serious regulatory history has been identified. Please provide full disclosure of all past regulatory actions and current compliance status."
        )
        covered.add("regulatory")

    # Only add missing-doc questions for topics not already covered above
    AML_KEYWORDS = {"aml", "cft", "mlro", "anti-money"}
    OWNERSHIP_KEYWORDS = {"ubo", "ownership", "beneficial", "trust"}

    for doc in profile.get("missing_docs", []):
        doc_lower = doc.lower()
        if any(kw in doc_lower for kw in AML_KEYWORDS) and "aml" in covered:
            continue
        if any(kw in doc_lower for kw in OWNERSHIP_KEYWORDS) and "ownership" in covered:
            continue
        questions.append(f"Missing document required: {doc}.")

    for activity in profile.get("activities_undeclared", []):
        questions.append(
            f"Documents reference '{activity}' which does not appear in the declared activities list. Please clarify whether this activity is being conducted."
        )

    return questions
