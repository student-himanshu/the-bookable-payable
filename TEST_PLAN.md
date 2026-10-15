# TEST_PLAN.md

Status legend: PASS / FAIL / BLOCKED / NOT RUN. Results below are from the Phase 1 sandbox
(Linux, Python 3.12.3) unless stated.

## Test categories

| ID | Category | Command | Phase | Status |
|---|---|---|---|---|
| T1 | Environment check | `python --version` ; `pdftotext -v` ; `tesseract --list-langs` | 1 | PASS (Python 3.12.3, poppler, tesseract 5 with eng+osd only) |
| T2 | Oracle integrity (erp.py hash) | `python -m unittest tests.test_baseline.OracleIntegrity` | 1 | PASS |
| T3 | Oracle example on sample | `python example_check.py` | 1 | PASS (438.0 EUR) |
| T4 | Oracle characterisation | `python -m unittest tests.test_baseline.OracleBehaviour tests.test_baseline.OracleNumParsingTraps` | 1 | PASS |
| T5 | Master-data shape/consistency | `python -m unittest tests.test_baseline.MasterData` | 1 | PASS |
| T6 | Sample schema shape | `python -m unittest tests.test_baseline.SampleSchemaShape` | 1 | PASS |
| T7 | PDF inventory (42 files / 111 pages) | `python -m unittest tests.test_baseline.DocumentInventory` ; `python tools/inventory_pdfs.py` | 1 | PASS |
| T8 | Full baseline suite | `python -m unittest discover -s tests -v` | 1 | PASS (37 tests) |
| T9 | Same suite under pytest | `python -m pytest tests -v` | 1 | NOT RUN (pytest not installed; sandbox has no network) |
| T10 | setup.ps1 | `powershell -File .\setup.ps1` | 1 | NOT RUN (no PowerShell in sandbox) |
| T11 | Extraction + OCR fallback, page boundaries | unit + per-document report | 2 | NOT RUN |
| T12 | Classification (invoice / credit memo / supporting / non-payable / multi-payable) | unit tests + labelled review of all 42 PDFs | 2 | NOT RUN |
| T13 | Parsing: locale numbers, dates, currency | unit tests | 3 | NOT RUN |
| T14 | Master-data matching (supplier, buyer, tax, term, PO), incl. scale | unit tests + large synthetic master | 3 | NOT RUN |
| T15 | Schema validation of every output | `python -m ... validate` | 3-5 | NOT RUN |
| T16 | Oracle comparison per payable (gross + structure) | QA tool | 4-5 | NOT RUN |
| T17 | Adversarial: multi-rate, withholding, rounding, malformed JSON, duplicates, OCR errors, missing master entries | tests | 4 | NOT RUN |
| T18 | Full pipeline: one `output/X.json` per PDF | single documented command | 5 | NOT RUN |

## Acceptance rules carried into later phases

1. `erp.py` hash must equal the recorded SHA-256 in every run.
2. Every number written to JSON is a plain dot-decimal string with no thousands separator and no
   trailing currency text (erp.num() silently turns anything else into 0.0; see T4).
3. A gross match with the oracle is necessary, never sufficient: structure (tax placement, names,
   rates, decomposed components) is checked separately.
4. Every emitted value must be traceable to document text; every code must exist in master data.
5. No fix may fire without an independent fact supporting it (README rule 3).

## Known limits of the Phase 1 environment

- No network: cannot install pytest/jsonschema or extra tesseract language packs.
- OCR is English-only in the sandbox; documents are German, Estonian, Portuguese, Turkish, Malay-region,
  etc. Local machines should install the matching tesseract language packs.
- There is no ground truth for any PDF other than the single sample (which does not match INV-01
  exactly; see AUDIT.md F-6), so "correct" can only be judged by the oracle plus the document itself.
