import random

from app.drift import compute_drift, confidence_from_ks, population_stability_index


def test_psi_zero_on_identical_distributions():
    random.seed(0)
    ref = [random.gauss(0.3, 0.1) for _ in range(300)]
    cur = list(ref)
    assert population_stability_index(ref, cur) < 0.01


def test_psi_flags_significant_shift():
    random.seed(0)
    ref = [random.gauss(0.3, 0.08) for _ in range(300)]
    cur = [random.betavariate(9, 1.4) for _ in range(300)]
    psi = population_stability_index(ref, cur)
    assert psi > 0.20


def test_compute_drift_verdicts():
    random.seed(42)
    ref = [random.gauss(0.3, 0.08) for _ in range(500)]
    # Same distribution: verdict should not be "significant". KS on small
    # samples can flip stable<->minor by chance so we accept both.
    same = compute_drift(ref, [random.gauss(0.3, 0.08) for _ in range(200)])
    assert same.verdict in {"stable", "minor"}
    corrupt = compute_drift(ref, [random.betavariate(9, 1.4) for _ in range(200)])
    assert corrupt.verdict == "significant"


def test_confidence_score_monotone():
    assert confidence_from_ks(1.0) == 100.0
    assert confidence_from_ks(0.5) > confidence_from_ks(0.05) > confidence_from_ks(0.001)
    assert confidence_from_ks(1e-4) == 0.0
    assert confidence_from_ks(1e-30) == 0.0
    assert confidence_from_ks(0.0) == 0.0
