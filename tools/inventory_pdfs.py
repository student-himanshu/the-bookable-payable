"""Phase 1 inventory: one row per PDF in documents/ -> reports/pdf_inventory.{json,md}.

    python tools/inventory_pdfs.py                 # fast: pages, text layer, images, sha256
    python tools/inventory_pdfs.py --ocr-first-page  # also OCR page 1 (needs pdftoppm + tesseract)

Read-only with respect to documents/ and erp.py.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "documents"
REPORTS = ROOT / "reports"


def run(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace").stdout


def page_count(pdf: Path) -> int:
    from pypdf import PdfReader
    return len(PdfReader(str(pdf)).pages)


def inspect(pdf: Path, ocr: bool) -> dict:
    text = run(["pdftotext", "-layout", str(pdf), "-"])
    imgs = run(["pdfimages", "-list", str(pdf)]).strip().splitlines()
    row = {
        "file": pdf.name,
        "kb": round(pdf.stat().st_size / 1024),
        "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
        "pages": page_count(pdf),
        "text_layer_chars": len(text.strip()),
        "embedded_images": max(0, len(imgs) - 2),
    }
    row["kind"] = "text-layer" if row["text_layer_chars"] > 200 else (
        "mixed/sparse-text" if row["text_layer_chars"] > 0 else "scanned-image")
    if ocr:
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["pdftoppm", "-r", "150", "-f", "1", "-l", "1", "-png", str(pdf),
                            f"{td}/p"], capture_output=True)
            png = next(Path(td).glob("p*.png"), None)
            snippet = run(["tesseract", str(png), "-", "--psm", "6"]) if png else ""
        row["page1_ocr_head"] = [ln for ln in snippet.splitlines() if ln.strip()][:12]
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ocr-first-page", action="store_true")
    args = ap.parse_args()
    if args.ocr_first_page and not (shutil.which("tesseract") and shutil.which("pdftoppm")):
        print("tesseract/pdftoppm not found on PATH", file=sys.stderr)
        return 2
    pdfs = sorted(DOCS.glob("*.pdf"))
    with ThreadPoolExecutor(max_workers=4) as ex:
        rows = list(ex.map(lambda p: inspect(p, args.ocr_first_page), pdfs))
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "pdf_inventory.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    md = ["| file | KB | pages | text chars | images | kind |", "|---|---:|---:|---:|---:|---|"]
    md += [f"| {r['file']} | {r['kb']} | {r['pages']} | {r['text_layer_chars']} | {r['embedded_images']} | {r['kind']} |"
           for r in rows]
    md.append(f"\nTotal: {len(rows)} PDFs, {sum(r['pages'] for r in rows)} pages.")
    (REPORTS / "pdf_inventory.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"{len(rows)} PDFs, {sum(r['pages'] for r in rows)} pages -> reports/pdf_inventory.[json|md]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
