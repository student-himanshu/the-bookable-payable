"""Phase 1 baseline tests.

Characterise the fixed ERP oracle (erp.py), the shipped sample, the master data and the
PDF inventory. stdlib `unittest` only, so they run with either:

    python -m unittest discover -s tests -v
    python -m pytest tests -v            (if pytest is installed)

These tests never modify erp.py. Tests that need pypdf are skipped if it is missing.
"""
from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from erp import erp_book, num, round2  # noqa: E402

# SHA-256 of erp.py exactly as shipped in candidate_kit-2.zip (recorded in Phase 1).
ERP_SHA256 = "e3c743d1a9c0d26cf2344bd9fa679f440ddcac003942e64a8b692323d9104bf0"
EXPECTED_PDF_COUNT = 42
EXPECTED_PAGE_COUNT = 111


def gross(payable: dict) -> float:
    return erp_book(payable)["will_book_gross"]


def line(qty="1", price="100", **kw) -> dict:
    d = {"quantity": qty, "unit_price": price}
    d.update(kw)
    return d


class OracleIntegrity(unittest.TestCase):
    def test_erp_is_unmodified(self):
        digest = hashlib.sha256((ROOT / "erp.py").read_bytes()).hexdigest()
        self.assertEqual(digest, ERP_SHA256, "erp.py differs from the shipped oracle")

    def test_sample_autodraft_foots_to_438(self):
        sample = json.loads((ROOT / "sample_autodraft.json").read_text(encoding="utf-8"))
        self.assertEqual(erp_book(sample), {"will_book_gross": 438.0, "currency": "EUR"})


class OracleBehaviour(unittest.TestCase):
    """Characterisation of what erp.py actually does (not what we wish it did)."""

    def test_empty_payable_is_zero(self):
        self.assertEqual(erp_book({}), {"will_book_gross": 0.0, "currency": ""})

    def test_basic_line(self):
        self.assertEqual(gross({"line_items": [line("4", "73.00")]}), 292.0)

    def test_line_percentage_discount(self):
        self.assertEqual(gross({"line_items": [line("2", "50", discount_percentage="10")]}), 90.0)

    def test_line_amount_discount_is_total_not_per_unit(self):
        self.assertEqual(gross({"line_items": [line("2", "50", discount="10")]}), 90.0)

    def test_discount_percentage_wins_over_amount(self):
        self.assertEqual(
            gross({"line_items": [line("1", "100", discount_percentage="10", discount="50")]}), 90.0)

    def test_line_tax_from_rate(self):
        self.assertEqual(gross({"line_items": [line("1", "100", tax_rate="19")]}), 119.0)

    def test_line_tax_explicit_amount_beats_rate(self):
        self.assertEqual(
            gross({"line_items": [line("1", "100", taxes=[{"tax_rate": "19", "tax_amount": "5.00"}])]}),
            105.0)

    def test_three_line_rates_stay_per_line(self):
        p = {"line_items": [line("1", "100", tax_rate="19"), line("1", "100", tax_rate="7"),
                            line("1", "100", tax_rate="0")]}
        self.assertEqual(gross(p), 326.0)

    def test_header_tax_on_net_base(self):
        p = {"line_items": [line("1", "100")], "taxes": [{"tax_rate": "20"}]}
        self.assertEqual(gross(p), 120.0)

    def test_header_discount_reduces_header_tax_base(self):
        p = {"line_items": [line("1", "100")], "discount_amount": "10", "taxes": [{"tax_rate": "20"}]}
        self.assertEqual(gross(p), 108.0)

    def test_charges_added_but_not_in_header_tax_base(self):
        p = {"line_items": [line("1", "100")], "freight_charges": "10", "insurance_charges": "5",
             "extra_charges": "2", "excise_duties": "3", "taxes": [{"tax_rate": "10"}]}
        self.assertEqual(gross(p), 130.0)  # 100 + 10 tax + 20 charges

    def test_header_discount_is_not_apportioned_to_line_taxes(self):
        p = {"line_items": [line("1", "100", tax_rate="10")], "discount_amount": "20"}
        self.assertEqual(gross(p), 90.0)  # 100 - 20 + 10 (line tax still on 100)

    def test_withholding_negative_header_tax(self):
        p = {"line_items": [line("1", "100")], "taxes": [{"tax_rate": "", "tax_amount": "-5.00"}]}
        self.assertEqual(gross(p), 95.0)

    def test_negative_line_tax_amount(self):
        p = {"line_items": [line("1", "100", taxes=[{"tax_amount": "-5"}])]}
        self.assertEqual(gross(p), 95.0)

    def test_zero_amount_line_kept(self):
        self.assertEqual(gross({"line_items": [line("1", "0"), line("1", "10")]}), 10.0)

    def test_round2_half_up(self):
        self.assertEqual(round2(1.005), 1.01)
        self.assertEqual(round2(2.675), 2.68)

    def test_credit_memo_has_no_sign_handling(self):
        # README says to see "erp.py's sign handling", but erp.py has none: a CREDIT_MEMO
        # with positive magnitudes books a positive gross.
        p = {"invoice_type": "CREDIT_MEMO", "line_items": [line("1", "100")]}
        self.assertEqual(gross(p), 100.0)

    def test_currency_passthrough_and_default(self):
        self.assertEqual(erp_book({"currency": "GHS"})["currency"], "GHS")
        self.assertEqual(erp_book({"currency": None})["currency"], "")

    def test_non_dict_payable_raises(self):
        with self.assertRaises(ValueError):
            erp_book([])

    def test_bad_line_entry_raises(self):
        with self.assertRaises(ValueError):
            erp_book({"line_items": ["nope"]})


class OracleNumParsingTraps(unittest.TestCase):
    """erp.num() fails SILENTLY to 0.0. Our serialiser must always emit plain dot-decimals."""

    def test_plain_and_symbol_prefix(self):
        self.assertEqual(num("1234.56"), 1234.56)
        self.assertEqual(num("€ 12.50"), 12.5)
        self.assertEqual(num("12.5%"), 12.5)

    def test_thousands_separator_becomes_zero(self):
        self.assertEqual(num("1,234.56"), 0.0)

    def test_european_decimal_comma_becomes_zero(self):
        self.assertEqual(num("1.234,56"), 0.0)
        self.assertEqual(num("73,00"), 0.0)

    def test_trailing_currency_becomes_zero(self):
        self.assertEqual(num("73.00 EUR"), 0.0)
        self.assertEqual(num("73.00€"), 0.0)

    def test_unlisted_prefix_symbol_becomes_zero(self):
        self.assertEqual(num("R100.00"), 0.0)
        self.assertEqual(num("RM100.00"), 0.0)
        self.assertEqual(num("S$100.00"), 0.0)

    def test_none_and_empty(self):
        self.assertEqual(num(None), 0.0)
        self.assertEqual(num(""), 0.0)


class MasterData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        md = ROOT / "master_data"
        cls.suppliers = json.loads((md / "suppliers.json").read_text(encoding="utf-8"))["suppliers"]
        cls.taxes = json.loads((md / "tax_master.json").read_text(encoding="utf-8"))["taxes"]
        cls.terms = json.loads((md / "payment_terms.json").read_text(encoding="utf-8"))["payment_terms"]
        cls.pos = json.loads((md / "po_master.json").read_text(encoding="utf-8"))["purchase_orders"]
        cls.books = json.loads((md / "chart_of_books.json").read_text(encoding="utf-8"))["companies"]

    def test_supplier_shape_and_unique_ids(self):
        keys = {"supplier_id", "name", "vat_id", "country", "email", "address", "bank_iban"}
        for s in self.suppliers:
            self.assertTrue(keys <= set(s), s)
        ids = [s["supplier_id"] for s in self.suppliers]
        self.assertEqual(len(ids), len(set(ids)))

    def test_tax_shape_and_unique_codes(self):
        for t in self.taxes:
            self.assertTrue({"code", "country", "tax_type", "rate", "name"} <= set(t), t)
        codes = [t["code"] for t in self.taxes]
        self.assertEqual(len(codes), len(set(codes)))

    def test_payment_terms_shape(self):
        for t in self.terms:
            self.assertTrue({"payment_term_id", "days", "text_aliases"} <= set(t), t)

    def test_po_supplier_ids_exist_in_supplier_master(self):
        ids = {s["supplier_id"] for s in self.suppliers}
        for po in self.pos:
            self.assertIn(po["supplier_id"], ids)

    def test_chart_of_books_has_sample_buyer(self):
        found = [(c["company_code"], bu["business_unit_code"], loc["location_code"])
                 for c in self.books for bu in c["business_units"] for loc in bu["locations"]]
        self.assertIn(("BOLTGROUP", "EE004", "LOC_EE_001"), found)

    def test_sample_codes_resolve(self):
        sample = json.loads((ROOT / "sample_autodraft.json").read_text(encoding="utf-8"))
        self.assertIn(sample["supplier"]["supplier_id"], {s["supplier_id"] for s in self.suppliers})
        self.assertIn(sample["payment_term_id"], {t["payment_term_id"] for t in self.terms})
        # NOTE: sample tax_type_code "VAT" is NOT a tax_master code (see AUDIT.md finding F-5).
        self.assertNotIn(sample["taxes"][0]["tax_type_code"], {t["code"] for t in self.taxes})


class SampleSchemaShape(unittest.TestCase):
    TOP = {"invoice_number", "invoice_date", "due_date", "invoice_type", "currency", "supplier",
           "buyer", "payment_term_id", "po_number", "po_id", "gross_total", "subtotal",
           "total_tax_amount", "discount_amount", "freight_charges", "insurance_charges",
           "extra_charges", "excise_duties", "taxes", "line_items"}
    LINE = {"description", "item_type", "uom", "quantity", "unit_price", "total", "discount",
            "discount_percentage", "tax_rate", "tax_amount", "taxes"}

    def test_sample_has_every_documented_key(self):
        sample = json.loads((ROOT / "sample_autodraft.json").read_text(encoding="utf-8"))
        self.assertEqual(self.TOP - set(sample), set())
        for li in sample["line_items"]:
            self.assertEqual(self.LINE - set(li), set())


class DocumentInventory(unittest.TestCase):
    def test_pdf_count(self):
        self.assertEqual(len(list((ROOT / "documents").glob("*.pdf"))), EXPECTED_PDF_COUNT)

    def test_every_pdf_opens_and_page_total(self):
        try:
            from pypdf import PdfReader
        except ImportError:
            self.skipTest("pypdf not installed")
        total = 0
        for pdf in sorted((ROOT / "documents").glob("*.pdf")):
            n = len(PdfReader(str(pdf)).pages)
            self.assertGreaterEqual(n, 1, pdf.name)
            total += n
        self.assertEqual(total, EXPECTED_PAGE_COUNT)


if __name__ == "__main__":
    unittest.main(verbosity=2)
