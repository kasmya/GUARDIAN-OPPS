# GuardianOps Report Package

The academic report follows the Manipal University Jaipur project-report format
(title page, certificate page, declaration, acknowledgments, abstract, contents,
lists of figures and tables, Chapters 1 to 5, references, annexures).

| File | Purpose |
| --- | --- |
| `GuardianOps_Report.docx` | Editable report (Times New Roman, A4). Fill the bracketed placeholders here. |
| `GuardianOps_Report.pdf` | The same report exported by Word, with all page numbers in the contents and lists filled in. |
| `figures/` | Diagrams (`fig_1_1` to `fig_4_7`) and 2x screenshots (`fig_4_*`) used by the report. |
| `results/drift_evaluation.json` | Output of `services/guardian/tools/evaluate_drift.py` (false-alarm and detection simulation). |
| `results/verification_run.txt` | Saved output of `scripts/ci_smoke.sh` (endpoint audit and end-to-end scenario). |
| `assets/muj_logo.png` | University logo used on the title page. |
| `build/` | Generators: `make_figures.py`, `capture_screenshots.py`, `build_report.py`, `content.py`, `docx_lib.py`. |

## Fill in before submitting

Square-bracket placeholders: student name, registration number, course name and code,
faculty guide, head of department, and the signed certificate page (page 2 is reserved for it).
The department line on the title page is kept from the format sample; change it if yours differs.
The declaration is a statement you make as the author; read it and adjust it to your
institution's rules on tools and assistance before signing.

## Rebuild

```bash
python report/build/make_figures.py                 # diagrams (Playwright + Edge)
python report/build/capture_screenshots.py          # needs the stack running on 8001-8003 and 8080
python report/build/build_report.py                 # needs Microsoft Word for the PDF export
```

Every number in the report comes from `report/results/` or from the test and audit
output described in Chapter 4. The Docker Compose stack was not run when the report was
written; Chapter 4 says so.
