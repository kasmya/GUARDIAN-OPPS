# GuardianOps — Report Package

This folder contains the academic report deliverable, separate from the project's
own `README.md` / `DIARY.md` / `ROADMAP.md` (which document the engineering side
for other developers).

## Contents

| File | Purpose |
| --- | --- |
| `GuardianOps_Report.md` | The full report — markdown source. All 10 required sections, with `[PLACEHOLDER: ...]` markers for anything only you can fill in (your name, course code, professor, citations). |
| `figures/dashboard_demo.jpg` | Real screenshot: healthy steady-state dashboard |
| `figures/pipeline_demo.jpg` | Real screenshot: crash detected, Session Ledger updated |
| `figures/drift_alert_demo.jpg` | Real screenshot: auto-generated incident report + live narration console |
| `figures/architecture.txt` | Placeholder instructions for rendering `architecture.png` — see the file |

## Before you submit

1. **Fill in every `[PLACEHOLDER: ...]`** in `GuardianOps_Report.md` — your name, course, institution, professor, submission date confirmation, and citation formatting per your course's required style (IEEE/APA/etc).
2. **Capture the two remaining screenshots** listed in `../screenshots/05_demo_walkthrough.md` (pending-approval card, replay confusion matrix) — both take under 2 minutes with `start-guardianops.bat` running.
3. **Convert to your required file format.** The markdown source converts cleanly:
   - To Word: open in any editor that supports Markdown import (Word 365, Google Docs via "Open with Google Docs"), or run `pandoc GuardianOps_Report.md -o GuardianOps_Report.docx` if you have [Pandoc](https://pandoc.org/) installed.
   - To PDF: `pandoc GuardianOps_Report.md -o GuardianOps_Report.pdf`, or export from Word/Google Docs once converted.
4. **Tell Claude your exact formatting requirements** (font, spacing, citation style, page limits, section numbering convention) and it will reflow this content into that exact format — the content itself is already final and fact-checked against the live system.

## What's real vs. placeholder in the report

Every number in §7 (Results) was captured from a live run of the system on the
date stated in the report — not invented. The `audit.sh` output and `pytest`
output backing those numbers are reproducible by anyone who clones this repo
and runs the commands in the main `README.md`. Only the following are
placeholders, by design, because they're information only you have:

- Your name, institution, course code, professor name
- The exact citation format your course requires
- The repository's public URL (fill in once you've pushed)
- Two optional screenshots (drift banner, replay modal) — instructions in
  `screenshots/05_demo_walkthrough.md`
