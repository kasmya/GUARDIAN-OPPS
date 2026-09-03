from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from . import config as cfg
from . import monitor, recovery, store
from .config import POLICY_ID, POLICY_TEXT, REPORTS_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)
log = logging.getLogger("guardian")

app = FastAPI(title="guardian", version="1.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _startup() -> None:
    store.init_db()
    asyncio.create_task(
        monitor.monitor_loop(
            on_crash=recovery.on_crash,
            on_silent_failure=recovery.on_silent_failure,
        )
    )
    asyncio.create_task(recovery.watch_for_crash_recovery())
    log.info("guardian started")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "guardian"}


@app.get("/status")
def status() -> dict:
    snap = monitor.STATE.snapshot()
    snap["policy"] = {"id": POLICY_ID, "text": POLICY_TEXT}
    return snap


@app.get("/live-metrics")
def live_metrics() -> dict:
    return monitor.live_metrics()


@app.get("/score-history")
def score_history(limit: int = 80) -> dict:
    return monitor.score_history(limit=limit)


@app.get("/baseline")
def baseline() -> dict:
    return monitor.baseline_snapshot()


@app.get("/session-stats")
def session_stats() -> dict:
    """Aggregate the incident ledger into the numbers the dashboard's
    Session Ledger card shows. Everything here is derived from real rows
    in the incidents table — no fabricated metrics."""
    rows = store.list_incidents(limit=500)
    crashes = [r for r in rows if r["type"] == "crash"]
    silents = [r for r in rows if r["type"] == "silent_failure"]
    resolved = [r for r in rows if r["status"] == "resolved"]
    pending = [r for r in rows if r["status"] == "pending_approval"]
    mttrs = [r["mttr_seconds"] for r in resolved if r.get("mttr_seconds")]
    blast = sum(r.get("blast_radius") or 0 for r in rows)
    return {
        "total_incidents": len(rows),
        "crashes": len(crashes),
        "silent_failures": len(silents),
        "resolved": len(resolved),
        "pending_approvals": len(pending),
        "avg_mttr_seconds": round(sum(mttrs) / len(mttrs), 2) if mttrs else None,
        "total_blast_radius": blast,
        "autonomous_rate": (
            round(100 * len(crashes) / len(rows), 1) if rows else None
        ),
    }


@app.post("/check-now")
async def check_now() -> dict:
    return await monitor.force_check_now()


@app.get("/incidents")
def incidents(limit: int = 50) -> dict:
    return {"incidents": store.list_incidents(limit=limit)}


@app.get("/pending-approvals")
def pending() -> dict:
    return {"pending": store.list_pending_approvals()}


@app.post("/approve/{incident_id}")
async def approve(incident_id: int) -> dict:
    try:
        return await recovery.approve_incident(incident_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/report/latest")
def latest_report() -> dict:
    latest = store.latest_resolved()
    if not latest:
        raise HTTPException(404, "no resolved incidents yet")
    p = latest.get("report_path")
    if not p or not Path(p).exists():
        raise HTTPException(404, "report file missing")
    return {
        "incident_id": latest["id"],
        "path": p,
        "markdown": Path(p).read_text(encoding="utf-8"),
    }


@app.get("/reports")
def list_reports() -> dict:
    if not REPORTS_DIR.exists():
        return {"reports": []}
    files = sorted(REPORTS_DIR.glob("incident-*.md"), reverse=True)
    return {"reports": [f.name for f in files]}


@app.get("/reports/{name}")
def get_report(name: str) -> dict:
    path = REPORTS_DIR / name
    if not path.exists() or ".." in name:
        raise HTTPException(404, "not found")
    return {"name": name, "markdown": path.read_text(encoding="utf-8")}


@app.get("/config")
def get_config() -> dict:
    """Return the runtime-mutable subset of Guardian's config plus the
    fixed-at-startup values (window sizes) for reference."""
    return {
        "mutable": {
            "psi_alert": cfg.PSI_ALERT,
            "psi_warn": cfg.PSI_WARN,
            "poll_interval_s": cfg.POLL_INTERVAL_S,
            "drift_check_interval_s": cfg.DRIFT_CHECK_INTERVAL_S,
            "consecutive_alerts_for_incident": cfg.CONSECUTIVE_ALERTS_FOR_INCIDENT,
        },
        "fixed": {
            "window_size": cfg.WINDOW_SIZE,
            "baseline_size": cfg.BASELINE_SIZE,
            "crash_health_misses": cfg.CRASH_HEALTH_MISSES,
        },
    }


class ConfigPatch(dict):
    pass


@app.post("/config")
async def post_config(patch: dict) -> dict:
    """Update Guardian's runtime-mutable config. Values take effect on the
    monitor loop's next iteration — no restart required.

    Silently ignores unknown keys and out-of-range values. Returns the full
    current config (post-update) so the dashboard can show what actually
    stuck. See GET /config for the shape and for which keys are mutable."""
    log.info("config patch requested: %s", patch)

    def _clamp(v, lo, hi):
        try:
            return max(lo, min(hi, float(v)))
        except (TypeError, ValueError):
            return None

    if "psi_alert" in patch:
        v = _clamp(patch["psi_alert"], 0.02, 1.0)
        if v is not None:
            cfg.PSI_ALERT = round(v, 3)
    if "psi_warn" in patch:
        v = _clamp(patch["psi_warn"], 0.01, cfg.PSI_ALERT)
        if v is not None:
            cfg.PSI_WARN = round(v, 3)
    if "poll_interval_s" in patch:
        v = _clamp(patch["poll_interval_s"], 0.5, 60.0)
        if v is not None:
            cfg.POLL_INTERVAL_S = round(v, 2)
    if "drift_check_interval_s" in patch:
        v = _clamp(patch["drift_check_interval_s"], 1.0, 600.0)
        if v is not None:
            cfg.DRIFT_CHECK_INTERVAL_S = round(v, 2)
    if "consecutive_alerts_for_incident" in patch:
        v = _clamp(patch["consecutive_alerts_for_incident"], 1, 10)
        if v is not None:
            cfg.CONSECUTIVE_ALERTS_FOR_INCIDENT = int(v)

    return get_config()


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
