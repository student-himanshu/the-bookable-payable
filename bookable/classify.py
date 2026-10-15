"""Page classification and document segmentation (rule-based, evidence-carrying).

What it does
------------
1. `classify_page(text)` scores a single page against multilingual lexicons and returns a
   `PageClass`: a label, a subtype, a confidence *bucket* (high/medium/low - heuristic, not a
   calibrated probability) and the exact evidence (keyword + line) behind the decision.
2. `segment_document(pages)` groups consecutive pages into logical documents (segments),
   attaching untitled continuation pages to the segment they follow, and starting a new
   segment on a class change, a restarted page counter or a different document number.
3. Anything ambiguous is NOT guessed: it is labelled UNKNOWN or kept with
   `needs_review` reasons so later phases (and the person reading the report) can see it.

Labels
------
INVOICE / CREDIT_MEMO       payable candidates (-> `payables[]`)
SUPPORTING                  delivery notes, customs/duty printouts, waybills, payment advices
NON_PAYABLE                 reminders, forms, e-mails, quotations, proformas, POs, statements
UNKNOWN                     not enough evidence (never silently turned into a payable)

No filename-specific logic exists here; every rule is a language/vocabulary rule.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Optional

PAYABLE_LABELS = ("INVOICE", "CREDIT_MEMO")
TITLE_THRESHOLD = 3.0       # minimum score for a page to be labelled by vocabulary alone
HEAD_LINES = 8              # first N non-empty lines count as the page head
MAX_HEADLINE_WORDS = 6      # a short line anywhere also counts as a headline


def normalise(s: str) -> str:
    """Lower-case, strip accents, collapse whitespace: OCR-tolerant matching form."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("\u00df", "ss").lower()
    return re.sub(r"[ \t]+", " ", s)


# (class key, subtype, label, regex, headline weight, body weight, body cap)
_L = []


def _add(label, subtype, patterns, head, body, cap=3, maxrem=2):
    for p in patterns:
        _L.append((label, subtype, re.compile(p), head, body, cap, maxrem))


_add("INVOICE", "invoice", [
    r"\binvoice\b", r"\brechnung\b", r"\barve\b", r"\bfactura\b", r"\bfatura\b",
    r"\bfaktu ?ra\w*", r"\bfacture\b", r"\bnota fiscal\b", r"\bfac\s+[a-z]?\d", r"\barve ?nr\b",
    r"\bn\W{0,3}v\W{0,3}o\W{0,3}i?\W{0,3}c\W{0,3}e\b",     # letter-spaced "I N V O I C E"
], 4, 1)
_add("INVOICE", "invoice", [r"\b(?:customs|commercial|consolidated)\s+(?:consolidated\s+)?invoice\b"], 2, 0, 1)
_add("CREDIT_MEMO", "credit_memo", [
    r"\bcredit\s+(?:note|memo(?:randum)?)\b", r"\bgutschrift\b", r"\bkreedit\s?arve\b",
    r"\bnota de credito\b", r"\bnota credito\b", r"\bavoir\b", r"\bcredit adjustment\b",
], 6, 2)
_add("NON_PAYABLE", "payment_reminder", [
    r"\bmahnung\b", r"\bzahlungserinnerung\b", r"\bpayment reminder\b", r"\breminder notice\b",
    r"\boverdue (?:notice|invoice)\b", r"\bfinal (?:notice|demand)\b", r"\bmeeldetuletus\b",
    r"\blembrete de pagamento\b",
], 6, 2)
_add("NON_PAYABLE", "proforma", [r"\bpro[\s-]?forma\b"], 6, 2)
_add("NON_PAYABLE", "quotation", [
    r"\bquotation\b", r"\bangebot\b", r"\bpakkumine\b", r"\borcamento\b", r"\bcotacao\b",
], 5, 0.5, 1)
_add("NON_PAYABLE", "purchase_order", [
    r"\bpurchase order\b", r"\bbestellung\b", r"\btellimus\b", r"\bordem de compra\b",
    r"\border confirmation\b", r"\bauftragsbestatigung\b",
], 5, 0.5, 1)
_add("NON_PAYABLE", "statement", [
    r"\bstatement of account\b", r"\baccount statement\b", r"\bkontoauszug\b", r"\bextrato de conta\b",
], 5, 0, 1)
_add("NON_PAYABLE", "form", [
    r"\b(?:application|request|approval|claim|donation|sponsorship)s?\s+form\b",
    r"\bdonations?\b", r"\bcharitable\b", r"\bsponsorship\b",
], 3, 1, 2)
_add("SUPPORTING", "delivery_note", [
    r"\bdelivery (?:note|order)\b", r"\bpacking (?:list|slip)\b", r"\blieferschein\b",
    r"\bsaatelehe\b", r"\bguia de remessa\b", r"\bguia de transporte\b", r"\bgoods receipt\b",
    r"\bshipment receipt\b", r"\bconsignment note\b", r"\bproof of delivery\b",
], 5, 1)
_add("SUPPORTING", "shipping_document", [
    r"\bair ?waybill\b", r"\bwaybill\b", r"\bbill of lading\b", r"\bcargo manifest\b",
    r"\bcartage advice\b", r"\bshipment advice\b", r"\bcargo\b", r"\bmanifest\b",
], 5, 1)
_add("SUPPORTING", "customs_document", [
    r"\bcustoms declaration\b", r"\bimport declaration\b", r"\bduty calculator\b", r"\bicums\b",
    r"\bestancia aduaneira\b", r"\btipo declara\w+", r"\bzollanmeldung\b",
], 5, 2, 4)
_add("SUPPORTING", "customs_document", [
    r"\baduaneir\w*", r"\bdeclara[cg]\w+", r"\bexpedidor\b", r"\bimporter of record\b", r"\bhs ?code\b",
    r"\btariff\b",
], 0, 2, 1)
_add("SUPPORTING", "payment_advice", [
    r"\bpayment advice\b", r"\bremittance (?:advice|slip)\b", r"\bpayment slip\b", r"\bzahlschein\b",
], 6, 2, 3, 4)
# vocabulary that only makes sense together (each distinct term counts once)
_add("SUPPORTING", "shipping_document", [
    r"\bport of (?:loading|discharge)\b", r"\bgross wt\b", r"\bmawb\b", r"\bhawb\b", r"\bvessel\b",
    r"\bvoyage\b", r"\bcontainer(?:ised|ized)?\b", r"\bnotify party\b", r"\bshipper\b", r"\bkgm\b",
], 0, 1, 1)

# e-mail print-out: needs at least two header fields
_EMAIL_FIELDS = [re.compile(r"^\s*" + k + r"\s*:", re.M) for k in ("from", "sent", "to", "subject")]

_TOTAL_RE = re.compile(
    r"\b(?:total|gesamt\w*|summe|endbetrag|kokku|amount due|balance due|grand total|total a pagar|"
    r"valor total|montante|l\s?alt|i alt|betrag|subtotal|sub total|net total)\b")
_MONEY_RE = re.compile(r"[-(]?\s*\d{1,3}(?:[., ]\d{3})*[.,]\d{2}\b|[-(]?\s*\d+[.,]\d{2}\b")
_NEG_TOTAL_RE = re.compile(
    r"\b(?:total|gesamt\w*|summe|endbetrag|kokku|amount due|grand total)\b[^\n\d()-]{0,25}"
    r"(?:(?:-|minus)\s*\d|\(\s*\d[\d.,]*\s*\))")
_INVOICE_ISH = re.compile(
    r"\b(?:vat|iva|mwst|ust|gst|moms|kmkr|sst|tax|unit price|einzelpreis|quantity|qty|menge|quant|"
    r"descricao|description|beschreibung|kirjeldus|preco|price|amount|subtotal|sub total|levy|kogus|hind|"
    r"summa|kaibemaks|belob|antal|kobspris|qtd|valor|codigo|unitario|incidencia|item|rate|nhil|getfund)\b")

_PAGE_MARK = re.compile(
    r"(?:page|seite|leht|lehekulg\w*|pagina|pag|side|folha)\s*(?:no\.?)?\s*(\d{1,3})\s*(?:of|von|/|de|av|\|)\s*(\d{1,3})")
_PAGE_MARK3 = re.compile(r"lehek\w*\s*arv\W{0,3}(\d{1,3})\s*/\s*(\d{1,3})")   # Estonian "Lehekulgede arv: 1/2"
_PAGE_MARK2 = re.compile(r"\bn?\W{0,2}\s*(\d{1,2})\s*de\s*(\d{1,2})\b")   # "N° 1 de 1"
_ID_LABELLED = re.compile(
    r"(?:invoice|rechnung|arve|factura|fatura|faktura|credit note|gutschrift|kreeditarve|tax invoice)"
    r"\s*(?:no|nr|number|num|n[o0]|#)\.?\s*[:.#]?\s*([a-z0-9][a-z0-9\-/_.]{3,})", re.I)
_ID_DIRECT = re.compile(r"\binvoice\s+([a-z]{0,4}[-]?\d{5,}[a-z0-9\-/]*)", re.I)


@dataclass
class Evidence:
    kind: str           # label/subtype that fired
    keyword: str
    where: str          # "headline" | "body"
    line: str


@dataclass
class PageClass:
    page: int
    label: str                      # INVOICE | CREDIT_MEMO | SUPPORTING | NON_PAYABLE | UNKNOWN
    subtype: str
    confidence: str                 # high | medium | low | none
    scores: dict
    evidence: list
    page_marker: Optional[tuple] = None     # (n, total) as printed
    doc_ids: list = field(default_factory=list)
    qualifiers: list = field(default_factory=list)
    titled: bool = False            # label came from headline/vocabulary, not inferred
    notes: list = field(default_factory=list)


def _lines(text: str):
    """Non-empty text segments; layout-mode lines are split into their columns (3+ spaces)."""
    out = []
    for l in text.splitlines():
        for part in re.split(r"\s{3,}", l.strip()):
            if part.strip():
                out.append(part.strip())
    return out


def page_marker(text: str) -> Optional[tuple]:
    n = normalise(text)
    for rx in (_PAGE_MARK, _PAGE_MARK3, _PAGE_MARK2):
        m = rx.search(n)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if 1 <= a <= b <= 999:
                return (a, b)
    return None


def doc_ids(text: str) -> list:
    out = []
    for rx in (_ID_LABELLED, _ID_DIRECT):
        for m in rx.finditer(text or ""):
            tok = m.group(1).strip(".-/_").upper()
            if len(tok) >= 4 and any(c.isdigit() for c in tok) and tok not in out:
                out.append(tok)
    return out[:4]


def classify_page(text: str, page: int = 1) -> PageClass:
    raw_lines = _lines(text)
    norm_lines = [normalise(l) for l in raw_lines]
    head_idx = set(range(min(HEAD_LINES, len(norm_lines))))
    for i, l in enumerate(norm_lines):
        if len(l.split()) <= MAX_HEADLINE_WORDS and len(l) <= 50:
            head_idx.add(i)

    agg: dict = {}          # (label, subtype) -> score
    evidence: list = []
    lenient = ("INVOICE", "CREDIT_MEMO")
    ref_re = re.compile(r"[:#]|\bn[or]\.?(?:\s|$)|\bnumber\b")
    for label, sub, rx, head_w, body_w, cap, maxrem in _L:
        head_hits, body_hits, first_line = 0, 0, ""
        for i, l in enumerate(norm_lines):
            m = rx.search(l)
            if not m:
                continue
            c = len(rx.findall(l))
            if not first_line:
                first_line = raw_lines[i]
            in_head = i in head_idx
            if label in lenient:
                starts = l.lstrip(" #*|[(-.").startswith(m.group(0).strip())
                is_head = in_head or starts
            else:
                rem = l[:m.start()] + " " + l[m.end():]
                title_like = len(rem.split()) <= maxrem and not ref_re.search(rem)
                is_head = in_head and title_like
            if is_head:
                head_hits += 1
            else:
                body_hits += c
        if not (head_hits or body_hits):
            continue
        score = (head_w if head_hits else 0) + min(body_hits, cap) * body_w
        if score <= 0:
            continue
        key = (label, sub)
        agg[key] = agg.get(key, 0.0) + score
        evidence.append(Evidence(f"{label}/{sub}", rx.pattern, "headline" if head_hits else "body",
                                 first_line[:120]))

    # e-mail print-out
    norm_text = "\n".join(norm_lines)
    if sum(1 for rx in _EMAIL_FIELDS if rx.search(norm_text)) >= 3:
        agg[("NON_PAYABLE", "email")] = agg.get(("NON_PAYABLE", "email"), 0.0) + 6
        evidence.append(Evidence("NON_PAYABLE/email", "from/sent/to/subject header block", "headline", ""))

    total_lines = [l for l in norm_lines if _TOTAL_RE.search(l)]
    fin = sum(1 for l in total_lines if _MONEY_RE.search(l))
    neg_total = bool(_NEG_TOTAL_RE.search(norm_text))
    ish = len(set(_INVOICE_ISH.findall(norm_text)))

    marker = page_marker(text)
    ids = doc_ids(text)
    quals: list = []
    notes: list = []

    # A credit title always outranks the word "invoice" appearing in the same page.
    if ("CREDIT_MEMO", "credit_memo") in agg and ("INVOICE", "invoice") in agg:
        agg[("INVOICE", "invoice")] = min(agg[("INVOICE", "invoice")], agg[("CREDIT_MEMO", "credit_memo")] - 1)

    scores = {f"{k[0]}/{k[1]}": round(v, 1) for k, v in sorted(agg.items(), key=lambda kv: -kv[1])}
    ranked = sorted(agg.items(), key=lambda kv: -kv[1])

    label, subtype, confidence, titled = "UNKNOWN", "unclassified", "none", False
    if ranked and ranked[0][1] >= TITLE_THRESHOLD:
        (label, subtype), top = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else 0.0
        # equal-strength rivals across different labels => refuse to guess
        credit_over_invoice = label == "CREDIT_MEMO" and ranked[1][0][0] == "INVOICE"
        if len(ranked) > 1 and ranked[1][0][0] != label and top - second <= 1.0 and not credit_over_invoice:
            notes.append(f"tie between {label}/{subtype} and {ranked[1][0][0]}/{ranked[1][0][1]}")
            label, subtype, confidence = "UNKNOWN", "ambiguous", "low"
        else:
            titled = True
            has_head = any(e.where == "headline" and e.kind == f"{label}/{subtype}" for e in evidence)
            margin = top - second
            confidence = "high" if has_head and top >= 4 and margin >= 3 else ("medium" if has_head or margin >= 2 else "low")
    elif ish >= 4 and fin >= 1:
        label, subtype, confidence = "INVOICE", "untitled_invoice_like", "low"
        notes.append("no title found; invoice-like content (tax/price vocabulary + total amount)")
    elif len("".join(norm_lines)) < 80:
        notes.append("almost no text on page (blank, drawing or unreadable)")

    if label == "INVOICE" and neg_total:
        label, subtype, confidence = "CREDIT_MEMO", "negative_total", "low"
        notes.append("invoice-like page whose printed total is negative: possible credit memo")
        quals.append("negative_total")
    elif label == "CREDIT_MEMO" and neg_total:
        quals.append("negative_total")
    if label == "UNKNOWN" and neg_total:
        quals.append("negative_total")
        notes.append("negative total printed but no document title found")
    if re.search(r"\bcustoms\b", norm_text) and label == "INVOICE":
        quals.append("customs")
    if re.search(r"\b(?:duplicado|duplicate|duplikat|kopie|triplicado|copy)\b", norm_text) and label in PAYABLE_LABELS:
        quals.append("copy_marker")

    return PageClass(page=page, label=label, subtype=subtype, confidence=confidence, scores=scores,
                     evidence=[asdict(e) for e in evidence[:8]], page_marker=marker, doc_ids=ids,
                     qualifiers=quals, titled=titled, notes=notes)


@dataclass
class Segment:
    index: int
    label: str
    subtype: str
    pages: list
    confidence: str
    doc_ids: list
    payable_candidate: bool
    page_labels: list
    needs_review: list
    boundary_reason: str


_CONF_RANK = {"high": 3, "medium": 2, "low": 1, "none": 0}


def _same_id(a: list, b: list) -> Optional[bool]:
    if not a or not b:
        return None
    return bool(set(a) & set(b))


def segment_document(page_classes: list, *, ocr_conf: Optional[dict] = None) -> list:
    """Group `PageClass` objects (in page order) into logical segments."""
    segs: list = []
    cur: Optional[dict] = None

    def close():
        nonlocal cur
        if cur is None:
            return
        titled = [p for p in cur["pcs"] if p.titled or p.label != "UNKNOWN"]
        pool = titled or cur["pcs"]
        best = max(pool, key=lambda p: (_CONF_RANK[p.confidence], len(p.evidence)))
        label, subtype = best.label, best.subtype
        # a segment with a payable title stays payable even if a continuation page looks different
        conf = best.confidence
        review = list(cur["review"])
        if cur.get("restarts"):
            review.append(f"page counter restarted on pages {cur['restarts']} but the document number is unchanged: "
                          "kept as ONE segment; verify whether these are separate payables")
        untitled = [p.page for p in cur["pcs"] if p.label == "UNKNOWN" and not p.titled]
        review = [r for r in review if "untitled continuation" not in r]
        if untitled:
            review.append(f"pages {untitled} attached as untitled continuation")
        if label == "UNKNOWN":
            review.append("segment could not be classified")
        if conf == "low":
            review.append("low classification confidence")
        if any("customs" in p.qualifiers for p in cur["pcs"]):
            review.append("customs invoice: confirm it is a payable")
        if any("negative_total" in p.qualifiers for p in cur["pcs"]):
            review.append("negative total printed: confirm invoice vs credit memo")
        if ocr_conf:
            low = [p.page for p in cur["pcs"] if ocr_conf.get(p.page) is not None and ocr_conf[p.page] < 60]
            if low:
                review.append(f"low OCR confidence on pages {low}")
        ids: list = []
        for p in cur["pcs"]:
            for i in p.doc_ids:
                if i not in ids:
                    ids.append(i)
        segs.append(Segment(
            index=len(segs) + 1, label=label, subtype=subtype, pages=[p.page for p in cur["pcs"]],
            confidence=conf, doc_ids=ids[:6], payable_candidate=label in PAYABLE_LABELS,
            page_labels=[f"{p.page}:{p.label}" + ("" if p.titled else "*") for p in cur["pcs"]],
            needs_review=review, boundary_reason=cur["reason"]))
        cur = None

    for pc in page_classes:
        if cur is None:
            cur = {"pcs": [pc], "review": [], "reason": "first page"}
            continue
        seg_label = next((p.label for p in cur["pcs"] if p.titled), None) or \
            next((p.label for p in cur["pcs"] if p.label != "UNKNOWN"), None)
        seg_ids = [i for p in cur["pcs"] for i in p.doc_ids]
        seg_marker_total = next((p.page_marker[1] for p in cur["pcs"] if p.page_marker), None)
        reason = None
        review_note = None

        seg_sub = next((p.subtype for p in cur["pcs"] if p.titled), None) or \
            next((p.subtype for p in cur["pcs"] if p.label != "UNKNOWN"), None)
        if pc.label != "UNKNOWN" and seg_label is not None and pc.label != seg_label and \
                (pc.titled or pc.label != "INVOICE"):
            reason = f"class change {seg_label} -> {pc.label}"
        elif pc.titled and seg_label is not None and pc.label not in PAYABLE_LABELS and pc.subtype != seg_sub:
            reason = f"subtype change {seg_sub} -> {pc.subtype}"
        elif pc.titled and pc.label in PAYABLE_LABELS:
            same = _same_id(seg_ids, pc.doc_ids)
            restart = pc.page_marker is not None and pc.page_marker[0] == 1 and len(cur["pcs"]) >= 1 \
                and any(p.page_marker for p in cur["pcs"])
            if same is False:
                reason = "different document number"
            elif restart and same is None:
                reason = "page counter restarted (no document number to compare)"
            elif restart and same is True:
                review_note = f"RESTART:{pc.page}"
        if reason:
            close()
            cur = {"pcs": [pc], "review": [], "reason": reason}
        else:
            cur["pcs"].append(pc)
            if review_note:
                cur.setdefault("restarts", []).append(int(review_note.split(":")[1]))
            if not pc.titled and pc.label == "UNKNOWN":
                cur["review"].append(f"page {pc.page} attached as untitled continuation")
    close()
    return segs


_NUM_TOKEN = re.compile(r"\d[\d.,/-]{2,}")


def _num_tokens(text: str) -> set:
    return set(_NUM_TOKEN.findall(text or ""))


def mark_duplicates(segments: list, page_texts: dict, page_classes: list, min_similarity: float = 0.8) -> None:
    """Relabel a payable segment that is a marked copy/duplicate of an earlier payable segment.

    Evidence required: (a) the page carries a copy/duplicate marker AND (b) its numeric tokens
    (amounts, dates, numbers) overlap an earlier payable segment by >= `min_similarity`.
    Without both, nothing is changed (a lone "Copy" invoice stays payable, flagged).
    """
    by_page = {pc.page: pc for pc in page_classes}
    seen: list = []
    for seg in segments:
        if not seg.payable_candidate:
            continue
        toks = set()
        for pg in seg.pages:
            toks |= _num_tokens(page_texts.get(pg, ""))
        marked = any("copy_marker" in by_page[pg].qualifiers for pg in seg.pages)
        dup_of = None
        if marked and toks:
            for prev_idx, prev_toks in seen:
                inter = len(toks & prev_toks)
                if inter / max(1, min(len(toks), len(prev_toks))) >= min_similarity:
                    dup_of = prev_idx
                    break
        if dup_of is not None:
            seg.label, seg.subtype, seg.payable_candidate = "SUPPORTING", "duplicate_copy", False
            seg.needs_review.append(f"marked copy/duplicate of segment {dup_of} (numeric overlap >= {min_similarity})")
        else:
            if marked:
                seg.needs_review.append("page marked copy/duplicate but no earlier matching segment: kept as payable")
            seen.append((seg.index, toks))
