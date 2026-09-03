# GuardianOps

A self-healing safety net for a real-time fraud-detection API. GuardianOps watches the API 24/7, catches both *total outages* and *silent wrong-answer failures*, auto-fixes what it safely can, and holds a human approval gate for the rest — with a full audit trail per incident.

> **New here?** Read [`DIARY.md`](DIARY.md) first. It walks through what the project is, why every design choice was made, and what to say if a professor asks about it.

---

## What GuardianOps actually does — in one paragraph

A bank runs a fraud-detection API that scores every card transaction in real time. That API can fail in two ways: **(1)** it crashes outright, and **(2)** it stays up but starts giving quietly wrong answers because a model got corrupted, a deploy went bad, or an upstream data pipeline shifted. The second kind is more dangerous — the service *looks* healthy while approving fraud or declining legitimate cards. **GuardianOps is the second-opinion layer.** It polls the fraud API, detects both classes of failure, restarts the API automatically when it crashes, and — for the silent kind — creates a *pending approval* that a human must sign off before rollback. Every incident gets a full audit trail: SQLite row + MLflow run + auto-generated markdown post-mortem.

---

## Architecture

Three services, all in Docker Compose:

```
                     ┌────────────────┐
    [Chaos buttons]──▶│ chaos-injector │
                     └───────┬────────┘
                             │ (crash / slow / corrupt)
                             ▼
        transactions──▶┌──────────────┐
                        │  fraud-api    │◀───── polled every 2 s
                        │  (FastAPI)    │
                        └───────┬──────┘
                             ↕ metrics + outputs
                             ▼
                        ┌──────────────┐        ┌──────────┐
                        │   guardian    │───────▶│  MLflow  │
                        │  (FastAPI +   │        │ (audit   │
                        │  bg tasks)    │        │  ledger) │
                        └───────┬──────┘        └──────────┘
                             │
                             ├─── Prometheus + Grafana
                             └─── Frontend dashboard
```

| Service | Port | Purpose |
| --- | --- | --- |
| `fraud-api` | 8001 | The "production" system under protection. Scores transactions. |
| `guardian` | 8002 | The brain — polls, computes drift, opens/resolves incidents. |
| `chaos-injector` | 8003 | Fires scripted failures (crash / slow / corrupt) into fraud-api. |
| `prometheus` | 9090 | Metrics scraping. |
| `grafana` | 3000 | Time-series dashboards. |
| `mlflow` | 5000 | Incident ledger (repurposed experiment tracker). |
| `frontend` | 8080 | The instrument-panel dashboard. |

---

## Quick start

**With Docker (recommended):**

```bash
docker compose up --build
```

Then open <http://localhost:8080>.

**Local Python (no Docker):**

```bash
# from the project root, one uvicorn per service:
STATE_FILE=./shared/state.json \
  python -m uvicorn app.main:app --app-dir services/fraud-api --port 8001 &

FRAUD_API_URL=http://127.0.0.1:8001 \
DATA_DIR=./data/guardian REPORTS_DIR=./data/reports \
MLFLOW_TRACKING_URI=file://$PWD/data/mlflow \
  python -m uvicorn app.main:app --app-dir services/guardian --port 8002 &

FRAUD_API_URL=http://127.0.0.1:8001 \
  python -m uvicorn app.main:app --app-dir services/chaos-injector --port 8003 &

python -m http.server 8080 --directory frontend &
```

Give Guardian about **60 seconds on first boot** to warm fraud-api and capture its 200-sample baseline. Until then the confidence gauge sits at 100 with no drift metric.

---

## Is any of this real, or is it fake data?

**Every value shown on the dashboard is computed live from real code.** Nothing is hard-coded. Nothing is randomised at the display layer. Here is exactly where each value comes from:

| Value on the dashboard | Comes from | Real math or mock? |
| --- | --- | --- |
| Fraud score (0-1 per transaction) | `services/fraud-api/app/scoring.py` — weighted formula on `amount`, `hour`, `merchant_category`, `country_risk` + bounded noise | **Real**. Rule-based, not ML, but honest math. |
| Confidence Score (0-100) | Guardian's `drift.confidence_from_psi()` | **Real**. Derived from PSI in real time. |
| Drift PSI + KS p-value | Guardian's `drift.compute_drift()` — `scipy.stats.ks_2samp` and a hand-rolled Population Stability Index | **Real**. Same statistics banks use in production. |
| Baseline distribution (200 samples) | Guardian polls fraud-api at boot until it has 200 clean scores | **Real**. Actual samples from actual `/score` calls. |
| Uptime, latency p50, throughput | Guardian's `live_metrics()` — rolling 60-second aggregation of its own polls | **Real**. Every value is derived from the actual poll history. |
| Incident rows | SQLite table `incidents` in `data/guardian/guardian.db` | **Real**. On-disk rows created by Guardian's monitor loop. |
| MTTR (seconds) | `(resolved_at - detected_at).total_seconds()` on each row | **Real**. Wall-clock duration. |
| Blast Radius (transactions saved) | Counter in Guardian's monitor state incremented on every score during an active incident | **Real**. Actual observed count. |
| Reasoning strings | Generated at incident-detection time with the actual PSI + KS p-value | **Real**. Composed from live drift statistics. |
| Auto-generated report | Markdown file written to `data/reports/incident-NNNN-<ts>.md` | **Real**. Actual file on disk. |
| MLflow runs | Actual runs in the `guardianops-incidents` experiment | **Real**. Queryable in the MLflow UI at :5000. |
| Session Ledger tiles | `GET /session-stats` — aggregation over the incidents table | **Real**. Straight from SQL. |
| Score Distribution histogram | Client-side binning of `/baseline` + `/score-history` samples | **Real**. Actual samples. |
| Guardian Narration lines | Client-side diff of successive `/status` + `/incidents` polls | **Real**. Emitted from actual state transitions. |
| Timeline dots | From `/incidents` — one dot per real incident | **Real**. |
| Estimated Exposure ($) | Active incident's `blast_radius` × $84.72 average tx value | **Derived** (real blast × a documented average). |

**What is synthetic:** the *transactions themselves*. Guardian polls fraud-api's `/score` endpoint every 2 seconds; each poll causes `Transaction.sample()` to generate a random synthetic transaction (amount, hour, category, country risk) which then gets scored. This is by design — the project demos the **operational safety net around a fraud model**, not the fraud model itself. In a real deployment the `/score` endpoint would be hit by live production traffic; the safety net around it (which is what GuardianOps is) would be identical.

**To feed real transactions:** send `POST /score` with a JSON body `{"amount": ..., "merchant_category": ..., "hour": ..., "country_risk": ...}` to `http://localhost:8001/score`. Every one gets scored, counted, and drift-checked exactly like a synthetic one.

---

## The demo script

Rehearse this three times before presenting. Total: about 3.5 minutes.

1. **Show a healthy dashboard.** Confidence 100, all badges green, empty incident history.
2. **Click TERMINATE PROCESS.** fraud-api crashes. The scope trace hits a `NO SIGNAL / SERVICE DOWN` gap. Within ~5 seconds Docker restarts fraud-api and Guardian resolves the crash automatically — auto-restart callout appears. **This is the safe class of failure.**
3. **Click CORRUPT OUTPUT.** fraud-api stays up (green badge, no latency spike), but the scope trace turns red as scores drift out of baseline. Confidence gauge visibly decays. A `DRIFT SCORE` callout appears with the real PSI value. Within ~30 seconds a `Pending Authorization` card appears with the full reasoning string. **This is the dangerous class of failure.**
4. **Read the reasoning string out loud.** It cites the actual PSI, actual KS p-value, and the policy that requires human sign-off. This is the sentence that sells the project.
5. **Watch the Blast Radius counter tick up** on the Estimated Exposure card — real transactions that would have got wrong scores.
6. **Click AUTHORIZE ROLLBACK.** Guardian rolls fraud-api back to clean mode, resolves the incident, and generates a markdown post-mortem. `AUTHORIZED` callout appears on the scope.
7. **Scroll to the Auto-Generated Incident Report.** Read the first two lines. Everything on the page was written by Guardian; a human wrote none of it.
8. **Open Grafana (localhost:3000)** to show the same PSI and confidence trend as Prometheus time-series.
9. **Open MLflow (localhost:5000)** to show each incident as a queryable run with tags, metrics, and the report attached as an artifact.

Talking points during the demo live in [`DIARY.md`](DIARY.md) section "Quick-reference: what to say when a professor asks…".

---

## Repo layout

```
mlops-project/
├── README.md                # this file
├── DIARY.md                 # plain-language walkthrough of every design choice
├── AUDIT.md                 # per-component pass/fail audit
├── docker-compose.yml
├── .github/workflows/ci.yml # 3-job CI: test-fraud-api, test-guardian, build images
├── services/
│   ├── fraud-api/           # the scored system
│   ├── guardian/            # the brain (drift, incidents, reports)
│   └── chaos-injector/      # failure injection surface
├── frontend/
│   └── index.html           # single-file dashboard (CSS + JS inline)
├── prometheus/prometheus.yml
├── grafana/provisioning/    # datasource + dashboard, checked in
└── data/                    # SQLite, reports, MLflow store (gitignored)
```

Guardian and fraud-api each have their own `tests/` directory with per-service pytest suites (both packages happen to be named `app`, so a single pytest run over both would collide — the CI runs them as two separate jobs).

---

## What's missing on purpose

- **No trained ML model.** The scorer is rule-based. See `DIARY.md` "Why not a real ML model?" — the project demos the safety net *around* a model, not the model itself. Swapping in a scikit-learn model is a one-file change.
- **No Kubernetes.** Docker Compose is the smallest primitive that gives us multi-service networking + restart policies + volumes. K8s would triple the setup cost with zero demo value at three services.
- **No streaming.** A single REST call per "transaction" is enough for the demo. Adding Kafka would obscure the operational story.
- **No cloud deploy.** Everything runs locally. Nothing about the design would change if you moved it to a cloud host.
- **No authentication.** The "ACTING AS" dropdown on the approval card is display-only (documented in the UI). A real deploy would gate `/approve/{id}` on an identity check.
- **No dynamic Guardian config.** The settings-panel sliders are display-only (documented in-panel). Guardian's tunables live in `services/guardian/app/config.py`; changing behaviour means editing that file and restarting the service. The honest UI is better than a slider that silently does nothing.

---

## Verification

Every endpoint has an end-to-end audit in [`AUDIT.md`](AUDIT.md). Every value on the dashboard traces back to a specific line of code — the audit lists which endpoint feeds which UI element and what the observed values were during the last audit run.

Unit tests: 9 passing (3 fraud-api + 4 guardian drift + 2 guardian governance). Run them with:

```bash
cd services/fraud-api  && python -m pytest -q
cd services/guardian   && python -m pytest -q
```
