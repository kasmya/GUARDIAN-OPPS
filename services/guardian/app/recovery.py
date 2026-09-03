"""Governance layer.

Two rules:
- CRASH  -> auto-restart. We do NOT actually restart from here; docker-compose's
            restart policy does that. Guardian's job is to *observe*, *log*, and
            *time* the recovery, plus emit the explainability string.
- SILENT -> human approval required. We create a pending_approval row; a person
            hits POST /approve/{id}; we call fraud-api /admin/reset to clear
            the corrupt flag.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import httpx

from . import monitor, store
from .config import FRAUD_API_URL, POLICY_ID
from .mlflow_logger import log_incident
from .reports import write_report

log = logging.getLogger(__name__)


def _reasoning_crash(state: monitor.MonitorState) -> str:
    return (
        f"Health check to fraud-api failed {state.consecutive_health_misses} "
        f"consecutive times (threshold {monitor.CRASH_HEALTH_MISSES if hasattr(monitor,'CRASH_HEALTH_MISSES') else 2}). "
        "Classified as crash. Container-level restart policy handles recovery; "
        f"Guardian records MTTR and audits the event per policy P-001."
    )


def _reasoning_silent(drift: dict) -> str:
    return (
        f"Population Stability Index on fraud-score distribution rose to "
        f"{drift['psi']:.3f} (alert threshold 0.20). Kolmogorov-Smirnov "
        f"p={drift['ks_pvalue']:.2e}. No crash, no latency spike — the "
        f"service is up but returning a shifted distribution. Auto-restart "
        f"withheld pending human sign-off per policy {POLICY_ID} "
        f"(silent-failure class)."
    )


async def on_crash(state: monitor.MonitorState) -> None:
    reasoning = _reasoning_crash(state)
    evidence = {
        "consecutive_health_misses": state.consecutive_health_misses,
        "detected_by": "http_health_check",
    }
    inc_id = store.create_incident(
        type_="crash",
        status="in_progress",
        reasoning=reasoning,
        evidence=evidence,
        action="auto_restart",
    )
    state.running_incident_id = inc_id
    state.active_incident_type = "crash"
    state.incident_started_at = time.monotonic()
    state.transactions_seen_since_incident = 0
    log.warning("[incident %s] CRASH detected — waiting for auto-restart", inc_id)


async def watch_for_crash_recovery() -> None:
    """Loops looking for ANY in-progress crash incident and resolves it once
    fraud-api is healthy again. Queries the DB directly rather than reading
    STATE, so a silent_failure firing right after a crash cannot clobber the
    crash-resolution tracking."""
    import asyncio

    async with httpx.AsyncClient() as client:
        while True:
            if monitor.STATE.fraud_up:
                inflight = [
                    r for r in store.list_incidents(limit=20)
                    if r["type"] == "crash" and r["status"] == "in_progress"
                ]
                for inc in inflight:
                    detected_at = datetime.fromisoformat(inc["detected_at"])
                    now = datetime.now(timezone.utc)
                    mttr = round((now - detected_at).total_seconds(), 2)
                    blast = monitor.STATE.transactions_seen_since_incident \
                        if monitor.STATE.running_incident_id == inc["id"] else 0
                    inc_snapshot = dict(inc)
                    inc_snapshot.update(
                        {
                            "action": "auto_restart",
                            "mttr_seconds": mttr,
                            "blast_radius": blast,
                            "status": "resolved",
                            "resolved_at": now.isoformat(timespec="seconds"),
                        }
                    )
                    report_path = write_report(inc_snapshot)
                    store.resolve_incident(
                        inc["id"],
                        action="auto_restart",
                        mttr_seconds=mttr,
                        blast_radius=blast,
                        report_path=report_path,
                    )
                    log_incident(store.get_incident(inc["id"]) or inc_snapshot, report_path)
                    log.info("[incident %s] CRASH resolved in %.2fs", inc["id"], mttr)
                    if monitor.STATE.running_incident_id == inc["id"]:
                        monitor.reset_incident_state()
            await asyncio.sleep(1.0)


async def on_silent_failure(state: monitor.MonitorState, drift: dict) -> None:
    reasoning = _reasoning_silent(drift)
    evidence = {"drift": drift, "policy": POLICY_ID}
    inc_id = store.create_incident(
        type_="silent_failure",
        status="pending_approval",
        reasoning=reasoning,
        evidence=evidence,
        action="rollback_to_clean_mode",
    )
    state.running_incident_id = inc_id
    state.active_incident_type = "silent_failure"
    state.incident_started_at = time.monotonic()
    state.transactions_seen_since_incident = 0
    log.warning(
        "[incident %s] SILENT FAILURE flagged — awaiting human approval", inc_id
    )


async def approve_incident(incident_id: int) -> dict:
    inc = store.get_incident(incident_id)
    if not inc or inc["status"] != "pending_approval":
        raise ValueError(f"incident {incident_id} not pending approval")

    async with httpx.AsyncClient() as client:
        await client.post(f"{FRAUD_API_URL}/admin/reset", timeout=3.0)

    # Clear the rolling window and drift counters so the residual corrupted
    # scores don't re-trigger the same incident before they age out naturally.
    monitor.STATE.window.clear()
    monitor.STATE.consecutive_drift_alerts = 0

    started = monitor.STATE.incident_started_at or time.monotonic()
    mttr = round(time.monotonic() - started, 2)
    blast = monitor.STATE.transactions_seen_since_incident
    inc.update(
        {
            "action": "rollback_approved",
            "mttr_seconds": mttr,
            "blast_radius": blast,
            "status": "resolved",
        }
    )
    report_path = write_report(inc)
    store.resolve_incident(
        incident_id,
        action="rollback_approved",
        mttr_seconds=mttr,
        blast_radius=blast,
        report_path=report_path,
    )
    log_incident(store.get_incident(incident_id) or inc, report_path)
    monitor.reset_incident_state()
    return store.get_incident(incident_id) or {}
