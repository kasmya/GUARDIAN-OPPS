"""API-level and governance tests for Guardian.

These tests exercise behaviour that was wrong at some point during
development (see Table 4.2 of the report): hard-coded drift thresholds,
an approval that crashed instead of failing cleanly, a report that printed
"None", and report-name validation.
"""
import asyncio
import random

import httpx
import pytest
from fastapi.testclient import TestClient

from app import config as cfg
from app import monitor, recovery, reports, store
from app.drift import compute_drift
from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """TestClient without running startup events (no background monitor loop)."""
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "g.db")
    monkeypatch.setattr(reports, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr("app.main.REPORTS_DIR", tmp_path / "reports")
    store.init_db()
    monitor.reset_incident_state()
    yield TestClient(app)


@pytest.fixture(autouse=True)
def restore_config():
    saved = (cfg.PSI_ALERT, cfg.PSI_WARN, cfg.POLL_INTERVAL_S,
             cfg.DRIFT_CHECK_INTERVAL_S, cfg.CONSECUTIVE_ALERTS_FOR_INCIDENT)
    yield
    (cfg.PSI_ALERT, cfg.PSI_WARN, cfg.POLL_INTERVAL_S,
     cfg.DRIFT_CHECK_INTERVAL_S, cfg.CONSECUTIVE_ALERTS_FOR_INCIDENT) = saved


# ------------------------------------------------------------------ drift
def _clearly_shifted():
    """Baseline N(0.30, 0.08) vs a live window N(0.45, 0.08): a big, real shift."""
    random.seed(7)
    ref = [random.gauss(0.30, 0.08) for _ in range(400)]
    cur = [random.gauss(0.45, 0.08) for _ in range(120)]
    return ref, cur


def test_psi_threshold_parameter_decides_the_verdict():
    """The PSI alert level is a real parameter (it is the runtime-configurable
    slider), not a constant: same data, different threshold, different verdict."""
    ref, cur = _clearly_shifted()
    permissive = compute_drift(ref, cur, psi_alert=0.05, psi_warn=0.02)
    strict = compute_drift(ref, cur, psi_alert=50.0, psi_warn=40.0)
    assert permissive.psi == pytest.approx(strict.psi)
    assert permissive.ks_pvalue < 1e-4                 # statistically real shift
    assert permissive.verdict == "significant"
    assert strict.verdict != "significant"             # effect size below the (huge) threshold


def test_too_few_samples_is_always_stable():
    r = compute_drift([0.3] * 10, [0.9] * 10)
    assert r.verdict == "stable" and r.psi == 0.0


# ----------------------------------------------------------------- config
def test_config_post_clamps_and_keeps_warn_below_alert(client):
    r = client.post("/config", json={"psi_alert": 5})          # above max 1.0
    assert r.status_code == 200
    assert r.json()["mutable"]["psi_alert"] == 1.0
    r = client.post("/config", json={"psi_alert": 0.05})
    m = r.json()["mutable"]
    assert m["psi_alert"] == 0.05 and m["psi_warn"] <= m["psi_alert"]


def test_config_post_ignores_unknown_and_bad_values(client):
    before = client.get("/config").json()
    r = client.post("/config", json={"nonsense": 1, "poll_interval_s": "abc"})
    assert r.status_code == 200
    assert r.json() == before


def test_config_change_is_visible_in_status(client):
    client.post("/config", json={"drift_check_interval_s": 9})
    assert client.get("/status").json()["config"]["drift_check_interval_s"] == 9.0


# --------------------------------------------------------------- approval
def test_approve_unknown_incident_is_400(client):
    assert client.post("/approve/999999").status_code == 400


def test_approve_when_fraud_api_down_is_502_and_incident_stays_pending(client, monkeypatch):
    inc_id = store.create_incident(
        "silent_failure", "pending_approval", "r", {"drift": {"psi": 0.4}}, "rollback_to_clean_mode"
    )

    class Boom:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k): raise httpx.ConnectError("down")

    monkeypatch.setattr(recovery.httpx, "AsyncClient", lambda *a, **k: Boom())
    r = client.post(f"/approve/{inc_id}")
    assert r.status_code == 502
    assert store.get_incident(inc_id)["status"] == "pending_approval"


def test_approve_success_resolves_incident_and_report_has_no_none(client, monkeypatch):
    inc_id = store.create_incident(
        "silent_failure", "pending_approval", "r", {"drift": {"psi": 0.4}}, "rollback_to_clean_mode"
    )

    class OK:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k):
            return httpx.Response(200, json={}, request=httpx.Request("POST", "http://x"))

    monkeypatch.setattr(recovery.httpx, "AsyncClient", lambda *a, **k: OK())
    monkeypatch.setattr(recovery, "log_incident", lambda *a, **k: None)   # no MLflow in unit tests
    r = client.post(f"/approve/{inc_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "resolved" and body["action"] == "rollback_approved"
    text = open(body["report_path"], encoding="utf-8").read()
    assert "None" not in text
    assert "Resolved at:** 20" in text      # an ISO timestamp, not 'in progress'
    # a second approval of the same incident is refused
    assert client.post(f"/approve/{inc_id}").status_code == 400


# ---------------------------------------------------------------- reports
def test_report_name_validation(client, tmp_path):
    rdir = tmp_path / "reports"
    rdir.mkdir(exist_ok=True)
    good = rdir / "incident-0001-20261025-120000.md"
    good.write_text("# ok", encoding="utf-8")
    assert client.get(f"/reports/{good.name}").status_code == 200
    for bad in ("..%2F..%2Fetc%2Fpasswd", "..", "secret.txt", "incident-1-2-3.md"):
        assert client.get(f"/reports/{bad}").status_code == 404


def test_report_latest_404_without_incidents(client):
    assert client.get("/report/latest").status_code == 404


# ------------------------------------------------------------ session stats
def test_session_stats_empty_and_populated(client):
    s = client.get("/session-stats").json()
    assert s["total_incidents"] == 0 and s["avg_mttr_seconds"] is None
    a = store.create_incident("crash", "in_progress", "r", {}, "auto_restart")
    store.resolve_incident(a, "auto_restart", 10.0, 3)
    b = store.create_incident("silent_failure", "pending_approval", "r", {}, "x")
    s = client.get("/session-stats").json()
    assert s["total_incidents"] == 2 and s["crashes"] == 1 and s["silent_failures"] == 1
    assert s["pending_approvals"] == 1 and s["resolved"] == 1
    assert s["avg_mttr_seconds"] == 10.0 and s["total_blast_radius"] == 3
