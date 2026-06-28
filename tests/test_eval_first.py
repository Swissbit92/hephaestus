"""Tests for the eval-first crucible skill — M1: gate core (ab_harness) + reliability."""
from __future__ import annotations

import random

import pytest

import ab_harness as ab
import baseline as bl
import judge as jg
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


# ---------------- baseline: freeze / load / immutability ----------------

def test_freeze_load_roundtrip(tmp_path):
    p = tmp_path / "baseline_v1.json"
    bl.freeze_baseline(p, "legacy", {"acc": 0.8}, results={"x": 1}, stamp="2026-06-28T00:00:00")
    loaded = bl.load_baseline(p)
    assert loaded["label"] == "legacy"
    assert loaded["stamp"] == "2026-06-28T00:00:00"
    assert loaded["report"] == {"acc": 0.8}
    assert loaded["results"] == {"x": 1}


def test_freeze_is_immutable(tmp_path):
    p = tmp_path / "baseline_v1.json"
    bl.freeze_baseline(p, "legacy", {"acc": 0.8})
    with pytest.raises(FileExistsError):
        bl.freeze_baseline(p, "legacy", {"acc": 0.9})       # never silently overwrite
    bl.freeze_baseline(p, "legacy", {"acc": 0.9}, force=True)  # explicit override allowed
    assert bl.load_baseline(p)["report"]["acc"] == 0.9


# ---------------- baseline: compare (match-or-beat gate) ----------------

def test_compare_clean_when_matched_or_beat():
    r = bl.compare_to_baseline({"a": 0.8, "b": 0.9}, {"a": 0.8, "b": 0.7})
    assert r["clean"] is True
    assert r["improvements"] == ["b"]
    assert r["regressions"] == []


def test_compare_flags_regression():
    r = bl.compare_to_baseline({"a": 0.7}, {"a": 0.8})
    assert r["regressions"] == ["a"]
    assert r["clean"] is False


def test_compare_tolerance_absorbs_small_drop():
    r = bl.compare_to_baseline({"a": 0.79}, {"a": 0.80}, tolerance=0.02)
    assert r["regressions"] == []
    assert r["clean"] is True


def test_compare_missing_key_blocks():
    r = bl.compare_to_baseline({"a": 0.8}, {"a": 0.8, "b": 0.5})
    assert r["missing"] == ["b"]
    assert r["clean"] is False


def test_compare_new_key_noted_not_blocking():
    r = bl.compare_to_baseline({"a": 0.8, "c": 0.6}, {"a": 0.8})
    assert r["new"] == ["c"]
    assert r["clean"] is True


# ---------------- judge: family guard ----------------

def test_family_extraction():
    assert jg.family("claude-sonnet-4-6") == "claude"
    assert jg.family("gpt-5") == "gpt"
    assert jg.family("gemini-2.5-pro") == "gemini"


def test_assert_judge_distinct():
    with pytest.raises(ValueError):
        jg.assert_judge_distinct("claude-sonnet-4-6", "claude-opus-4-8")  # self-grading
    jg.assert_judge_distinct("claude-sonnet-4-6", "gpt-5")                # different family OK


# ---------------- judge: prompt + parse ----------------

def test_build_ab_prompt_contains_rubric_and_outputs():
    p = jg.build_ab_prompt("the input", "LEFTOUT", "RIGHTOUT", "be concise")
    assert "be concise" in p and "LEFTOUT" in p and "RIGHTOUT" in p
    assert "JSON" in p and "longer" in p


def test_parse_ab_verdict_from_prose():
    assert jg.parse_ab_verdict('reasoning... {"choice": "right", "reason": "x"} end')["choice"] == "right"


def test_parse_ab_verdict_garbage_is_tie():
    assert jg.parse_ab_verdict("no json here")["choice"] == "tie"


# ---------------- judge: swap augmentation (the upgrade) ----------------

def _content_judge(win="WIN"):
    """A consistent judge that prefers whichever response actually contains `win`,
    regardless of position."""
    def jf(prompt: str) -> str:
        left = prompt.split("# Response LEFT\n", 1)[1].split("\n\n# Response RIGHT", 1)[0]
        right = prompt.split("# Response RIGHT\n", 1)[1].split("\n\n", 1)[0]
        if win in left and win not in right:
            return '{"choice": "left", "reason": "x"}'
        if win in right and win not in left:
            return '{"choice": "right", "reason": "x"}'
        return '{"choice": "tie", "reason": "x"}'
    return jf


def _position_biased_judge(prompt: str) -> str:
    return '{"choice": "left", "reason": "always left"}'   # ignores content


def test_judge_pair_consistent_judge_picks_winner():
    pair = ab.BlindPair("1", left="WIN response", right="lose response", left_is="A")
    assert jg.judge_pair(pair, "in", "rubric", _content_judge()) == "left"


def test_judge_pair_position_bias_resolves_to_tie():
    pair = ab.BlindPair("1", left="alpha", right="beta", left_is="A")
    # the biased judge always says "left" -> flips under swap -> order-dependent -> tie
    assert jg.judge_pair(pair, "in", "rubric", _position_biased_judge) == "tie"


def test_judge_pairs_integrates_with_tally():
    pairs = [
        ab.BlindPair("1", left="WIN a", right="lose a", left_is="B"),   # candidate(B) on left
        ab.BlindPair("2", left="lose b", right="WIN b", left_is="A"),   # candidate(B) on right
    ]
    picks = jg.judge_pairs(pairs, "rubric", _content_judge())
    # case1: left(WIN) wins, left_is=B -> b_win; case2: right(WIN) wins, right_is=B -> b_win
    t = ab.tally(pairs, picks)
    assert t["b_wins"] == 2 and t["a_wins"] == 0
