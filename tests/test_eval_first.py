"""Tests for the eval-first crucible skill — M1: gate core (ab_harness) + reliability."""
from __future__ import annotations

import random

import pytest

import ab_harness as ab
import reliability as rel


# ---------------- ab_harness: make_blind_pairs ----------------

def test_make_blind_pairs_only_common_ids():
    a = {"1": "a1", "2": "a2", "3": "a3"}
    b = {"2": "b2", "3": "b3", "4": "b4"}
    pairs = ab.make_blind_pairs(a, b, rng=random.Random(0))
    assert {p.case_id for p in pairs} == {"2", "3"}


def test_make_blind_pairs_side_invariant_holds():
    a = {"x": "A-x", "y": "A-y"}
    b = {"x": "B-x", "y": "B-y"}
    for p in ab.make_blind_pairs(a, b, rng=random.Random(7)):
        if p.left_is == "A":
            assert p.left == a[p.case_id] and p.right == b[p.case_id]
        else:
            assert p.left == b[p.case_id] and p.right == a[p.case_id]


def test_make_blind_pairs_deterministic_with_seed():
    a = {str(i): f"a{i}" for i in range(6)}
    b = {str(i): f"b{i}" for i in range(6)}
    p1 = ab.make_blind_pairs(a, b, rng=random.Random(42))
    p2 = ab.make_blind_pairs(a, b, rng=random.Random(42))
    assert [(p.case_id, p.left_is) for p in p1] == [(p.case_id, p.left_is) for p in p2]


def test_make_blind_pairs_attaches_meta():
    pairs = ab.make_blind_pairs({"1": "a"}, {"1": "b"}, rng=random.Random(0),
                                meta={"1": {"group": "g", "category": "c"}})
    assert pairs[0].meta == {"group": "g", "category": "c"}


# ---------------- ab_harness: tally ----------------

def test_tally_decodes_picks_respecting_side():
    pairs = [
        ab.BlindPair("1", "L", "R", left_is="A"),  # A on left
        ab.BlindPair("2", "L", "R", left_is="B"),  # B on left
        ab.BlindPair("3", "L", "R", left_is="A"),
        ab.BlindPair("4", "L", "R", left_is="A"),
    ]
    picks = {"1": "left", "2": "left", "3": "right", "4": "tie"}
    t = ab.tally(pairs, picks)
    # 1: left=A -> a_win; 2: left=B -> b_win; 3: right on A-left -> b_win; 4: tie
    assert t["a_wins"] == 1
    assert t["b_wins"] == 2
    assert t["ties"] == 1
    assert t["decided"] == 3
    assert t["a_win_rate"] == round(1 / 3, 4)


def test_tally_missing_pick_is_skip():
    pairs = [ab.BlindPair("1", "L", "R", left_is="A")]
    t = ab.tally(pairs, {})
    assert t["skipped"] == 1
    assert t["decided"] == 0
    assert t["a_win_rate"] is None


# ---------------- ab_harness: sign test ----------------

def test_sign_test_empty_is_none():
    assert ab._two_sided_sign_test(0, 0) is None


def test_sign_test_even_split_is_one():
    assert ab._two_sided_sign_test(3, 3) == 1.0


def test_sign_test_lopsided_is_significant():
    assert ab._two_sided_sign_test(10, 0) < 0.05
    # 6 vs 0: 2 * (1/64) = 0.03125
    assert ab._two_sided_sign_test(6, 0) == 0.0312


# ---------------- ab_harness: verdict (the gate) ----------------

def test_verdict_candidate_better():
    v = ab.verdict({"a_win_rate": 0.1, "sign_test_p": 0.002})
    assert "CANDIDATE BETTER" in v and "flip" in v


def test_verdict_candidate_worse():
    v = ab.verdict({"a_win_rate": 0.9, "sign_test_p": 0.002})
    assert "CANDIDATE WORSE" in v and "do NOT flip" in v


def test_verdict_parity():
    v = ab.verdict({"a_win_rate": 0.5, "sign_test_p": 1.0})
    assert "PARITY" in v and "may flip" in v


def test_verdict_no_decided():
    assert ab.verdict({"a_win_rate": None, "sign_test_p": None}) == "no decided pairs"


def test_verdict_custom_labels():
    v = ab.verdict({"a_win_rate": 0.9, "sign_test_p": 0.01},
                   arm_a_label="v1", arm_b_label="v2")
    assert "v1 wins" in v


# ---------------- reliability ----------------

def test_avg_at_k():
    assert rel.avg_at_k([]) == 0.0
    assert rel.avg_at_k([True, True, False, False]) == 0.5


def test_pass_hat_k():
    assert rel.pass_hat_k([True, True, True]) is True
    assert rel.pass_hat_k([True, False, True]) is False
    assert rel.pass_hat_k([]) is False


def test_pass_any():
    assert rel.pass_any([False, True]) is True
    assert rel.pass_any([False, False]) is False
    assert rel.pass_any([]) is False


def test_pass_at_k_estimate_normal():
    # n=5, c=1, k=3: 1 - C(4,3)/C(5,3) = 1 - 4/10 = 0.6
    assert rel.pass_at_k_estimate(5, 1, 3) == pytest.approx(0.6)


def test_pass_at_k_estimate_edges():
    assert rel.pass_at_k_estimate(5, 0, 3) == 0.0          # no passes
    assert rel.pass_at_k_estimate(5, 5, 3) == 1.0          # all pass (n-c < k)
    with pytest.raises(ValueError):
        rel.pass_at_k_estimate(5, 1, 0)                    # k must be positive
    with pytest.raises(ValueError):
        rel.pass_at_k_estimate(3, 1, 5)                    # k cannot exceed n
