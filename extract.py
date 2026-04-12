from openai import OpenAI
from dotenv import load_dotenv
import json

load_dotenv()

MODEL = "gpt-4o-mini-2024-07-18"
SEED = 42

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = OpenAI()
    return _client


def extract_profile(submission, docs):
    docs_text = "\n\n".join(
        f"=== {name} ===\n{content}" for name, content in docs.items()
    )

    prompt = f"""You are a financial regulatory analyst reviewing an authorization submission for ORION (Operational Risk & Integrity Office).

Submission metadata:
{json.dumps(submission, indent=2)}

Supporting documents:
{docs_text}

Analyze this submission and extract a structured risk profile. Return ONLY valid JSON with no additional text:

{{
  "ownership": "clear | complex | opaque",
  "aml_present": true | false,
  "regulatory_history": "clean | minor_issues | major_issues",
  "cyber": "strong | adequate | weak | inadequate",
  "financial_health": "healthy | marginal | stressed | distressed",
  "privacy": "compliant | partial | non_compliant",
  "has_pep": true | false,
  "has_criminal_flag": true | false,
  "missing_docs": ["list of missing or materially incomplete documents"],
  "activities_verified": ["activities confirmed present in documents"],
  "activities_undeclared": ["activities found in docs but absent from declared list"],
  "key_findings": ["concise list of notable risk findings"]
}}

Classification rules:
- ownership: "clear" = all UBOs identified with >25% threshold; "complex" = multi-layer structure or trusts with named beneficiaries; "opaque" = trust beneficiaries undisclosed or UBO chain unresolved
- aml_present: true only if a formal, complete AML/CFT policy exists — compliance notes or drafts do not count
- regulatory_history: "clean" = no issues; "minor_issues" = past minor breaches resolved; "major_issues" = unresolved or serious breaches
- cyber: assess from any cyber/IT security references in documents
- financial_health: "healthy" = positive equity + adequate capital; "marginal" = tight capital headroom; "distressed" = negative equity or liquidity concerns
- privacy: assess from any GDPR/data protection references
- has_pep: true if any key personnel are politically exposed persons
- has_criminal_flag: true if any criminal history or sanctions mentioned
- missing_docs: list documents that are expected for this type of firm but absent or incomplete"""

    response = _get_client().chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0,
        seed=SEED,
    )

    content = response.choices[0].message.content
    try:
        profile = json.loads(content)
        profile["_model"] = response.model  # actual resolved model version from API
        profile["_fp"] = response.system_fingerprint  # backend routing fingerprint
        return profile
    except json.JSONDecodeError:
        return {"error": content}
