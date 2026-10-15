"""Vision/LLM rescue for payables the rule-based builder could not foot.

The model only READS the page images (raw components, as printed). Everything that decides
correctness stays deterministic and in our hands:

* numbers are re-parsed and re-formatted by us (dot-decimal, plain strings);
* every master-data code is recomputed by `MasterData` - codes the model returns are discarded;
* acceptance gate: the ERP recompute (`erp.erp_book`) must equal the printed gross, otherwise the
  rescue is rejected and the rule-based record (with its flags) is kept. No fix is ever applied
  that the document's own arithmetic does not confirm.

Needs `pip install anthropic pypdfium2 pillow` and ANTHROPIC_API_KEY. Without them rescue is
simply unavailable (reported, never fatal). The client is injectable, so tests use a fake.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
from decimal import Decimal
from pathlib import Path
from typing import Optional

from erp import erp_book

from .build import _country, grounding_check
from .config import load_env
from .master import MasterData
from .numbers import fmt_amount, fmt_plain, fmt_price, parse_amount

load_env()
DEFAULT_MODEL = os.environ.get("BOOKABLE_MODEL", "")      # "" -> backend default
GEMINI_DEFAULT = "gemini-2.5-flash"                       # override with BOOKABLE_MODEL if Google renamed it
CLAUDE_DEFAULT = "claude-sonnet-5-5"

SYSTEM = """You read supplier documents for an accounting system. You transcribe what is PRINTED, nothing else.
Return ONE JSON object and no prose. Rules:
- Copy values exactly as printed; never compute, round, balance or infer a number. Unknown -> "".
- Numbers are plain dot-decimal strings without currency or thousands separators ("1234.56"; European "1.234,56" -> "1234.56").
- unit_price is the NET (tax-exclusive) unit price AS PRINTED. If the document prints only tax-inclusive prices, copy them and set "prices_include_tax": true.
- Put each tax where the document puts it: a rate printed per line goes in that line's "taxes"; one tax stated once for the whole document goes in header "taxes". A document with three line rates yields three line-level taxes.
- Credit notes: invoice_type "CREDIT_MEMO" with POSITIVE magnitudes.
- gross_total is the amount the document says is owed (total incl. tax, before any 'amount paid/credited' deductions unless that is the stated payable).
- Do not output master-data codes. Keys: invoice_number, invoice_date (YYYY-MM-DD), due_date, invoice_type, currency (ISO),
  supplier{name,address,vat_id}, po_number, payment_terms_text, gross_total, subtotal, total_tax_amount, discount_amount,
  freight_charges, insurance_charges, extra_charges, excise_duties, prices_include_tax,
  taxes[{tax_type,tax_name,tax_rate,tax_amount}],
  line_items[{description,item_type(GOODS|SERVICE|FREIGHT|TAX),uom,quantity,unit_price,total,discount,discount_percentage,
              tax_rate,tax_amount,taxes[{tax_type,tax_name,tax_rate,tax_amount}]}]."""

MONEY = ("gross_total", "subtotal", "total_tax_amount", "discount_amount", "freight_charges",
         "insurance_charges", "extra_charges", "excise_duties")
TAX_KEYS = ("tax_type", "tax_name", "tax_rate", "tax_amount")


# ------------------------------------------------------------------ plumbing
def render_pages(pdf: Path, pages: list, dpi: int = 150) -> list:
    """-> list of base64 PNG strings for the given 1-based pages."""
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(pdf))
    out = []
    try:
        for n in pages:
            img = doc[n - 1].render(scale=dpi / 72.0).to_pil().convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            out.append(base64.b64encode(buf.getvalue()).decode())
    finally:
        doc.close()
    return out


class GeminiBackend:
    """google-genai SDK (`pip install google-genai`). Key from GEMINI_API_KEY or GOOGLE_API_KEY."""
    name, default_model = "gemini", GEMINI_DEFAULT

    def __init__(self, client=None, api_key: str = ""):
        if client is None:
            from google import genai
            client = genai.Client(api_key=api_key)
        self.client = client

    def generate(self, images: list, text: str, model: str) -> str:
        from google.genai import types
        parts = [types.Part.from_bytes(data=base64.b64decode(b), mime_type="image/png") for b in images]
        parts.append(text)
        cfg = types.GenerateContentConfig(system_instruction=SYSTEM, temperature=0,
                                          response_mime_type="application/json")
        resp = self.client.models.generate_content(model=model or self.default_model, contents=parts, config=cfg)
        return getattr(resp, "text", "") or ""


class ClaudeBackend:
    name, default_model = "claude", CLAUDE_DEFAULT

    def __init__(self, client):
        self.client = client

    def generate(self, images: list, text: str, model: str) -> str:
        content = [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b}}
                   for b in images] + [{"type": "text", "text": text}]
        resp = self.client.messages.create(model=model or self.default_model, max_tokens=8000, temperature=0,
                                           system=SYSTEM, messages=[{"role": "user", "content": content}])
        return "".join(getattr(b, "text", "") for b in resp.content)


def make_client(provider: str = ""):
    """Backend for the first available key (Gemini, then Claude), or None. `provider` forces one."""
    gem = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if provider in ("", "gemini") and gem:
        try:
            return GeminiBackend(api_key=gem)
        except Exception:
            if provider == "gemini":
                return None
    if provider in ("", "claude", "anthropic") and os.environ.get("ANTHROPIC_API_KEY"):
        try:
            import anthropic
            return ClaudeBackend(anthropic.Anthropic())
        except Exception:
            return None
    return None


def call_model(client, images: list, ocr_text: str, model: str = DEFAULT_MODEL) -> str:
    text = ("OCR text of the same pages (may be wrong; the images are authoritative):\n"
            + ocr_text[:6000] + "\n\nReturn the JSON object.")
    if hasattr(client, "generate"):
        return client.generate(images, text, model)
    return ClaudeBackend(client).generate(images, text, model)      # bare Anthropic-style client


def parse_json(s: str) -> Optional[dict]:
    """Tolerant JSON extraction (code fences, leading prose). None if nothing parses."""
    if not s:
        return None
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", s, re.S)
    cand = m.group(1) if m else s[s.find("{"): s.rfind("}") + 1]
    try:
        d = json.loads(cand)
        return d if isinstance(d, dict) else None
    except Exception:
        return None


# ------------------------------------------------------------------ normalise (we own the numbers)
def _num(v, price=False, plain=False) -> str:
    if v in ("", None):
        return ""
    d = parse_amount(str(v), ".") if not isinstance(v, (int, float)) else Decimal(str(v))
    if d is None:
        return ""
    return fmt_price(abs(d)) if price else fmt_plain(abs(d)) if plain else fmt_amount(abs(d))


def _tax(md: MasterData, t: dict, country: str) -> dict:
    t = t or {}
    rate = _num(t.get("tax_rate"), plain=True)
    code = md.match_tax(float(rate), str(t.get("tax_name") or ""), country).code if rate != "" else ""
    out = {"tax_type": str(t.get("tax_type") or "VAT"), "tax_name": str(t.get("tax_name") or ""),
           "tax_rate": rate, "tax_amount": _num(t.get("tax_amount")), "tax_type_code": code}
    if str(t.get("tax_amount") or "").strip().startswith("-"):        # withholding stays negative
        out["tax_amount"] = "-" + out["tax_amount"]
    return out


def normalise(raw: dict, md: MasterData, ocr_text: str) -> dict:
    """Model output -> schema-conformant payable with OUR number formatting and OUR codes."""
    sup_raw = raw.get("supplier") or {}
    name = str(sup_raw.get("name") or "")
    sup = md.match_supplier(ocr_text + "\n" + name + "\n" + str(sup_raw.get("vat_id") or ""), name)
    vat_ids = [re.sub(r"[\s\-]", "", str(sup_raw.get("vat_id") or ""))] if sup_raw.get("vat_id") else []
    country = _country(md, sup.record, [v.upper() for v in vat_ids])
    term = md.match_terms(str(raw.get("payment_terms_text") or ""), None)
    inv_date, due = str(raw.get("invoice_date") or ""), str(raw.get("due_date") or "")
    if not term.code and re.fullmatch(r"\d{4}-\d\d-\d\d", inv_date) and re.fullmatch(r"\d{4}-\d\d-\d\d", due):
        from datetime import date
        term = md.match_terms("", (date.fromisoformat(due) - date.fromisoformat(inv_date)).days)
    po_no = str(raw.get("po_number") or "")
    po = md.match_po(po_no, sup.code)
    buyer = md.match_buyer(ocr_text)
    p = {
        "invoice_number": str(raw.get("invoice_number") or ""), "invoice_date": inv_date, "due_date": due,
        "invoice_type": "CREDIT_MEMO" if str(raw.get("invoice_type")).upper() == "CREDIT_MEMO" else "INVOICE",
        "currency": str(raw.get("currency") or "").upper()[:3],
        "supplier": {"name": name, "supplier_id": sup.code, "address": str(sup_raw.get("address") or ""),
                     "vat_id": str(sup_raw.get("vat_id") or "")},
        "buyer": dict(buyer.record) if buyer.code and buyer.record else
        {"company_code": "", "business_unit_code": "", "location_code": ""},
        "payment_term_id": term.code, "po_number": po_no, "po_id": po.code,
    }
    for k in MONEY:
        p[k] = _num(raw.get(k))
    p["taxes"] = [_tax(md, t, country) for t in (raw.get("taxes") or []) if isinstance(t, dict)]
    items = []
    for li in raw.get("line_items") or []:
        if not isinstance(li, dict):
            continue
        lt = [_tax(md, t, country) for t in (li.get("taxes") or []) if isinstance(t, dict)]
        rate = _num(li.get("tax_rate"), plain=True)
        if not lt and rate != "":
            lt = [_tax(md, {"tax_type": "VAT", "tax_name": f"VAT {rate}%", "tax_rate": rate,
                            "tax_amount": li.get("tax_amount")}, country)]
        itype = str(li.get("item_type") or "GOODS").upper()
        items.append({
            "description": str(li.get("description") or ""), "item_type": itype if itype in
            ("GOODS", "SERVICE", "FREIGHT", "TAX") else "GOODS", "uom": str(li.get("uom") or ""),
            "quantity": _num(li.get("quantity"), plain=True), "unit_price": _num(li.get("unit_price"), price=True),
            "total": _num(li.get("total")), "discount": _num(li.get("discount")),
            "discount_percentage": _num(li.get("discount_percentage"), plain=True),
            "tax_rate": rate if lt else "", "tax_amount": "" if lt else _num(li.get("tax_amount")), "taxes": lt})
    p["line_items"] = items
    return p


# ------------------------------------------------------------------ acceptance gate
def accept(p: dict, raw: dict) -> tuple:
    """-> (ok, reason). The ONLY thing that licenses replacing a rule-based record."""
    if raw.get("prices_include_tax"):
        return False, "model reports tax-inclusive prices: ERP needs net prices, not derivable from the page"
    if not p["line_items"]:
        return False, "no line items"
    if not p["gross_total"]:
        return False, "no printed gross"
    erp = Decimal(str(erp_book(p)["will_book_gross"]))
    if abs(erp - Decimal(p["gross_total"])) > Decimal("0.005"):
        return False, f"ERP gross {erp} != printed gross {p['gross_total']}"
    return True, "ERP recompute equals printed gross"


def rescue(pdf: Path, pages: list, ocr_text: str, md: MasterData, client, *, cache_dir: Optional[Path] = None,
           model: str = DEFAULT_MODEL) -> tuple:
    """-> (payable | None, info dict). Never raises."""
    info = {"attempted": True, "accepted": False, "reason": "", "ungrounded_vs_ocr": []}
    try:
        key = hashlib.sha256((Path(pdf).read_bytes() + str(pages).encode() + model.encode())).hexdigest()[:20]
        cache = Path(cache_dir) / f"{key}.json" if cache_dir else None
        text = None
        if cache and cache.exists():
            text = cache.read_text(encoding="utf-8")
        else:
            text = call_model(client, render_pages(Path(pdf), pages), ocr_text, model)
            if cache:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(text, encoding="utf-8")
        raw = parse_json(text)
        if raw is None:
            info["reason"] = "model output was not JSON"
            return None, info
        p = normalise(raw, md, ocr_text)
        ok, why = accept(p, raw)
        info.update(accepted=ok, reason=why, ungrounded_vs_ocr=grounding_check(p, ocr_text))
        return (p if ok else None), info
    except Exception as exc:
        info["reason"] = f"{type(exc).__name__}: {exc}"
        return None, info
