"""Locale-aware amount and date parsing.

`erp.num()` silently turns anything that is not a plain dot-decimal into 0.0, so every value we
emit must go through `fmt_amount` (plain `1234.56`). Parsing here is the only place where
locale guessing happens, and ambiguity is reported, never hidden.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

_CENT = Decimal("0.01")

# A numeric token: digits with optional thousands/decimal separators.
NUM_RE = re.compile(r"(?<![\d.,])(?<![A-Za-z]{3})-?\d[\d.,']*\d(?![\w])|(?<![\d.,])(?<![A-Za-z]{3})-?\d(?![\w])")
PCT_RE = re.compile(r"(?<![\w.,])(\d{1,3}(?:[.,]\d{1,2})?)\s*%")


def doc_decimal_hint(text: str) -> str:
    """'.' or ',' : which character this document uses as decimal separator (2-digit tails)."""
    comma = len(re.findall(r"\d,\d{2}(?!\d)", text))
    dot = len(re.findall(r"\d\.\d{2}(?!\d)", text))
    return "," if comma > dot else "."


def parse_amount(token: str, decimal_hint: str = ".") -> Optional[Decimal]:
    """Parse one numeric token. Returns None when it is not a sane number.

    Rules: if both separators occur the last one is the decimal mark; one separator occurring
    several times is a thousands mark; one separator occurring once is a decimal mark unless it
    is followed by exactly three digits AND the document's hint says it is the other character.
    """
    if token is None:
        return None
    s = str(token).strip()
    neg = s.startswith("-") or s.startswith("(") or s.endswith("-") or s.upper().endswith("CR")
    s = re.sub(r"[^\d.,' ]", "", s).strip().replace("'", "").replace(" ", "")
    if not s or not re.search(r"\d", s):
        return None
    has_c, has_d = "," in s, "." in s
    if has_c and has_d:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        thou = "." if dec == "," else ","
        s = s.replace(thou, "").replace(dec, ".")
    elif has_c or has_d:
        sep = "," if has_c else "."
        parts = s.split(sep)
        if len(parts) > 2:                       # 1.234.567
            s = "".join(parts)
        else:
            tail = parts[1]
            if len(tail) == 3 and decimal_hint != sep and parts[0] not in ("", "0"):
                s = "".join(parts)               # 1.234 with ',' decimals -> thousands
            else:
                s = parts[0] + "." + tail
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    return -d if neg else d


def fmt_amount(d: Optional[Decimal], places: int = 2) -> str:
    """Plain dot-decimal string, never locale-formatted. '' for None."""
    if d is None:
        return ""
    q = _CENT if places == 2 else Decimal(1).scaleb(-places)
    return format(d.quantize(q), "f")


def fmt_plain(d: Optional[Decimal]) -> str:
    """Dot-decimal without forcing 2 places (quantities, rates, unit prices): 4, 2.5, 73.00."""
    if d is None:
        return ""
    s = format(d.normalize(), "f")
    return s


def fmt_price(d: Optional[Decimal], printed: str = "") -> str:
    """Unit price: keep at least 2 places, more if the document printed more."""
    if d is None:
        return ""
    s = format(d, "f")
    if "." not in s:
        return s + ".00"
    frac = s.split(".")[1].rstrip("0")
    return s.split(".")[0] + "." + frac.ljust(2, "0")


# ---------------------------------------------------------------- dates
_MONTHS = {}
for _i, _names in enumerate([
    ("jan", "january", "januar", "janeiro", "jaanuar", "enero", "janvier", "ocak", "januari", "janv"),
    ("feb", "february", "februar", "fevereiro", "veebruar", "febrero", "fevrier", "subat", "februari", "febr"),
    ("mar", "march", "marz", "maerz", "marco", "marts", "marzo", "mars", "mart", "maart"),
    ("apr", "april", "abril", "aprill", "avril", "nisan"),
    ("may", "mai", "maio", "mayo", "mei", "mayis", "maj"),
    ("jun", "june", "juni", "junho", "juuni", "junio", "juin", "haziran"),
    ("jul", "july", "juli", "julho", "juuli", "julio", "juillet", "temmuz"),
    ("aug", "august", "agosto", "augusti", "aout", "agustos", "ogos", "augustus"),
    ("sep", "sept", "september", "setembro", "septiembre", "septembre", "eylul"),
    ("oct", "october", "oktober", "outubro", "oktoober", "octubre", "octobre", "ekim", "okt"),
    ("nov", "november", "novembro", "novembre", "noviembre", "kasim"),
    ("dec", "december", "dezember", "dezembro", "detsember", "diciembre", "decembre", "aralik", "des", "dez"),
], start=1):
    for _n in _names:
        _MONTHS[_n] = _i

DATE_PATTERNS = [
    re.compile(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)"),                       # ISO
    re.compile(r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](\d{4})(?!\d)"),               # d.m.Y
    re.compile(r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](\d{2})(?!\d)"),               # d.m.y
    re.compile(r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?[ .\-]+([A-Za-zÀ-ſ]{3,9})\.?[ ,.\-]+(\d{4})(?!\d)"),
    re.compile(r"\b([A-Za-z]{3,9})\.? (\d{1,2})(?:st|nd|rd|th)?, (\d{4})\b"),       # June 18, 2018
]


def _mk(y: int, m: int, d: int) -> Optional[date]:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _month(name: str) -> Optional[int]:
    import unicodedata
    n = unicodedata.normalize("NFKD", name.lower())
    n = "".join(c for c in n if not unicodedata.combining(c))
    return _MONTHS.get(n)


def find_dates(text: str, prefer: str = "dmy") -> list:
    """-> [(date, ambiguous, matched_text)] in order of appearance.

    `prefer` resolves numeric a/b/Y dates where both a and b are <= 12 ('dmy' or 'mdy').
    The `ambiguous` flag is True whenever that preference decided the result.
    """
    out = []
    for pi, rx in enumerate(DATE_PATTERNS):
        for m in rx.finditer(text):
            g = m.groups()
            d = None
            amb = False
            if pi == 0:
                d = _mk(int(g[0]), int(g[1]), int(g[2]))
            elif pi in (1, 2):
                a, b, y = int(g[0]), int(g[1]), int(g[2])
                if pi == 2:
                    y += 2000 if y < 70 else 1900
                if a > 12 and b <= 12:
                    d = _mk(y, b, a)
                elif b > 12 and a <= 12:
                    d = _mk(y, a, b)
                elif a == b:
                    d = _mk(y, a, b)
                else:
                    amb = True
                    d = _mk(y, b, a) if prefer == "dmy" else _mk(y, a, b)
            elif pi == 3:
                mo = _month(g[1])
                if mo:
                    d = _mk(int(g[2]), mo, int(g[0]))
            elif pi == 4:
                mo = _month(g[0])
                if mo:
                    d = _mk(int(g[2]), mo, int(g[1]))
            if d is not None:
                out.append((m.start(), d, amb, m.group(0)))
    out.sort(key=lambda t: t[0])
    seen, res = set(), []
    for pos, d, amb, txt in out:
        if (pos, d) in seen:
            continue
        seen.add((pos, d))
        res.append((d, amb, txt))
    return res
