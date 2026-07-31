"""Batch evaluation: predicted authorization level vs dataset ground truth.

Usage: python evaluate.py

Prints per-submission results, overall accuracy, in-sample vs held-out
(if dataset/held_out.json is present), per-class accuracy,
misclassification breakdown, and composite-range hit rate.
"""

import json
import os
from collections import Counter

from ingest import ingest
from extract import extract_profile
from score import score_profile, get_authorization_level

LEVELS = ("APPROVE", "CONDITIONAL", "DEFER", "REJECT")
HELD_OUT_MANIFEST = os.path.join("dataset", "held_out.json")


def _load_held_out_ids():
    if not os.path.exists(HELD_OUT_MANIFEST):
        return set()
    with open(HELD_OUT_MANIFEST) as f:
        data = json.load(f)
    return set(data.get("submission_ids", []))


def evaluate():
    results = []  # (sid, expected, got, composite, in_range, ok, held_out)
    confusion = Counter()
    held_out_ids = _load_held_out_ids()

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

        submission, docs, _ = ingest(sub)
        profile = extract_profile(submission, docs)

        if "error" in profile:
            print(f"{sid}  expected={expected:12s}  got=EXTRACTION_ERROR  FAIL")
            results.append((sid, expected, "ERROR", None, None, False, sid in held_out_ids))
            confusion[(expected, "ERROR")] += 1
            continue

        _, composite = score_profile(profile)
        got = get_authorization_level(composite, profile)

        in_range = None
        if "expected_composite_range" in gt:
            lo, hi = gt["expected_composite_range"]
            in_range = lo <= composite <= hi

        ok = got == expected
        is_held = sid in held_out_ids
        results.append((sid, expected, got, composite, in_range, ok, is_held))
        confusion[(expected, got)] += 1
        tag = " [held-out]" if is_held else ""
        print(
            f"{sid}  expected={expected:12s}  got={got:12s}  "
            f"composite={composite:5.2f}  {'OK' if ok else 'FAIL'}{tag}"
        )

    if not results:
        print("No submissions evaluated.")
        return

    total = len(results)
    correct = sum(1 for r in results if r[5])
    print(f"\n=== Summary ===")
    print(f"Accuracy: {correct}/{total} ({correct / total * 100:.0f}%)")

    if held_out_ids:
        in_sample = [r for r in results if not r[6]]
        held = [r for r in results if r[6]]
        if in_sample:
            c = sum(1 for r in in_sample if r[5])
            print(f"In-sample accuracy: {c}/{len(in_sample)} ({c / len(in_sample) * 100:.0f}%)")
        if held:
            c = sum(1 for r in held if r[5])
            print(f"Held-out accuracy:  {c}/{len(held)} ({c / len(held) * 100:.0f}%)")
        else:
            print("Held-out accuracy:  (manifest present, but no matching labeled packs ran)")

    by_class = {}
    for _, expected, _, _, _, ok, _ in results:
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
        print(
            "Note: composite-range mismatches are expected when human severity "
            "intuition ≠ the deterministic formula — do not retune weights for that alone."
        )

    print(
        "\nCaveat: labeled accuracy is rubric-calibrated on this dataset; "
        "re-run after prompt edits. ORION_EXTRACTION_VOTES=1 for cheap smoke runs."
    )


if __name__ == "__main__":
    evaluate()
