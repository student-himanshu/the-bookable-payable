"""Phase 2 driver: extract + classify + segment every PDF and write the per-document report.

    python -m bookable.phase2                       # all PDFs in documents/ -> reports/
    python -m bookable.phase2 --only INV-01 DU-08   # selected PDFs (stem or filename)
    python -m bookable.phase2 --no-ocr              # text layer only (fast, scanned pages empty)

Outputs (under --out, default reports/):
    extraction_report.json / extraction_report.md   one row per PDF
    extracted/<name>.json                           per-page text, method, OCR confidence, page class
Exit code: 0 = every PDF processed (review flags are not failures), 1 = at least one PDF failed
to open or yielded no text on any page, 2 = bad arguments.
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

from .classify import classify_page, mark_duplicates, segment_document
from .extract import DEFAULT_DPI, DEFAULT_LANGS, DocumentText, extract_document

ROOT = Path(__file__).resolve().parent.parent


def analyse(pdf: Path, *, ocr: bool, cache_dir, langs, dpi) -> tuple:
    doc: DocumentText = extract_document(pdf, ocr=ocr, cache_dir=cache_dir, langs=langs, dpi=dpi)
    pcs = [classify_page(p.text, p.page) for p in doc.pages]
    ocr_conf = {p.page: p.ocr_confidence for p in doc.pages}
    segs = segment_document(pcs, ocr_conf=ocr_conf)
    mark_duplicates(segs, {p.page: p.text for p in doc.pages}, pcs)
    review: list = []
    if doc.errors:
        review += doc.errors
    if doc.ocr_langs_missing and any(p.method == "ocr" for p in doc.pages):
        review.append("OCR ran without language packs: " + ",".join(doc.ocr_langs_missing))
    empty = [p.page for p in doc.pages if p.method == "empty"]
    if empty:
        review.append(f"pages with no extracted text: {empty}")
    payable_segs = [s for s in segs if s.payable_candidate]
    if len(payable_segs) > 1:
        review.append(f"{len(payable_segs)} payable candidates in one PDF: verify segmentation")
    if not payable_segs:
        review.append("no payable candidate: all content would be declined")
    summary = {
        "file": doc.file,
        "sha256": doc.sha256,
        "pages": doc.n_pages,
        "methods": {m: sum(1 for p in doc.pages if p.method == m) for m in sorted({p.method for p in doc.pages})},
        "mean_ocr_confidence": (round(sum(c for c in ocr_conf.values() if c is not None) /
                                      max(1, sum(1 for c in ocr_conf.values() if c is not None)), 1)
                                if any(c is not None for c in ocr_conf.values()) else None),
        "segments": [asdict(s) for s in segs],
        "payable_candidates": len(payable_segs),
        "review": review,
        "ok": bool(doc.pages) and any(p.chars for p in doc.pages) and not any(
            e.startswith("cannot open") for e in doc.errors),
    }
    detail = {
        "file": doc.file, "sha256": doc.sha256,
        "ocr_langs_requested": doc.ocr_langs_requested, "ocr_langs_used": doc.ocr_langs_used,
        "ocr_langs_missing": doc.ocr_langs_missing, "errors": doc.errors,
        "pages": [{**asdict(p), "classification": asdict(c)} for p, c in zip(doc.pages, pcs)],
        "segments": summary["segments"],
    }
    return summary, detail


def render_md(rows: list) -> str:
    out = ["# Phase 2 extraction & classification report", "",
           "Heuristic, evidence-based classification. `*` after a page label = untitled continuation page.",
           "No ground truth exists for these PDFs; entries marked REVIEW need a human look.", "",
           "| file | pages | method | OCR conf | segments (label pages) | payables | review |",
           "|---|---:|---|---:|---|---:|---|"]
    for r in rows:
        segs = "<br>".join(
            f"{s['label']}{'/' + s['subtype'] if s['subtype'] not in ('invoice', 'credit_memo') else ''} "
            f"p{s['pages'][0]}-{s['pages'][-1]} [{s['confidence']}]" for s in r["segments"])
        rev = "<br>".join(r["review"] + [f"seg{s['index']}: " + "; ".join(s["needs_review"])
                                          for s in r["segments"] if s["needs_review"]])
        meth = ",".join(f"{k}:{v}" for k, v in r["methods"].items())
        out.append(f"| {r['file']} | {r['pages']} | {meth} | {r['mean_ocr_confidence'] or '-'} | {segs} | "
                   f"{r['payable_candidates']} | {rev or 'ok'} |")
    n_ok = sum(1 for r in rows if r["ok"])
    out += ["", f"Processed {len(rows)} PDFs; {n_ok} produced text; "
                f"{sum(r['payable_candidates'] for r in rows)} payable candidates in total."]
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bookable.phase2")
    ap.add_argument("--docs", type=Path, default=ROOT / "documents")
    ap.add_argument("--out", type=Path, default=ROOT / "reports")
    ap.add_argument("--cache", type=Path, default=ROOT / ".cache" / "ocr")
    ap.add_argument("--only", nargs="*", default=None, help="PDF stems or filenames")
    ap.add_argument("--no-ocr", action="store_true")
    ap.add_argument("--dpi", type=int, default=DEFAULT_DPI)
    ap.add_argument("--langs", default="+".join(DEFAULT_LANGS), help="tesseract languages joined by '+'")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args(argv)

    if not args.docs.is_dir():
        print(f"documents folder not found: {args.docs}", file=sys.stderr)
        return 2
    pdfs = sorted(args.docs.glob("*.pdf"))
    if args.only:
        wanted = {w.lower().removesuffix(".pdf") for w in args.only}
        pdfs = [p for p in pdfs if p.stem.lower() in wanted]
        missing = wanted - {p.stem.lower() for p in pdfs}
        if missing:
            print(f"not found in {args.docs}: {sorted(missing)}", file=sys.stderr)
            return 2
    if not pdfs:
        print("no PDFs to process", file=sys.stderr)
        return 2

    langs = tuple(args.langs.split("+"))
    cache = None if args.no_ocr else args.cache
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        results = list(ex.map(lambda p: analyse(p, ocr=not args.no_ocr, cache_dir=cache, langs=langs,
                                                dpi=args.dpi), pdfs))
    (args.out / "extracted").mkdir(parents=True, exist_ok=True)
    rows = []
    for summary, detail in results:
        rows.append(summary)
        (args.out / "extracted" / f"{summary['file']}.json").write_text(
            json.dumps(detail, indent=1, ensure_ascii=False), encoding="utf-8")
    (args.out / "extraction_report.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    (args.out / "extraction_report.md").write_text(render_md(rows), encoding="utf-8")
    failed = [r["file"] for r in rows if not r["ok"]]
    print(f"{len(rows)} PDFs processed; {len(rows) - len(failed)} with text; "
          f"{sum(r['payable_candidates'] for r in rows)} payable candidates -> {args.out}")
    if failed:
        print("FAILED (no text or unreadable): " + ", ".join(failed), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
