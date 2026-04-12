import json
import os

from ingest import ingest
from extract import extract_profile
from score import score_profile, get_authorization_level

correct = 0
total = 0

for sid in sorted(os.listdir("dataset")):
    sub = f"dataset/{sid}/submission.json"
    gt  = f"dataset/{sid}/ground_truth.json"
    if not os.path.exists(sub):
        continue

    expected = json.load(open(gt))["expected_authorization_level"]
    submission, docs = ingest(sub)
    profile = extract_profile(submission, docs)
    _, composite = score_profile(profile)
    got = get_authorization_level(composite, profile)

    match = got == expected
    correct += match
    total += 1
    print(f"{sid}  expected={expected:12s}  got={got:12s}  {'OK' if match else 'FAIL'}")

print(f"\nAccuracy: {correct}/{total}")
