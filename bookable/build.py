"""Assemble one schema-conformant payable from a segment's text, choosing the STRUCTURE that the
ERP recompute can foot to the printed total.

Principle (the "independent fact" that licenses any structural choice): every value emitted is
copied from the document; what we choose between is only *where* a printed tax goes (line vs
header, derived vs explicit amount) and whether printed header charges apply. The choice is
validated by `erp.erp_book` against the printed gross. If nothing foots, the most faithful
structure is emitted anyway and the record is flagged - no number is ever invented to balance it.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from erp import erp_book  # noqa: E402  (oracle: imported, never modified)

from .fields import Header, extract_header, lines_of
from .lines import Row, parse_rows
from .master import MasterData, alnum
from .numbers import NUM_RE, PCT_RE, find_dates, fmt_amount, fmt_plain, fmt_price, parse_amount, doc_decimal_hint

FREIGHT_RE = re.compile(r"\b(freight|shipping|versand|frete|transport|delivery\s+charge|postage)\b", re.I)
SERVICE_RE = re.compile(r"\b(service|services|consult\w*|fee|management|hours?|hrs?|std|stunden|projekt\w*|verification|"
                        r"license|licence|subscription|rent\w*|maintenance|support|audit|legal|training|tund)\b", re.I)
TAXWORD_TYPE = {"VAT": "VAT", "MWST": "VAT", "M.W.ST": "VAT", "UST": "VAT", "KM": "VAT", "MOMS": "VAT", "TVA": "VAT",
                "BTW": "VAT", "IVA": "IVA", "GST": "GST", "SST": "SST", "NHIL": "NHIL", "GETFUND": "GETFL",
                "LEVY": "LEVY", "TAX": "TAX", "STEUER": "TAX", "MAKS": "TAX"}
COUNTRY_BY_VAT_PREFIX = {"DE": "DE", "EE": "EE", "GB": "GB", "PT": "PT", "DK": "DK", "CH": "CH", "NL": "NL",
                         "ES": "ES", "FR": "FR", "IT": "IT", "SE": "SE", "NO": "NO", "PL": "PL"}
MONEY_FIELDS = ("gross_total", "subtotal", "total_tax_amount", "discount_amount", "freight_charges",
                "insurance_charges", "extra_charges", "excise_duties")


@dataclass
class BuildReport:
    status: str = "ok"                      # ok | review | not_footing
    flags: list = field(default_factory=list)
    structure: str = ""
    printed_gross: str = ""
    erp_gross: str = ""
    diff: str = ""
    supplier_match: str = ""
    ungrounded: list = field(default_factory=list)
    n_rows: int = 0


def _tax_obj(md: MasterData, rate: Optional[Decimal], name: str, label: str, country: str,
             amount: str = "") -> dict:
    code = md.match_tax(float(rate), name, country).code if rate is not None else ""
    return {"tax_type": TAXWORD_TYPE.get(label.upper(), "VAT" if label == "" else label.upper()),
            "tax_name": name, "tax_rate": fmt_plain(rate) if rate is not None else "",
            "tax_amount": amount, "tax_type_code": code}


def _item_type(r: Row) -> str:
    if FREIGHT_RE.search(r.description):
        return "FREIGHT"
    if re.fullmatch(r"(?i)h|hr|hrs|std|tund|saat|day|days|month|mth", r.uom or "") or SERVICE_RE.search(r.description):
        return "SERVICE"
    return "GOODS"


def _line_dict(r: Row, tax: Optional[dict], printed_rate_text: str) -> dict:
    d = {"description": r.description, "item_type": _item_type(r), "uom": r.uom,
         "quantity": fmt_plain(r.quantity), "unit_price": fmt_price(r.unit_price), "total": fmt_amount(r.total),
         "discount": "", "discount_percentage": fmt_plain(r.discount_pct) if r.discount_pct else "",
         "tax_rate": "", "tax_amount": "", "taxes": []}
    if tax is not None:
        d["tax_rate"] = tax["tax_rate"]
        d["taxes"] = [dict(tax)]
    return d


def _country(md: MasterData, supplier_rec: Optional[dict], vat_ids: list) -> str:
    if supplier_rec and supplier_rec.get("country"):
        return supplier_rec["country"]
    prefixes = {COUNTRY_BY_VAT_PREFIX.get(v[:2]) for v in vat_ids if v[:2] in COUNTRY_BY_VAT_PREFIX}
    prefixes.discard(None)
    return prefixes.pop() if len(prefixes) == 1 else ""


def build_payable(text: str, md: MasterData, *, label: str = "INVOICE", doc_ids: Optional[list] = None) -> tuple:
    """-> (payable dict, BuildReport). Never raises on unparseable content."""
    rep = BuildReport()
    lines = lines_of(text)
    hint = doc_decimal_hint(text)
    h: Header = extract_header(text, doc_ids=doc_ids, label=label)
    rep.flags += h.notes
    rows, unverified = parse_rows(lines, hint)
    rep.n_rows = len(rows)
    if unverified:
        rep.flags.append(f"{len(unverified)} numeric line(s) in the item table failed qty x price = total: {unverified[:3]}")

    sup = md.match_supplier(text, h.supplier_name)
    rep.supplier_match = f"{sup.method}:{sup.score:.2f}" if sup.code else (f"none (best {sup.score:.2f})" if sup.score else "none")
    country = _country(md, sup.record, h.vat_ids)
    vat_id = ""
    if sup.record and sup.record.get("vat_id") and alnum(sup.record["vat_id"]) in {alnum(v) for v in h.vat_ids}:
        vat_id = next(v for v in h.vat_ids if alnum(v) == alnum(sup.record["vat_id"]))
    elif len(h.vat_ids) == 1:
        vat_id = h.vat_ids[0]

    terms_days = None
    if h.invoice_date and h.due_date:
        from datetime import date
        terms_days = (date.fromisoformat(h.due_date) - date.fromisoformat(h.invoice_date)).days
    term = md.match_terms(h.payment_terms_text or "", None)
    if not term.code:
        term = md.match_terms("", terms_days)
    po = md.match_po(h.po_number, sup.code)
    buyer = md.match_buyer(text)

    # ---- tax objects from the printed summary
    def summary_taxes(explicit: bool) -> list:
        out, seen = [], set()
        for tl in h.tax_lines:
            if tl["rate"] is None or (tl["rate"], tl["line"]) in seen:
                continue
            seen.add((tl["rate"], tl["line"]))
            amt = ""
            if explicit and tl["amounts"]:
                amt = fmt_amount(abs(tl["amounts"][-1]))
            out.append(_tax_obj(md, tl["rate"], tl["name"], tl["label"], country, amt))
        return out

    def line_tax_for(r: Row) -> Optional[dict]:
        if r.tax_rate is None:
            return None
        nm = next((t["name"] for t in h.tax_lines if t["rate"] == r.tax_rate), "")
        lab = next((t["label"] for t in h.tax_lines if t["rate"] == r.tax_rate), "VAT")
        if not nm:
            nm = f"{lab} {fmt_plain(r.tax_rate)}%"
        return _tax_obj(md, r.tax_rate, nm, lab, country)

    base = {
        "invoice_number": h.invoice_number, "invoice_date": h.invoice_date, "due_date": h.due_date,
        "invoice_type": "CREDIT_MEMO" if label == "CREDIT_MEMO" else "INVOICE",
        "currency": h.currency,
        "supplier": {"name": h.supplier_name, "supplier_id": sup.code, "address": "", "vat_id": vat_id},
        "buyer": {"company_code": "", "business_unit_code": "", "location_code": ""},
        "payment_term_id": term.code, "po_number": h.po_number, "po_id": po.code,
        "gross_total": fmt_amount(abs(h.gross)) if h.gross is not None else "",
        "subtotal": fmt_amount(abs(h.subtotal)) if h.subtotal is not None else "",
        "total_tax_amount": fmt_amount(abs(h.total_tax)) if h.total_tax is not None else "",
        "discount_amount": "", "freight_charges": "", "insurance_charges": "", "extra_charges": "", "excise_duties": "",
        "taxes": [], "line_items": [],
    }
    if buyer.code and buyer.record:
        base["buyer"] = dict(buyer.record)

    row_has_rate = any(r.tax_rate is not None for r in rows)
    charge_sets = [{}]
    if h.charges:
        charge_sets.append({k: fmt_amount(v) for k, v in h.charges.items()})
    variants = []
    for cs in charge_sets:
        if row_has_rate:
            variants.append(("line-level taxes", cs, True, "none"))
        if h.tax_lines:
            variants.append(("header taxes (rate-derived)", cs, False, "derived"))
            variants.append(("header taxes (printed amounts)", cs, False, "explicit"))
        variants.append(("no taxes", cs, False, "none"))

    targets = [abs(v) for v, _, _ in h.gross_candidates]
    chosen, chosen_gross = None, None
    first = None
    for name, cs, line_level, hdr_mode in variants:
        p = _compose(base, rows, cs, line_level, hdr_mode, line_tax_for, summary_taxes)
        g = Decimal(str(erp_book(p)["will_book_gross"]))
        if first is None:
            first = (name, p, g)
        hit = next((t for t in targets if abs(g - t) <= Decimal("0.005")), None)
        if hit is not None and rows:
            p["gross_total"] = fmt_amount(hit)       # the printed total this structure foots to
            chosen, chosen_gross = (name, p), g
            break
    if chosen is None:
        name, p, g = first if first else ("no taxes", dict(base), Decimal(0))
        chosen, chosen_gross = (name, p), g
        if not rows:
            rep.flags.append("no item row passed the qty x unit price = total test; line_items left empty")
        if h.gross is None:
            rep.flags.append("no printed gross total found")
        else:
            rep.status = "not_footing"
            rep.diff = fmt_amount(chosen_gross - abs(h.gross))
            if rows and abs(sum(r.total for r in rows) - abs(h.gross)) <= Decimal("0.02") and h.tax_lines:
                rep.flags.append("line totals already equal the gross: unit prices are probably tax-INCLUSIVE "
                                 "(ERP expects net) - needs a net/gross decision (Phase 4)")
    payable = chosen[1]
    rep.structure = chosen[0]
    rep.printed_gross = payable["gross_total"]
    rep.erp_gross = fmt_amount(chosen_gross)
    for fld in ("invoice_number", "invoice_date", "currency"):
        if not payable[fld]:
            rep.flags.append(f"missing {fld}")
    if h.negative_total and label != "CREDIT_MEMO":
        rep.flags.append("negative total on a document classified as INVOICE: type needs review")
    if sup.record is None and sup.candidates and sup.score >= 0.5:
        rep.flags.append(f"supplier near-miss not accepted: {sup.candidates}")
    rep.ungrounded = grounding_check(payable, text)
    if rep.ungrounded:
        rep.flags.append(f"ungrounded values: {rep.ungrounded}")
    if rep.status == "ok" and (rep.flags):
        rep.status = "review"
    return payable, rep


def _compose(base: dict, rows: list, charges: dict, line_level: bool, hdr_mode: str, line_tax_for, summary_taxes) -> dict:
    p = {k: (dict(v) if isinstance(v, dict) else list(v) if isinstance(v, list) else v) for k, v in base.items()}
    p.update(charges)
    p["line_items"] = [_line_dict(r, line_tax_for(r) if line_level else None, "") for r in rows]
    if hdr_mode == "derived":
        p["taxes"] = summary_taxes(False)
    elif hdr_mode == "explicit":
        p["taxes"] = summary_taxes(True)
    return p


def grounding_check(payable: dict, text: str) -> list:
    """Every non-empty numeric value must be a number that is printed on the document."""
    seen = set()
    for hint in (".", ","):
        for m in NUM_RE.finditer(text):
            v = parse_amount(m.group(0), hint)
            if v is not None and abs(v) < Decimal("1e12"):
                seen.add(abs(v).quantize(Decimal("0.0001")))
        for m in PCT_RE.finditer(text):
            v = parse_amount(m.group(1), hint)
            if v is not None:
                seen.add(abs(v).quantize(Decimal("0.0001")))

    def ok(s) -> bool:
        if s in ("", None):
            return True
        try:
            d = abs(Decimal(str(s))).quantize(Decimal("0.0001"))
        except Exception:
            return False
        return d == 0 or d in seen

    bad = []
    for k in MONEY_FIELDS:
        if not ok(payable.get(k)):
            bad.append(f"{k}={payable.get(k)}")
    for i, li in enumerate(payable.get("line_items", []), 1):
        for k in ("quantity", "unit_price", "total", "discount", "discount_percentage", "tax_rate", "tax_amount"):
            if not ok(li.get(k)):
                bad.append(f"line{i}.{k}={li.get(k)}")
    for t in payable.get("taxes", []):
        for k in ("tax_rate", "tax_amount"):
            if not ok(t.get(k)):
                bad.append(f"tax.{k}={t.get(k)}")
    return bad
