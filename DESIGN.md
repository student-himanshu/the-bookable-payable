# DESIGN

## 1. What I understood about these documents that I did not on day one
A document is not a record to copy; it is a set of printed *parts* that a machine (`erp.py`) must be able to rebuild
into what is owed. On day one I treated "extract the fields" as the task. The shift was to treat the ERP recompute as
the judge: a record is only as good as the gross it reproduces *from the parts I emit*. That turned many "different"
failures into one question: where does each printed tax/charge/discount live, and does the ERP's formula (header taxes
on the net of lines, line taxes on the line, charges added outside the tax base) land on the printed total from those
parts? Concretely I learned: (a) `erp.num()` silently zeroes any non-dot-decimal text, so number formatting is a
correctness issue, not cosmetics; (b) quantity x price is commutative, so arithmetic alone cannot say which printed
number is the quantity; (c) several documents print tax-inclusive prices while the ERP needs net prices; (d) the page
count of a PDF says little about the number of payables (DU-02: 20 pages, one invoice number, restarting page counters).

## 2. What the system does with a document unlike any it has seen
It never extrapolates a layout. Each step is gated by an independent fact printed on the page:
- A line is accepted as an item only if quantity x unit price (less discount %) equals its printed total to the cent.
  Lines that fail are reported, not coerced.
- Where a tax goes (line vs header, derived vs printed amount, printed charges or not) is chosen among a few candidate
  structures by asking the ERP which one reproduces the printed gross. If none does, the most faithful structure is
  emitted and flagged `not_footing`; no figure is adjusted to balance it.
- Every emitted number is checked to appear on the document; every master-data code is a real match (VAT id, IBAN,
  e-mail, or >=80% token coverage with at least two tokens; tax by rate+country; an ambiguous match stays blank).
- Optional vision rescue (Gemini/Claude) only *reads* the page; we re-format the numbers, recompute all codes
  ourselves, and accept the result only if the ERP gross equals the printed gross and prices are not tax-inclusive.
This generalises because the acceptance test is the document's own arithmetic, not a vendor-specific rule. The cost is
recall: unfamiliar documents mostly end as flagged or blank, which I consider the honest failure mode.

## 3. A document that cannot be solved the way the others were
INV-01 (Rechnung 852566): the shipped `sample_autodraft.json` names the supplier "Phocus Direct Communication GmbH" and
number 265345, but page 1 prints neither a supplier name nor that number (the VAT id line is garbled by OCR). The
supplier code cannot be recovered from the page without guessing, so my output leaves `supplier_id` blank; I treat the
sample as illustrative, not ground truth. (I looked at page 1 only; I did not rule out a hidden letterhead.) Related
unsolved class: tax-inclusive price documents - the net unit price is not printed, so deriving it would put a number
on the record that is not on the document. These are flagged rather than faked.

## Honest status
Rules-only, 12 of 39 payables foot to the printed gross on the open set; that is not proof the other fields are right.
The vision stage has unit tests with a fake model but has not been measured end-to-end on the real documents by me.
No held-back results are known, so I cannot quantify the open-vs-held-back distance.
