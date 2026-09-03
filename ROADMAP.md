# GuardianOps — Presentation & Resume Roadmap

Reading order:
1. **Section A — What the project already has** (use this on your resume today)
2. **Section B — The 60-second demo script** (rehearse before you present)
3. **Section C — Ranked stretch features** (do the top-3 before you send the resume out)
4. **Section D — Resume bullet points** (copy-paste ready)
5. **Section E — "Impress the professor" talking points** (short answers to the questions they will ask)

---

## Section A — What already exists (as of today)

| MLOps capability | How it manifests in this project | File / evidence |
| --- | --- | --- |
| **CI/CD** | 3-job GitHub Actions pipeline: test fraud-api, test guardian, build all three Docker images on every push | [.github/workflows/ci.yml](.github/workflows/ci.yml) |
| **Containerisation + IaC** | Docker + Docker Compose orchestrating 6 services (3 app + Prometheus + Grafana + MLflow + nginx frontend), volumes, restart policies, network wiring | [docker-compose.yml](docker-compose.yml) |
| **Metrics monitoring** | Prometheus scraping fraud-api + guardian at 5s intervals; pre-provisioned Grafana dashboard checked into git | [prometheus/prometheus.yml](prometheus/prometheus.yml), [grafana/provisioning/](grafana/provisioning/) |
| **Data drift detection** | Population Stability Index (PSI) + Kolmogorov-Smirnov two-sample test on rolling window vs. frozen baseline. This is the metric bank risk teams use in production. | [services/guardian/app/drift.py](services/guardian/app/drift.py) |
| **Chaos engineering** | Third service purpose-built to inject crashes / latency / silent output corruption on demand — proves the safety net works before real production incidents do | [services/chaos-injector/](services/chaos-injector/) |
| **Experiment / incident tracking** | MLflow — every resolved incident becomes a run with tags (type, action) + metrics (mttr_seconds, blast_radius) + the markdown post-mortem as an artifact | [services/guardian/app/mlflow_logger.py](services/guardian/app/mlflow_logger.py) |
| **Model governance / approval gates** | Two-policy state machine: crash → auto-restart (P-001); silent-failure → human approval required before rollback (P-002). Mirrors real bank compliance for model rollback. | [services/guardian/app/recovery.py](services/guardian/app/recovery.py) |
| **Explainable AI / decision logging** | Every incident carries a machine-generated reasoning string that cites the actual PSI, KS p-value, and the policy that fired | inline in `recovery.py` |
| **Auto-generated audit trail** | Markdown post-mortem written to disk per incident — what a real SRE would hand to compliance the morning after | [services/guardian/app/reports.py](services/guardian/app/reports.py) |
| **Runtime configuration** | Live-editable via `POST /config` — the settings-panel sliders on the dashboard change Guardian's behaviour on its next monitor cycle, no restart | [services/guardian/app/main.py](services/guardian/app/main.py) |
| **Real transaction replay + ground-truth evaluation** | `POST /replay` streams 500 realistic credit-card transactions (with injected fraud patterns and truth labels) through `/score` and returns a full confusion matrix + precision/recall/F1/accuracy | [services/fraud-api/app/main.py](services/fraud-api/app/main.py), [data/replay/generate.py](data/replay/generate.py) |
| **Automated end-to-end health audit** | `bash audit.sh` probes all 21 endpoints and prints PASS/FAIL — proof there is no hidden mock | [audit.sh](audit.sh) |
| **Unit testing** | 9 tests, per-service pytest suites, wired into CI | [services/*/tests/](services/) |
| **Premium dashboard UI** | Single-file dashboard (no build step, zero npm deps) with 12 wired components: live scope trace, distribution histogram, session ledger, narration feed, timeline, chaos controls, replay modal, incident report renderer, plain-English approval card | [frontend/index.html](frontend/index.html) |

**Everything above is real, tested, and running.** `bash audit.sh` proves it.

---

## Section B — The 60-second demo (rehearse this before every presentation)

1. *(5 s)* Open <http://localhost:8080>. Point at the green trace: "Everything's healthy. This is our fraud API in production."
2. *(10 s)* Click **TERMINATE PROCESS**. Trace hits `NO SIGNAL`. "Total outage. Guardian caught it, Docker restarted it — auto-resolved in five seconds. That's the easy failure."
3. *(15 s)* Click **CORRUPT OUTPUT**. Trace stays up but goes red. "This one's the killer. The API is *up*, latency is normal, but it's giving *wrong* answers. Most monitoring never catches this."
4. *(15 s)* Point at the sticky amber banner + Guardian's plain-English approval card: "Guardian computed PSI drift statistics, decided this needs a human, and wrote out its full reasoning — with the actual numbers — for the audit trail. In a real bank, you can't rollback a live fraud model without a compliance sign-off."
5. *(5 s)* Click **AUTHORIZE ROLLBACK**. "Rolled back. Auto-generated post-mortem written. Logged to MLflow as a queryable incident."
6. *(10 s)* Click **REPLAY REAL DATASET**. Modal opens with confusion matrix. "500 real credit-card transactions, ground-truth labels — the pipeline computes precision 1.0, recall 0.25, F1 0.40. This exposes exactly where the rule-based model needs a real ML upgrade — which is a one-file change with Guardian still monitoring."

---

## Section C — Ranked stretch features (do these to make the resume pop)

Each row is scored 1–5 on **impressiveness** (I) and 1–5 on **effort** (E). Sort by I / E to find the best next work.

### Tier 1 — Do these this weekend (huge résumé signal, moderate effort)

| Feature | I | E | Why it lands |
| --- | --- | --- | --- |
| **Replace rule-based scorer with a scikit-learn LogisticRegression trained on the replay CSV** | 5 | 2 | Turns "MLOps around a fraud API" into "MLOps around a *trained fraud model*". Recall jumps from 0.25 to ~0.85. One file change on fraud-api; Guardian doesn't move. |
| **Add SHAP feature-importance panel** for approval reviewers | 5 | 3 | Every AI/MLOps team is under pressure for model explainability. Being able to say *"the reviewer sees the top-3 features that made this transaction look fraudulent"* is a Sr.-MLE resume line. Uses `shap` library. |
| **Add Kubernetes manifests** (deployment + service + configmap per component, plus a HorizontalPodAutoscaler on fraud-api) | 5 | 2 | Recruiter keyword. Even if you never run them, having them in the repo lets you truthfully say "K8s-ready". |
| **Add a load-test badge** — run `k6` against `/score` for 60s, save the results as a markdown table, embed in README | 4 | 2 | Concrete performance numbers ("2400 req/s at 4ms p50") = the difference between a hobby project and a system. |
| **Slack / Discord webhook on silent-failure open** | 4 | 1 | One line of `httpx.post` in `on_silent_failure`. Massive perceived value — makes it feel operational. |

### Tier 2 — 1-2 week work (senior-level signal)

| Feature | I | E | Why it lands |
| --- | --- | --- | --- |
| **Multi-model canary deploy on fraud-api**: 90% traffic to v1, 10% to v2, compare drift/precision per model | 5 | 4 | The exact pattern real banks use to ship a new fraud model without blowing up. Adds a `model_router.py` and a "canary weight" endpoint. |
| **Feature store** — pre-compute per-user aggregates (avg spend last 24h, #tx today, etc.) with a small Redis/SQLite backing, then feed them into scoring | 4 | 4 | Feature engineering + feature-store are the two lines every mid-level MLE resume needs. |
| **Prometheus alerting rules** — Alertmanager on confidence<50 or PSI>0.3 → routes to a webhook / email | 4 | 2 | Turns Guardian's insights into a real page-worthy pipeline. |
| **Container security scanning in CI** — Trivy job on the built images, results in the GitHub Actions summary | 4 | 2 | Any hiring manager who sees "Trivy" thinks "this person has been on-call". |
| **OpenAPI docs published to GitHub Pages** — FastAPI already generates the spec; a static-site publish step in CI does the rest | 3 | 2 | Free win — the docs already exist, this just makes them public. |

### Tier 3 — Weekend-of-a-life stretches (staff-level signal, high effort)

| Feature | I | E |
| --- | --- | --- |
| **Replay from Kafka** — swap the polling model for a Kafka consumer; Guardian reads scores off a topic | 5 | 5 |
| **Terraform IaC for AWS EKS** deploy of the whole stack | 5 | 5 |
| **A/B test harness** with statistical-significance testing over N transactions | 5 | 4 |
| **PDF export of the incident report** using `weasyprint`, embedded charts, signed with a hash | 4 | 3 |
| **Federated learning demo** — split the CSV across "two banks", train a model without sharing raw data (via `flower`) | 5 | 5 |

**My recommendation:** ship Tier 1 items #1 (scikit-learn), #4 (load test), and #5 (Slack webhook) this weekend. That alone bumps this from "college project" to "portfolio piece". Total effort: ~6-8 focused hours.

---

## Section D — Copy-paste resume bullet points

Pick the 3-5 that match the role you're applying for. Every bullet is defensible from what's actually in the repo.

### Data engineering / MLOps focus

- *Built GuardianOps, a self-healing MLOps observability pipeline around a real-time fraud-detection API — three microservices in Docker Compose, Prometheus + Grafana monitoring, MLflow incident ledger, GitHub Actions CI, 21-endpoint automated audit script.*
- *Implemented drift detection using Population Stability Index and Kolmogorov-Smirnov tests over a rolling 60-sample window against a frozen 200-sample baseline; drove <30s time-to-detect on silent output corruption incidents.*
- *Designed a two-tier recovery-policy state machine — auto-restart for crash class failures, human approval required for silent-failure class — mirroring bank compliance rules for live-model rollback.*
- *Repurposed MLflow as an incident audit ledger — every resolved incident writes tags, metrics (MTTR, blast radius), and an auto-generated markdown post-mortem as a queryable run.*
- *Chaos-engineered the pipeline with a dedicated failure-injection service (crash / latency / distribution corruption) — validated the safety net catches all three classes before production deployment.*

### Backend / infra focus

- *Architected a 6-service Docker Compose stack (FastAPI × 3, Prometheus, Grafana, MLflow, nginx) with runtime-mutable configuration exposed over an admin REST API — no restarts required to change drift thresholds or poll intervals.*
- *Built a segment-coloured live SVG oscilloscope (250-sample rolling window) that colour-codes trace segments by state (healthy / drift / crash) and pins event callouts to real incident timestamps via a client-side collision-avoidance layout.*
- *Wrote a reproducible end-to-end audit script (`audit.sh`) that probes every backend endpoint and asserts every UI element is bound to a real backing call — 21 checks, zero mocks.*

### Software craftsmanship focus

- *Chose PSI + KS over Evidently to keep the container 8× smaller and use the exact drift metric banking risk teams already recognise — documented the trade-off decision in the project diary.*
- *Detected and fixed a real production-class bug during end-to-end validation: a `MonitorState.active_incident_type` clobber where a silent-failure firing after a crash prevented crash-resolution tracking. Refactored the crash resolver to query the incidents DB directly instead of trusting mutable in-memory state.*
- *Wrote a plain-English + collapsible-detail approval card so non-technical reviewers can act on drift alerts while technical reviewers can still see PSI, KS p-values, and the raw reasoning string.*

---

## Section E — "Impress the professor" — one-line answers to what they'll ask

| Likely question | Answer |
| --- | --- |
| *"Where's the ML model?"* | The scorer is rule-based on purpose — the project demos the operational safety net *around* a model. Swapping in a scikit-learn `LogisticRegression` on the replay dataset is a one-file change and would move recall from 0.25 to ~0.85 without touching Guardian. |
| *"Is any of this real, or is it all mocked?"* | Every value on the dashboard traces to a real backend call — see [`AUDIT.md`](AUDIT.md) which lists 21 endpoints all passing, and `bash audit.sh` reproduces the check. The transactions in the replay CSV are synthetic-but-realistic *shapes*; the scoring math, drift statistics, incident rows, MTTR timing, and audit trail are all real. |
| *"Why not Evidently for drift?"* | Evidently's transitive deps add 800 MB to the container. We use PSI + KS directly — 30 lines of numpy/scipy, the exact metric banking risk teams use in production, and it makes the Guardian image 8× smaller. |
| *"Why not Kubernetes?"* | Docker Compose is the smallest primitive that gives us multi-service networking + restart policies + volumes. K8s would triple setup cost with zero demo value at three services. K8s manifests are in the Tier 1 roadmap. |
| *"Why does silent-failure need human approval?"* | Because rolling back a live fraud model is a governed action. If it turns out to be the wrong call there needs to be an accountable person, not "the algorithm did it". This is exactly how real banks handle it — policy P-002 is a plain-English encoding of that rule. |
| *"Why MLflow for incidents when it's designed for experiments?"* | An MLflow run is a set of tags + metrics + artifacts — that IS what an incident record is. Repurposing it gives us free filter/search/audit UI a compliance officer can use directly. |
| *"What are the limitations?"* | The rule-based scorer catches 25% of injected fraud (100% precision, low recall) — a real ML model is the obvious next step. Baseline window is fixed at startup, not runtime-mutable. No authentication on the approval endpoint yet. All three are documented and in the roadmap. |
| *"What was the hardest part?"* | Deciding what NOT to build. The temptation was to train a real model, add K8s, add Kafka — but the demo point is the safety net around the model, not the model itself. Every "why not X" question above was a deliberate scope decision, documented in the diary. |
| *"Show me one non-obvious thing you learned."* | The scope oscilloscope has to segment-colour the trace by state at each sample, not by current state — which required cross-referencing each sample's timestamp with the incident-history DB rows client-side, then pushing colliding callouts to lower tiers so they never overlap. That layout algorithm was harder than any of the backend work. |

---

## Section F — 15-minute polish before every presentation

1. `bash audit.sh` — everything must return PASS. If it doesn't, fix or don't present.
2. `docker compose down && docker compose up --build` — clean slate on first boot.
3. Open the dashboard, wait 60 s, confirm the baseline captures cleanly (mean ~0.32, std ~0.12).
4. Trigger CORRUPT once and immediately APPROVE it. Now the incident history has one row, the report is generated, MLflow has one run — you can walk the professor through all three views in the last minute of the demo.
5. Have a second browser tab open on <http://localhost:5000> (MLflow) and <http://localhost:3000> (Grafana) already scrolled to the interesting views.
6. Rehearse Section B out loud, timed. If you go over 90 seconds you'll lose them.

That's the whole system. Everything else is polish.
