"""Header-level field extraction from the text of ONE payable segment.

Everything returned is a substring-derived value from the document (grounded). Anything not
found is None / "" - never invented. Labels are multilingual (en, de, et, pt, es, fr, tr, ms, nl).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from .master import fold
from .numbers import NUM_RE, PCT_RE, doc_decimal_hint, find_dates, parse_amount

ISO_CCY = ["EUR", "USD", "GBP", "ZAR", "GHS", "KES", "MYR", "CHF", "DKK", "SEK", "NOK", "PLN", "CZK",
           "HUF", "RON", "TRY", "CAD", "AUD", "NZD", "INR", "AED", "NGN", "BRL", "JPY", "CNY", "SGD"]
SYMBOL_CCY = {"€": "EUR", "£": "GBP", "RM": "MYR", "GH₵": "GHS", "₵": "GHS",
              "KSH": "KES", "KES": "KES", "R": "ZAR"}

INV_NO_LABELS = [
    r"(?:tax\s+)?invoice\s*(?:no\.?|number|nr\.?|#|num\.?)\s*[:#.\-]?\s*",
    r"rechnungs?\s*(?:nr\.?|nummer|no\.?)\s*[:.\-]?\s*",
    r"credit\s+(?:note|memo)\s*(?:no\.?|number|nr\.?|#)?\s*[:.\-]?\s*",
    r"gutschrift\s*(?:nr\.?|nummer)?\s*[:.\-]?\s*",
    r"(?:fatura|factura|facture|arve|arve\s*nr\.?)\s*(?:no\.?|n[º°o]\.?|nr\.?|num\.?|numero|número)?\s*[:.\-]?\s*",
    r"document\s*(?:no\.?|number|nr\.?)\s*[:.\-]?\s*",
    r"\bno\.?\s*(?:da\s+)?(?:fatura|factura)\s*[:.\-]?\s*",
    r"inv(?:oice)?\s*#\s*",
]
INV_NO_VALUE = r"([A-Z0-9][A-Z0-9\-/._]{2,24})"

DATE_LABELS = [r"invoice\s*date", r"date\s+of\s+invoice", r"rechnungsdatum", r"datum", r"data\s*(?:da\s+)?(?:fatura|emiss\w+)?",
               r"fecha", r"arve\s*kuup\w+", r"kuup\w+", r"tarih", r"date", r"tax\s+point"]
DUE_LABELS = [r"due\s*date", r"payment\s+due", r"pay(?:able)?\s+(?:by|until)", r"fällig\w*", r"zahlbar\s+bis",
              r"zahlung\w*\s+bis", r"bis\s+(?:zum|spatestens)", r"vencimento", r"data\s+de\s+venc\w+",
              r"mäksetähtaeg|maksetahtaeg|tähtaeg|tahtaeg", r"vade\s+tarihi", r"fecha\s+de\s+venc\w+",
              r"échéance|echeance", r"betalingsfrist", r"begleichen\s+sie\s+den\s+betrag\s+bis(?:\s+zum)?",
              r"please\s+pay\s+by", r"pay\s+by"]

GROSS_PRIMARY = [r"kogusumma(?:\s*\(\w+\))?", r"arve\s+kokku(?:\s*\(\w+\))?", r"tasuda(?:\s*\(\w+\))?", r"summa\s+koos\s+k\w+",
                 r"total\s+da\s+factura", r"total\s+inc\w*(?:\s+(?:gst|vat|sst|iva))?", r"total\s+tax\s+inclusive\s+value",
                 r"total\s+a\s+pagar", r"grand\s+total(?:\s+\(including\s+vat\))?", r"total\s+due", r"endbetrag", r"gesamtbetrag", r"rechnungsbetrag", r"invoice\s+total", r"total\s+invoice",
                 r"total\s+amount", r"total\s+gross", r"total\s+due", r"grand\s+total", r"gross\s+(?:amount|total)",
                 r"total\s+a\s+pagar", r"total\s+geral", r"brutto(?:betrag|summe)?", r"kokku\s+tasuda", r"total\s+(?:incl|inc)\w*",
                 r"total\s+[A-Z]{3}\b", r"summa\s+kokku", r"amount\s+payable", r"^total\b", r"total\s+a\s+pay\w+"]
GROSS_SECONDARY = [r"total\s+current\s+charges", r"total\s*(?:\$|\u20ac|\u00a3|[A-Z]{3})", r"amount\s+due", r"balance\s+due", r"zu\s+zahlen", r"zahlbetrag", r"to\s+pay", r"payable",
                   r"gesamtsumme", r"total\s*:"]
SUBTOTAL_LABELS = [r"sub\s?-?\s?total", r"zwischensumme", r"net\s+(?:amount|total|value)", r"total\s+net", r"nettosumme",
                   r"netto(?:betrag)?", r"gesamt(?:summe)?\s+netto", r"neto", r"valor\s+líquido", r"kokku\s+km-ta",
                   r"total\s+excl\w*", r"subtotal"]
TAX_TOTAL_LABELS = [r"total\s+(?:vat|tax|iva)", r"(?:vat|tax|iva|mwst|ust)\s+total", r"total\s+mwst", r"summe\s+mwst",
                    r"km\s+kokku", r"tax\s+amount", r"vat\s+amount"]
CHARGE_LABELS = {
    "discount_amount": [r"discount", r"rabatt", r"desconto", r"allahindlus", r"skonto", r"remise"],
    "freight_charges": [r"freight", r"shipping", r"versand\w*", r"frete", r"delivery\s+charge", r"transport\w*", r"postage"],
    "insurance_charges": [r"insurance", r"versicherung", r"seguro"],
    "excise_duties": [r"excise", r"verbrauchsteuer"],
    "extra_charges": [r"surcharge", r"handling", r"bearbeitungsgeb\w+", r"fuel\s+surcharge", r"admin\w*\s+fee"],
}
PO_LABELS = [r"p\.?\s?o\.?\s*(?:number|no\.?|nr\.?|#)?", r"purchase\s+order(?:\s+(?:no\.?|number))?",
             r"bestell\w*(?:\s*(?:nr\.?|nummer))?", r"your\s+order(?:\s+(?:no\.?|number|ref\w*))?",
             r"order\s+(?:no\.?|number)", r"ordem\s+de\s+compra", r"tellimus\w*"]
TERMS_RE = re.compile(r"(?:payment\s+terms?|terms\s+of\s+payment|zahlungsbedingung\w*|zahlungsziel|zahlbar|"
                      r"condi\w+\s+de\s+pagamento|maksetingimus\w*|terms)\s*[:\-]?\s*([^\n]{3,80})", re.I)
VAT_RE = re.compile(r"(?<![A-Z0-9])((?:AT|BE|BG|CY|CZ|DE|DK|EE|EL|ES|FI|FR|GB|HR|HU|IE|IT|LT|LU|LV|MT|NL|PL|PT|RO|SE|SI|SK|CH|NO)"
                    r"\s?[0-9A-Z][0-9A-Z \-]{6,13}[0-9A-Z])(?![A-Z0-9])")
LEGAL = re.compile(r"\b(gmbh|ou|oü|oy|ag|ltd|limited|llc|inc|plc|pty|cc|sdn\.?\s*bhd|lda|ltda|s\.?a\.?|s\.?l\.?|as|ab|bv|"
                   r"nv|corp|kg|ug|co\.|keskus|consult|services|distribution)\b", re.I)
BUYER_MARK = re.compile(r"northwind|bolt\s|bill\s*to|invoice\s*to|sold\s*to|deliver\s*to|ship\s*to|attention|herrn|frau", re.I)


@dataclass
class Header:
    invoice_number: str = ""
    invoice_date: str = ""
    due_date: str = ""
    currency: str = ""
    po_number: str = ""
    payment_terms_text: str = ""
    supplier_name: str = ""
    vat_ids: list = field(default_factory=list)
    gross: Optional[Decimal] = None
    gross_label: str = ""
    gross_candidates: list = field(default_factory=list)      # [(Decimal, label)]
    subtotal: Optional[Decimal] = None
    total_tax: Optional[Decimal] = None
    charges: dict = field(default_factory=dict)               # field -> Decimal
    tax_lines: list = field(default_factory=list)             # [{rate, amount, name, line}]
    negative_total: bool = False
    notes: list = field(default_factory=list)


def lines_of(text: str) -> list:
    return [re.sub(r"[ \t]{2,}", "  ", ln).strip() for ln in text.splitlines() if ln.strip()]


_SPACE_THOUSANDS = re.compile(r"(?<![\d.,])(\d{1,3}) (\d{3}[.,]\d{2})(?!\d)")


def _amounts(line: str, hint: str) -> list:
    line = _SPACE_THOUSANDS.sub(r"\1\2", PCT_RE.sub(" ", line))
    out = []
    for m in NUM_RE.finditer(line):
        v = parse_amount(m.group(0), hint)
        if v is not None:
            out.append((m.start(), m.group(0), v))
    return out


def labelled_amount(lines: list, patterns: list, hint: str, *, exclude: Optional[re.Pattern] = None,
                    last: bool = True) -> Optional[tuple]:
    """First/last line matching any label with a money-looking number on it (or on the next line)."""
    rx = re.compile("(?:" + "|".join(patterns) + ")", re.I)
    hits = []
    for i, ln in enumerate(lines):
        m = rx.search(ln)
        if not m or (exclude and exclude.search(ln)):
            continue
        tail = ln[m.end():]
        am = [a for a in _amounts(tail, hint) if re.search(r"[.,]\d{2}\b|^\d+$", a[1])]
        if not am and i + 1 < len(lines) and not rx.search(lines[i + 1]):
            am = [a for a in _amounts(lines[i + 1], hint) if re.search(r"[.,]\d{2}\b", a[1])]
        if am:
            hits.append((am[-1][2], ln, i))
    if not hits:
        return None
    return hits[-1] if last else hits[0]


def labelled_amounts_all(lines: list, patterns: list, hint: str, *, exclude: Optional[re.Pattern] = None,
                         keep: Optional[re.Pattern] = None) -> list:
    """Every (value, line) whose label matches; `exclude` is ignored on lines that match `keep`."""
    rx = re.compile("(?:" + "|".join(patterns) + ")", re.I)
    hits = []
    for i, ln in enumerate(lines):
        m = rx.search(ln)
        if not m:
            continue
        if exclude and exclude.search(ln) and not (keep and keep.search(ln)):
            continue
        am = [a for a in _amounts(ln[m.end():], hint) if re.search(r"[.,]\d{2}\b", a[1])]
        if not am and i + 1 < len(lines) and not rx.search(lines[i + 1]):
            am = [a for a in _amounts(lines[i + 1], hint) if re.search(r"[.,]\d{2}\b", a[1])]
        if am:
            hits.append((am[-1][2], ln))
    return hits


def extract_currency(text: str) -> str:
    up = text.upper()
    counts = {c: len(re.findall(r"(?<![A-Z])" + c + r"(?![A-Z])", up)) for c in ISO_CCY}
    best = max(counts, key=counts.get)
    if counts[best]:
        return best
    for sym, c in SYMBOL_CCY.items():
        if sym in text and sym not in ("R",):
            return c
    if "$" in text:
        return ""                    # $ is USD/CAD/AUD/...: ambiguous, leave blank
    if re.search(r"(?<![A-Za-z])R\s?\d[\d, ]*\.\d{2}", text):
        return "ZAR"
    return ""


def extract_header(text: str, *, doc_ids: Optional[list] = None, label: str = "INVOICE",
                   buyer_hint: bool = True) -> Header:
    h = Header()
    lines = lines_of(text)
    hint = doc_decimal_hint(text)
    flat = "\n".join(lines)

    # --- invoice number
    for pat in INV_NO_LABELS:
        m = re.search(r"(?i)" + pat + INV_NO_VALUE, flat)
        if m and re.search(r"\d", m.group(1)) and not re.fullmatch(r"(?i)date|datum|no|nr", m.group(1)):
            h.invoice_number = m.group(1).strip(".-/_")
            break
    if not h.invoice_number and doc_ids:
        h.invoice_number = doc_ids[0]
        h.notes.append("invoice_number taken from classifier doc_ids (no labelled field)")
    # --- dates (label-driven; unlabelled dates are not guessed)
    prefer = "mdy" if re.search(r"\b(?:Inc|LLC|USA|United States)\b", text) and not re.search(r"\d{1,2}\.\d{1,2}\.\d{4}", text) else "dmy"
    h.invoice_date = _labelled_date(lines, DATE_LABELS, prefer, h, "invoice_date", skip=DUE_LABELS)
    h.due_date = _labelled_date(lines, DUE_LABELS, prefer, h, "due_date")
    if not h.invoice_date:
        alld = find_dates(flat, prefer)
        if alld and not h.due_date:
            h.invoice_date = alld[0][0].isoformat()
            h.notes.append("invoice_date = first date on page (no label)" + (" [ambiguous d/m]" if alld[0][1] else ""))
    # --- currency / totals
    h.currency = extract_currency(text)
    neg = re.compile(r"\b(?:vat|tax|mwst|ust|iva|km|sub\s?total|net|discount|rabatt|excl|less|credit)\w*", re.I)
    keep = re.compile(r"incl|inclusive|koos|km-ga|c/\s?iva|brutto|grand|total\s+(?:amount|due|tax)", re.I)
    seen_vals = set()
    for pri, pats in enumerate((GROSS_PRIMARY, GROSS_SECONDARY)):
        for v, ln in reversed(labelled_amounts_all(lines, pats, hint, exclude=neg, keep=keep)):
            if v not in seen_vals:
                seen_vals.add(v)
                h.gross_candidates.append((v, ln, pri))
    if h.gross_candidates:
        h.gross, h.gross_label = h.gross_candidates[0][0], h.gross_candidates[0][1]
    sub = labelled_amount(lines, SUBTOTAL_LABELS, hint)
    h.subtotal = sub[0] if sub else None
    tt = labelled_amount(lines, TAX_TOTAL_LABELS, hint)
    h.total_tax = tt[0] if tt else None
    if h.gross is not None and h.gross < 0:
        h.negative_total = True
    # --- charges (header level)
    for fld, pats in CHARGE_LABELS.items():
        got = labelled_amount([ln for ln in lines if not re.search(r"\d\s*%.*discount", ln, re.I)], pats, hint)
        if got and got[0] != 0:
            h.charges[fld] = abs(got[0])
    # --- tax summary lines
    h.tax_lines = _tax_lines(lines, hint)
    # --- PO / terms / vat ids / supplier name
    h.po_number = _po(flat)
    tm = TERMS_RE.search(flat)
    h.payment_terms_text = tm.group(0).strip() if tm else ""
    seen = []
    for m in VAT_RE.finditer(flat.upper()):
        v = re.sub(r"[\s\-]", "", m.group(1))
        if v not in seen and re.search(r"\d{5}", v):
            seen.append(v)
    h.vat_ids = seen
    h.supplier_name = _supplier_name(lines)
    return h


def _labelled_date(lines, labels, prefer, h, name, skip=()):
    rx = re.compile("(?:" + "|".join(labels) + r")\s*[:.]?\s*", re.I)
    skiprx = re.compile("(?:" + "|".join(skip) + ")", re.I) if skip else None
    for i, ln in enumerate(lines):
        if skiprx and skiprx.search(ln):
            continue
        m = rx.search(ln)
        if not m:
            continue
        ds = find_dates(ln[m.end():], prefer) or (find_dates(lines[i + 1], prefer) if i + 1 < len(lines) and len(ln) < 40 else [])
        if ds:
            if ds[0][1]:
                h.notes.append(f"{name} ambiguous d/m vs m/d: read as {prefer}")
            return ds[0][0].isoformat()
    return ""


def _po(flat: str) -> str:
    for pat in PO_LABELS:
        m = re.search(r"(?i)(?<![A-Za-z])" + pat + r"\s*[:#.\-]?\s*((?=[A-Z0-9\-/]*\d)[A-Z0-9][A-Z0-9\-/]{3,24})", flat)
        if m:
            return m.group(1)
    return ""


def _tax_lines(lines: list, hint: str) -> list:
    out = []
    rx = re.compile(r"(?i)(vat|mwst|m\.w\.st|ust|iva|km|moms|tva|btw|gst|sst|nhil|getfund|levy|tax|steuer|maks)\b[^%\n]{0,30}?"
                    r"(\d{1,2}(?:[.,]\d{1,2})?)\s*%")
    for ln in lines:
        if re.search(r"(?i)^\s*(sub\s?total|total\s+net)", ln):
            continue
        m = rx.search(ln) or re.search(r"(?i)(\d{1,2}(?:[.,]\d{1,2})?)\s*%\s*(vat|mwst|ust|iva|km|moms|tva|gst)", ln)
        if not m:
            continue
        if m.re.pattern.startswith("(?i)(vat"):
            name, rate_s = m.group(1), m.group(2)
        else:
            rate_s, name = m.group(1), m.group(2)
        rate = parse_amount(rate_s, hint)
        after = ln[m.end():]
        am = [a for a in _amounts(after, hint) if re.search(r"[.,]\d{2}\b", a[1])]
        out.append({"rate": rate, "name": re.sub(r"\s+", " ", ln[:m.end()]).strip(), "label": name.upper(),
                    "amounts": [a[2] for a in am], "line": ln})
    return out


def _supplier_name(lines: list) -> str:
    """Best-effort printed supplier name: first head line with a legal-form word that is not
    obviously the buyer. Empty when unsure (master matching can still resolve the id)."""
    for ln in lines[:14]:
        if BUYER_MARK.search(ln):
            continue
        if LEGAL.search(ln) and len(ln) <= 80 and not re.search(r"\d{4,}", ln):
            return re.sub(r"\s+", " ", ln).strip()
    return ""
