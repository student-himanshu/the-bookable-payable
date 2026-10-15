# Phase 3 — field extraction, master matching, output JSON

Run (after Phase 2 setup, venv active):

    python -m bookable.phase3                    # full: extract (OCR cache) -> output/*.json
    python -m bookable.phase3 --from-reports     # reuse reports/extracted/*.json (fast, no OCR)
    python -m bookable.phase3 --only INV-01      # one file
    python -m unittest discover -s tests -v      # 103 tests

Outputs: `output/<name>.json` (payables[] + declined[]), `reports/phase3_report.md|json`.

Modules: `numbers.py` (locale-safe amounts/dates), `master.py` (indexed supplier/tax/terms/PO/buyer
matching, blank when unsure), `fields.py` (header, totals, tax summary), `lines.py` (item rows verified by
qty x price = total), `build.py` (structure chosen by ERP footing, grounding check), `phase3.py` (CLI).

Honest status: rule-based baseline. On the 42 open PDFs, 12 of 39 payables foot to the printed gross.
Every record in the report carries flags saying why it does not. Not proof of correctness.
