"""Phase 2: page classification + segmentation. Pure text in, no OCR / PDFs required."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bookable.classify import (classify_page, doc_ids, mark_duplicates, normalise,  # noqa: E402
                               page_marker, segment_document)


def cp(text, page=1):
    return classify_page(text, page)


class PageClassification(unittest.TestCase):
    def test_german_invoice(self):
        p = cp("Rechnung\nRechnung Nr.: 852566\nGesamtsumme 438,00 EUR\nMwSt 0,00")
        self.assertEqual((p.label, p.confidence), ("INVOICE", "high"))
        self.assertIn("852566", p.doc_ids)

    def test_estonian_invoice_and_joined_label(self):
        self.assertEqual(cp("ARVE\nKuupaev 2025/06/06\nArve nr. EMK_2492").label, "INVOICE")
        self.assertEqual(cp("Arvenr.: 18533\nKuupaev: 25.03.2026").label, "INVOICE")

    def test_portuguese_invoice_title_at_line_start(self):
        self.assertEqual(cp("Fatura FN 05/80906935 Data 2026-06-15 Reference: REF-8414 Original").label, "INVOICE")

    def test_danish_split_word(self):
        self.assertEqual(cp("Kundenr. 197218 Faktu ra 3025139\nSide 1").label, "INVOICE")

    def test_letter_spaced_invoice(self):
        self.assertEqual(cp("TAX | N VO | C E 30 Apr 2025\nTotal 100.00").label, "INVOICE")

    def test_credit_note_beats_invoice_word(self):
        p = cp("Credit Note No.: 5900366703\nIn respect of Invoice No. 0394289238\nTotal 12.00")
        self.assertEqual(p.label, "CREDIT_MEMO")

    def test_estonian_credit_note(self):
        self.assertEqual(cp("Kreeditarve arvele nr. 6265\nArve kokku -400,00 EUR").label, "CREDIT_MEMO")

    def test_negative_total_on_untitled_invoice_is_flagged_not_trusted(self):
        text = ("Description Qty Price VAT Amount\nService 1 100.00 tax 100.00\nsubtotal -100.00\n"
                "Total Amount Due -100.00")
        p = cp(text)
        self.assertEqual(p.label, "CREDIT_MEMO")
        self.assertEqual(p.confidence, "low")
        self.assertIn("negative_total", p.qualifiers)

    def test_parenthesised_column_after_total_is_not_negative(self):
        p = cp("Invoice\nTotal (873.53 0.00 0.00 873.53 0.00")
        self.assertEqual(p.label, "INVOICE")
        self.assertNotIn("negative_total", p.qualifiers)

    def test_payment_reminder(self):
        p = cp("Mahnung\nBitte begleichen Sie den offenen Betrag")
        self.assertEqual((p.label, p.subtype), ("NON_PAYABLE", "payment_reminder"))

    def test_delivery_note_title(self):
        p = cp("Delivery note\nItem Qty\nWidget 4")
        self.assertEqual((p.label, p.subtype), ("SUPPORTING", "delivery_note"))

    def test_delivery_note_reference_inside_invoice_does_not_win(self):
        p = cp("Tax Invoice\nDelivery note: 8358769 from 30.06.2026\nTotal 100.00")
        self.assertEqual(p.label, "INVOICE")

    def test_order_reference_label_is_not_a_purchase_order(self):
        p = cp("Arve #9972-907\nTellimus #2287\nKokku 100,00")
        self.assertEqual(p.label, "INVOICE")

    def test_layout_columns_are_split(self):
        text = "200 Stevens Drive" + " " * 30 + "Purchase Order: 16299\nInvoice Date: 6/12/2018"
        self.assertEqual(cp(text).label, "INVOICE")

    def test_line_item_with_cargo_word_is_not_a_cargo_document(self):
        p = cp("Invoice 123456\n7 Cargo Agents Building Fee 1.000 EA USD 15.00 15.00\nTotal Amount Due 15.00")
        self.assertEqual(p.label, "INVOICE")

    def test_email_printout(self):
        p = cp("From: a@b.com\nSent: Wednesday, March 18, 2026\nTo: c@d.com\nSubject: FW: donations")
        self.assertEqual((p.label, p.subtype), ("NON_PAYABLE", "email"))

    def test_payment_advice(self):
        p = cp("PAYMENT ADVICE 9446690440 Maria Kask\nInvoice Number INV-75162461\nAmount Due 8,550.00")
        self.assertEqual((p.label, p.subtype), ("SUPPORTING", "payment_advice"))

    def test_shipping_vocabulary_without_title(self):
        p = cp("PORT OF LOADING: X\nPORT OF DISCHARGE: Y\nTOTAL GROSS WT/UNIT: 567 KGM\nVESSEL: Z")
        self.assertEqual(p.label, "SUPPORTING")

    def test_untitled_invoice_like_is_low_confidence(self):
        p = cp("Item Qty Price Amount\nMeals 60 90.00 5400.00\nVAT 15% 810.00\nTotal 6210.00")
        self.assertEqual((p.label, p.subtype, p.confidence), ("INVOICE", "untitled_invoice_like", "low"))

    def test_blank_and_garbage_are_unknown_not_payable(self):
        for t in ("", "   \n  ", "f+ [o0sof 0000] oro] xa | 10000]"):
            p = cp(t)
            self.assertEqual(p.label, "UNKNOWN", t)

    def test_tie_between_labels_refuses_to_guess(self):
        p = cp("Invoice\nDelivery note")   # equal-strength headlines
        self.assertEqual(p.label, "UNKNOWN")
        self.assertTrue(p.notes)

    def test_normalise_strips_accents(self):
        self.assertEqual(normalise("Rechnung \u00dcber FA\u00c7ADE"), "rechnung uber facade")


class Parsers(unittest.TestCase):
    def test_page_marker_variants(self):
        self.assertEqual(page_marker("Page 2 of 5"), (2, 5))
        self.assertEqual(page_marker("Seite 1 von 3"), (1, 3))
        self.assertEqual(page_marker("Lehekulgede arv: 1/2"), (1, 2))
        self.assertEqual(page_marker("N\u00ba 1 de 1"), (1, 1))
        self.assertIsNone(page_marker("no marker here 12/31/25"))

    def test_doc_ids(self):
        self.assertEqual(doc_ids("Invoice Number 554701215"), ["554701215"])
        self.assertIn("ADIPL/INV/070/17", doc_ids("Invoice No. : ADIPL/INV/070/17"))
        self.assertEqual(doc_ids("Invoice Date 01/06/2026"), [])


def pages(*texts):
    return [classify_page(t, i + 1) for i, t in enumerate(texts)]


class Segmentation(unittest.TestCase):
    INV_A = "Invoice\nInvoice No. A1001\nPage 1 of 1\nTotal 10.00"
    INV_B = "Invoice\nInvoice No. B2002\nPage 1 of 1\nTotal 20.00"

    def test_two_different_numbers_two_payables(self):
        segs = segment_document(pages(self.INV_A, self.INV_B))
        self.assertEqual([s.payable_candidate for s in segs], [True, True])
        self.assertEqual(segs[1].boundary_reason, "different document number")

    def test_continuation_page_attached(self):
        segs = segment_document(pages("Invoice\nInvoice No. A1001\nPage 1 of 2\nTotal 10.00",
                                      "Terms and conditions apply."))
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0].pages, [1, 2])
        self.assertTrue(any("untitled continuation" in r for r in segs[0].needs_review))

    def test_invoice_plus_supporting_page(self):
        segs = segment_document(pages(self.INV_A, "Delivery note\nWidget 4"))
        self.assertEqual([s.label for s in segs], ["INVOICE", "SUPPORTING"])
        self.assertEqual(sum(s.payable_candidate for s in segs), 1)

    def test_restart_with_same_number_stays_one_segment_and_is_flagged(self):
        segs = segment_document(pages("Invoice\nInvoice Number 554701\nPage 1 of 2\nTotal 1.00",
                                      "Invoice\nInvoice Number 554701\nPage 1 of 1\nTotal 2.00"))
        self.assertEqual(len(segs), 1)
        self.assertTrue(any("restarted" in r for r in segs[0].needs_review))

    def test_restart_without_numbers_splits(self):
        segs = segment_document(pages("Invoice\nPage 1 of 1\nTotal 1.00", "Invoice\nPage 1 of 1\nTotal 2.00"))
        self.assertEqual(len(segs), 2)

    def test_untitled_invoice_then_customs_printout_splits(self):
        segs = segment_document(pages("Item Qty Price Amount\nMeals 6 9.00 54.00\nVAT 15% 8.10\nTotal 62.10",
                                      "ICUMS Duty Calculator\nCustoms declaration"))
        self.assertEqual([s.label for s in segs], ["INVOICE", "SUPPORTING"])

    def test_supporting_subtype_change_splits(self):
        segs = segment_document(pages("Delivery note\nA 1", "Payment advice\nAmount Due 5.00"))
        self.assertEqual(len(segs), 2)

    def test_all_unknown_is_not_payable(self):
        segs = segment_document(pages("", "zzz"))
        self.assertFalse(any(s.payable_candidate for s in segs))
        self.assertTrue(segs[0].needs_review)

    def test_low_ocr_confidence_is_flagged(self):
        pcs = pages(self.INV_A)
        segs = segment_document(pcs, ocr_conf={1: 41.0})
        self.assertTrue(any("low OCR confidence" in r for r in segs[0].needs_review))


class DuplicateDetection(unittest.TestCase):
    ORIG = "FAC A98/712 Original\nTotal 1 234.56 on 12/06/2026 ref 4455 6677\nInvoice"
    DUP = "FAC A98/712 Duplicado\nTotal 1 234.56 on 12/06/2026 ref 4455 6677\nInvoice"

    def _run(self, a, b):
        pcs = pages(a, b)
        # force two segments (copy detection works on segments)
        segs = segment_document(pcs)
        if len(segs) == 1:
            segs = segment_document(pcs[:1]) + segment_document(pcs[1:])
            segs[1].index = 2
        mark_duplicates(segs, {1: a, 2: b}, pcs)
        return segs

    def test_marked_copy_with_matching_numbers_is_not_a_second_payable(self):
        segs = self._run(self.ORIG, self.DUP)
        self.assertTrue(segs[0].payable_candidate)
        self.assertFalse(segs[1].payable_candidate)
        self.assertEqual(segs[1].subtype, "duplicate_copy")

    def test_copy_marker_without_numeric_match_stays_payable(self):
        other = "Invoice\nDuplicado\nTotal 999.99 on 01/01/2020 ref 1111 2222"
        segs = self._run(self.ORIG, other)
        self.assertTrue(segs[1].payable_candidate)
        self.assertTrue(any("no earlier matching" in r for r in segs[1].needs_review))

    def test_matching_numbers_without_copy_marker_stay_separate_payables(self):
        same = "Invoice\nTotal 1 234.56 on 12/06/2026 ref 4455 6677"
        segs = self._run(self.ORIG, same)
        self.assertTrue(segs[1].payable_candidate)


if __name__ == "__main__":
    unittest.main(verbosity=2)
