"""Drift statistics.

Two complementary signals are computed on every drift check:

* Kolmogorov-Smirnov two-sample test (``scipy.stats.ks_2samp``).  It is
  non-parametric and its p-value is *calibrated for the sample sizes involved*,
  so it decides whether a difference between the live window and the frozen
  baseline is statistically real.
* Population Stability Index (PSI), the classic credit-risk drift measure.  It
  quantifies *how large* the shift is (an effect size).  Conventional bands are
  <0.10 stable, 0.10-0.20 minor, >0.20 significant, but those bands were
  defined for samples of thousands.  With a 60-sample live window PSI is
  strongly biased upwards: measured on healthy simulated traffic its mean is
  about 0.3 with NO drift at all (a first-order estimate,
  (bins-1) * (1/n_ref + 1/n_cur) = 0.195, is already at the alarm line).  Using
  PSI alone therefore raised a false incident in every simulated healthy hour
  (report Section 4.3).  PSI is consequently used only as an effect-size filter
  *after* the KS test has rejected 'same distribution'.

Decision rule used by ``compute_drift``:

    significant : KS p < KS_P_SIGNIFICANT  AND  PSI >= psi_alert
    minor       : KS p < KS_P_MINOR        AND  PSI >= psi_warn
    stable      : otherwise

A silent-failure incident additionally requires ``significant`` on several
consecutive checks (``CONSECUTIVE_ALERTS_FOR_INCIDENT``, default 3).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats

KS_P_SIGNIFICANT = 1e-4
KS_P_MINOR = 1e-2
PSI_BINS = 10
MIN_REFERENCE = 30
MIN_CURRENT = 15


@dataclass
class DriftResult:
    psi: float
    ks_statistic: float
    ks_pvalue: float
    n_reference: int
    n_current: int
    verdict: str  # "stable" | "minor" | "significant"

    def as_dict(self) -> dict:
        return {
            "psi": round(self.psi, 4),
            "ks_statistic": round(self.ks_statistic, 4),
            "ks_pvalue": float(f"{self.ks_pvalue:.4g}"),
            "n_reference": self.n_reference,
            "n_current": self.n_current,
            "verdict": self.verdict,
        }


def population_stability_index(
    reference: np.ndarray, current: np.ndarray, bins: int = PSI_BINS
) -> float:
    """Standard PSI on quantile bins of the reference sample."""
    if len(reference) < bins or len(current) < bins:
        return 0.0
    edges = np.quantile(reference, np.linspace(0, 1, bins + 1))
    edges[0] -= 1e-6
    edges[-1] += 1e-6
    ref_counts, _ = np.histogram(reference, bins=edges)
    cur_counts, _ = np.histogram(current, bins=edges)
    ref_p = np.clip(ref_counts / max(len(reference), 1), 1e-6, None)
    cur_p = np.clip(cur_counts / max(len(current), 1), 1e-6, None)
    return float(np.sum((cur_p - ref_p) * np.log(cur_p / ref_p)))


def compute_drift(
    reference: list[float],
    current: list[float],
    psi_alert: float = 0.20,
    psi_warn: float = 0.10,
) -> DriftResult:
    """Compare a live window with the frozen baseline (see module docstring)."""
    ref = np.asarray(reference, dtype=float)
    cur = np.asarray(current, dtype=float)
    if len(ref) < MIN_REFERENCE or len(cur) < MIN_CURRENT:
        return DriftResult(0.0, 0.0, 1.0, len(ref), len(cur), "stable")

    psi = population_stability_index(ref, cur)
    ks_stat, ks_p = stats.ks_2samp(ref, cur)

    verdict = "stable"
    if ks_p < KS_P_SIGNIFICANT and psi >= psi_alert:
        verdict = "significant"
    elif ks_p < KS_P_MINOR and psi >= psi_warn:
        verdict = "minor"
    return DriftResult(psi, float(ks_stat), float(ks_p), len(ref), len(cur), verdict)


def confidence_from_ks(ks_pvalue: float) -> float:
    """Confidence (0-100) that the live window still matches the baseline.

    Based on how far the KS p-value has fallen toward the alarm level:
    p = 1 (identical) -> 100, p = KS_P_SIGNIFICANT (1e-4) or smaller -> 0,
    linear in log10(p) in between.  Healthy traffic has uniformly distributed
    p-values, so the gauge sits high (median about 90) and only a real shift
    drives it to zero.
    """
    if ks_pvalue >= 1.0:
        return 100.0
    floor = -np.log10(KS_P_SIGNIFICANT)
    depth = min(max(-np.log10(max(ks_pvalue, 1e-300)), 0.0), floor)
    return float(round(100.0 * (1.0 - depth / floor), 1))
