"""PDF text extraction with per-page OCR fallback.

Design
------
* Page boundaries are preserved: every page is extracted, diagnosed and stored separately.
* A page uses its embedded text layer when that layer holds enough real text; otherwise the
  page is rasterised and OCR'd. Sparse text layers are kept as evidence (`text_layer_text`).
* Nothing is guessed: if a page cannot be read, it is returned with method "empty" and a
  warning, never silently dropped. Document-level failures go in `DocumentText.errors`.
* Missing OCR language packs are reported (`ocr_langs_missing`) instead of failing; this is
  a configuration limitation, not a code defect.

Dependencies: pypdf (text layer), pypdfium2 (rasterising), pytesseract + Pillow, and the
`tesseract` executable for OCR. OCR is optional: without it, scanned pages come back "empty"
with a clear warning.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

MIN_TEXT_LAYER_CHARS = 40       # non-space characters needed to trust the text layer
DEFAULT_DPI = 200
DEFAULT_LANGS = ("eng", "deu", "est", "por", "tur", "msa", "fra", "spa", "nld", "dan")
LOW_CONFIDENCE = 45.0           # mean word confidence below which a rotation retry is attempted
CACHE_VERSION = 1


@dataclass
class PageText:
    page: int                       # 1-based
    method: str                     # text-layer | ocr | empty
    text: str
    chars: int                      # non-space characters in `text`
    text_layer_chars: int
    ocr_confidence: Optional[float] = None   # mean word confidence 0-100
    ocr_words: int = 0
    rotation_applied: int = 0       # degrees clockwise applied before OCR
    text_layer_text: str = ""       # kept only when the text layer was not used
    warnings: list = field(default_factory=list)


@dataclass
class DocumentText:
    file: str
    sha256: str
    n_pages: int
    pages: list
    ocr_langs_requested: list = field(default_factory=list)
    ocr_langs_used: list = field(default_factory=list)
    ocr_langs_missing: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @staticmethod
    def from_dict(d: dict) -> "DocumentText":
        pages = [PageText(**p) for p in d["pages"]]
        return DocumentText(**{**d, "pages": pages})


def _nonspace(s: str) -> int:
    return len(re.sub(r"\s+", "", s or ""))


def _clean(s: str) -> str:
    s = (s or "").replace("\x00", "")
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def available_ocr_langs() -> Optional[set]:
    """Installed tesseract languages, or None if tesseract/pytesseract is unusable."""
    try:
        import pytesseract
        return set(pytesseract.get_languages(config=""))
    except Exception:
        return None


def resolve_langs(requested) -> tuple:
    """-> (used, missing, installed_or_None). Always keeps at least 'eng' if installed."""
    installed = available_ocr_langs()
    requested = list(requested)
    if installed is None:
        return [], requested, None
    used = [l for l in requested if l in installed]
    missing = [l for l in requested if l not in installed]
    if not used and "eng" in installed:
        used = ["eng"]
    return used, missing, installed


def _ocr_image(img, lang: str, psm: int = 6, timeout: int = 180):
    """-> (text, mean_conf, n_words). Rebuilds lines from tesseract word boxes."""
    import pytesseract
    from pytesseract import Output
    data = pytesseract.image_to_data(img, lang=lang, config=f"--psm {psm}",
                                     output_type=Output.DICT, timeout=timeout)
    lines: dict = {}
    confs = []
    for i, word in enumerate(data["text"]):
        word = (word or "").strip()
        if not word:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        lines.setdefault(key, []).append(word)
        try:
            c = float(data["conf"][i])
        except (TypeError, ValueError):
            c = -1.0
        if c >= 0:
            confs.append(c)
    text = "\n".join(" ".join(ws) for ws in lines.values())
    mean = sum(confs) / len(confs) if confs else 0.0
    return text, mean, len(confs)


def _ocr_with_rotation(img, lang: str, dpi: int):
    """OCR; if confidence is poor, try the orientation tesseract's OSD suggests."""
    text, conf, words = _ocr_image(img, lang)
    rotation = 0
    if conf < LOW_CONFIDENCE or words < 15:
        try:
            import pytesseract
            from pytesseract import Output
            osd = pytesseract.image_to_osd(img, config="--psm 0 -c min_characters_to_try=20",
                                           output_type=Output.DICT)
            angle = int(osd.get("rotate", 0)) % 360
        except Exception:
            angle = 0
        if angle:
            rimg = img.rotate(-angle, expand=True)
            t2, c2, w2 = _ocr_image(rimg, lang)
            if c2 * max(w2, 1) > conf * max(words, 1):
                text, conf, words, rotation = t2, c2, w2, angle
    return text, conf, words, rotation


def _render_page(pdf_doc, index: int, dpi: int):
    page = pdf_doc[index]
    bitmap = page.render(scale=dpi / 72.0)
    return bitmap.to_pil().convert("L")


def extract_document(pdf_path, *, dpi: int = DEFAULT_DPI, langs=DEFAULT_LANGS,
                     ocr: bool = True, cache_dir: Optional[Path] = None) -> DocumentText:
    """Extract every page of one PDF. Never raises for a bad page or a bad file."""
    pdf_path = Path(pdf_path)
    raw = pdf_path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    used, missing, installed = resolve_langs(langs) if ocr else ([], list(langs), None)
    lang_arg = "+".join(used)

    cache_file = None
    if cache_dir is not None:
        cache_dir = Path(cache_dir)
        key = f"{sha[:16]}-{dpi}-{lang_arg or 'none'}-{int(ocr)}-v{CACHE_VERSION}.json"
        cache_file = cache_dir / key
        if cache_file.exists():
            try:
                return DocumentText.from_dict(json.loads(cache_file.read_text(encoding="utf-8")))
            except Exception:
                pass  # corrupt cache entry: recompute

    doc = DocumentText(file=pdf_path.name, sha256=sha, n_pages=0, pages=[],
                       ocr_langs_requested=list(langs), ocr_langs_used=used,
                       ocr_langs_missing=missing)
    if ocr and installed is None:
        doc.errors.append("OCR unavailable: tesseract/pytesseract not usable; scanned pages will be empty")

    try:
        from pypdf import PdfReader
        reader = PdfReader(str(pdf_path))
        n = len(reader.pages)
    except Exception as exc:  # unreadable / encrypted / not a PDF
        doc.errors.append(f"cannot open PDF: {type(exc).__name__}: {exc}")
        return doc
    doc.n_pages = n

    pdfium_doc = None
    for i in range(n):
        warnings: list = []
        tl = ""
        try:
            tl = _clean(reader.pages[i].extract_text(extraction_mode="layout") or "")
        except Exception as exc:
            warnings.append(f"text layer unreadable: {type(exc).__name__}")
        tl_chars = _nonspace(tl)

        if tl_chars >= MIN_TEXT_LAYER_CHARS:
            doc.pages.append(PageText(page=i + 1, method="text-layer", text=tl, chars=tl_chars,
                                      text_layer_chars=tl_chars, warnings=warnings))
            continue

        page = PageText(page=i + 1, method="empty", text="", chars=0, text_layer_chars=tl_chars,
                        text_layer_text=tl, warnings=warnings)
        if not ocr or installed is None or not lang_arg:
            page.warnings.append("no usable text layer and OCR not available")
        else:
            try:
                if pdfium_doc is None:
                    import pypdfium2 as pdfium
                    pdfium_doc = pdfium.PdfDocument(str(pdf_path))
                img = _render_page(pdfium_doc, i, dpi)
                text, conf, words, rot = _ocr_with_rotation(img, lang_arg, dpi)
                text = _clean(text)
                page.text, page.chars = text, _nonspace(text)
                page.ocr_confidence, page.ocr_words, page.rotation_applied = round(conf, 1), words, rot
                page.method = "ocr" if page.chars else "empty"
                if not page.chars:
                    page.warnings.append("OCR returned no text (blank or unreadable page)")
                elif conf < LOW_CONFIDENCE:
                    page.warnings.append(f"low OCR confidence ({conf:.0f})")
                if rot:
                    page.warnings.append(f"page rotated {rot} deg before OCR")
            except Exception as exc:
                page.warnings.append(f"OCR failed: {type(exc).__name__}: {exc}")
        doc.pages.append(page)

    if pdfium_doc is not None:
        try:
            pdfium_doc.close()
        except Exception:
            pass

    if cache_file is not None:
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(doc.to_dict(), ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    return doc
