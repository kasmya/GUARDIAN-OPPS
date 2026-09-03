"""Log every resolved incident as an MLflow run.

MLflow is normally used for model experiments; we are (deliberately) repurposing
it as the incident audit ledger. Every incident becomes a run with tags for
type/action, params for the detection config, and metrics for MTTR + blast
radius. The report file is uploaded as the artifact. If a compliance officer
asks "show me every silent-failure incident from Q3", they filter runs by tag.
"""
from __future__ import annotations

import logging
from typing import Optional

from .config import MLFLOW_TRACKING_URI

log = logging.getLogger(__name__)


def log_incident(incident: dict, report_path: Optional[str] = None) -> None:
    try:
        import mlflow
    except ImportError:
        log.warning("mlflow not installed; skipping run")
        return

    try:
        mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
        mlflow.set_experiment("guardianops-incidents")
        with mlflow.start_run(run_name=f"incident-{incident['id']:04d}"):
            mlflow.set_tags(
                {
                    "incident.type": incident.get("type", ""),
                    "incident.status": incident.get("status", ""),
                    "incident.action": incident.get("action", ""),
                }
            )
            if incident.get("mttr_seconds") is not None:
                mlflow.log_metric("mttr_seconds", float(incident["mttr_seconds"]))
            mlflow.log_metric("blast_radius", int(incident.get("blast_radius", 0)))
            if report_path:
                try:
                    mlflow.log_artifact(report_path)
                except Exception as e:
                    log.warning("could not upload report artifact: %s", e)
    except Exception as e:
        log.warning("MLflow logging failed (non-fatal): %s", e)
