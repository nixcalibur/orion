"""Batch evaluation: predicted authorization level vs dataset ground truth.

Usage: python evaluate.py

Prints per-submission results, overall accuracy, per-class accuracy,
misclassification breakdown, and composite-range hit rate.
"""

import json
import os
from collections import Counter

from ingest import ingest
from extract import extract_profile
from score import score_profile, get_authorization_level

LEVELS = ("APPROVE", "CONDITIONAL", "DEFER", "REJECT")


def evaluate():
    results = []  # (sid, expected, got, composite, in_range, ok)
    confusion = Counter()

    for sid in sorted(os.listdir("dataset")):
        sub = f"dataset/{sid}/submission.json"
        gt_path = f"dataset/{sid}/ground_truth.json"
        if not os.path.exists(sub):
            continue
        if not os.path.exists(gt_path):
            print(f"{sid}  SKIP (no ground truth)")
            continue

        with open(gt_path) as f:
            gt = json.load(f)
        expected = gt["expected_authorization_level"]

        submission, docs = ingest(sub)
        profile = extract_profile(submission, docs)

        if "error" in profile:
            print(f"{sid}  expected={expected:12s}  got=EXTRACTION_ERROR  FAIL")
            results.append((sid, expected, "ERROR", None, None, False))
            confusion[(expected, "ERROR")] += 1
            continue

        _, composite = score_profile(profile)
        got = get_authorization_level(composite, profile)

        in_range = None
        if "expected_composite_range" in gt:
            lo, hi = gt["expected_composite_range"]
            in_range = lo <= composite <= hi

        ok = got == expected
        results.append((sid, expected, got, composite, in_range, ok))
        confusion[(expected, got)] += 1
        print(
            f"{sid}  expected={expected:12s}  got={got:12s}  "
            f"composite={composite:5.2f}  {'OK' if ok else 'FAIL'}"
        )

    if not results:
        print("No submissions evaluated.")
        return

    total = len(results)
    correct = sum(1 for r in results if r[5])
    print(f"\n=== Summary ===")
    print(f"Accuracy: {correct}/{total} ({correct / total * 100:.0f}%)")

    by_class = {}
    for _, expected, _, _, _, ok in results:
        by_class.setdefault(expected, [0, 0])
        by_class[expected][1] += 1
        if ok:
            by_class[expected][0] += 1

    print("\nPer-class accuracy:")
    for level in LEVELS:
        if level in by_class:
            c, t = by_class[level]
            print(f"  {level:12s}  {c}/{t}")

    misses = [(e, g, n) for (e, g), n in sorted(confusion.items()) if e != g]
    if misses:
        print("\nMisclassifications:")
        for e, g, n in misses:
            print(f"  {e} predicted as {g}: {n}")

    ranged = [r for r in results if r[4] is not None]
    if ranged:
        hits = sum(1 for r in ranged if r[4])
        print(f"\nComposite within expected range: {hits}/{len(ranged)}")


if __name__ == "__main__":
    evaluate()
