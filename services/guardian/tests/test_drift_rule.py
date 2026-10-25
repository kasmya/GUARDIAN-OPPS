"""Pins down the false-alarm behaviour of the drift decision rule.

Before the rule was changed, PSI >= 0.20 alone opened an incident in every
simulated healthy hour, because PSI over a 60-sample window averages about 0.195
with no drift at all.  These tests use the project's real scorer.
"""
import importlib.util
import random
import sys
from pathlib import Path

import pytest

from app.drift import (
    KS_P_SIGNIFICANT,
    compute_drift,
    confidence_from_ks,
)

_spec = importlib.util.spec_from_file_location(
    "fraud_scoring", Path(__file__).resolve().parents[2] / "fraud-api" / "app" / "scoring.py"
)
scoring = importlib.util.module_from_spec(_spec)
sys.modules["fraud_scoring"] = scoring
_spec.loader.exec_module(scoring)


def healthy(n):
    return [scoring.score_normal(scoring.Transaction.sample()) for _ in range(n)]


def corrupt(n):
    return [scoring.score_corrupt(None) for _ in range(n)]


def test_raw_psi_on_healthy_windows_really_sits_near_the_alarm_line():
    """Documents WHY PSI alone was unusable: healthy windows average PSI > 0.2."""
    random.seed(11)
    psis = []
    for _ in range(60):
        ref = healthy(200)
        psis.append(compute_drift(ref, healthy(60)).psi)
    assert 0.20 < sum(psis) / len(psis) < 0.45


def test_healthy_windows_are_never_significant():
    random.seed(21)
    flagged = 0
    for _ in range(150):
        ref = healthy(200)
        flagged += compute_drift(ref, healthy(60)).verdict == "significant"
    assert flagged == 0


def test_severe_corruption_is_always_significant():
    random.seed(31)
    for _ in range(50):
        ref = healthy(200)
        r = compute_drift(ref, corrupt(60))
        assert r.verdict == "significant"
        assert r.ks_pvalue < KS_P_SIGNIFICANT and r.psi > 1.0


def test_confidence_gauge_is_high_when_healthy_and_zero_when_corrupted():
    random.seed(41)
    healthy_conf, corrupt_conf = [], []
    for _ in range(60):
        ref = healthy(200)
        healthy_conf.append(confidence_from_ks(compute_drift(ref, healthy(60)).ks_pvalue))
        corrupt_conf.append(confidence_from_ks(compute_drift(ref, corrupt(60)).ks_pvalue))
    healthy_conf.sort()
    assert healthy_conf[len(healthy_conf) // 2] >= 80          # median healthy reading
    assert max(corrupt_conf) <= 5                               # corrupted reads ~0


def test_result_is_serialisable_with_a_valid_verdict():
    d = compute_drift([0.3] * 40 + [0.31] * 40, [0.3] * 40).as_dict()
    assert d["verdict"] in {"stable", "minor", "significant"}
    assert {"psi", "ks_statistic", "ks_pvalue", "n_reference", "n_current"} <= set(d)
