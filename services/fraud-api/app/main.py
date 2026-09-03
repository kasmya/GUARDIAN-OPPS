from __future__ import annotations

import os
import time
from typing import Optional

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from pydantic import BaseModel, Field

from .scoring import Transaction, score_corrupt, score_normal
from .state import read_state, reset_state, write_state

app = FastAPI(title="fraud-api", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _reset_state_on_startup() -> None:
    """Always boot in normal mode. Prevents a corrupt/slow flag left in the
    shared state file from a previous run silently poisoning Guardian's
    baseline capture."""
    reset_state()

REQUESTS = Counter("fraud_api_requests_total", "Requests to /score", ["outcome"])
LATENCY = Histogram(
    "fraud_api_latency_seconds",
    "End-to-end latency of /score",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)
MODE = Gauge("fraud_api_mode", "0=normal 1=slow 2=corrupt")


class TxIn(BaseModel):
    amount: float = Field(..., ge=0)
    merchant_category: str
    hour: int = Field(..., ge=0, le=23)
    country_risk: float = Field(0.1, ge=0.0, le=1.0)


class ScoreOut(BaseModel):
    score: float
    label: str
    model_version: str


def _mode_gauge(mode: str) -> None:
    MODE.set({"normal": 0, "slow": 1, "corrupt": 2}.get(mode, 0))


@app.get("/health")
def health() -> dict:
    st = read_state()
    _mode_gauge(st["mode"])
    return {"status": "ok", "mode": st["mode"], "service": "fraud-api"}


@app.post("/score", response_model=ScoreOut)
def score(tx: Optional[TxIn] = None) -> ScoreOut:
    start = time.perf_counter()
    state = read_state()
    _mode_gauge(state["mode"])

    if state["slow_ms"]:
        time.sleep(state["slow_ms"] / 1000.0)

    txn = (
        Transaction(**tx.model_dump())
        if tx is not None
        else Transaction.sample()
    )

    if state["corrupt"]:
        s = score_corrupt(txn)
    else:
        s = score_normal(txn)

    label = "fraud" if s > 0.7 else "review" if s > 0.4 else "ok"
    REQUESTS.labels(outcome=label).inc()
    LATENCY.observe(time.perf_counter() - start)
    return ScoreOut(score=s, label=label, model_version="rules-1.0")


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ---- admin endpoints (triggered by chaos-injector, never by end users) ----

@app.post("/admin/crash")
def admin_crash() -> dict:
    """Self-terminate. Docker Compose restart policy brings us back."""
    import threading

    def _die() -> None:
        time.sleep(0.15)
        os._exit(1)

    threading.Thread(target=_die, daemon=True).start()
    return {"status": "terminating"}


@app.post("/admin/slow")
def admin_slow(ms: int = 800) -> dict:
    return write_state({"mode": "slow", "slow_ms": ms})


@app.post("/admin/corrupt")
def admin_corrupt() -> dict:
    return write_state({"mode": "corrupt", "corrupt": True})


@app.post("/admin/reset")
def admin_reset() -> dict:
    return reset_state()


# ------------------------- REPLAY (real-data mode) ------------------------
# Streams a bundled CSV of realistic credit-card transactions through the
# *same* scoring code path that /score uses. This exists so the dashboard
# can prove the pipeline handles real transaction shapes, not just the
# random ones Guardian generates when it polls /score.

import csv
from pathlib import Path

_REPLAY_CSV_CANDIDATES = [
    Path("/data/replay/transactions.csv"),
    Path(__file__).resolve().parents[3] / "data" / "replay" / "transactions.csv",
]


def _find_replay_csv() -> Path | None:
    for p in _REPLAY_CSV_CANDIDATES:
        if p.exists():
            return p
    return None


@app.get("/replay/info")
def replay_info() -> dict:
    p = _find_replay_csv()
    if not p:
        return {"available": False, "path": None, "rows": 0}
    with p.open() as f:
        rows = sum(1 for _ in f) - 1  # minus header
    return {"available": True, "path": str(p), "rows": max(rows, 0)}


@app.post("/replay")
def replay(limit: int = 200) -> dict:
    """Score the first `limit` rows of the bundled real-transactions CSV.
    Every row goes through score_normal() — the exact same code /score uses
    for a single request. Returns a summary the dashboard can display."""
    p = _find_replay_csv()
    if not p:
        return {"error": "replay CSV not found", "candidates": [str(x) for x in _REPLAY_CSV_CANDIDATES]}

    from .scoring import Transaction, score_normal

    scored = []
    total_amount = 0.0
    fraud = review = ok = 0
    with p.open() as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if i >= limit:
                break
            txn = Transaction(
                amount=float(row["amount"]),
                merchant_category=row["merchant_category"],
                hour=int(row["hour"]),
                country_risk=float(row["country_risk"]),
            )
            s = score_normal(txn)
            label = "fraud" if s > 0.7 else "review" if s > 0.4 else "ok"
            REQUESTS.labels(outcome=label).inc()
            scored.append({"amount": txn.amount, "category": txn.merchant_category,
                           "hour": txn.hour, "score": s, "label": label})
            total_amount += txn.amount
            if label == "fraud":
                fraud += 1
            elif label == "review":
                review += 1
            else:
                ok += 1

    n = len(scored)
    mean_score = sum(s["score"] for s in scored) / n if n else 0.0
    return {
        "scored": n,
        "mean_amount": round(total_amount / n, 2) if n else 0.0,
        "mean_score": round(mean_score, 4),
        "flagged_fraud": fraud,
        "flagged_review": review,
        "flagged_ok": ok,
        "first_20": scored[:20],
    }
