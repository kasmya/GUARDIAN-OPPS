"""Offline evaluation of Guardian's silent-failure detector.

Answers two questions with simulation instead of opinion:

1. FALSE ALARMS  - how often does the detector open an incident on a healthy
   system?  (N independent simulated hours of normal traffic)
2. DETECTION     - how often, and how fast, does it open an incident when the
   score distribution shifts?  (Beta-corruption and fixed score offsets)

The simulation uses the project's real code: ``score_normal`` / ``score_corrupt``
from fraud-api and ``compute_drift`` / ``confidence_from_ks`` from guardian,
driven with the same timing as the monitor loop (one /score sample every 2 s,
one drift check every 5 s, a 60-sample rolling window against a 200-sample
baseline, an incident after K consecutive 'significant' checks).

Run (from the repository root, with the guardian dependencies installed):

    python services/guardian/tools/evaluate_drift.py --runs 200 --out report/results/drift_evaluation.json

Everything is seeded, so the printed numbers are reproducible.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import random
import statistics
import sys
import time
from pathlib import Path

import numpy as np
from scipy import stats

ROOT = Path(__file__).resolve().parents[3]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


drift = _load("guardian_drift", ROOT / "services/guardian/app/drift.py")
scoring = _load("fraud_scoring", ROOT / "services/fraud-api/app/scoring.py")

POLL_S, CHECK_S, WINDOW, BASELINE = 2.0, 5.0, 60, 200


# ------------------------------------------------------------ traffic models
def healthy(n):
    return [scoring.score_normal(scoring.Transaction.sample()) for _ in range(n)]


def corrupt(n):
    return [scoring.score_corrupt(None) for _ in range(n)]


def shifted(offset):
    return lambda n: [min(1.0, max(0.0, s + offset)) for s in healthy(n)]


# ------------------------------------------------------------ decision rules
def rule_current(ref, win):
    return drift.compute_drift(ref, win).verdict == "significant"


def rule_legacy(ref, win):
    """The rule shipped before this evaluation: PSI >= 0.20 OR KS p < 0.001."""
    psi = drift.population_stability_index(np.array(ref), np.array(win))
    _, p = stats.ks_2samp(ref, win)
    return psi >= 0.20 or p < 0.001


RULES = {
    "legacy (PSI>=0.20 or KS p<0.001, 2 checks)": (rule_legacy, 2),
    "current (KS p<1e-4 and PSI>=0.20, 3 checks)": (rule_current, 3),
}


def seconds_to_incident(rule, k, stream_fn, n_samples, seed):
    """Seconds until an incident opens, or None if it never does."""
    random.seed(seed)
    ref = healthy(BASELINE)
    window = healthy(WINDOW)               # the window starts full of healthy data
    stream = stream_fn(n_samples)
    consecutive, last_check = 0, 0.0
    for i, s in enumerate(stream):
        t = (i + 1) * POLL_S
        window = window[1:] + [s]
        if t - last_check >= CHECK_S:
            last_check = t
            consecutive = consecutive + 1 if rule(ref, window) else 0
            if consecutive >= k:
                return t
    return None


def gauge_distribution(runs=60, seed=77):
    """Confidence-gauge values on healthy windows and on fully corrupted windows."""
    random.seed(seed)
    healthy_vals, corrupt_vals = [], []
    for _ in range(runs):
        ref = healthy(BASELINE)
        healthy_vals.append(drift.confidence_from_ks(drift.compute_drift(ref, healthy(WINDOW)).ks_pvalue))
        corrupt_vals.append(drift.confidence_from_ks(drift.compute_drift(ref, corrupt(WINDOW)).ks_pvalue))
    q = lambda v, p: float(np.percentile(v, p))
    return {
        "healthy": {"median": q(healthy_vals, 50), "p05": q(healthy_vals, 5), "min": min(healthy_vals)},
        "corrupt": {"median": q(corrupt_vals, 50), "p95": q(corrupt_vals, 95), "max": max(corrupt_vals)},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=200, help="simulated healthy hours per rule")
    ap.add_argument("--power-runs", type=int, default=100, help="runs per drift scenario")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    t0 = time.time()
    result = {"config": {"poll_s": POLL_S, "check_s": CHECK_S, "window": WINDOW, "baseline": BASELINE,
                         "healthy_hours_per_rule": args.runs, "power_runs": args.power_runs}, "rules": {}}
    scenarios = [("severe corruption (Beta(9,1.4))", corrupt),
                 ("score offset +0.20", shifted(0.20)),
                 ("score offset +0.15", shifted(0.15)),
                 ("score offset +0.10", shifted(0.10)),
                 ("score offset +0.05", shifted(0.05))]

    for name, (rule, k) in RULES.items():
        fa = sum(seconds_to_incident(rule, k, healthy, 1800, 10_000 + j) is not None for j in range(args.runs))
        entry = {"false_alarm_hours": fa, "hours": args.runs, "false_alarm_pct": round(100 * fa / args.runs, 1),
                 "detection": {}}
        for label, fn in scenarios:
            delays = [seconds_to_incident(rule, k, fn, 300, 50_000 + j) for j in range(args.power_runs)]
            hit = [d for d in delays if d is not None]
            entry["detection"][label] = {
                "detected_pct": round(100 * len(hit) / args.power_runs, 1),
                "median_seconds": statistics.median(hit) if hit else None,
                "p90_seconds": float(np.percentile(hit, 90)) if hit else None,
            }
        result["rules"][name] = entry

    result["confidence_gauge"] = gauge_distribution()
    result["runtime_seconds"] = round(time.time() - t0, 1)

    # ------------------------------------------------------------- print
    print(f"\nFALSE ALARMS on healthy traffic ({args.runs} simulated hours per rule)")
    for name, e in result["rules"].items():
        print(f"  {name:<46} {e['false_alarm_hours']:>3}/{e['hours']} hours with a false incident ({e['false_alarm_pct']}%)")
    print(f"\nDETECTION ({args.power_runs} runs per scenario; incident within 5 minutes of onset)")
    for name, e in result["rules"].items():
        print(f"  {name}")
        for label, d in e["detection"].items():
            med = f"{d['median_seconds']:.0f}s" if d["median_seconds"] is not None else "-"
            print(f"      {label:<34} detected {d['detected_pct']:>5}%   median delay {med}")
    g = result["confidence_gauge"]
    print(f"\nCONFIDENCE GAUGE  healthy: median {g['healthy']['median']:.0f}, 5th pct {g['healthy']['p05']:.0f}"
          f"  |  fully corrupted: median {g['corrupt']['median']:.0f}")
    print(f"\n(runtime {result['runtime_seconds']} s)")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"written {args.out}")


if __name__ == "__main__":
    main()
