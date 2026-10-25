# Demo walkthrough — captions + exact click sequence

Use this as your script when presenting, and as the caption source when you paste
screenshots into the report. Total time: under 4 minutes.

---

## Setup (before you start clicking)

```bash
start-guardianops.bat
```

Wait for the 4 terminal windows to open and for the browser to auto-launch at
`http://127.0.0.1:8080`. Give it another **30–60 seconds** after the page loads —
Guardian needs that time to capture its 200-sample baseline. You'll know it's
ready when the CONFIDENCE readout shows `100/100` and the oscilloscope trace
turns a steady green.

---

## 01 — `01_dashboard_healthy.jpg`

**What it shows:** steady-state operation. Nothing wrong.

**Caption suggestion:**
> GuardianOps dashboard at steady state. Session Ledger shows zero incidents,
> Confidence sits at 100/100, and the live score trace (green) tracks the
> dashed baseline mean closely.

**No action needed** — this is just the default view after the baseline capture completes.

---

## 02 — `02_crash_detected.jpg`

**What it shows:** fraud-api killed outright; Guardian has classified it as a crash and is mid-recovery.

**Click sequence:**
1. Click **TERMINATE PROCESS** (red button, top-left of the chaos panel)
2. Screenshot within ~3 seconds — you want to catch the `DOWN` state and the
   `RESPONDING · CRASH` guardian status before it auto-resolves

**Caption suggestion:**
> Immediately after a chaos-injected process crash. FRAUD API reads DOWN,
> Session Ledger has incremented Crashes to 1, Autonomous Rate shows 100%
> (no human involvement required for this class of failure).

**Note:** under Docker Compose, the container restarts itself automatically
within a few seconds (`restart: on-failure` policy). If you're running the
local `start-guardianops.bat` version instead, you'll need to manually
re-launch the `fraud-api` window — Guardian will detect the recovery either way.

---

## 03 — `03_incident_report_narration.jpg`

**What it shows:** the auto-generated incident post-mortem document + the live Guardian Narration console, both populated from the crash you just resolved.

**Click sequence:**
1. Wait for the crash to auto-resolve (confirmed by the Narration console logging "incident resolved via auto_restart")
2. Scroll down to the **Incident Post-Mortem** section

**Caption suggestion:**
> Auto-generated incident report for the resolved crash — classification,
> timeline, MTTR (16.57s in our validation run), governing policy (P-001),
> and full machine-generated reasoning. No human wrote any of this text.
> The Guardian Narration console above shows the same event as a live,
> timestamped decision log.

---

## 04 — pending-approval card (recommended, not yet captured)

**What it shows:** the plain-English drift-incident card, mid-incident, waiting on a human.

**Click sequence:**
1. Click **CORRUPT OUTPUT** (amber button in the chaos panel)
2. Wait ~15–20 seconds — Guardian needs two consecutive significant-drift
   readings (10 seconds apart) before it opens the incident
3. Watch for the sticky amber banner to appear at the top of the page:
   *"1 silent-failure incident awaiting your sign-off"*
4. Screenshot the banner + the Pending Authorization card below it (scroll down
   to the "Recovery Policy" section)

**Caption suggestion:**
> A silent-failure (output-drift) incident mid-flight. PSI has crossed the
> 0.20 threshold (0.40 observed in our validation run) while the service
> itself reports healthy — no crash, no latency spike. Guardian has
> deliberately taken no corrective action and is waiting for a human to
> click Authorize Rollback, per policy P-002.

**Do NOT click Authorize yet** if you want this exact screenshot — approving
resolves the incident and the banner disappears.

---

## 05 — Replay Real Dataset modal (recommended, not yet captured)

**What it shows:** the confusion matrix + precision/recall/F1/accuracy from
scoring the labeled 500-transaction dataset.

**Click sequence:**
1. (If you haven't already) click **Authorize Rollback** to close out the
   drift incident from step 04
2. Click **REPLAY REAL DATASET** button
3. Wait ~2–3 seconds for the modal to populate
4. Screenshot the confusion-matrix grid + the four metric tiles

**Caption suggestion:**
> Evaluation of the fraud scorer against 500 labeled transactions (20 ground-
> truth fraud cases, 4% injected rate). Precision 1.00 / Recall 0.25 / F1 0.40 /
> Accuracy 0.97 — the rule-based scorer raises zero false alarms but misses
> most of the subtler fraud patterns, motivating the Future Work item of
> swapping in a trained classifier.

---

## Full reset between takes

```bash
stop-guardianops.bat
```
then delete `data/guardian/guardian.db` and re-run `start-guardianops.bat`
for a completely clean incident history before a live demo.
