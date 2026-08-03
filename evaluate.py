"""Batch evaluation: predicted authorization level vs dataset ground truth.

Usage: python evaluate.py
       python evaluate.py --check-min-accuracy 0.75   # fail if held-out accuracy < floor

Prints per-submission results, overall accuracy, in-sample vs held-out
(if dataset/held_out.json is present), per-class accuracy,
misclassification breakdown, and composite-range hit rate.
"""

import argparse
import json
import os
import sys
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


def evaluate(check_min_accuracy: float | None = None, held_out_only: bool = False) -> int:
    """Run the evaluation. Returns 0 on pass, 1 when a check floor is unmet."""
    results = []  # (sid, expected, got, composite, in_range, ok, held_out)
    confusion = Counter()
    held_out_ids = _load_held_out_ids()

    sids = sorted(os.listdir("dataset"))
    if held_out_only:
        sids = [sid for sid in sids if sid in held_out_ids]
        print(f"Held-out-only mode: {len(sids)} pack(s)\n")

    for sid in sids:
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
        return 1

    total = len(results)
    correct = sum(1 for r in results if r[5])
    print(f"\n=== Summary ===")
    print(f"Accuracy: {correct}/{total} ({correct / total * 100:.0f}%)")

    held = []
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
            "Note: ranges are formula-consistent (see README), so a miss means the "
            "extracted profile differs from the labeled profile - a fidelity signal, "
            "not a human-vs-formula mismatch."
        )

    print(
        "\nCaveat: labeled accuracy is rubric-calibrated on this dataset; "
        "re-run after prompt edits. ORION_EXTRACTION_VOTES=1 for cheap smoke runs."
    )

    if check_min_accuracy is not None:
        if not held:
            print("\nERROR: --check-min-accuracy requested but no held-out packs ran.")
            return 1
        held_correct = sum(1 for r in held if r[5])
        held_acc = held_correct / len(held)
        print(
            f"\nGuardrail: held-out accuracy {held_acc:.0%} "
            f"(floor {check_min_accuracy:.0%}) -> {'PASS' if held_acc >= check_min_accuracy else 'FAIL'}"
        )
        if held_acc < check_min_accuracy:
            return 1
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ORION batch evaluation")
    parser.add_argument(
        "--check-min-accuracy",
        type=float,
        default=None,
        help="Fail (exit 1) when held-out accuracy is below this fraction",
    )
    parser.add_argument(
        "--held-out-only",
        action="store_true",
        help="Evaluate only the packs listed in dataset/held_out.json",
    )
    args = parser.parse_args()
    sys.exit(evaluate(check_min_accuracy=args.check_min_accuracy, held_out_only=args.held_out_only))
