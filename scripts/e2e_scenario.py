"""End-to-end scenario test for the silent-failure path (stdlib only).

    python scripts/e2e_scenario.py

Against a running stack (default: the local ports) this script:

  1. speeds Guardian up through the runtime-config API (poll 0.5 s, check 1 s)
  2. waits for the baseline and for the rolling window to fill with healthy data
  3. asserts that NO incident opens while the system is healthy (false-alarm check)
  4. injects silent corruption through the chaos-injector
  5. waits for Guardian to open a pending_approval incident
  6. asserts that Guardian did NOT roll back on its own (policy P-002)
  7. approves the incident through the API
  8. asserts: incident resolved, fraud-api back to mode=normal, markdown report
     served, MLflow-independent audit trail present
  9. restores the original configuration

Exit code 0 = every assertion held.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

G = os.environ.get("GUARDIAN_URL", "http://127.0.0.1:8002")
F = os.environ.get("FRAUD_URL", "http://127.0.0.1:8001")
C = os.environ.get("CHAOS_URL", "http://127.0.0.1:8003")


def call(method: str, url: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else (b"" if method == "POST" else None)
    req = urllib.request.Request(url, data=data, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def wait_for(label: str, predicate, timeout: float, every: float = 1.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = predicate()
        if v:
            return v
        time.sleep(every)
    raise AssertionError(f"timed out after {timeout:.0f}s waiting for: {label}")


def step(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    original = call("GET", f"{G}/config")[1]["mutable"]
    try:
        call("POST", f"{C}/reset")
        step("1. speeding Guardian up via POST /config (poll 0.5 s, drift check 1 s)")
        call("POST", f"{G}/config", {"poll_interval_s": 0.5, "drift_check_interval_s": 1})

        step("2. waiting for the 200-sample baseline and a full 60-sample window")
        wait_for("baseline", lambda: call("GET", f"{G}/baseline")[1]["size"] >= 200, 120)
        wait_for("window", lambda: call("GET", f"{G}/status")[1]["window_size"] >= 60, 120)

        before = call("GET", f"{G}/incidents?limit=500")[1]["incidents"]
        open_before = {i["id"] for i in before if i["status"] != "resolved"}

        step("3. healthy for 40 s: no new incident may open")
        time.sleep(40)
        now = call("GET", f"{G}/incidents?limit=500")[1]["incidents"]
        new = [i for i in now if i["id"] not in {b["id"] for b in before}]
        assert not new, f"FALSE ALARM on healthy traffic: {[(i['id'], i['type']) for i in new]}"
        step("   ok - no false alarm")

        step("4. injecting silent corruption via chaos-injector")
        code, body = call("POST", f"{C}/corrupt")
        assert code == 200 and body["scenario"] == "corrupt", (code, body)
        assert call("GET", f"{F}/health")[1]["mode"] == "corrupt"

        step("5. waiting for a pending_approval silent_failure incident")
        def pending():
            ps = call("GET", f"{G}/pending-approvals")[1]["pending"]
            return [p for p in ps if p["id"] not in open_before and p["type"] == "silent_failure"]
        inc = wait_for("pending incident", pending, 180)[0]
        step(f"   incident #{inc['id']} opened, psi={inc['evidence']['drift']['psi']}, "
             f"ks_p={inc['evidence']['drift']['ks_pvalue']}")
        assert inc["status"] == "pending_approval"
        assert "p=" in inc["reasoning"] and "P-002" in inc["reasoning"]

        step("6. policy P-002: Guardian must NOT roll back by itself")
        time.sleep(6)
        assert call("GET", f"{F}/health")[1]["mode"] == "corrupt", "Guardian rolled back without approval!"
        step("   ok - still corrupt and still pending after 6 s")

        step("7. approving the rollback")
        code, resolved = call("POST", f"{G}/approve/{inc['id']}")
        assert code == 200, (code, resolved)
        assert resolved["status"] == "resolved" and resolved["action"] == "rollback_approved", resolved

        step("8. verifying the outcome")
        assert call("GET", f"{F}/health")[1]["mode"] == "normal"
        code, rep = call("GET", f"{G}/report/latest")
        assert code == 200 and f"Incident {inc['id']:04d}" in rep["markdown"], rep
        assert "None" not in rep["markdown"], "report still prints None"
        assert call("POST", f"{G}/approve/{inc['id']}")[0] == 400, "double approval must be refused"
        stats = call("GET", f"{G}/session-stats")[1]
        assert stats["resolved"] >= 1 and stats["silent_failures"] >= 1
        step(f"   ok - resolved in {resolved['mttr_seconds']} s, report served, double approval refused")
        print("\nE2E SCENARIO PASSED")
        return 0
    except AssertionError as e:
        print(f"\nE2E SCENARIO FAILED: {e}")
        return 1
    finally:
        call("POST", f"{C}/reset")
        call("POST", f"{G}/config", {k: original[k] for k in
                                      ("psi_alert", "poll_interval_s", "drift_check_interval_s",
                                       "consecutive_alerts_for_incident")})


if __name__ == "__main__":
    sys.exit(main())
