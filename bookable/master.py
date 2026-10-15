"""Master-data resolution with inverted indexes (no full scan per lookup).

Every resolver returns a `Match` whose `code` is "" when nothing genuinely matches. A weak
match is never promoted to a code: below the threshold the answer is an honest blank.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

LEGAL_SUFFIXES = {
    "gmbh", "ou", "oy", "ag", "ltd", "limited", "llc", "inc", "plc", "pty", "cc", "sdn", "bhd",
    "lda", "ltda", "sa", "sl", "as", "ab", "bv", "nv", "co", "corp", "kg", "ug", "se", "srl",
    "spa", "sas", "sarl", "the", "of", "and", "ja", "und", "e", "et", "de", "da", "do",
}


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).replace("ß", "ss").lower()
    return re.sub(r"\s+", " ", s)


def alnum(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", fold(s))


def name_tokens(s: str) -> list:
    return [t for t in re.findall(r"[a-z0-9]+", fold(s)) if t not in LEGAL_SUFFIXES and len(t) > 1]


@dataclass
class Match:
    code: str = ""
    method: str = ""
    score: float = 0.0
    record: Optional[dict] = None
    candidates: list = field(default_factory=list)


class MasterData:
    def __init__(self, directory: Path):
        d = Path(directory)

        def load(name, key):
            return json.loads((d / name).read_text(encoding="utf-8")).get(key, [])

        self.suppliers = load("suppliers.json", "suppliers")
        self.taxes = load("tax_master.json", "taxes")
        self.terms = load("payment_terms.json", "payment_terms")
        self.pos = load("po_master.json", "purchase_orders")
        self.companies = load("chart_of_books.json", "companies")
        self._index()

    # ------------------------------------------------------------------ indexes
    def _index(self):
        self.s_by_vat, self.s_by_iban, self.s_by_email, self.s_by_tok = {}, {}, {}, defaultdict(set)
        for i, s in enumerate(self.suppliers):
            if s.get("vat_id"):
                self.s_by_vat[alnum(s["vat_id"])] = i
            if s.get("bank_iban"):
                self.s_by_iban[alnum(s["bank_iban"])] = i
            if s.get("email") and "@" in s["email"]:
                self.s_by_email[s["email"].lower()] = i
            for t in set(name_tokens(s["name"])):
                self.s_by_tok[t].add(i)
        self.tax_by_rate = defaultdict(list)
        for t in self.taxes:
            self.tax_by_rate[float(t["rate"])].append(t)
        self.po_by_num = {alnum(p["po_number"]): p for p in self.pos}
        self.po_by_num.update({alnum(p["po_id"]): p for p in self.pos})
        self.locations = []          # (company, bu, loc, tokens, address-key)
        for c in self.companies:
            for bu in c.get("business_units", []):
                for loc in bu.get("locations", []):
                    self.locations.append((c, bu, loc))

    # ------------------------------------------------------------------ supplier
    def match_supplier(self, text: str, printed_name: str = "", exclude_vat: set = frozenset()) -> Match:
        """Strongest evidence first: bank IBAN, VAT id, e-mail, then name tokens (>=0.8 coverage)."""
        flat = alnum(text)
        for iban, i in self.s_by_iban.items():
            if iban in flat:
                return Match(self.suppliers[i]["supplier_id"], "iban", 1.0, self.suppliers[i])
        for vat, i in self.s_by_vat.items():
            if vat not in exclude_vat and len(vat) >= 6 and vat in flat:
                return Match(self.suppliers[i]["supplier_id"], "vat_id", 1.0, self.suppliers[i])
        low = text.lower()
        for em, i in self.s_by_email.items():
            if em in low:
                return Match(self.suppliers[i]["supplier_id"], "email", 0.95, self.suppliers[i])
        hay = set(re.findall(r"[a-z0-9]+", fold(printed_name + " " + text)))
        cands = defaultdict(int)
        for t in hay:
            for i in self.s_by_tok.get(t, ()):
                cands[i] += 1
        best, best_score = None, 0.0
        ranked = []
        for i, hits in cands.items():
            need = len(set(name_tokens(self.suppliers[i]["name"])))
            if not need:
                continue
            cov = hits / need
            ranked.append((cov, i))
            if cov > best_score:
                best, best_score = i, cov
        ranked.sort(reverse=True)
        cl = [(round(c, 2), self.suppliers[i]["supplier_id"]) for c, i in ranked[:3]]
        # a single distinctive token is not enough: need >=2 tokens (or the only token) at full coverage
        if best is not None and best_score >= 0.8:
            toks = set(name_tokens(self.suppliers[best]["name"]))
            if len(toks) >= 2 or best_score == 1.0:
                return Match(self.suppliers[best]["supplier_id"], "name", best_score,
                             self.suppliers[best], cl)
        return Match("", "", best_score, None, cl)

    # ------------------------------------------------------------------ tax
    def match_tax(self, rate, tax_name: str = "", country: str = "") -> Match:
        """Resolve a tax by rate, then disambiguate by country / type words. Ambiguity -> blank."""
        if rate is None or rate == "":
            return Match()
        try:
            r = float(rate)
        except (TypeError, ValueError):
            return Match()
        cands = list(self.tax_by_rate.get(r, []))
        if not cands:
            return Match()
        nm = fold(tax_name)
        if country:
            sub = [t for t in cands if t["country"] == country.upper()]
            if sub:
                cands = sub
        if len(cands) > 1:
            word_hit = [t for t in cands if fold(t["tax_type"]) in nm.split() or
                        (t["tax_type"] == "VAT" and re.search(r"\b(vat|mwst|ust|iva|km|moms|tva|btw)\b", nm))]
            if len(word_hit) >= 1:
                cands = word_hit
        if len(cands) > 1:
            rc = [t for t in cands if re.search(r"reverse|\brc\b", nm) == bool(re.search(r"_RC$", t["code"]))]
            if rc:
                cands = rc
        if len(cands) == 1:
            return Match(cands[0]["code"], "rate" + ("+country" if country else ""), 0.9, cands[0])
        return Match("", "ambiguous", 0.0, None, [t["code"] for t in cands])

    # ------------------------------------------------------------------ payment terms
    def match_terms(self, text: str, days: Optional[int] = None) -> Match:
        """Alias text first (longest alias wins), then an explicit day count printed as terms."""
        low = fold(text)
        best = None
        for t in self.terms:
            for al in t.get("text_aliases", []):
                if re.search(r"(?<![\w])" + re.escape(fold(al)) + r"(?![\w])", low):
                    if best is None or len(al) > best[0]:
                        best = (len(al), t)
        if best:
            return Match(best[1]["payment_term_id"], "alias", 1.0, best[1])
        if days is not None:
            for t in self.terms:
                if t["days"] == days:
                    return Match(t["payment_term_id"], "days", 0.8, t)
        return Match()

    # ------------------------------------------------------------------ PO
    def match_po(self, po_number: str, supplier_id: str = "") -> Match:
        if not po_number:
            return Match()
        p = self.po_by_num.get(alnum(po_number))
        if p and (not supplier_id or p.get("supplier_id") in ("", supplier_id)):
            return Match(p["po_id"], "po_number", 1.0, p)
        return Match()

    # ------------------------------------------------------------------ buyer
    def match_buyer(self, text: str) -> Match:
        """Match the tenant by printed business-unit name or invoice-to address. Else blank."""
        flat = alnum(text)
        hits = []
        for c, bu, loc in self.locations:
            nm = alnum(bu["business_unit_name"])
            addr = alnum(loc.get("invoice_to_address", ""))
            if nm and nm in flat:
                hits.append((2, c, bu, loc))
            elif addr and addr in flat:
                hits.append((1.5, c, bu, loc))
        if not hits:
            return Match()
        top = max(h[0] for h in hits)
        top_hits = [h for h in hits if h[0] == top]
        # an address shared by several business units cannot identify one of them: honest blank
        if len({(h[1]["company_code"], h[2]["business_unit_code"]) for h in top_hits}) != 1:
            return Match("", "ambiguous", 0.0, None,
                         [h[2]["business_unit_code"] for h in top_hits])
        _, c, bu, loc = top_hits[0]
        return Match(bu["business_unit_code"], "name" if top == 2 else "address", top / 2,
                     {"company_code": c["company_code"], "business_unit_code": bu["business_unit_code"],
                      "location_code": loc["location_code"]})
