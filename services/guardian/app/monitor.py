"""Background monitor.

One asyncio task loop. Every POLL_INTERVAL_S it does:
1. Health-check fraud-api. Consecutive misses -> crash incident.
2. Send a synthetic transaction and record the score.
3. Every DRIFT_CHECK_INTERVAL_S, compare the recent window vs. the baseline
   and update the exported PSI + Confidence Score metrics. A sustained
   significant drift raises a silent-failure incident.

The baseline is captured *once* at startup from a warm fraud-api, so we always
have a "known-good" reference to compare against.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Tuple

import httpx
import numpy as np
from prometheus_client import Gauge

from .config import (
    BASELINE_SIZE,
    CONSECUTIVE_ALERTS_FOR_INCIDENT,
    CRASH_HEALTH_MISSES,
    DRIFT_CHECK_INTERVAL_S,
    FRAUD_API_URL,
    POLL_INTERVAL_S,
    PSI_ALERT,
    PSI_WARN,
    WINDOW_SIZE,
)
from .drift import compute_drift, confidence_from_psi

log = logging.getLogger(__name__)

CONFIDENCE = Gauge("guardian_confidence_score", "0-100, higher = healthier")
DRIFT_PSI = Gauge("guardian_drift_psi", "PSI of recent scores vs baseline")
FRAUD_UP = Gauge("guardian_fraud_api_up", "1 if last health check succeeded")


# (unix_ts, score, latency_seconds, ok)
Sample = Tuple[float, float, float, bool]


@dataclass
class MonitorState:
    baseline: list[float] = field(default_factory=list)
    window: Deque[float] = field(default_factory=lambda: deque(maxlen=WINDOW_SIZE))
    samples: Deque[Sample] = field(default_factory=lambda: deque(maxlen=240))
    health_history: Deque[bool] = field(default_factory=lambda: deque(maxlen=90))
    consecutive_health_misses: int = 0
    consecutive_drift_alerts: int = 0
    last_drift: dict | None = None
    confidence: float = 100.0
    running_incident_id: int | None = None
    active_incident_type: str | None = None
    incident_started_at: float | None = None
    transactions_seen_since_incident: int = 0
    fraud_up: bool = True

    def snapshot(self) -> dict:
        return {
            "confidence": self.confidence,
            "last_drift": self.last_drift,
            "window_size": len(self.window),
            "baseline_size": len(self.baseline),
            "fraud_api_up": self.fraud_up,
            "active_incident_id": self.running_incident_id,
            "active_incident_type": self.active_incident_type,
            "blast_radius_current": self.transactions_seen_since_incident,
            "config": {
                "poll_interval_s": POLL_INTERVAL_S,
                "drift_check_interval_s": DRIFT_CHECK_INTERVAL_S,
                "window_size": WINDOW_SIZE,
                "baseline_size": BASELINE_SIZE,
                "psi_alert": PSI_ALERT,
                "psi_warn": PSI_WARN,
            },
        }


STATE = MonitorState()


async def _sample_score(client: httpx.AsyncClient) -> tuple[float | None, float]:
    t0 = time.perf_counter()
    try:
        r = await client.post(f"{FRAUD_API_URL}/score", timeout=5.0)
        r.raise_for_status()
        return float(r.json()["score"]), time.perf_counter() - t0
    except Exception:
        return None, time.perf_counter() - t0


async def _health(client: httpx.AsyncClient) -> bool:
    try:
        r = await client.get(f"{FRAUD_API_URL}/health", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


async def _capture_baseline(client: httpx.AsyncClient) -> None:
    log.info("capturing baseline of %d scores from fraud-api...", BASELINE_SIZE)
    baseline: list[float] = []
    attempts = 0
    while len(baseline) < BASELINE_SIZE and attempts < BASELINE_SIZE * 3:
        s, _ = await _sample_score(client)
        if s is not None:
            baseline.append(s)
        else:
            await asyncio.sleep(0.3)
        attempts += 1
    STATE.baseline = baseline
    log.info("baseline captured: %d samples", len(baseline))


async def monitor_loop(on_crash, on_silent_failure) -> None:
    """on_crash(state) and on_silent_failure(state, drift_dict) are async
    callbacks provided by recovery.py."""
    async with httpx.AsyncClient() as client:
        for _ in range(30):
            if await _health(client):
                break
            await asyncio.sleep(1.0)

        await _capture_baseline(client)

        last_drift_check = 0.0
        while True:
            healthy = await _health(client)
            FRAUD_UP.set(1 if healthy else 0)
            STATE.fraud_up = healthy
            STATE.health_history.append(healthy)

            if not healthy:
                STATE.consecutive_health_misses += 1
                if (
                    STATE.consecutive_health_misses >= CRASH_HEALTH_MISSES
                    and STATE.active_incident_type != "crash"
                ):
                    await on_crash(STATE)
            else:
                STATE.consecutive_health_misses = 0

                score, latency = await _sample_score(client)
                if score is not None:
                    STATE.window.append(score)
                    STATE.samples.append((time.time(), score, latency, True))
                    if STATE.active_incident_type:
                        STATE.transactions_seen_since_incident += 1
                else:
                    STATE.samples.append((time.time(), 0.0, latency, False))

                now = time.monotonic()
                if now - last_drift_check >= DRIFT_CHECK_INTERVAL_S:
                    last_drift_check = now
                    d = _run_drift_check()
                    if d and d["verdict"] == "significant":
                        STATE.consecutive_drift_alerts += 1
                    elif d:
                        STATE.consecutive_drift_alerts = 0

                    if (
                        STATE.consecutive_drift_alerts
                        >= CONSECUTIVE_ALERTS_FOR_INCIDENT
                        and STATE.active_incident_type != "silent_failure"
                    ):
                        await on_silent_failure(STATE, STATE.last_drift or {})

            await asyncio.sleep(POLL_INTERVAL_S)


def _run_drift_check() -> dict | None:
    # Require the window to be full — a half-full window under-samples the
    # tail of the distribution and inflates PSI, producing false positives
    # during Guardian's first ~2 minutes.
    if not STATE.baseline or len(STATE.window) < WINDOW_SIZE:
        return None
    d = compute_drift(STATE.baseline, list(STATE.window))
    STATE.last_drift = d.as_dict()
    STATE.confidence = confidence_from_psi(d.psi, PSI_ALERT)
    CONFIDENCE.set(STATE.confidence)
    DRIFT_PSI.set(d.psi)
    return STATE.last_drift


async def force_check_now() -> dict:
    """Run an immediate drift check on demand (dashboard button)."""
    d = _run_drift_check()
    if d is None:
        return {"verdict": "insufficient_data", "psi": 0.0, "n_current": len(STATE.window)}
    return d


def live_metrics() -> dict:
    """Aggregate the last 60 seconds of monitor samples into the numbers the
    dashboard shows in the readouts (latency p50, throughput, uptime)."""
    now = time.time()
    recent = [s for s in STATE.samples if now - s[0] <= 60]
    ok_recent = [s for s in recent if s[3]]
    if ok_recent:
        lats = sorted(s[2] for s in ok_recent)
        p50_ms = lats[len(lats) // 2] * 1000
    else:
        p50_ms = None
    throughput_per_min = len(ok_recent)
    checks = list(STATE.health_history)
    uptime = 100.0 * (sum(1 for x in checks if x) / len(checks)) if checks else 100.0
    return {
        "latency_ms_p50": round(p50_ms, 1) if p50_ms is not None else None,
        "throughput_per_min": throughput_per_min,
        "uptime_pct": round(uptime, 2),
        "samples_in_window": len(ok_recent),
    }


def baseline_snapshot() -> dict:
    """Return the frozen baseline (raw samples + summary) so the dashboard
    can render a baseline-vs-live histogram on the client."""
    return {
        "samples": list(STATE.baseline),
        "size": len(STATE.baseline),
        "mean": float(np.mean(STATE.baseline)) if STATE.baseline else 0.5,
        "std": float(np.std(STATE.baseline)) if STATE.baseline else 0.0,
    }


def score_history(limit: int = 80) -> dict:
    baseline_mean = float(np.mean(STATE.baseline)) if STATE.baseline else 0.5
    baseline_std = float(np.std(STATE.baseline)) if STATE.baseline else 0.1
    live = [
        {"t": s[0], "score": s[1], "ok": s[3]}
        for s in list(STATE.samples)[-limit:]
    ]
    verdict = (STATE.last_drift or {}).get("verdict", "stable")
    return {
        "baseline_mean": round(baseline_mean, 4),
        "baseline_std": round(baseline_std, 4),
        "baseline_size": len(STATE.baseline),
        "live": live,
        "current_verdict": verdict,
        "psi": (STATE.last_drift or {}).get("psi", 0.0),
        "confidence": STATE.confidence,
    }


def reset_incident_state() -> None:
    STATE.consecutive_drift_alerts = 0
    STATE.running_incident_id = None
    STATE.active_incident_type = None
    STATE.incident_started_at = None
    STATE.transactions_seen_since_incident = 0
