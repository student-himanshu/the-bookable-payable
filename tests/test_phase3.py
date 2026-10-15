"""Phase 3 tests: numbers, master matching, row detection, structure choice, output contract."""
from __future__ import annotations

import json
import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bookable.build import build_payable, grounding_check  # noqa: E402
from bookable.lines import parse_row  # noqa: E402
from bookable.master import MasterData  # noqa: E402
from bookable.numbers import find_dates, fmt_amount, fmt_plain, fmt_price, parse_amount  # noqa: E402
from erp import erp_book, num  # noqa: E402

MD = MasterData(ROOT / "master_data")

INV01 = """Northwind Operations OU
Rechnung Nr.: 852566
Rechnungsdatum: 02.02.2026
Pos Beschreibung Einzelpreis Menge Gesamtpreis
1 Projektmanagement Nachberechnung aus November 73,00 € 4 Std. 292,00 €
2 Projektmanagement Nachberechnung aus Dezember 73,00 € 2 Std. 146,00 €
Gesamtsumme 438,00 €
zzgl. 0 % MwSt 0,00 €
Endbetrag 438,00 €
Bitte begleichen Sie den Betrag bis zum 12.02.2026 auf eine der aufgeführten Bankverbindungen.
"""

INV14 = """Invoice Date Silverbrook Media Limited
INVOICE 01 May 2026
Invoice Number INV-1587
Description Quantity Unit Price VAT Amount GBP
Management Fee for June 2026 1.00 14,620.18 20% 14,620.18
Business Rates for June 2026 1.00 9,987.50 No VAT 9,987.50
Utilities for June 2026 1.00 1,435.00 20% 1,435.00
Subtotal 26,042.68
Total No VAT 0.00
Total VAT 20% 3,211.04
Invoice Total GBP 29,253.72
Due Date: 31 May 2026
"""


class Numbers(unittest.TestCase):
    def test_locales(self):
        self.assertEqual(parse_amount("1.234,56"), Decimal("1234.56"))
        self.assertEqual(parse_amount("1,234.56"), Decimal("1234.56"))
        self.assertEqual(parse_amount("73,00", ","), Decimal("73.00"))
        self.assertEqual(parse_amount("R129,514.32"), Decimal("129514.32"))
        self.assertEqual(parse_amount("1.234", ","), Decimal("1234"))
        self.assertEqual(parse_amount("-327,87", ","), Decimal("-327.87"))
        self.assertIsNone(parse_amount("abc"))

    def test_output_is_always_erp_safe(self):
        for d in (Decimal("73"), Decimal("1234.5"), Decimal("0.1")):
            self.assertEqual(num(fmt_amount(d)), float(d))
        self.assertEqual(fmt_plain(Decimal("133.00")), "133")
        self.assertEqual(fmt_price(Decimal("73")), "73.00")
        self.assertEqual(fmt_price(Decimal("0.521")), "0.521")

    def test_dates(self):
        self.assertEqual(find_dates("02.02.2026")[0][0].isoformat(), "2026-02-02")
        self.assertEqual(find_dates("18-Jun-2018")[0][0].isoformat(), "2018-06-18")
        self.assertEqual(find_dates("31 May 2026")[0][0].isoformat(), "2026-05-31")
        d, amb, _ = find_dates("06/05/2026")[0]
        self.assertTrue(amb)
        self.assertEqual(d.isoformat(), "2026-05-06")                       # dmy preferred
        self.assertEqual(find_dates("13/05/2026")[0][1], False)             # unambiguous


class Master(unittest.TestCase):
    def test_supplier_by_vat_and_iban(self):
        self.assertEqual(MD.match_supplier("VAT ID: DE 209 177 122").code, "2845695")
        self.assertEqual(MD.match_supplier("IBAN EE472200221017274226").code, "2807582")

    def test_supplier_no_match_is_blank(self):
        m = MD.match_supplier("Acme Rockets Inc, 12 Main Street")
        self.assertEqual(m.code, "")

    def test_supplier_single_common_token_is_not_enough(self):
        self.assertEqual(MD.match_supplier("Direct Services for you").code, "")

    def test_tax_resolution_and_ambiguity(self):
        self.assertEqual(MD.match_tax(19, "MwSt 19%", "DE").code, "DE_190_VAT")
        self.assertEqual(MD.match_tax(15, "VAT 15%", "ZA").code, "ZAF_150_VAT")
        self.assertEqual(MD.match_tax(15, "VAT 15%", "").code, "")          # ZA vs GH: ambiguous -> blank
        self.assertEqual(MD.match_tax(99, "x", "DE").code, "")

    def test_terms_and_po(self):
        self.assertEqual(MD.match_terms("Payment terms: Net 30").code, "Net_30")
        self.assertEqual(MD.match_terms("", 14).code, "Net_14")
        self.assertEqual(MD.match_po("PO-EE-2026-0044").code, "PO-EE-2026-0044")
        self.assertEqual(MD.match_po("PO-XX-9999").code, "")

    def test_buyer_shared_address_is_ambiguous_blank(self):
        self.assertEqual(MD.match_buyer("Vana-Louna 15, 10134 Tallinn, Estonia").code, "")
        self.assertEqual(MD.match_buyer("Bolt Holdings OU").record["business_unit_code"], "EE004")


class Rows(unittest.TestCase):
    def test_arithmetic_consistency_finds_row(self):
        r = parse_row("Management Fee for June 2026 1.00 14,620.18 20% 14,620.18", ".", 1)
        self.assertIsNotNone(r)
        self.assertEqual((r.quantity, r.unit_price, r.total, r.tax_rate),
                         (Decimal("1.00"), Decimal("14620.18"), Decimal("14620.18"), Decimal(20)))

    def test_inconsistent_numbers_are_not_a_row(self):
        self.assertIsNone(parse_row("Widget 3 10.00 99.00", ".", 1))

    def test_percentage_discount_row(self):
        r = parse_row("Gadget 2 50.00 10% 90.00", ".", 1)
        self.assertEqual(r.discount_pct, Decimal(10))

    def test_dates_are_not_numbers(self):
        self.assertIsNone(parse_row("Delivery 02.02.2026 2026 1", ".", 1))


class Build(unittest.TestCase):
    def test_inv01_foots_to_printed_gross(self):
        p, rep = build_payable(INV01, MD, label="INVOICE")
        self.assertEqual(p["invoice_number"], "852566")
        self.assertEqual((p["invoice_date"], p["due_date"]), ("2026-02-02", "2026-02-12"))
        self.assertEqual(p["gross_total"], "438.00")
        self.assertEqual(erp_book(p)["will_book_gross"], 438.0)
        self.assertEqual(p["currency"], "EUR")
        self.assertEqual(len(p["line_items"]), 2)
        self.assertEqual(p["line_items"][0]["quantity"], "4")
        self.assertEqual(p["line_items"][0]["unit_price"], "73.00")
        self.assertEqual(rep.ungrounded, [])

    def test_three_rates_stay_line_level(self):
        p, rep = build_payable(INV14, MD, label="INVOICE")
        self.assertEqual(rep.structure, "line-level taxes")
        self.assertEqual([li["tax_rate"] for li in p["line_items"]], ["20", "0", "20"])
        self.assertEqual(p["taxes"], [])
        self.assertEqual(erp_book(p)["will_book_gross"], 29253.72)

    def test_no_invented_values(self):
        p, _ = build_payable(INV01, MD)
        p["line_items"][0]["unit_price"] = "74.00"
        self.assertTrue(any("unit_price" in b for b in grounding_check(p, INV01)))

    def test_not_footing_is_flagged_not_forced(self):
        text = "Invoice No: A1234\nDescription Qty Unit Price Amount\nWidget 2 10.00 20.00\nTotal 99.00\n"
        p, rep = build_payable(text, MD)
        self.assertEqual(rep.status, "not_footing")
        self.assertEqual(p["gross_total"], "99.00")            # printed value kept, nothing balanced
        self.assertEqual(len(p["line_items"]), 1)

    def test_credit_memo_positive_magnitudes(self):
        text = ("Credit Note No.: 5900366703\nDescription Qty Unit Price Amount\nWidget 2 -10.00 -20.00\n"
                "Total Amount EUR -20.00\n")
        p, _ = build_payable(text, MD, label="CREDIT_MEMO")
        self.assertEqual(p["invoice_type"], "CREDIT_MEMO")
        self.assertEqual(p["gross_total"], "20.00")
        self.assertEqual(p["line_items"][0]["unit_price"], "10.00")

    def test_garbage_does_not_crash(self):
        p, rep = build_payable("%%%% ???\n\n 12", MD)
        self.assertEqual(p["line_items"], [])
        self.assertIn(rep.status, ("review", "not_footing"))


class OutputContract(unittest.TestCase):
    """If output/ exists (after `python -m bookable.phase3`), every file obeys the contract."""

    TOP = {"invoice_number", "invoice_date", "due_date", "invoice_type", "currency", "supplier", "buyer",
           "payment_term_id", "po_number", "po_id", "gross_total", "subtotal", "total_tax_amount",
           "discount_amount", "freight_charges", "insurance_charges", "extra_charges", "excise_duties",
           "taxes", "line_items"}

    def test_every_output_file(self):
        out = ROOT / "output"
        files = sorted(out.glob("*.json")) if out.is_dir() else []
        if not files:
            self.skipTest("no output/ yet")
        sup = {s["supplier_id"] for s in MD.suppliers}
        taxes = {t["code"] for t in MD.taxes}
        terms = {t["payment_term_id"] for t in MD.terms}
        pos = {p["po_id"] for p in MD.pos}
        for f in files:
            d = json.loads(f.read_text(encoding="utf-8"))
            self.assertEqual(set(d), {"file", "payables", "declined"}, f.name)
            self.assertEqual(d["file"], f.stem + ".pdf")
            for p in d["payables"]:
                self.assertTrue(self.TOP <= set(p), f.name)
                self.assertIn(p["invoice_type"], ("INVOICE", "CREDIT_MEMO"))
                self.assertIn(p["supplier"]["supplier_id"], sup | {""})
                self.assertIn(p["payment_term_id"], terms | {""})
                self.assertIn(p["po_id"], pos | {""})
                for k in ("gross_total", "subtotal", "total_tax_amount"):
                    if p[k]:
                        self.assertEqual(num(p[k]), float(Decimal(p[k])), f"{f.name} {k} not plain dot-decimal")
                for li in p["line_items"]:
                    for k in ("quantity", "unit_price", "total"):
                        self.assertEqual(num(li[k]), float(Decimal(li[k])), f"{f.name} line {k}")
                    for t in li["taxes"]:
                        self.assertIn(t["tax_type_code"], taxes | {""})
                for t in p["taxes"]:
                    self.assertIn(t["tax_type_code"], taxes | {""})
                erp_book(p)                                  # must not raise


if __name__ == "__main__":
    unittest.main(verbosity=2)
