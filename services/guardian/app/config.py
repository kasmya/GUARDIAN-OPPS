"""All tunables live here so the demo can be tightened without hunting."""
from __future__ import annotations

import os
from pathlib import Path

FRAUD_API_URL = os.environ.get("FRAUD_API_URL", "http://fraud-api:8000")
CHAOS_URL = os.environ.get("CHAOS_URL", "http://chaos-injector:8000")
MLFLOW_TRACKING_URI = os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000")

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
REPORTS_DIR = Path(os.environ.get("REPORTS_DIR", "/reports"))
DB_PATH = DATA_DIR / "guardian.db"

POLL_INTERVAL_S = 2.0
DRIFT_CHECK_INTERVAL_S = 5.0
WINDOW_SIZE = 60
BASELINE_SIZE = 200

PSI_WARN = 0.10
PSI_ALERT = 0.20
CONSECUTIVE_ALERTS_FOR_INCIDENT = 2

CRASH_HEALTH_MISSES = 2

POLICY_ID = "P-002"
POLICY_TEXT = (
    "Silent-failure incidents require a human approval before rollback. "
    "Crash incidents may be auto-restarted (policy P-001)."
)
