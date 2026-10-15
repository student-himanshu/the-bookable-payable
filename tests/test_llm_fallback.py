"""Vision-rescue tests with a fake model client (no network, no key)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bookable import llm_fallback as lf  # noqa: E402
from bookable.master import MasterData  # noqa: E402
from bookable.phase3 import process  # noqa: E402
from erp import erp_book  # noqa: E402

MD = MasterData(ROOT / "master_data")
GOOD = {"invoice_number": "A-1", "invoice_date": "2026-01-05", "due_date": "2026-01-15", "invoice_type": "INVOICE",
        "currency": "eur", "supplier": {"name": "Acme", "vat_id": "DE209177122"}, "gross_total": "1.190,00",
        "taxes": [], "line_items": [{"description": "Work", "item_type": "SERVICE", "quantity": "10",
                                     "unit_price": "100,00", "total": "1.000,00", "tax_rate": "19"}]}


class Parsing(unittest.TestCase):
    def test_fenced_and_prose_json(self):
        self.assertEqual(lf.parse_json('Here:\n```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(lf.parse_json('sure {"a": 2} done'), {"a": 2})
        self.assertIsNone(lf.parse_json("no json"))
        self.assertIsNone(lf.parse_json(""))


class Normalise(unittest.TestCase):
    def setUp(self):
        self.p = lf.normalise(json.loads(json.dumps(GOOD)), MD, "text")

    def test_numbers_become_erp_safe(self):
        self.assertEqual(self.p["gross_total"], "1190.00")
        li = self.p["line_items"][0]
        self.assertEqual((li["quantity"], li["unit_price"], li["total"]), ("10", "100.00", "1000.00"))
        self.assertEqual(erp_book(self.p)["will_book_gross"], 1190.0)

    def test_codes_are_ours_not_the_models(self):
        raw = json.loads(json.dumps(GOOD))
        raw["supplier"]["supplier_id"] = "FAKE"
        raw["payment_term_id"] = "Net_999"
        p = lf.normalise(raw, MD, "text")
        self.assertEqual(p["supplier"]["supplier_id"], "2845695")      # resolved from the VAT id by us
        self.assertEqual(p["payment_term_id"], "Net_10")                # from dates, by us
        self.assertEqual(p["line_items"][0]["taxes"][0]["tax_type_code"], "DE_190_VAT")
        self.assertEqual(p["currency"], "EUR")


class Gate(unittest.TestCase):
    def test_accepts_only_when_erp_foots(self):
        p = lf.normalise(json.loads(json.dumps(GOOD)), MD, "")
        self.assertTrue(lf.accept(p, GOOD)[0])
        p["gross_total"] = "1200.00"
        ok, why = lf.accept(p, GOOD)
        self.assertFalse(ok)
        self.assertIn("!=", why)

    def test_rejects_tax_inclusive_prices(self):
        p = lf.normalise(json.loads(json.dumps(GOOD)), MD, "")
        self.assertFalse(lf.accept(p, {**GOOD, "prices_include_tax": True})[0])

    def test_rejects_empty(self):
        self.assertFalse(lf.accept({"line_items": [], "gross_total": "1.00"}, {})[0])


class Rescue(unittest.TestCase):
    def _fake_client(self, payload: str):
        def create(**kw):
            return SimpleNamespace(content=[SimpleNamespace(text=payload)])
        return SimpleNamespace(messages=SimpleNamespace(create=create))

    def test_rescue_with_fake_model_and_cache(self):
        pdf = next((ROOT / "documents").glob("*.pdf"))
        calls = []
        client = self._fake_client(json.dumps(GOOD))
        orig = lf.render_pages
        lf.render_pages = lambda *a, **k: ["AAAA"]
        try:
            with tempfile.TemporaryDirectory() as td:
                p, info = lf.rescue(pdf, [1], "ocr", MD, client, cache_dir=Path(td))
                self.assertIsNotNone(p, info)
                self.assertTrue(info["accepted"])
                # second call must come from cache: a client that explodes proves no network use
                boom = SimpleNamespace(messages=SimpleNamespace(create=lambda **k: 1 / 0))
                p2, info2 = lf.rescue(pdf, [1], "ocr", MD, boom, cache_dir=Path(td))
                self.assertEqual(p2, p)
        finally:
            lf.render_pages = orig

    def test_rescue_rejects_non_footing_and_never_raises(self):
        bad = dict(GOOD, gross_total="999.00")
        pdf = next((ROOT / "documents").glob("*.pdf"))
        orig = lf.render_pages
        lf.render_pages = lambda *a, **k: ["AAAA"]
        try:
            p, info = lf.rescue(pdf, [1], "", MD, self._fake_client(json.dumps(bad)))
            self.assertIsNone(p)
            self.assertFalse(info["accepted"])
            p, info = lf.rescue(pdf, [1], "", MD, self._fake_client("garbage"))
            self.assertIsNone(p)
            p, info = lf.rescue(pdf, [1], "", MD, SimpleNamespace(messages=SimpleNamespace(create=lambda **k: 1 / 0)))
            self.assertIsNone(p)
            self.assertIn("ZeroDivisionError", info["reason"])
        finally:
            lf.render_pages = orig


class Integration(unittest.TestCase):
    def test_process_replaces_only_non_footing_records(self):
        seg = {"index": 1, "label": "INVOICE", "subtype": "invoice", "pages": [1], "confidence": "high",
               "doc_ids": [], "payable_candidate": True, "needs_review": [], "boundary_reason": ""}
        texts = {1: "Invoice No: Z9\nTotal 99.00\n"}                    # rule-based cannot build rows
        calls = []

        def rescuer(file, s, text):
            calls.append(file)
            return lf.normalise(json.loads(json.dumps(GOOD)), MD, text), {"attempted": True, "accepted": True}

        rec, reps = process("X.pdf", [seg], texts, MD, rescuer)
        self.assertEqual(calls, ["X.pdf"])
        self.assertEqual(rec["payables"][0]["gross_total"], "1190.00")
        self.assertTrue(reps[0]["structure"].startswith("llm-vision"))
        # a record that already foots is never sent to the model
        good_text = "Invoice No: A1234\nDescription Qty Unit Price Amount\nWidget 2 10.00 20.00\nTotal 20.00\n"
        calls.clear()
        process("Y.pdf", [seg], {1: good_text}, MD, rescuer)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)


class GeminiBackendTest(unittest.TestCase):
    def test_gemini_backend_with_fake_client(self):
        try:
            import google.genai  # noqa: F401
        except Exception:
            self.skipTest("google-genai not installed")
        seen = {}

        def gen(**kw):
            seen.update(kw)
            return SimpleNamespace(text=json.dumps(GOOD))
        client = lf.GeminiBackend(client=SimpleNamespace(models=SimpleNamespace(generate_content=gen)))
        import base64
        out = lf.call_model(client, [base64.b64encode(b"x").decode()], "ocr")
        self.assertEqual(json.loads(out)["invoice_number"], "A-1")
        self.assertEqual(seen["model"], lf.GEMINI_DEFAULT)

    def test_make_client_prefers_gemini_key(self):
        import os
        old = {k: os.environ.pop(k, None) for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY")}
        try:
            self.assertIsNone(lf.make_client())
        finally:
            for k, v in old.items():
                if v is not None:
                    os.environ[k] = v


class EnvLoader(unittest.TestCase):
    def test_loads_without_overriding(self):
        import os
        from bookable.config import load_env
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / ".env"
            f.write_text('# c\nTEST_P4_A="quoted val"\nexport TEST_P4_B=plain # note\nTEST_P4_C=file\n', encoding="utf-8")
            os.environ["TEST_P4_C"] = "real"
            try:
                keys = load_env(f)
                self.assertEqual(os.environ["TEST_P4_A"], "quoted val")
                self.assertEqual(os.environ["TEST_P4_B"], "plain")
                self.assertEqual(os.environ["TEST_P4_C"], "real")        # real env wins
                self.assertEqual(sorted(keys), ["TEST_P4_A", "TEST_P4_B"])
                self.assertEqual(load_env(Path(td) / "missing"), [])
            finally:
                for k in ("TEST_P4_A", "TEST_P4_B", "TEST_P4_C"):
                    os.environ.pop(k, None)
