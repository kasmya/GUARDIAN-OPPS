"""HTTP-level tests for fraud-api: scoring, failure modes and the /replay evaluator."""
import csv
import random
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main as fraud_main
from app.main import app
from app.state import reset_state

client = TestClient(app)

HIGH_RISK = dict(amount=9000.0, merchant_category="electronics", hour=3, country_risk=0.9)
LOW_RISK = dict(amount=20.0, merchant_category="grocery", hour=12, country_risk=0.05)


@pytest.fixture(autouse=True)
def clean_state():
    reset_state()
    yield
    reset_state()


def test_health_reports_mode():
    assert client.get("/health").json() == {"status": "ok", "mode": "normal", "service": "fraud-api"}


def test_score_with_explicit_transaction_is_deterministic_in_band():
    hi = client.post("/score", json=HIGH_RISK).json()
    lo = client.post("/score", json=LOW_RISK).json()
    assert hi["label"] == "fraud" and hi["score"] > 0.7
    assert lo["label"] == "ok" and lo["score"] < 0.4


def test_score_without_body_samples_a_transaction():
    r = client.post("/score")
    assert r.status_code == 200 and 0.0 <= r.json()["score"] <= 1.0


@pytest.mark.parametrize("bad", [
    dict(HIGH_RISK, hour=24),
    dict(HIGH_RISK, amount=-1),
    dict(HIGH_RISK, country_risk=2),
])
def test_score_rejects_invalid_input(bad):
    assert client.post("/score", json=bad).status_code == 422


def test_corrupt_mode_shifts_scores_up_and_reset_restores_them():
    random.seed(1)
    normal = [client.post("/score", json=LOW_RISK).json()["score"] for _ in range(60)]
    assert client.post("/admin/corrupt").json()["mode"] == "corrupt"
    assert client.get("/health").json()["mode"] == "corrupt"
    corrupt = [client.post("/score", json=LOW_RISK).json()["score"] for _ in range(60)]
    assert sum(corrupt) / 60 > sum(normal) / 60 + 0.4          # clearly shifted
    assert client.post("/admin/reset").json()["mode"] == "normal"
    again = [client.post("/score", json=LOW_RISK).json()["score"] for _ in range(60)]
    assert sum(again) / 60 < 0.2


def test_slow_mode_adds_latency():
    import time
    client.post("/admin/slow?ms=200")
    t = time.perf_counter()
    client.post("/score", json=LOW_RISK)
    assert time.perf_counter() - t >= 0.2


def test_metrics_endpoint_exposes_prometheus_text():
    client.post("/score", json=LOW_RISK)
    body = client.get("/metrics").text
    assert "fraud_api_requests_total" in body and "fraud_api_latency_seconds" in body


def test_replay_confusion_matrix_and_metrics(tmp_path, monkeypatch):
    """Four labelled rows, one of each outcome, so the maths is checkable by hand."""
    rows = [
        dict(HIGH_RISK, tx_id="TP", merchant_name="x", is_fraud=1),   # flagged, is fraud   -> TP
        dict(HIGH_RISK, tx_id="FP", merchant_name="x", is_fraud=0),   # flagged, legit      -> FP
        dict(LOW_RISK,  tx_id="TN", merchant_name="x", is_fraud=0),   # not flagged, legit  -> TN
        dict(LOW_RISK,  tx_id="FN", merchant_name="x", is_fraud=1),   # not flagged, fraud  -> FN
    ]
    p = tmp_path / "t.csv"
    with p.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    monkeypatch.setattr(fraud_main, "_REPLAY_CSV_CANDIDATES", [p])

    r = client.post("/replay?limit=100").json()
    assert r["scored"] == 4
    assert r["confusion_matrix"] == {
        "true_positive": 1, "false_positive": 1, "true_negative": 1, "false_negative": 1}
    assert r["metrics"] == {"precision": 0.5, "recall": 0.5, "f1": 0.5, "accuracy": 0.5}
    assert {m["tx_id"] for m in r["misclassified"]} == {"FP", "FN"}
    assert client.get("/replay/info").json() == {"available": True, "path": str(p), "rows": 4}


def test_replay_reports_missing_dataset(monkeypatch):
    monkeypatch.setattr(fraud_main, "_REPLAY_CSV_CANDIDATES", [Path("/definitely/not/here.csv")])
    assert "error" in client.post("/replay").json()
    assert client.get("/replay/info").json()["available"] is False


def test_bundled_dataset_has_expected_shape():
    """The committed CSV: 500 rows, 20 labelled fraud (4 %)."""
    csv_path = Path(__file__).resolve().parents[3] / "data" / "replay" / "transactions.csv"
    with csv_path.open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 500
    assert sum(r["is_fraud"] == "1" for r in rows) == 20


def test_replay_info_counts_the_bundled_rows():
    """Regression: CR CR LF line endings once made this endpoint report 1001 rows."""
    info = client.get("/replay/info").json()
    assert info["available"] is True
    assert info["rows"] == 500
