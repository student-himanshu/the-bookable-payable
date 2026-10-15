"""Phase 2: extraction + OCR fallback + driver. Synthetic PDFs are generated with Pillow."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bookable import phase2  # noqa: E402
from bookable.extract import available_ocr_langs, extract_document, resolve_langs  # noqa: E402

try:
    from PIL import Image, ImageDraw, ImageFont
    HAVE_PIL = True
except ImportError:  # pragma: no cover
    HAVE_PIL = False

HAVE_OCR = available_ocr_langs() is not None and "eng" in (available_ocr_langs() or set())


def make_image_pdf(path: Path, lines: list, *, blank: bool = False) -> None:
    img = Image.new("RGB", (1240, 900), "white")
    if not blank:
        d = ImageDraw.Draw(img)
        font = ImageFont.load_default(size=46)
        for i, line in enumerate(lines):
            d.text((60, 60 + i * 90), line, fill="black", font=font)
    img.save(path, "PDF", resolution=150)


@unittest.skipUnless(HAVE_PIL, "Pillow not installed")
class Extraction(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    @unittest.skipUnless(HAVE_OCR, "tesseract not available")
    def test_scanned_page_uses_ocr(self):
        pdf = self.dir / "scan.pdf"
        make_image_pdf(pdf, ["INVOICE 77123", "Total 100.00 EUR"])
        d = extract_document(pdf, langs=("eng",))
        self.assertEqual(d.n_pages, 1)
        self.assertEqual(d.pages[0].method, "ocr")
        self.assertIn("INVOICE", d.pages[0].text.upper())
        self.assertGreater(d.pages[0].ocr_confidence, 50)

    @unittest.skipUnless(HAVE_OCR, "tesseract not available")
    def test_blank_page_is_empty_with_warning_not_dropped(self):
        pdf = self.dir / "blank.pdf"
        make_image_pdf(pdf, [], blank=True)
        d = extract_document(pdf, langs=("eng",))
        self.assertEqual(len(d.pages), 1)
        self.assertEqual(d.pages[0].method, "empty")
        self.assertTrue(d.pages[0].warnings)

    def test_ocr_disabled_reports_clearly(self):
        pdf = self.dir / "scan.pdf"
        make_image_pdf(pdf, ["INVOICE 1"])
        d = extract_document(pdf, ocr=False)
        self.assertEqual(d.pages[0].method, "empty")
        self.assertTrue(any("OCR not available" in w for w in d.pages[0].warnings))

    def test_corrupt_file_does_not_raise(self):
        bad = self.dir / "bad.pdf"
        bad.write_bytes(b"this is not a pdf")
        d = extract_document(bad)
        self.assertEqual(d.pages, [])
        self.assertTrue(any(e.startswith("cannot open PDF") for e in d.errors))

    def test_missing_language_is_reported_not_fatal(self):
        used, missing, installed = resolve_langs(("eng", "zzz"))
        if installed is None:
            self.skipTest("tesseract not available")
        self.assertIn("zzz", missing)
        self.assertIn("eng", used)

    @unittest.skipUnless(HAVE_OCR, "tesseract not available")
    def test_cache_round_trip(self):
        pdf = self.dir / "scan.pdf"
        make_image_pdf(pdf, ["INVOICE 5"])
        cache = self.dir / "cache"
        first = extract_document(pdf, langs=("eng",), cache_dir=cache)
        self.assertEqual(len(list(cache.glob("*.json"))), 1)
        second = extract_document(pdf, langs=("eng",), cache_dir=cache)
        self.assertEqual(first.to_dict(), second.to_dict())

    def test_real_text_layer_pdf_needs_no_ocr(self):
        pdf = ROOT / "documents" / "INV-36.pdf"
        if not pdf.exists():
            self.skipTest("INV-36.pdf not present")
        d = extract_document(pdf, ocr=False)
        self.assertEqual(d.pages[0].method, "text-layer")
        self.assertIn("Oracle America", d.pages[0].text)

    @unittest.skipUnless(HAVE_OCR, "tesseract not available")
    def test_real_scanned_invoice_ocr(self):
        pdf = ROOT / "documents" / "INV-01.pdf"
        if not pdf.exists():
            self.skipTest("INV-01.pdf not present")
        d = extract_document(pdf, langs=("eng",))
        self.assertEqual(d.pages[0].method, "ocr")
        self.assertIn("852566", d.pages[0].text)
        self.assertIn("438,00", d.pages[0].text)


@unittest.skipUnless(HAVE_PIL and HAVE_OCR, "Pillow/tesseract not available")
class Driver(unittest.TestCase):
    def test_cli_selected_pdfs_and_exit_codes(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            docs, out = td / "docs", td / "out"
            docs.mkdir()
            make_image_pdf(docs / "A.pdf", ["INVOICE 90210", "Total 55.00"])
            make_image_pdf(docs / "B.pdf", ["DELIVERY NOTE", "Widget 4"])
            rc = phase2.main(["--docs", str(docs), "--out", str(out), "--cache", str(td / "c"),
                              "--langs", "eng", "--only", "A", "--workers", "1"])
            self.assertEqual(rc, 0)
            report = json.loads((out / "extraction_report.json").read_text(encoding="utf-8"))
            self.assertEqual([r["file"] for r in report], ["A.pdf"])
            self.assertEqual(report[0]["payable_candidates"], 1)
            self.assertTrue((out / "extracted" / "A.pdf.json").exists())
            self.assertTrue((out / "extraction_report.md").read_text(encoding="utf-8").startswith("# Phase 2"))
            # unknown selection -> usage error, nothing processed
            self.assertEqual(phase2.main(["--docs", str(docs), "--out", str(out), "--only", "ZZZ"]), 2)
            # missing folder -> usage error
            self.assertEqual(phase2.main(["--docs", str(td / "nope"), "--out", str(out)]), 2)

    def test_unreadable_pdf_gives_exit_1(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            docs = td / "docs"
            docs.mkdir()
            (docs / "bad.pdf").write_bytes(b"nope")
            rc = phase2.main(["--docs", str(docs), "--out", str(td / "out"), "--no-ocr", "--workers", "1"])
            self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
