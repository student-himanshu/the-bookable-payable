"""Phase 3 driver: documents/*.pdf -> output/<name>.json (schema-conformant) + reports/phase3_report.*

    python -m bookable.phase3                      # full run (OCR cache used if present)
    python -m bookable.phase3 --from-reports       # reuse reports/extracted/*.json (no OCR, fast)
    python -m bookable.phase3 --only INV-01 DU-10  # selected PDFs

Per PDF: payable segments -> `payables[]`; every other segment -> `declined[]` with a reason.
Exit code 0 even when records are flagged for review: flags are information, not failures.
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

from .build import build_payable
from .master import MasterData

ROOT = Path(__file__).resolve().parent.parent


def _segments_from_detail(detail: dict) -> tuple:
    texts = {p["page"]: p["text"] for p in detail["pages"]}
    return detail["segments"], texts


def process(file: str, segments: list, texts: dict, md: MasterData) -> tuple:
    payables, declined, reports = [], [], []
    for seg in segments:
        text = "\n".join(texts.get(p, "") for p in seg["pages"])
        if seg["payable_candidate"]:
            try:
                payable, rep = build_payable(text, md, label=seg["label"], doc_ids=seg.get("doc_ids"))
            except Exception as exc:     # one bad document must never stop the batch
                declined.append({"doc_type": "unprocessable",
                                 "reason": f"internal error while building payable: {type(exc).__name__}: {exc}"})
                continue
            payables.append(payable)
            reports.append({"segment": seg["index"], "pages": seg["pages"], "label": seg["label"],
                            "classifier_review": seg.get("needs_review", []), **asdict(rep)})
        else:
            reason = "; ".join(seg.get("needs_review", [])) or seg.get("boundary_reason", "")
            declined.append({"doc_type": seg["subtype"] if seg["subtype"] not in ("", None) else seg["label"],
                             "reason": f"{seg['label']} pages {seg['pages'][0]}-{seg['pages'][-1]} "
                                       f"({seg['confidence']} confidence) is not a payable"
                                       + (f": {reason}" if reason else "")})
    return {"file": file, "payables": payables, "declined": declined}, reports


def render_md(rows: list) -> str:
    out = ["# Phase 3 field-extraction report", "",
           "`footing` = ERP recompute vs printed gross. `OK` only means the structure foots; it is NOT proof every field is right.",
           "", "| file | seg | status | structure | printed | ERP | rows | supplier | flags |",
           "|---|---:|---|---|---:|---:|---:|---|---|"]
    for r in rows:
        for s in r["segments"]:
            out.append(f"| {r['file']} | {s['segment']} | {s['status']} | {s['structure']} | {s['printed_gross']} | "
                       f"{s['erp_gross']} | {s['n_rows']} | {s['supplier_match']} | {'<br>'.join(s['flags']) or '-'} |")
        if not r["segments"]:
            out.append(f"| {r['file']} | - | no payable | - | - | - | - | - | declined only |")
    tot = [s for r in rows for s in r["segments"]]
    foot = sum(1 for s in tot if s["printed_gross"] and s["printed_gross"] == s["erp_gross"] and s["n_rows"] > 0)
    out += ["", f"Payables built: {len(tot)}; ERP foots to printed gross: {foot}; NOT footing / needs work: {len(tot) - foot}."]
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bookable.phase3")
    ap.add_argument("--docs", type=Path, default=ROOT / "documents")
    ap.add_argument("--out", type=Path, default=ROOT / "output")
    ap.add_argument("--reports", type=Path, default=ROOT / "reports")
    ap.add_argument("--master", type=Path, default=ROOT / "master_data")
    ap.add_argument("--cache", type=Path, default=ROOT / ".cache" / "ocr")
    ap.add_argument("--from-reports", action="store_true", help="reuse reports/extracted/*.json instead of re-extracting")
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--no-ocr", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args(argv)

    md = MasterData(args.master)
    wanted = {w.lower().removesuffix(".pdf") for w in args.only} if args.only else None
    jobs = []
    if args.from_reports:
        for f in sorted((args.reports / "extracted").glob("*.json")):
            if wanted and f.name.lower().removesuffix(".json").removesuffix(".pdf") not in wanted:
                continue
            d = json.loads(f.read_text(encoding="utf-8"))
            segs, texts = _segments_from_detail(d)
            jobs.append((d["file"], segs, texts))
    else:
        from .extract import DEFAULT_LANGS
        from .phase2 import analyse
        pdfs = sorted(args.docs.glob("*.pdf"))
        if wanted:
            pdfs = [p for p in pdfs if p.stem.lower() in wanted]
        if not pdfs:
            print(f"no PDFs to process in {args.docs}", file=sys.stderr)
            return 2
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
            res = list(ex.map(lambda p: analyse(p, ocr=not args.no_ocr, cache_dir=None if args.no_ocr else args.cache,
                                                langs=DEFAULT_LANGS, dpi=200), pdfs))
        for _, detail in res:
            segs, texts = _segments_from_detail(detail)
            jobs.append((detail["file"], segs, texts))
    if not jobs:
        print("nothing to process", file=sys.stderr)
        return 2

    args.out.mkdir(parents=True, exist_ok=True)
    args.reports.mkdir(parents=True, exist_ok=True)
    rows = []
    for file, segs, texts in jobs:
        rec, reps = process(file, segs, texts, md)
        (args.out / (Path(file).stem + ".json")).write_text(
            json.dumps(rec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        rows.append({"file": file, "segments": reps})
    (args.reports / "phase3_report.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    (args.reports / "phase3_report.md").write_text(render_md(rows), encoding="utf-8")
    n_pay = sum(len(r["segments"]) for r in rows)
    print(f"{len(rows)} PDFs -> {args.out}; {n_pay} payables; report: {args.reports / 'phase3_report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
