"""Dataset integrity: the held-out manifest must resolve to real packs."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

ROOT = os.path.dirname(os.path.dirname(__file__))
DATASET = os.path.join(ROOT, "dataset")


def _held_out_ids():
    with open(os.path.join(DATASET, "held_out.json")) as f:
        return json.load(f)["submission_ids"]


def test_held_out_manifest_packs_exist():
    for sid in _held_out_ids():
        base = os.path.join(DATASET, sid)
        assert os.path.isdir(base), f"held-out pack missing: {sid}"
        assert os.path.exists(os.path.join(base, "submission.json")), sid
        assert os.path.exists(os.path.join(base, "ground_truth.json")), sid
        assert os.path.isdir(os.path.join(base, "docs")), sid


def test_held_out_manifest_ids_unique():
    ids = _held_out_ids()
    assert len(ids) == len(set(ids)), "duplicate ids in held-out manifest"


def test_held_out_manifest_has_multiple_packs():
    """The held-out set should be large enough to be a meaningful check."""
    assert len(_held_out_ids()) >= 10


def test_every_manifest_doc_ref_resolves():
    """Each submission's document_refs must point to an existing file."""
    for sid in _held_out_ids():
        with open(os.path.join(DATASET, sid, "submission.json")) as f:
            submission = json.load(f)
        for ref in submission.get("document_refs", []):
            assert os.path.exists(os.path.join(ROOT, ref)), f"{sid}: missing doc {ref}"


def test_all_ground_truth_ranges_are_formula_consistent():
    """expected_composite_range must equal the deterministic formula applied to
    the labeled profile (+/- 0.5). Keeps range-hits a real extraction-fidelity
    metric instead of an independent severity guess."""
    import sys
    sys.path.insert(0, ROOT)
    from score import score_profile

    checked = 0
    for sid in os.listdir(DATASET):
        gt_path = os.path.join(DATASET, sid, "ground_truth.json")
        if not os.path.isfile(gt_path):
            continue
        with open(gt_path) as f:
            gt = json.load(f)
        if "profile" not in gt:
            continue
        _, comp = score_profile(gt["profile"])
        lo, hi = gt["expected_composite_range"]
        assert lo <= comp <= hi, (
            f"{sid}: formula composite {comp:.2f} outside stated range [{lo}, {hi}]"
        )
        assert hi - lo <= 1.0, f"{sid}: range too wide: [{lo}, {hi}]"
        checked += 1
    assert checked >= 30, f"expected >= 30 labeled packs, found {checked}"
