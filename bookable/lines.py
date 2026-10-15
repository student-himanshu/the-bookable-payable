"""Line-item row detection by arithmetic consistency.

A text line is accepted as an item row only when numbers on it satisfy
`quantity x unit_price (less discount %) = line total` to the cent. That is an independent fact
about the document, so it works across layouts and languages without per-vendor rules.
Rows that cannot be verified this way are NOT emitted as items; the caller flags them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from itertools import combinations
from typing import Optional

from .numbers import NUM_RE, PCT_RE, DATE_PATTERNS, parse_amount

TOTALS_START = re.compile(
    r"^\W*(sub\s?-?\s?total|total|gesamt|zwischensumme|summe|netto|net\s+(amount|total|value)|"
    r"amount\s+due|invoice\s+total|endbetrag|vat\b|mwst|zzgl|tax\b|iva\b|kokku|km\b|"
    r"less\b|balance|freight|shipping|versand|discount|rabatt|payment\s+terms)", re.I)
TABLE_HEADER = re.compile(
    r"\b(description|beschreibung|bezeichnung|descri\w+|item|artikel|produto|kirjeldus|"
    r"quantity|qty|menge|quantidade|kogus|aciklama|tanim|miktar|deskripsi)\b", re.I)
UOM_RE = re.compile(r"\b(std|stk|stck|st|pcs|pc|ea|hr|hrs|h|kg|g|l|lt|m|m2|m3|box|lot|unit|units|"
                    r"mth|month|day|days|tk|tund|un|ud|adet|saat)\b\.?", re.I)
NOVAT = re.compile(r"\b(no\s+vat|exempt|zero[- ]rated|reverse\s+charge|0\s*%)\b", re.I)
TOL = Decimal("0.0151")


@dataclass
class Row:
    line_no: int
    description: str
    quantity: Decimal
    unit_price: Decimal
    total: Decimal
    discount_pct: Optional[Decimal] = None
    tax_rate: Optional[Decimal] = None
    uom: str = ""
    raw: str = ""
    qty_printed: bool = True
    printed: dict = field(default_factory=dict)


def _strip_dates(s: str) -> str:
    for rx in DATE_PATTERNS:
        s = rx.sub(" ", s)
    return s


def _close(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) <= max(TOL, abs(b) * Decimal("0.0002"))


def table_region(lines: list) -> tuple:
    """-> (start, end) indexes of the item table: after the last header-ish line in the first
    half, up to the first totals line that follows at least one numeric row."""
    start = 0
    for i, ln in enumerate(lines):
        if len(TABLE_HEADER.findall(ln)) >= 2 or (TABLE_HEADER.search(ln) and
                                                   re.search(r"price|preis|amount|betrag|total|summa|hind|valor", ln, re.I)):
            start = i + 1
            break
    end = len(lines)
    for i in range(start, len(lines)):
        if TOTALS_START.match(lines[i]) and any(NUM_RE.search(l) for l in lines[start:i]):
            end = i
            break
    return start, end


def _is_int_token(tok: str) -> bool:
    return not re.search(r"[.,]\d{1,2}$", tok)


def _orders(toks: list, vals: list, i: int, j: int, order: str) -> list:
    """Both (qty, unit) assignments of two numbers, most plausible first. Multiplication is
    commutative, so the arithmetic cannot say which is which: use (1) the one printed without
    decimals, (2) a value of exactly 1, (3) the table header's column order, (4) qty-first."""
    a, b = (i, j), (j, i)                                  # (qty_idx, unit_idx)
    ia, ib = _is_int_token(toks[i][1]), _is_int_token(toks[j][1])
    if ia != ib:
        return [a, b] if ia else [b, a]
    if (vals[i] == 1) != (vals[j] == 1):
        return [a, b] if vals[i] == 1 else [b, a]
    if order == "price_first":
        return [b, a]
    return [a, b]


_SPACE_THOUSANDS = re.compile(r"(?<![\d.,])(\d{1,3}) (\d{3}[.,]\d{2})(?!\d)")


def parse_row(line: str, hint: str, line_no: int, order: str = "") -> Optional[Row]:
    """Parse one text line as an item row. If the plain reading fails, retry once with
    space-separated thousands joined ("6 976.80" -> "6976.80"); arithmetic decides which is right."""
    r = _parse_row(line, hint, line_no, order)
    if r is None:
        merged = _SPACE_THOUSANDS.sub(r"\1\2", line)
        if merged != line:
            r = _parse_row(merged, hint, line_no, order)
    return r


def _parse_row(line: str, hint: str, line_no: int, order: str = "") -> Optional[Row]:
    work = _strip_dates(line)
    pcts = []
    for m in PCT_RE.finditer(work):
        v = parse_amount(m.group(1), hint)
        if v is not None:
            pcts.append(v)
    work_np = PCT_RE.sub(" ", work)
    toks = [(m.start(), m.group(0), parse_amount(m.group(0), hint)) for m in NUM_RE.finditer(work_np)]
    toks = [(p, t, v) for p, t, v in toks if v is not None]
    # a leading small integer followed by a word is the position number, not a quantity
    if toks and re.match(r"^\W*\d{1,3}\s+[^\W\d]", work_np) and toks[0][0] <= 2 and _is_int_token(toks[0][1]):
        toks = toks[1:]
    if len(toks) < 2:
        return None
    vals = [abs(v) for _, _, v in toks]
    n = len(vals)
    found = None
    for k in range(n - 1, 0, -1):                      # total is the right-most consistent number
        t = vals[k]
        if t == 0 and n > 2:
            continue
        for i, j in combinations(range(k), 2):
            for qi, ui in _orders(toks, vals, i, j, order):
                q, u = vals[qi], vals[ui]
                if q == 0 or u == 0:
                    continue
                base = q * u
                if _close(base, t):
                    found = (qi, ui, k, None)
                    break
                for d in pcts:
                    if d > 0 and _close(base * (Decimal(100) - d) / Decimal(100), t):
                        found = (qi, ui, k, d)
                        break
                if found:
                    break
            if found:
                break
        if found:
            break
    qty_printed = True
    if not found:                                       # unit price == total  (single unit, qty absent)
        for k in range(n - 1, 0, -1):
            for i in range(k):
                if vals[i] == vals[k] and vals[k] > 0 and re.search(r"[.,]\d{2}\b", toks[k][1]):
                    found = (None, i, k, None)
                    qty_printed = False
                    break
            if found:
                break
    if not found:
        return None
    qi, ui, k, disc = found
    if vals[k] == 1 and vals[ui] == 1 and (qi is None or vals[qi] == 1):
        return None                                     # "1 1 1": a wrapped description, not an item
    qty = vals[qi] if qi is not None else Decimal(1)
    # description: line text left of the first numeric token that is part of the match
    first = min(toks[x][0] for x in (qi, ui, k) if x is not None)
    desc = work_np[:first]
    if len(re.findall(r"[^\W\d_]", desc)) < 3:          # numbers-first layouts: take the letters elsewhere
        desc = re.sub(r"[\d.,%€$£\s-]+", " ", work_np[first:])
    desc = re.sub(r"^\s*\d{1,3}[.)]?\s+(?=\D)", "", desc)      # leading position number
    desc = re.sub(r"[€$£]|\b(eur|usd|gbp|zar)\b", " ", desc, flags=re.I)
    desc = re.sub(r"\s+", " ", desc).strip(" -:|")
    if len(re.findall(r"[^\W\d_]", desc)) < 2:
        return None
    um = UOM_RE.search(work_np[toks[qi][0]:] if qi is not None else "")
    rate = None
    others = [p for p in pcts if p != disc]
    if others:
        rate = others[0]
    elif NOVAT.search(line):
        rate = Decimal(0)
    return Row(line_no=line_no, description=desc[:200], quantity=qty, unit_price=vals[ui], total=vals[k],
               discount_pct=disc, tax_rate=rate, uom=(um.group(1) if um else ""), raw=line.strip(),
               qty_printed=qty_printed,
               printed={"quantity": toks[qi][1] if qi is not None else "", "unit_price": toks[ui][1],
                        "total": toks[k][1]})


def column_order(header: str) -> str:
    q = re.search(r"qty|quantity|menge|kogus|qtd|quant\w*|cant\w*|miktar|kiekis", header, re.I)
    p = re.search(r"unit\s*price|price|preis|einzelpreis|hind|pre[c\u00e7]o|prego|precio|fiyat|harga|unitario|unit\u00e1rio", header, re.I)
    if q and p:
        return "price_first" if p.start() < q.start() else "qty_first"
    return ""


def parse_rows(lines: list, hint: str) -> tuple:
    """-> (rows, unverified_numeric_lines). Unverified lines are numeric lines in the table
    region that failed the arithmetic test: surfaced for review instead of guessed."""
    s, e = table_region(lines)
    order = column_order(lines[s - 1]) if s > 0 else ""
    rows, unverified = [], []
    for i in range(s, e):
        ln = lines[i]
        if not NUM_RE.search(_strip_dates(ln)):
            continue
        r = parse_row(ln, hint, len(rows) + 1, order)
        if r:
            rows.append(r)
        elif re.search(r"\d[.,]\d{2}\b", _strip_dates(ln)):
            unverified.append(ln.strip())
    return rows, unverified
