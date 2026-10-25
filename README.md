# GuardianOps

**A self-healing MLOps safety net for a real-time fraud-detection API.**

GuardianOps watches a fraud API around the clock, catches both total outages *and* silent wrong-answer failures, auto-fixes what it safely can, and holds a human-approval gate for the rest — with a full audit trail per incident and a real ML evaluation loop against a labeled dataset.

> First-time reader? Skim this README top to bottom (5 min), then open [`DIARY.md`](DIARY.md) for the plain-language design walk-through, and [`ROADMAP.md`](ROADMAP.md) for the presentation script + resume bullets.

---

## Table of contents

- [Why this project exists](#why-this-project-exists)
- [Architecture](#architecture)
- [Feature highlights](#feature-highlights)
- [Quick start](#quick-start)
- [The dashboard, panel by panel](#the-dashboard-panel-by-panel)
- [Endpoints (every UI element is backed by one of these)](#endpoints)
- [Is any of this real, or is it mocked?](#is-any-of-this-real-or-is-it-mocked)
- [Running tests + audit](#running-tests--audit)
- [Repo layout](#repo-layout)
- [What is *not* included (on purpose)](#what-is-not-included-on-purpose)
- [Further reading](#further-reading)

---

## Why this project exists

A bank runs a fraud-detection API that scores every card transaction in real time. That API can fail in two ways:

1. **It crashes.** Obvious. Someone gets paged. It restarts.
2. **It stays up but starts giving quietly wrong answers** because a model got corrupted, a deploy went bad, or an upstream data pipeline shifted. The service *looks* healthy while approving fraud or declining legitimate cards. Nobody notices until money is lost.

The second class is more dangerous. Most monitoring only catches the first.

**GuardianOps is the second-opinion layer.** It polls the fraud API, computes rolling drift statistics (PSI + Kolmogorov-Smirnov) against a frozen baseline, and:

- **crash** → auto-restarts the service (policy P-001), logs the incident with a real MTTR
- **silent-failure** → opens an incident and *waits for a human to authorize the rollback* (policy P-002), because you cannot silently mutate a live fraud model without a compliance sign-off

Every incident gets:
- a SQLite row with the reasoning and evidence
- an auto-generated markdown post-mortem on disk
- an MLflow run with tags (type, action) + metrics (MTTR, blast radius) + the report attached as an artifact

---

## Architecture

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
                             ├─── Prometheus ── Grafana
                             └─── Frontend dashboard
```

| Service | Port | Purpose |
| --- | --- | --- |
| `fraud-api` | 8001 | The "production" system under protection. Scores transactions via a rule-based function. Also serves `/replay` for evaluating on a labeled dataset. |
| `guardian` | 8002 | The brain — polls, computes drift, opens/resolves incidents, exposes live-mutable config. |
| `chaos-injector` | 8003 | Fires scripted failures (crash / slow / corrupt) into fraud-api on demand. |
| `prometheus` | 9090 | Metrics scraping. |
| `grafana` | 3000 | Time-series dashboards, pre-provisioned and checked into git. |
| `mlflow` | 5000 | Incident ledger (repurposed experiment tracker). |
| `frontend` | 8080 | The single-file instrument-panel dashboard. |

---

## Feature highlights

### The brain (Guardian)

- **Real drift detection.** Population Stability Index + Kolmogorov-Smirnov 2-sample test over a rolling 60-sample window against a 200-sample baseline captured at startup. Same metrics banking risk teams use in production.
- **Confidence Score (0–100)** exposed as a Prometheus gauge and dashboard gauge, falls with the Kolmogorov-Smirnov p-value of the live window against the baseline (100 when the distributions match, 0 at p <= 1e-4), so a healthy system sits high and corruption drives it to zero.
- **Two-tier recovery policy state machine.** Crash → auto-restart. Silent failure → human approval required. Encoded in code, mirrored on the dashboard.
- **Explainable reasoning strings** on every incident: PSI, KS p-value, threshold, and the policy that fired — composed in plain English at detection time.
- **Auto-generated markdown post-mortems** written to `data/reports/incident-NNNN-<ts>.md` on resolution. Print-ready.
- **MLflow incident ledger** — every incident is a queryable run with tags + metrics + artifact.
- **Runtime-mutable config** via `POST /config` (drift threshold, poll interval, drift-check cadence) — no restart needed. Settings panel on the dashboard hydrates from and posts to the live values.
- **Live-metrics endpoint** (`/live-metrics`) — 60-second rolling window aggregation of uptime %, latency p50, throughput.
- **Session-stats endpoint** (`/session-stats`) — aggregated ledger derived from the incidents table (used by the dashboard's Session Ledger tiles).

### Chaos injector

- **Three failure modes.** `crash` (SIGTERM-style process exit), `slow` (adjustable millisecond delay per `/score`), `corrupt` (silently returns scores from a shifted Beta distribution — no crash, no latency spike).
- **Separate service** so the "attacker surface" is architecturally distinct from the "victim" API.

### Real dataset + ground-truth evaluation

- **500 realistic credit-card transactions** in `data/replay/transactions.csv`, generated deterministically with:
  - log-normal amounts per merchant category
  - hour-of-day weighting (peaks 12–14 and 18–20, troughs 2–5)
  - mostly-domestic country risk with occasional foreign spikes
  - **~4 % deliberately-injected fraud patterns** (large-amount-odd-hour, ATM-burst, online-3AM, card-testing) with `is_fraud=1` labels
- **`POST /replay`** on fraud-api streams the CSV through the same `score()` code path a live request uses and returns:
  - Confusion matrix (TP / FP / TN / FN)
  - Precision · Recall · F1 · Accuracy
  - First 20 scored rows + all misclassified rows

### Dashboard (single HTML file, zero build step)

- **Instrument-panel aesthetic** — Space Grotesk + IBM Plex Mono, mossy signal-green accent, corner brackets, calibration ruler, dot-grid + radial-glow body background.
- **Live oscilloscope trace** with smooth Catmull-Rom curves, vertical **score-based colour gradient** (green low → amber mid → red high), gradient area fill, glow filter, and a pulsing "current sample" dot.
- **Interactive hover** on the scope — snaps to the nearest sample, shows crosshair + tooltip with time / score / verdict.
- **Event callouts** pinned to real incident times, merged into one per incident, 3-tier collision avoidance.
- **Session Ledger** — six tiles (Total / Crashes / Silent Failures / Avg MTTR / Autonomous Rate / Total Blast Radius) driven by `/session-stats`.
- **Score Distribution histogram** — baseline (frozen) vs live (last window), computed client-side, with μ / σ / sample count + verdict badge.
- **Guardian Narration console** — dark premium terminal with STREAM · LIVE indicator, per-line severity accents, animated line entry, live event counter.
- **Sticky pending-approval banner** appears at the top the moment the queue is non-empty; smooth-scrolls to the approval section on click.
- **Plain-English approval card** — headline + subhead + 3-tile facts grid + 4 collapsible detail sections (What is drift? / See the numbers / Why approval? / Full raw reasoning). Threshold + impact numbers read from live backend state.
- **Auto-generated incident report** with letterhead, dt/dd document layout, state-dependent rotated stamp, print-ready A4 stylesheet, COPY AS MARKDOWN, PRINT.
- **Real-dataset REPLAY modal** — six summary tiles, colour-coded 3×3 confusion matrix, four metric tiles (Precision / Recall / F1 / Accuracy each with a plain-English hint), segmented tabs (All scored / Missed fraud), full row table with verdict colour coding.
- **Runtime settings panel** — sliders that actually POST to `/config` and update Guardian's live behaviour on the next monitor cycle.
- **Connection badges** for Guardian / Fraud-API / Chaos-Injector that turn green / red based on live health probes.

### Ops discipline

- **GitHub Actions CI** — 3 parallel jobs (test-fraud-api, test-guardian, build-images) on every push.
- **38 unit and API tests** (16 fraud-api, 22 guardian), a 35-check endpoint audit, and an end-to-end silent-failure scenario, all run in CI.
- **Reproducible audit script** — `bash audit.sh` probes all 21 endpoints and prints PASS/FAIL with observed values. Zero mocks.

---

## Quick start

### Option A — One-click batch file (Windows, fastest, no Docker)

From the repo root, double-click (or run) `start-guardianops.bat`. It will:

1. Install each service's Python dependencies (`pip install -r requirements.txt`, safe to re-run)
2. Reset the shared state file to normal mode
3. Launch `fraud-api`, `guardian`, `chaos-injector`, and the frontend static server, each in its own terminal window
4. Wait ~15 seconds, then auto-open the dashboard at `http://127.0.0.1:8080` in your default browser

```bat
start-guardianops.bat
```

Give it another 30–60 seconds after the page loads for Guardian to capture its baseline (see "First-time boot expectations" below). When you're done, run `stop-guardianops.bat` to close all four service windows — it only targets windows titled `GuardianOps: ...`, so it won't touch anything else you have open.

This path skips Prometheus / Grafana / MLflow (Docker-only) — see Option B if you need those.

### Option B — Docker (recommended if you want the full observability stack)

```bash
docker compose up --build
```

Wait ~30 seconds for images to build and ~60 seconds after that for Guardian to warm the fraud-api baseline. Then open:

| URL | What |
| --- | --- |
| <http://localhost:8080> | The GuardianOps dashboard |
| <http://localhost:8002/docs> | Guardian's Swagger UI (all endpoints) |
| <http://localhost:8001/docs> | Fraud-API's Swagger UI |
| <http://localhost:3000> | Grafana (anonymous viewer enabled) |
| <http://localhost:5000> | MLflow incident ledger |
| <http://localhost:9090> | Prometheus |

### Option C — Local Python, manual (no Docker, no batch file)

Requires Python 3.11. From the repo root:

```bash
# 1. Install per-service deps
pip install -r services/fraud-api/requirements.txt
pip install -r services/guardian/requirements.txt
pip install -r services/chaos-injector/requirements.txt

# 2. Start each service in its own terminal (or background)
STATE_FILE=./shared/state.json \
  python -m uvicorn app.main:app --app-dir services/fraud-api --port 8001 --host 127.0.0.1

FRAUD_API_URL=http://127.0.0.1:8001 \
DATA_DIR=./data/guardian REPORTS_DIR=./data/reports \
MLFLOW_TRACKING_URI=file://$PWD/data/mlflow \
  python -m uvicorn app.main:app --app-dir services/guardian --port 8002 --host 127.0.0.1

FRAUD_API_URL=http://127.0.0.1:8001 \
  python -m uvicorn app.main:app --app-dir services/chaos-injector --port 8003 --host 127.0.0.1

python -m http.server 8080 --directory frontend --bind 127.0.0.1
```

**Note:** local mode does *not* start Prometheus / Grafana / MLflow (those are Docker-only) — the dashboard's `MLFLOW` and `GRAFANA` footer links will 404, but the core Guardian pipeline works end-to-end. Also, in local mode there is no `restart: on-failure` policy, so after you click TERMINATE PROCESS you need to manually re-launch the fraud-api uvicorn (the crash-recovery timer will resolve once you do).

### First-time boot expectations

1. All three service `/health` endpoints return 200 within ~5s.
2. Guardian captures its baseline (200 samples of `POST /score`) within ~60s.
3. Once the baseline is captured, the dashboard's confidence gauge stabilises at 100 and the trace turns green.
4. The runtime config strip shows Guardian's live values: `THRESHOLD 0.20 · WINDOW 60 SAMPLES · POLL 2s · DRIFT CHECK 5s`.

---

## The dashboard, panel by panel

Every panel on the dashboard is bound to a real backend call. If something is greyed out, it's because Guardian doesn't have data yet.

| Panel | Backing call(s) | What it does |
| --- | --- | --- |
| **Header clock + ACTIVE pulse** | client + `/status` result | Turns OFFLINE with a red dot if `/status` fails |
| **Config strip** | `/status.config` | Shows Guardian's live runtime config; the CONFIGURE button opens the settings panel |
| **Connection badges** (GUARDIAN / FRAUD-API / CHAOS) | `/health` probes | Green when reachable, red otherwise |
| **Session Ledger** (6 tiles) | `/session-stats` | Aggregation over the incidents table |
| **Fraud API status card** | `/status.fraud_api_up` + `/status.active_incident_type` | HEALTHY / DRIFT / DOWN |
| **Uptime / Latency / Confidence readouts** | `/live-metrics`, `/status.confidence` | 60s rolling |
| **Oscilloscope trace** | `/score-history` + LAST_INCIDENTS | Score-based gradient stroke, segment fill, hover crosshair + tooltip |
| **Scope event callouts** | Cross-reference of samples + incidents | Pinned to real timestamps, three-tier collision avoidance |
| **Estimated Exposure** | Active incident's blast × $84.72 avg | Ticks up live during a silent-failure incident |
| **Chaos control buttons** | `POST http://:8003/{crash\|slow\|corrupt}` | Injects real failures into fraud-api |
| **FORCE DRIFT CHECK NOW** | `POST /check-now` | Runs an immediate drift check; button label updates with the verdict |
| **REPLAY LABELLED DATASET** | `POST /replay?limit=500` | Streams the labeled CSV through `/score`, opens the modal with the confusion matrix |
| **Score Distribution histogram** | `/baseline` + `/score-history` | Client-side binning of both distributions over 20 bins |
| **Recovery Policy cards** | Static documentation of the policies Guardian enforces | Non-interactive by design |
| **Pending Authorization card** | `/pending-approvals` | Plain-English headline, facts grid, 4 collapsible info sections, AUTHORIZE ROLLBACK button |
| **Sticky pending banner** | Same call as above | Appears when queue is non-empty; smooth-scrolls to card on click |
| **Latest Incident block** | `/incidents[0]` | Type / window / status / blast radius / reasoning |
| **Incident Timeline strip** | Last 6 rows of `/incidents` | Colour-coded dots at real timestamps |
| **Guardian Narration console** | Client diff of `/status` + `/incidents` polls | Live scroll of state-change events, colour-coded by severity |
| **Auto-Generated Incident Report** | `/report/latest` + `/incidents[0]` | Letterhead, dl fields, signature block, rotated stamp; COPY + PRINT |
| **Incident History table** | `/incidents?limit=30` | Full ledger |
| **Footer links** | External | GUARDIAN CONNECTED (state), MLFLOW / GRAFANA / API DOCS (links) |
| **RESET CHAOS STATE** | `POST http://:8003/reset` | Clears all chaos flags |

---

## Endpoints

### fraud-api (port 8001)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Liveness + current mode |
| POST | `/score` | Score a transaction (JSON body optional; random sample if omitted) |
| POST | `/replay?limit=N` | Stream up to N rows from the labeled CSV through `score()`; return confusion matrix + precision/recall/F1 |
| GET | `/replay/info` | CSV metadata (path, row count) |
| POST | `/admin/crash` | Self-terminate (used only by chaos-injector) |
| POST | `/admin/slow?ms=N` | Set slow mode |
| POST | `/admin/corrupt` | Set corrupt mode |
| POST | `/admin/reset` | Clear all state to normal |
| GET | `/metrics` | Prometheus scrape target |

### guardian (port 8002)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Liveness |
| GET | `/status` | Snapshot of state + config + last_drift + active_incident |
| GET | `/live-metrics` | Rolling 60s uptime %, latency p50, throughput |
| GET | `/baseline` | Frozen baseline samples + mean + std |
| GET | `/score-history?limit=N` | Recent samples with timestamps + current verdict |
| GET | `/session-stats` | Aggregated ledger derived from incidents table |
| GET | `/incidents?limit=N` | Full incident history |
| GET | `/pending-approvals` | Filtered view — only pending_approval rows |
| GET | `/report/latest` | Markdown of the latest resolved incident's post-mortem |
| GET | `/reports` | List of all report file names |
| GET | `/reports/{name}` | One specific report |
| GET | `/config` | Current runtime config (mutable + fixed) |
| POST | `/config` | Patch mutable config (psi_alert, poll_interval_s, drift_check_interval_s, consecutive_alerts_for_incident) |
| POST | `/check-now` | Force an immediate drift check |
| POST | `/approve/{id}` | Approve a pending silent-failure rollback |
| GET | `/metrics` | Prometheus scrape target |

### chaos-injector (port 8003)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Liveness |
| POST | `/crash` | Proxy to fraud-api `/admin/crash` |
| POST | `/slow?ms=N` | Proxy to fraud-api `/admin/slow` |
| POST | `/corrupt` | Proxy to fraud-api `/admin/corrupt` |
| POST | `/reset` | Proxy to fraud-api `/admin/reset` |

---

## Is any of this real, or is it mocked?

**Every value on the dashboard is computed from real code. Nothing is hard-coded on the display layer.** Full breakdown:

| Value | Real math or mock? | Source file |
| --- | --- | --- |
| Fraud score | **Real** rule-based formula (amount + hour + category + country risk + bounded noise) | [`services/fraud-api/app/scoring.py`](services/fraud-api/app/scoring.py) |
| Confidence score | **Real** KS-p-value-driven gauge | [`services/guardian/app/drift.py`](services/guardian/app/drift.py) |
| PSI + KS drift | **Real** `scipy.stats.ks_2samp` + hand-rolled PSI | same |
| Baseline | **Real** — 200 actual `/score` calls captured at startup | [`services/guardian/app/monitor.py`](services/guardian/app/monitor.py) |
| Uptime / latency / throughput | **Real** — rolling 60s aggregation of poll history | same |
| Incidents | **Real** — SQLite rows in `data/guardian/guardian.db` | [`services/guardian/app/store.py`](services/guardian/app/store.py) |
| MTTR | **Real** — `resolved_at − detected_at` in wall-clock seconds | [`services/guardian/app/recovery.py`](services/guardian/app/recovery.py) |
| Blast radius | **Real** — counter of transactions Guardian observed during the incident | same |
| Reasoning strings | **Real** — composed at detection time with the actual PSI + KS values | same |
| Markdown reports | **Real** — files written to `data/reports/incident-NNNN-<ts>.md` | [`services/guardian/app/reports.py`](services/guardian/app/reports.py) |
| MLflow runs | **Real** — queryable in the MLflow UI at :5000 | [`services/guardian/app/mlflow_logger.py`](services/guardian/app/mlflow_logger.py) |
| Session Ledger tiles | **Real** — `SELECT COUNT / AVG / SUM` over the incidents table | [`services/guardian/app/main.py`](services/guardian/app/main.py) |
| Score distribution histogram | **Real** — client-side binning of `/baseline` + `/score-history` | [`frontend/index.html`](frontend/index.html) |
| Confusion matrix + precision/recall/F1 | **Real** — computed against the ground-truth `is_fraud` column | [`services/fraud-api/app/main.py`](services/fraud-api/app/main.py) |
| Guardian Narration lines | **Real** — client diff of successive `/status` polls | [`frontend/index.html`](frontend/index.html) |
| Estimated Exposure $ | **Derived** — live blast × $84.72 avg tx (documented) | same |

**What is synthetic:** the transaction *stream* Guardian polls. Every 2 s Guardian calls fraud-api's `/score` with a randomly-shaped transaction. In production this would be replaced by live traffic — the safety net around it (which is what GuardianOps *is*) stays identical. To exercise the pipeline on real transaction *shapes*, click **REPLAY LABELLED DATASET** — that streams 500 rows of seeded synthetic, ground-truth-labelled transactions from the CSV through the same `/score` code path.

---

## Running tests + audit

**Unit and API tests** — 38 passing (16 fraud-api, 22 guardian), per-service pytest suites:

```bash
cd services/fraud-api  && python -m pytest -q
cd services/guardian   && python -m pytest -q
```

**End-to-end audit** — probes the live endpoints (read, write, negative and failure-injection cases), prints PASS/FAIL with the observed value:

```bash
bash audit.sh
```

Runs 35 checks (plus one skipped when no report exists yet): service health, every Guardian read, `/config` round trip and clamping, `/approve` and report-name rejection, `/replay` confusion matrix, scoring and validation, chaos modes verified through the fraud-api health response, and the frontend. Then run the full silent-failure path with `python scripts/e2e_scenario.py` (or both with `bash scripts/ci_smoke.sh`). Full per-element pass/fail is in [`AUDIT.md`](AUDIT.md).

**CI** — `.github/workflows/ci.yml` runs both pytest suites, then boots the services and runs the audit and the end-to-end scenario (`scripts/ci_smoke.sh`), then builds the three Docker images. Triggers: push to main or master, pull requests, manual run.

---

## Repo layout

```
mlops-project/
├── README.md              ← this file
├── DIARY.md               ← plain-language walk-through of every design choice
├── ROADMAP.md             ← presentation script + resume bullets + ranked stretch features
├── AUDIT.md               ← per-UI-element pass/fail with backing call for every widget
├── audit.sh               ← reproducible endpoint probe (35 checks)
├── start-guardianops.bat  ← one-click Windows launcher (installs deps, starts all 4 services)
├── stop-guardianops.bat   ← stops only the GuardianOps service windows
├── docker-compose.yml     ← 7-service stack (3 apps + Prom + Grafana + MLflow + nginx)
├── .github/workflows/
│   └── ci.yml             ← 3-job pipeline: test-fraud-api, test-guardian, build
├── report/                ← academic report deliverable
│   ├── GuardianOps_Report.docx / .pdf ← project report in the university format
│   ├── README.md          ← placeholders to fill and how to rebuild
│   └── figures/           ← diagrams and 2x screenshots used by the report
├── screenshots/
│   ├── 01_dashboard_healthy.png
│   ├── 02_crash_detected.png
│   ├── 03_drift_pending_approval.png (and 04 to 06)
│   └── 05_demo_walkthrough.md ← exact click sequence + captions for every screenshot
├── demo/
│   └── demo_video_link.txt ← placeholder for a recorded walkthrough link
├── services/
│   ├── fraud-api/         ← the "production" system + /replay evaluator
│   │   ├── app/           ← main.py, scoring.py, state.py
│   │   ├── tests/         ← 16 pytest cases
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   ├── guardian/          ← the brain
│   │   ├── app/           ← main.py, monitor.py, drift.py, recovery.py, store.py,
│   │   │                    reports.py, mlflow_logger.py, config.py
│   │   ├── tests/         ← 22 pytest cases (drift rule, API, governance)
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   └── chaos-injector/    ← failure-injection surface (crash / slow / corrupt / reset)
│       ├── app/main.py
│       ├── Dockerfile
│       └── requirements.txt
├── frontend/
│   └── index.html         ← single-file dashboard (CSS + JS inline)
├── prometheus/
│   └── prometheus.yml     ← scrapes fraud-api + guardian every 5s
├── grafana/provisioning/  ← auto-loads datasource + dashboard on first boot
│   ├── datasources/prometheus.yml
│   └── dashboards/{dashboards.yml, guardianops.json}
├── data/
│   ├── replay/            ← labeled real-transaction dataset + generator
│   │   ├── generate.py    ← deterministic (seed 20260904), 4% ground-truth fraud
│   │   └── transactions.csv
│   ├── guardian/          ← [gitignored] SQLite DB, per-run state
│   ├── reports/           ← [gitignored] auto-generated markdown post-mortems
│   ├── mlflow/            ← [gitignored] MLflow store
│   └── grafana/           ← [gitignored] Grafana state
└── shared/
    └── state.json         ← fraud-api's shared mode flag (reset to normal on startup)
```

---

## What is *not* included (on purpose)

Every one of these was a deliberate scope decision. If a professor or interviewer asks *"why not X?"*, the answer is here:

- **No trained ML model.** The scorer is rule-based on purpose — the project demos the operational safety net *around* a model, not the model itself. Swapping in a `sklearn.LogisticRegression` trained on the replay dataset is a one-file change and would move recall from 0.25 to ~0.85 without touching Guardian. See ROADMAP.md Tier 1.
- **No Kubernetes.** Docker Compose is the smallest primitive that gives us multi-service networking + restart policies + volumes. K8s would triple the setup cost with zero demo value at three services.
- **No streaming (Kafka etc.).** A single REST call per transaction is enough for the demo. Streaming would obscure the operational story.
- **No cloud deploy.** Runs entirely locally. Nothing in the design would change on a cloud host.
- **No authentication.** The "ACTING AS" dropdown on the approval card is display-only and documented as `(no auth)`. A real deploy would gate `/approve/{id}` on an identity check.
- **No dynamic baseline resize.** `WINDOW_SIZE` is baked into a `deque(maxlen=…)` at container startup. The settings-panel slider is disabled with a `(fixed)` label — the honest UI beats one that silently does nothing.

---

## Further reading

- [`DIARY.md`](DIARY.md) — plain-language stage-by-stage walk-through, with a "quick-reference: what to say when a professor asks…" table
- [`ROADMAP.md`](ROADMAP.md) — presentation script + copy-paste resume bullets + Tier 1/2/3 stretch features ranked by impressiveness ÷ effort
- [`AUDIT.md`](AUDIT.md) — every dashboard element's backing endpoint, with the last audit's observed values
- [`report/GuardianOps_Report.md`](report/GuardianOps_Report.md) — the full academic report (title page → references), with every §7 metric captured from a real run; see [`report/README.md`](report/README.md) for what's left to fill in before submission
- [`screenshots/05_demo_walkthrough.md`](screenshots/05_demo_walkthrough.md) — exact click sequence + captions for every report screenshot

---

**Built by Ashwarya.** MLOps course project · 2026.
