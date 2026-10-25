# GuardianOps — A Self-Healing MLOps Pipeline for Real-Time Fraud Detection

---

## 1. Title Page

**Project Title:** GuardianOps — Self-Healing MLOps Pipeline for Real-Time Fraud Detection

**Student Name:** [PLACEHOLDER: Your full name as it should appear on the report]

**Course:** [PLACEHOLDER: Course code and title, e.g. "Advanced MLOps — CSE XXXX"]

**Institution:** [PLACEHOLDER: University / college name]

**Instructor:** [PLACEHOLDER: Professor's name]

**Date:** 25 October 2026

**Repository:** [PLACEHOLDER: public GitHub URL, e.g. https://github.com/pradhanashwarya2122/GuardianOps]

---

## 2. Abstract

*(Word count target: 200–250 words)*

Fraud-detection systems in production can fail in two fundamentally different ways. The first is a total outage — the service stops responding, which is immediately visible and typically self-resolves with a container restart. The second, far more dangerous failure mode is silent: the service remains live and continues responding with low latency, but its outputs have quietly drifted away from their expected distribution, for example after a bad deployment, a corrupted model artifact, or an upstream data-pipeline defect. Conventional uptime monitoring cannot detect this second class of failure because the service never stops answering.

GuardianOps is a three-service MLOps safety-net pipeline built to address this gap. A monitoring service ("Guardian") continuously polls a fraud-scoring API, maintains a frozen baseline distribution of healthy outputs, and compares a rolling window of live scores against that baseline using the Population Stability Index (PSI) and the Kolmogorov–Smirnov two-sample test — the same statistical tools used in production credit-risk monitoring. Detected failures are routed through a two-tier governance policy: process crashes are resolved autonomously via container restart, while silent output drift is escalated to a mandatory human-approval gate before any corrective rollback is applied. Every incident produces a structured audit trail: a database record, an auto-generated markdown post-mortem, and an MLflow-logged run with reasoning, timing, and impact metrics. The system was validated through a labeled 500-transaction dataset with injected fraud patterns, an automated 21-endpoint integration audit, and a 9-case unit test suite, all passing at submission time.

---

## 3. Problem Statement

Machine-learned and rule-based scoring services deployed in regulated, high-stakes domains such as banking fraud detection face an observability gap that standard infrastructure monitoring does not close.

Standard monitoring (uptime checks, HTTP status codes, latency percentiles) answers the question *"is the service running?"* It cannot answer the question *"is the service still giving correct answers?"* A fraud-scoring API that has been silently corrupted — by a bad model deploy, a schema change in an upstream feature pipeline, or data poisoning — will continue to return HTTP 200 with normal latency while every decision it makes is wrong. Because nothing in the infrastructure layer looks abnormal, this class of failure can persist undetected for an extended period, during which an organization is simultaneously declining legitimate transactions and approving fraudulent ones.

A second, related gap is governance: even once a problem is detected, not every corrective action should be automated. A process crash is safe to resolve without human involvement — a service is either answering or it is not. But silently rolling back a live fraud model is a consequential, auditable decision; applying it without a human in the loop removes the accountability that compliance frameworks in financial services require.

GuardianOps addresses both gaps directly: (1) it adds a statistical drift-detection layer on top of the scoring API that is independent of — and complementary to — standard uptime monitoring, and (2) it encodes a governance policy that distinguishes autonomous recovery actions from actions that require explicit human authorization, with every decision recorded for audit.

---

## 4. Objectives

- **Detect silent output-distribution drift** in a live scoring service using statistically grounded methods (PSI and the Kolmogorov–Smirnov test) rather than simple threshold or anomaly heuristics.
- **Distinguish two failure classes** — process-level crashes versus silent output drift — and route each through a distinct, policy-defined recovery path.
- **Automate recovery where it is safe** (crash → container restart) **and gate recovery where it is not** (drift → mandatory human approval before rollback), encoding this as an explicit two-policy governance model (P-001 / P-002).
- **Produce a complete, queryable audit trail** for every incident: structured database record, auto-generated markdown post-mortem, and an MLflow run with tags, metrics, and attached artifacts.
- **Validate the pipeline against a labeled dataset** with known ground-truth fraud/legitimate transactions, producing a real confusion matrix and precision/recall/F1/accuracy — not synthetic or assumed metrics.
- **Demonstrate the system end-to-end** via a reproducible chaos-injection harness (crash, latency, silent corruption) and an automated integration audit covering every exposed API endpoint.

---

## 5. Methodology

### 5.1 Architectural approach

GuardianOps is built as three independently deployable microservices plus a monitoring/observability layer, orchestrated with Docker Compose:

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
                        │  background   │        │  ledger) │
                        │  monitor)     │        └──────────┘
                        └───────┬──────┘
                             │
                             ├─── Prometheus ── Grafana
                             └─── Frontend dashboard (single-file)
```

| Component | Responsibility | Port |
| --- | --- | --- |
| `fraud-api` | The monitored system under protection; scores transactions via a deterministic rule-based function; exposes `/replay` for labeled-dataset evaluation | 8001 |
| `guardian` | The monitoring brain — polling, drift computation, incident lifecycle, governance enforcement, runtime-mutable configuration | 8002 |
| `chaos-injector` | A dedicated failure-injection surface (crash / latency / silent corruption), architecturally isolated from the monitored system | 8003 |
| `prometheus` | Time-series metrics scraping (5 s interval) | 9090 |
| `grafana` | Pre-provisioned dashboards over the Prometheus data source | 3000 |
| `mlflow` | Repurposed from its usual experiment-tracking role into an incident audit ledger | 5000 |
| `frontend` | A single static HTML/CSS/JS dashboard polling the Guardian API every 1.5 s | 8080 |

### 5.2 Drift-detection method

Guardian captures a **frozen baseline** of 200 scores from the fraud API at startup, representing the known-healthy output distribution. It then maintains a **rolling window** of the most recent 60 scores. Every 5 seconds it compares the rolling window against the frozen baseline using:

- **Population Stability Index (PSI).** A quantile-binned divergence measure widely used in banking/credit-risk model monitoring. The implementation follows the standard industry convention: PSI < 0.10 is considered stable, 0.10–0.20 is minor drift, and > 0.20 is treated as significant drift warranting intervention.
- **Kolmogorov–Smirnov two-sample test** (`scipy.stats.ks_2samp`), providing a p-value for the null hypothesis that both samples are drawn from the same distribution.

A drift verdict of "significant" must occur on two consecutive checks (10 seconds of sustained drift) before an incident is raised, to avoid single-sample false positives.

### 5.3 Governance policy

| Trigger | Policy | Action |
| --- | --- | --- |
| Two consecutive failed health checks | **P-001** | Automatic container restart (handled by Docker's `restart: on-failure` policy); Guardian observes and times the recovery, logs the incident |
| PSI > 0.20 sustained across two drift checks | **P-002** | Guardian opens a `pending_approval` incident and takes **no corrective action**; a human must call `POST /approve/{id}` before the system is reset to its clean state |

### 5.4 Tools and libraries

| Category | Technology |
| --- | --- |
| Language / runtime | Python 3.11 |
| Web framework | FastAPI + Uvicorn (all three services) |
| Statistical computing | NumPy, SciPy (`ks_2samp`) |
| Persistence | SQLite (incident ledger) |
| Experiment / audit tracking | MLflow (repurposed as an incident audit ledger) |
| Metrics + visualization | Prometheus + Grafana |
| Containerization | Docker, Docker Compose |
| Frontend | Vanilla HTML/CSS/JavaScript, hand-built SVG (no charting library, no build step) |
| Testing | pytest (9 unit tests across both services) |
| CI | GitHub Actions (3 parallel jobs: test fraud-api, test guardian, build images) |

### 5.5 Evaluation dataset

A 500-row synthetic-but-realistic credit-card transaction dataset was generated (`data/replay/generate.py`, fixed random seed for reproducibility) with:

- Log-normal transaction amounts, parameterized per merchant category (grocery, online, ATM, electronics, travel)
- Hour-of-day weighting reflecting realistic spending patterns
- Country-risk scores, predominantly low-risk/domestic with occasional high-risk/foreign values
- **4% (20 of 500) deliberately injected fraud patterns**, each carrying a ground-truth `is_fraud=1` label: large purchases at 2–5 AM from high-risk countries, rapid ATM withdrawal bursts abroad, high-value online purchases at 3–5 AM, and card-testing bursts (many small-value transactions from a high-risk origin)

This dataset is used exclusively for offline evaluation via `POST /replay`, separate from the live synthetic polling traffic Guardian generates during normal operation.

---

## 6. Implementation

This section walks through GuardianOps module by module. File paths are relative to the repository root.

### 6.1 `fraud-api` — the monitored system

**Files:** `services/fraud-api/app/main.py`, `scoring.py`, `state.py`

- `scoring.py` implements `score_normal()`, a deterministic rule-based function over amount, hour, merchant category, and country risk, producing a value in [0, 1]. A second function, `score_corrupt()`, draws from a different (Beta) distribution and is swapped in by the chaos-injector to simulate silent model corruption without crashing the process.
- `main.py` exposes `POST /score`, `GET /health`, `GET /metrics` (Prometheus format), and the chaos-control surface (`/admin/crash`, `/admin/slow`, `/admin/corrupt`, `/admin/reset`), plus `POST /replay` for dataset evaluation (§6.6).
- `state.py` persists the current operating mode (`normal` / `slow` / `corrupt`) to a shared JSON file so mode changes survive process boundaries.

**Suggested screenshot:** Swagger UI at `http://localhost:8001/docs` showing the `/score` and `/replay` endpoints.

### 6.2 `guardian` — the monitoring brain

**Files:** `services/guardian/app/monitor.py`, `drift.py`, `recovery.py`, `store.py`, `reports.py`, `mlflow_logger.py`, `config.py`, `main.py`

- `monitor.py` runs an asyncio background loop: polls `/health` every 2 s, polls `/score` and appends to a rolling window, and triggers a drift check every 5 s. This is the component responsible for Objective 1.
- `drift.py` implements `population_stability_index()` and wraps `scipy.stats.ks_2samp` to produce the PSI/KS verdicts described in §5.2.
- `recovery.py` implements the two-policy governance logic from §5.3, and generates the plain-English reasoning string attached to every incident (citing the actual PSI value, KS p-value, and policy ID).
- `store.py` is a thin SQLite wrapper maintaining the `incidents` table (type, status, timestamps, reasoning, evidence JSON, blast radius, MTTR).
- `reports.py` renders a markdown post-mortem per resolved incident.
- `mlflow_logger.py` logs each resolved incident as an MLflow run (tags: type/action; metrics: `mttr_seconds`, `blast_radius`; artifact: the markdown report).
- `config.py` holds Guardian's tunables (`PSI_ALERT`, `POLL_INTERVAL_S`, `DRIFT_CHECK_INTERVAL_S`, etc.); `main.py` exposes `GET/POST /config` so a subset of these can be changed at runtime without a service restart.

**Suggested screenshot:** the "Guardian Narration" console on the dashboard, showing a live sequence of state-transition log lines.

### 6.3 `chaos-injector` — the failure-injection surface

**File:** `services/chaos-injector/app/main.py`

A minimal proxy service exposing `POST /crash`, `/slow`, `/corrupt`, `/reset`, each of which calls the corresponding `fraud-api` admin endpoint. It is deliberately a separate service so the "attack surface" used for testing is architecturally isolated from the monitored system itself — a design choice made for defense-in-depth and to mirror how chaos-engineering tooling (e.g., Chaos Monkey) is kept out-of-band from production services in real deployments.

### 6.4 Governance + incident lifecycle

The incident state machine has three states: `in_progress` (crash, recovery underway) or `pending_approval` (drift, awaiting human sign-off), transitioning to `resolved`. The dashboard's "Pending Authorization" panel surfaces open `pending_approval` incidents with:

- A plain-English summary of what was detected
- A facts grid (drift severity vs. threshold, transactions affected so far, detection timestamp)
- Collapsible technical detail (raw PSI/KS values, baseline vs. live window sizes, full reasoning string)
- An "Authorize Rollback" action that calls `POST /approve/{id}`

**Suggested screenshot:** the pending-approval card with a silent-failure incident open (PSI ≈ 0.40, as observed during validation — see §7).

### 6.5 Observability stack

Prometheus scrapes `/metrics` from both `fraud-api` and `guardian` every 5 seconds (`prometheus/prometheus.yml`). Grafana auto-loads a pre-provisioned dashboard (`grafana/provisioning/`) on first boot, requiring no manual panel configuration. MLflow (`services/guardian/app/mlflow_logger.py`) is used unconventionally here — not for ML experiment tracking, but as a structured, queryable incident ledger, taking advantage of MLflow's existing tags/metrics/artifacts data model.

### 6.6 Dataset evaluation (`/replay`)

**File:** `services/fraud-api/app/main.py`, function `replay()`

Streams up to 500 rows of the labeled dataset (§5.5) through the exact same `score_normal()` code path used by live `/score` requests, then compares each prediction (`fraud` / `review` → predicted positive; `ok` → predicted negative) against the ground-truth `is_fraud` column to produce a confusion matrix and precision/recall/F1/accuracy. This closes the loop between "is the pipeline operationally healthy" (Guardian's job) and "is the underlying scorer actually any good" (the `/replay` evaluation's job) — two distinct questions that are often conflated in MLOps demonstrations.

**Suggested screenshot:** the "Replay Real Dataset" modal showing the confusion matrix and metric tiles.

### 6.7 Frontend dashboard

**File:** `frontend/index.html` (single file, no build step, no npm dependencies)

Polls six Guardian endpoints every 1.5 seconds (`/status`, `/live-metrics`, `/score-history`, `/incidents`, `/pending-approvals`, `/session-stats`) and renders: a live oscilloscope-style score trace (hand-built SVG, Catmull-Rom smoothed, gradient-colored by score magnitude), a baseline-vs-live distribution histogram, a session ledger of aggregate incident statistics, the Guardian narration console, and the auto-generated incident report viewer with print support.

**Suggested screenshot:** the full dashboard in its steady/healthy state (see `screenshots/01_dashboard_healthy.jpg`).

---

## 7. Results

All figures below were captured from a live run of the system on 25 October 2026, immediately prior to this report being written. Raw command output is preserved in the repository for verification (`audit.sh`, pytest output).

### 7.1 Unit test results

```
services/fraud-api:  3 passed in 0.03s
services/guardian:   6 passed in 1.43s
Total: 9 / 9 tests passing
```

### 7.2 Integration audit results

`audit.sh` probes all 21 exposed endpoints across the three services (service health, Guardian reads, Guardian writes, chaos-injector writes, frontend availability):

```
21 passed, 0 failed
```

### 7.3 Crash-recovery scenario (Policy P-001)

A crash was injected via `POST /chaos/crash`. Guardian's health-check loop detected two consecutive failures and opened a `crash`-type incident; the process was restarted and the incident auto-resolved.

| Metric | Observed value |
| --- | --- |
| Incident type | `crash` |
| Detection method | Consecutive HTTP health-check failures |
| Action taken | `auto_restart` (no human approval) |
| Time to recovery (MTTR) | **16.57 seconds** |
| Blast radius | 1 transaction |

### 7.4 Silent-failure scenario (Policy P-002)

Silent corruption was injected via `POST /chaos/corrupt`, switching the scorer to a shifted output distribution while the process continued answering normally (confirmed: no crash, no latency spike).

| Metric | Observed value |
| --- | --- |
| Incident type | `silent_failure` |
| Detection method | PSI + Kolmogorov–Smirnov drift check on rolling window vs. frozen baseline |
| PSI at detection | **0.402** (threshold: 0.20) |
| Action taken | `pending_approval` → `rollback_approved` after human authorization |
| Time to recovery (MTTR) | **81.06 seconds** (includes the time the incident sat awaiting approval) |
| Blast radius | 40 transactions |

The baseline captured at Guardian startup for this run: **200 samples, mean = 0.327, standard deviation = 0.107.**

### 7.5 Session-level aggregate (this run)

```json
{
  "total_incidents": 2,
  "crashes": 1,
  "silent_failures": 1,
  "resolved": 2,
  "pending_approvals": 0,
  "avg_mttr_seconds": 48.81,
  "total_blast_radius": 41,
  "autonomous_rate": 50.0
}
```

*(Autonomous rate = percentage of incidents resolved without human intervention; expected to trend lower as a proportion of total incidents in any session that deliberately exercises both policy paths, as this validation run did.)*

### 7.6 Dataset evaluation (`/replay`, 500 transactions, 20 ground-truth fraud)

| Metric | Value |
| --- | --- |
| Rows scored | 500 |
| Mean transaction amount | $244.41 |
| True Positives | 5 |
| False Positives | 0 |
| True Negatives | 480 |
| False Negatives | 15 |
| **Precision** | **1.00** |
| **Recall** | **0.25** |
| **F1 score** | **0.40** |
| **Accuracy** | **0.97** |

**Interpretation.** The rule-based scorer used in this project is intentionally simple (§6.1) — the project's objective is the operational safety net around a scoring service, not the scoring model's predictive quality. The result (perfect precision, low recall) is expected for a hand-tuned rule-based threshold function and is reported honestly rather than adjusted: zero false alarms, but the majority of the more subtle injected fraud patterns (e.g., card-testing bursts of very small amounts) are missed. This gap is the expected and motivating case for replacing the scorer with a trained classifier (see §9, Future Work) — a change that would not require any modification to Guardian, since Guardian monitors output statistics regardless of how the score is produced.

### 7.7 Screenshots captured for this report

| File | Captures |
| --- | --- |
| `screenshots/01_dashboard_healthy.jpg` | Full dashboard at steady state: confidence 100/100, session ledger at zero incidents, green oscilloscope trace |
| `screenshots/02_crash_detected.jpg` | Fraud API marked DOWN immediately after chaos-injected crash; session ledger showing 1 crash, 100% autonomous rate |
| `screenshots/03_incident_report_narration.jpg` | Auto-generated incident post-mortem document (letterhead, classification, timeline, MTTR, reasoning, policy, AUTO-RESOLVED stamp) alongside the live Guardian narration console |

[PLACEHOLDER: two additional screenshots recommended — (a) the pending-approval card during the silent-failure window with the amber banner visible, and (b) the Replay Real Dataset modal showing the confusion matrix. Both scenarios are reproducible in under two minutes by running `start-guardianops.bat`, clicking **CORRUPT OUTPUT**, waiting ~15s, and clicking **REPLAY REAL DATASET** — see `screenshots/05_demo_walkthrough.md` for the exact click sequence.]

---

## 8. Conclusion

Measured against the objectives stated in §4:

| Objective | Status | Evidence |
| --- | --- | --- |
| Detect silent drift via statistical methods | **Achieved** | PSI = 0.402 correctly flagged during the injected-corruption scenario (§7.4), using PSI + KS rather than a naive threshold |
| Distinguish and route two failure classes | **Achieved** | Crash → auto-restart (16.57s MTTR); drift → human-gated approval (§7.3, §7.4) |
| Automate safe recovery, gate unsafe recovery | **Achieved** | Two-policy governance model (P-001/P-002) implemented and exercised live |
| Complete audit trail per incident | **Achieved** | SQLite record + markdown report + MLflow run generated for both incidents in the validation run |
| Validate against a labeled dataset | **Achieved** | 500-row dataset, real confusion matrix (precision 1.00 / recall 0.25 / F1 0.40 / accuracy 0.97) |
| End-to-end demonstrable via chaos injection | **Achieved** | All three chaos modes (crash/slow/corrupt) exercised; 21/21 integration audit passing, 9/9 unit tests passing |

GuardianOps demonstrates that the operational discipline a production MLOps team applies around a model — monitoring, drift detection, governed recovery, and auditability — can be built, tested, and reasoned about independently of the model's own predictive quality. The project deliberately kept the underlying scorer simple so that the engineering effort and the report's results center on the safety-net layer itself, which is the stated scope of the course.

---

## 9. Future Work

These are realistic, scoped extensions of the existing codebase, not speculative features:

- **Replace the rule-based scorer with a trained classifier** (e.g., `scikit-learn LogisticRegression`) trained on the existing labeled dataset. This is a change confined to `fraud-api/app/scoring.py`; Guardian's drift-detection and governance logic require no modification, since they operate purely on output score distributions. Expected to materially improve recall (§7.6) at the cost of some precision.
- **Container-orchestrated deployment (Kubernetes manifests).** The current Docker Compose setup is appropriate for a 3-service local/academic deployment; a `Deployment`/`Service`/`HorizontalPodAutoscaler` manifest set would be the natural next step toward a cloud-deployable version.
- **Authentication on the approval endpoint.** `POST /approve/{id}` currently has no identity verification; the "Acting As" selector on the dashboard is display-only. A production version would require this to be backed by real authentication.
- **Alerting integration.** A single outbound webhook call (e.g., to Slack) on `pending_approval` incident creation would close the loop between detection and a human actually seeing the alert outside the dashboard.
- **Runtime-mutable baseline window.** The baseline sample count is currently fixed at container startup (it sizes an in-memory ring buffer); making this truly runtime-adjustable would require a small refactor of `guardian/app/monitor.py`'s state initialization.

---

## 10. References

[PLACEHOLDER: add formal citations in your course's required format — e.g. IEEE, APA. Suggested sources actually used in this project's design:]

1. [PLACEHOLDER: Citation for Population Stability Index methodology, e.g. a credit-risk modeling reference or industry whitepaper]
2. [PLACEHOLDER: Citation for the Kolmogorov–Smirnov two-sample test — standard statistics textbook or `scipy.stats.ks_2samp` documentation]
3. FastAPI documentation — https://fastapi.tiangolo.com/
4. MLflow documentation — https://mlflow.org/docs/latest/index.html
5. Prometheus documentation — https://prometheus.io/docs/
6. Docker Compose documentation — https://docs.docker.com/compose/
7. [PLACEHOLDER: Any course textbook or lecture material you are expected to cite]

---

*Report generated from the live GuardianOps repository on 25 October 2026. All metrics in §7 are reproducible by running `bash audit.sh` and the chaos-injection sequence described in `screenshots/05_demo_walkthrough.md` against a freshly started stack (`start-guardianops.bat` or `docker compose up --build`).*
