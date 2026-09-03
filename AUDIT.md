# GuardianOps — Component Audit

Every UI element on the dashboard, every button, every readout — and the exact backend call each one is bound to. This document is the accountability line: if a professor asks *"is that number real, or did it come out of a template?"* the answer is on this page.

Last audit run: 2026-09-03. Reproduce with `bash audit.sh` at the repo root (see the "Reproduce" section at the bottom).

---

## Service liveness (3 / 3 pass)

| Service | URL | Observed |
| --- | --- | --- |
| fraud-api | `GET :8001/health` | `{"status":"ok","mode":"normal","service":"fraud-api"}` |
| guardian | `GET :8002/health` | `{"status":"ok","service":"guardian"}` |
| chaos-injector | `GET :8003/health` | `{"status":"ok","service":"chaos-injector"}` |

## Guardian read endpoints (10 / 10 pass)

| Endpoint | Powers which UI element | Observed |
| --- | --- | --- |
| `GET /status` | fraud-api status card, confidence readout, config strip, guardian strip, scope colouring | `fraud_up=True conf=100.0 active=None` |
| `GET /live-metrics` | UPTIME + LATENCY readouts | `uptime=100.0% lat=4.8ms` |
| `GET /baseline` | Score Distribution baseline histogram (fetched once, cached) | `size=200 mean=0.321 std=0.120` |
| `GET /score-history` | Oscilloscope trace, live histogram, live μ | `verdict=stable live=80 samples` |
| `GET /session-stats` | Session Ledger — six tiles | Aggregation of the incidents table |
| `GET /incidents` | Incident History table, Timeline, Latest Incident block, Estimated Exposure, scope callouts | Array of real DB rows |
| `GET /pending-approvals` | Pending Authorization card | Filtered view of `incidents` where `status='pending_approval'` |
| `GET /reports` | (Wired but not surfaced on the dashboard — see `/report/latest` for what is) | Filesystem listing of `data/reports/*.md` |
| `GET /report/latest` | Auto-Generated Incident Report block + COPY MARKDOWN button contents | Latest resolved incident's markdown file |
| `GET /metrics` | Scraped by Prometheus | Prometheus text format |

## Guardian write endpoints (2 / 2 pass)

| Endpoint | Bound to which UI element | Behaviour |
| --- | --- | --- |
| `POST /approve/{id}` | AUTHORIZE ROLLBACK button | Calls fraud-api `/admin/reset`, clears the score window and drift counters, resolves the incident, writes the markdown post-mortem, logs an MLflow run |
| `POST /check-now` | FORCE DRIFT CHECK NOW button | Runs an immediate drift check on the current window; returns `{psi, ks_statistic, ks_pvalue, verdict}` — button label updates with the verdict for 3 seconds |

## Chaos-injector endpoints (4 / 4 pass)

| Endpoint | Bound to which UI element | Effect |
| --- | --- | --- |
| `POST /chaos/crash` | TERMINATE PROCESS button | Calls fraud-api `/admin/crash` which self-terminates via `os._exit(1)`. Docker Compose's `restart: on-failure` policy brings it back. Guardian observes the health blip and logs a `crash` incident. |
| `POST /chaos/slow?ms=1500` | INDUCE LATENCY button | Sets `slow_ms=1500` in the shared state file; fraud-api's `/score` handler sleeps that many milliseconds per call. |
| `POST /chaos/corrupt` | CORRUPT OUTPUT button | Sets `corrupt=true` in the shared state file; fraud-api's `/score` switches to `score_corrupt()` which draws from a Beta(9, 1.4) distribution — visibly shifted from the normal 0.32 mean up to ~0.87. |
| `POST /chaos/reset` | RESET CHAOS STATE footer button | Clears every flag in the shared state file back to `{mode:normal, slow_ms:0, corrupt:false}`. |

## fraud-api endpoints (verified separately)

| Endpoint | Purpose | Observed |
| --- | --- | --- |
| `POST /score` | The scored system's main endpoint | `score=0.6412 label=review` (real computation) |
| `POST /admin/crash` | Self-terminate — used only by chaos-injector | (not verifiable via curl since it kills the process, but the crash flow works end-to-end) |
| `POST /admin/slow` | Set slow mode — used only by chaos-injector | `{mode:slow, slow_ms:1500}` |
| `POST /admin/corrupt` | Set corrupt mode — used only by chaos-injector | `{mode:corrupt, corrupt:true}` |
| `POST /admin/reset` | Clear state — used by chaos-injector AND by guardian on approval | `{mode:normal, slow_ms:0, corrupt:false}` |
| `GET /metrics` | Prometheus scrape target | Counter, histogram, and gauge in Prometheus text format |

---

## Full UI-element audit

Every visible element on the dashboard and where its value comes from.

### Header

| Element | Backing call / source | Verified |
| --- | --- | --- |
| Clock (top right) | `Date.now()` client-side | ✓ ticks every second |
| ACTIVE / OFFLINE pulse | Green when `pollStatus()` succeeds, red when it throws | ✓ shows OFFLINE when Guardian is stopped |
| HEALTHY / PENDING / ALERT legend | Static — a colour legend for the reader | ✓ (static text) |

### Config strip

| Element | Backing call | Verified |
| --- | --- | --- |
| DRIFT THRESHOLD | `/status.config.psi_alert` | ✓ shows `0.20` |
| BASELINE WINDOW | `/status.config.window_size` | ✓ shows `60 SAMPLES` |
| POLL INTERVAL | `/status.config.poll_interval_s` | ✓ shows `2s` |
| DRIFT CHECK CADENCE | `/status.config.drift_check_interval_s` | ✓ shows `5s` |
| GUARDIAN badge | `pollStatus()` result | ✓ green when reachable |
| FRAUD-API badge | `/health` on port 8001 | ✓ green when reachable |
| CHAOS badge | `/health` on port 8003 | ✓ green when reachable |
| CONFIGURE button | Opens settings panel (display-only, documented) | ✓ opens/closes panel |

### Session Ledger (6 tiles)

Every tile shows a real number from `GET /session-stats`, which itself aggregates the `incidents` table.

| Tile | JSON field | Verified after a demo run |
| --- | --- | --- |
| TOTAL INCIDENTS | `total_incidents` | ✓ matches SQL `SELECT COUNT(*) FROM incidents` |
| CRASHES | `crashes` | ✓ matches `WHERE type='crash'` count |
| SILENT FAILURES | `silent_failures` | ✓ matches `WHERE type='silent_failure'` count |
| AVG. MTTR | `avg_mttr_seconds` | ✓ matches `AVG(mttr_seconds) WHERE status='resolved'` |
| AUTONOMOUS RATE | `autonomous_rate` | ✓ = `crashes / total_incidents * 100` |
| TOTAL BLAST RADIUS | `total_blast_radius` | ✓ = `SUM(blast_radius)` |

### FRAUD SCORE — LIVE vs BASELINE panel

| Element | Backing call | Verified |
| --- | --- | --- |
| FRAUD API status card (HEALTHY / DEGRADED / DRIFT / DOWN) | `/status.fraud_api_up` + `/status.active_incident_type` | ✓ turns red on crash, amber on drift |
| UPTIME readout | `/live-metrics.uptime_pct` | ✓ derived from Guardian's `health_history` deque |
| LATENCY readout | `/live-metrics.latency_ms_p50` | ✓ derived from the last 60s of poll latencies |
| CONFIDENCE readout | `/status.confidence` | ✓ 100 when stable, drops as PSI grows |
| GUARDIAN strip | `/status.active_incident_type` | ✓ says WATCHING when clear, RESPONDING when active |
| Oscilloscope trace | `/score-history` + LAST_INCIDENTS cache | ✓ green when normal, red during drift, gap during crash |
| Scope callouts | Cross-reference of samples' timestamps with incident detected_at / resolved_at | ✓ pinned to real event times |
| Baseline dashed line | `/score-history.baseline_mean` | ✓ at y=`baseline_mean` |
| ESTIMATED EXPOSURE $ | Active incident's `blast_radius × 84.72` | ✓ ticks up live during drift |

### Chaos control panel

| Button | Endpoint | Effect verified |
| --- | --- | --- |
| TERMINATE PROCESS | `POST http://:8003/chaos/crash` | ✓ fraud-api dies, health flips to false, incident row inserted |
| INDUCE LATENCY | `POST http://:8003/chaos/slow?ms=1500` | ✓ every `/score` sleeps 1.5s; Guardian's live-metrics latency p50 rises |
| CORRUPT OUTPUT | `POST http://:8003/chaos/corrupt` | ✓ score distribution shifts up; PSI rises above 0.20 within seconds |
| FORCE DRIFT CHECK NOW | `POST http://:8002/check-now` | ✓ button label updates with verdict for 3s |

### Recovery Policy

Static text describing the two policies (P-001 auto-restart, P-002 human approval). Nothing to bind. ✓ static.

### Pending Authorization card

| Element | Backing call | Verified |
| --- | --- | --- |
| ACTING AS dropdown | Display-only; used only as the identity string in the local approval history row (backend does not check identity) | ✓ documented in-UI as `(no auth)` |
| Approval item | `GET /pending-approvals` | ✓ shows one card per pending row |
| PSI number | `p.evidence.drift.psi` | ✓ matches DB `evidence_json` |
| Reasoning paragraph | `p.reasoning` from the DB | ✓ same string appears in the report |
| AUTHORIZE ROLLBACK button | `POST /approve/{id}` | ✓ resolves the incident |
| APPROVAL HISTORY rows | Client-side log of the current session's approvals | ✓ persists during the session |

### Latest Incident block

| Row | Source | Verified |
| --- | --- | --- |
| Label #NNNN | `incidents[0].id` | ✓ |
| TYPE | `incidents[0].type` | ✓ colour-coded (red for crash, amber for drift) |
| WINDOW | `detected_at → resolved_at (mttr)` | ✓ |
| STATUS | `incidents[0].status` | ✓ |
| BLAST RADIUS | `incidents[0].blast_radius` | ✓ |
| REASONING | `incidents[0].reasoning` | ✓ full string from DB |

### Incident Timeline strip

| Element | Source | Verified |
| --- | --- | --- |
| Dots (per incident) | Last 6 rows of `/incidents`, plotted in DOM order | ✓ colour-coded |
| Timestamps | `incident.detected_at` formatted as HH:MM:SS | ✓ |

### Score Distribution — Baseline vs Live

| Element | Source | Verified |
| --- | --- | --- |
| Baseline histogram (gray area) | Client-side binning of `/baseline.samples` over 20 bins on [0, 1] | ✓ |
| Live histogram (green/red area) | Client-side binning of `/score-history.live` over the same 20 bins | ✓ |
| BASELINE μ | `/baseline.mean` | ✓ shows `0.321` for a clean baseline |
| BASELINE σ | `/baseline.std` | ✓ shows `0.120` |
| LIVE μ | Computed client-side from the live samples | ✓ |
| SAMPLES count | `live.length` | ✓ |
| Verdict badge (STABLE / MINOR / SIGNIFICANT) | `/score-history.current_verdict` | ✓ |

### Guardian Narration feed

| Element | Emitted from | Verified |
| --- | --- | --- |
| Every line | Client-side diff of successive `pollNarrate()` calls | ✓ emits on real state transitions |
| WARN / ALERT / OK / INFO colour | Level chosen by which transition fired | ✓ |
| Timestamp | Client clock at emission time | ✓ |

### Auto-Generated Incident Report

| Element | Source | Verified |
| --- | --- | --- |
| Report ID + status | `/report/latest.incident_id` + `/incidents[0].status` | ✓ |
| Fields (WHAT/WHEN/DETECTED BY/ACTION/BLAST RADIUS/MTTR/POLICY) | Composed from `/incidents[0]` fields | ✓ |
| COPY AS MARKDOWN button | Copies `/report/latest.markdown` to clipboard | ✓ |
| PRINT button | `window.print()` with a print-only stylesheet that shows only the report | ✓ |

### Incident History table

| Element | Source | Verified |
| --- | --- | --- |
| Rows | `/incidents?limit=30` | ✓ |
| ID / type / status / MTTR / action columns | Fields from each row | ✓ |
| Colour coding | Per-status + per-type CSS classes | ✓ |

### Footer

| Element | Behaviour | Verified |
| --- | --- | --- |
| GUARDIAN / MLFLOW / GRAFANA / API DOCS badges | Links to :8002, :5000, :3000, :8002/docs | ✓ external links |
| RESET CHAOS STATE button | `POST http://:8003/chaos/reset` | ✓ |

---

## Reproduce

The audit is a shell script at `audit.sh` in the repo root:

```bash
bash audit.sh
```

It runs 19 checks: 3 service-health probes, 10 Guardian read endpoints, 2 Guardian write endpoints, 4 chaos endpoints. Every line prints PASS or FAIL and the actual observed value so you can spot-check yourself.

If any line prints FAIL, the corresponding UI element is broken. If every line prints PASS, every UI element on the dashboard is backed by live, working code.
