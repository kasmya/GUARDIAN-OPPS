"""Drift statistics.

We use two complementary signals:
- Population Stability Index (PSI): the classic banking/credit-risk drift metric.
  Bank teams recognise it instantly, which matters for the "why did you pick
  this?" question. Rule of thumb: PSI < 0.10 = stable, 0.10-0.20 = minor drift,
  > 0.20 = significant drift (rollback candidate).
- Kolmogorov-Smirnov two-sample test: a nonparametric distribution comparison.
  Gives us a p-value that is easy to phrase in the incident report.

We deliberately do NOT depend on Evidently here — see DIARY stage 4 for why.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats


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
            "ks_pvalue": round(self.ks_pvalue, 6),
            "n_reference": self.n_reference,
            "n_current": self.n_current,
            "verdict": self.verdict,
        }


def population_stability_index(
    reference: np.ndarray, current: np.ndarray, bins: int = 10
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


def compute_drift(reference: list[float], current: list[float]) -> DriftResult:
    ref = np.asarray(reference, dtype=float)
    cur = np.asarray(current, dtype=float)
    if len(ref) < 30 or len(cur) < 15:
        return DriftResult(0.0, 0.0, 1.0, len(ref), len(cur), "stable")

    psi = population_stability_index(ref, cur)
    ks_stat, ks_p = stats.ks_2samp(ref, cur)
    verdict = "stable"
    if psi >= 0.20 or ks_p < 0.001:
        verdict = "significant"
    elif psi >= 0.10 or ks_p < 0.05:
        verdict = "minor"
    return DriftResult(psi, float(ks_stat), float(ks_p), len(ref), len(cur), verdict)


def confidence_from_psi(psi: float, alert_psi: float = 0.20) -> float:
    """Map PSI to a 0-100 confidence score. Smooth so the dashboard trends."""
    if psi <= 0:
        return 100.0
    ratio = min(psi / max(alert_psi, 1e-6), 2.0)
    return float(round(max(0.0, 100.0 * (1.0 - 0.5 * ratio)), 1))
