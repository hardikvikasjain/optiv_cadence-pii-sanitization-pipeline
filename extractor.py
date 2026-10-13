"""
extractor.py  --  Case Study 2 (Cadence PII detection) / Person 1: file extraction.

One entry point for every supported format:

    from extractor import extract_file, extract_files
    result = extract_file("policy.pdf")
    result.segments        # list[Segment]  (standard structure, see FIELDS)
    result.to_records()    # list[dict]     -> hand to PII detection (Person 4)
    result.stats           # counts of pages / slides / paragraphs / tables processed
    result.failures        # anything that raised; failures are never silent
    result.full_text()     # segments joined in reading order

Supported: .docx, .pptx, .pdf (native text page-by-page, Tesseract OCR for image-only pages).

Design rules
  * One standard record per segment for every format (FIELDS below).
  * Never drop content silently: failures and skipped images produce a warning.
  * We do NOT rebuild Word/PDF formatting. We keep reading order + paragraph / table-cell /
    shape / page grouping so neighbouring context is preserved.
"""
from __future__ import annotations

import hashlib
import io
import logging
import re
import shutil
import subprocess
import tempfile
import zipfile
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("extractor")

# --------------------------------------------------------------------------- config
MIN_NATIVE_CHARS = 30      # PDF page with fewer non-space chars than this is treated as image-only -> OCR
OCR_DPI = 300              # render resolution for scanned PDF pages (150 dpi garbled emails in testing)
LOW_OCR_CONF = 70.0        # mean Tesseract word confidence below this adds a warning
MIN_IMAGE_PX = 80          # embedded images smaller than this on both sides are treated as icons, skipped
OCR_LANG = "eng"

FIELDS = [
    "file_name", "file_type", "location_type", "location_index", "page_or_slide",
    "segment_id", "text", "extraction_method", "confidence", "context", "style", "warning",
]


# --------------------------------------------------------------------------- data model
@dataclass
class Segment:
    file_name: str
    file_type: str                 # docx | pptx | pdf
    location_type: str             # paragraph | heading | table_cell | header | footer | footnote | textbox |
                                   # slide_shape | slide_table_cell | slide_notes | chart | pdf_block | pdf_page | image
    location_index: str            # e.g. "p12", "t3:r2:c1", "sh5", "sh4.2", "b3", "p7:img1"
    page_or_slide: Optional[int]   # slide number / pdf page number (None for docx body, which has no fixed pages)
    segment_id: str                # unique + stable: "<file>#00042"
    text: str
    extraction_method: str         # native_text | ocr
    confidence: Optional[float] = None   # OCR mean word confidence (0-100); None for native text
    context: Optional[str] = None  # nearest preceding heading (docx) / slide title (pptx)
    style: Optional[str] = None    # docx paragraph style, e.g. "Heading 2"
    warning: Optional[str] = None


@dataclass
class ExtractionResult:
    file_name: str
    file_type: str
    segments: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    failures: list = field(default_factory=list)   # [{"location": ..., "error": ...}]
    warnings: list = field(default_factory=list)   # file-level notes (e.g. images not OCR'd)
    backend: dict = field(default_factory=dict)

    def to_records(self) -> list:
        return [asdict(s) for s in self.segments]

    def full_text(self, sep: str = "\n\n") -> str:
        return sep.join(s.text for s in self.segments if s.text)

    def to_dataframe(self):
        import pandas as pd
        return pd.DataFrame(self.to_records(), columns=FIELDS)


# --------------------------------------------------------------------------- helpers
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _norm(text: str) -> str:
    """Normalise whitespace but keep line breaks (they carry structure)."""
    if not text:
        return ""
    text = text.replace("\x0b", "\n").replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    text = _CTRL.sub("", text)
    return "\n".join(line.rstrip() for line in text.split("\n")).strip()


class _Collector:
    def __init__(self, path: Path, ftype: str):
        self.file_name, self.ftype = path.name, ftype
        self.segments: list[Segment] = []
        self.n = 0

    def add(self, location_type, location_index, text, *, method="native_text", page=None, conf=None,
            context=None, style=None, warning=None, keep_empty=False) -> Optional[Segment]:
        text = _norm(text)
        if not text and not keep_empty:
            return None
        self.n += 1
        seg = Segment(self.file_name, self.ftype, location_type, str(location_index), page,
                      f"{self.file_name}#{self.n:05d}", text, method, conf, context, style, warning)
        self.segments.append(seg)
        return seg


# --------------------------------------------------------------------------- OCR
def _prep(img):
    """Grayscale + autocontrast; upscale small screenshots (Tesseract likes ~300dpi text)."""
    from PIL import Image, ImageOps
    img = ImageOps.autocontrast(img.convert("L"))
    if img.width < 1400:
        f = 2 if img.width >= 700 else 3
        img = img.resize((img.width * f, img.height * f), Image.LANCZOS)
    return img


def ocr_blocks(img, lang: str = OCR_LANG, psm: int = 3) -> list:
    """OCR a PIL image. Returns [(text, mean_confidence)] one entry per Tesseract paragraph, reading order.
    Line breaks inside a paragraph are kept."""
    import pytesseract
    from pytesseract import Output
    d = pytesseract.image_to_data(_prep(img), lang=lang, config=f"--oem 3 --psm {psm}", output_type=Output.DICT)
    paras: dict = {}
    for i, word in enumerate(d["text"]):
        if not str(word).strip():
            continue
        try:
            conf = float(d["conf"][i])
        except (TypeError, ValueError):
            conf = -1.0
        key = (d["block_num"][i], d["par_num"][i])
        lines = paras.setdefault(key, {})
        lines.setdefault(d["line_num"][i], []).append((word, conf))
    out = []
    for key, lines in paras.items():           # dict preserves Tesseract's reading order
        text = "\n".join(" ".join(w for w, _ in lines[ln]) for ln in sorted(lines))
        confs = [c for ws in lines.values() for _, c in ws if c >= 0]
        out.append((text, round(sum(confs) / len(confs), 1) if confs else None))
    return out


def _emf_to_png(blob: bytes, ext: str):
    """EMF/WMF -> PIL image via LibreOffice if installed (optional). Returns None if unavailable."""
    exe = shutil.which("soffice") or shutil.which("libreoffice")
    if not exe:
        return None
    from PIL import Image
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / f"img.{ext}"
        src.write_bytes(blob)
        try:
            subprocess.run([exe, "--headless", "--convert-to", "png", "--outdir", td, str(src)],
                           capture_output=True, timeout=120, check=False)
            out = Path(td) / "img.png"
            return Image.open(io.BytesIO(out.read_bytes())).copy() if out.exists() else None
        except Exception:
            return None


def _svg_text(blob: bytes) -> str:
    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(blob)
        return "\n".join(" ".join("".join(el.itertext()).split()) for el in root.iter()
                         if el.tag.endswith("}text") or el.tag == "text")
    except Exception:
        return ""


class _ImageOCR:
    """OCR embedded images once per unique image (logos repeat in every header/slide)."""

    def __init__(self, enabled: bool):
        self.enabled, self.cache, self.stats = enabled, {}, Counter()

    def run(self, c: _Collector, blob: bytes, ctype: str, loc: str, page, context, result: ExtractionResult):
        self.stats["images_found"] += 1
        if not self.enabled:
            self.stats["images_not_ocred"] += 1
            return
        digest = hashlib.sha1(blob).hexdigest()
        if digest in self.cache:
            self.stats["images_duplicate_skipped"] += 1
            return
        self.cache[digest] = loc
        ctype = (ctype or "").lower()
        try:
            from PIL import Image
            if "svg" in ctype:
                c.add("image", loc, _svg_text(blob), page=page, context=context)
                self.stats["images_ocred"] += 1
                return
            if "emf" in ctype or "wmf" in ctype or "x-emf" in ctype:
                img = _emf_to_png(blob, "emf" if "emf" in ctype else "wmf")
                if img is None:
                    self.stats["images_unsupported"] += 1
                    result.warnings.append(f"{loc}: vector image ({ctype}) not OCR'd - LibreOffice not available")
                    c.add("image", loc, "", page=page, context=context, keep_empty=True,
                          warning=f"vector image {ctype} not OCR'd (install LibreOffice to enable); may contain text")
                    return
            else:
                img = Image.open(io.BytesIO(blob))
                img.load()
            if img.width < MIN_IMAGE_PX and img.height < MIN_IMAGE_PX:
                self.stats["images_tiny_skipped"] += 1
                return
            blocks = ocr_blocks(img)
            self.stats["images_ocred"] += 1
            for text, conf in blocks:
                c.add("image", loc, text, method="ocr", page=page, conf=conf, context=context,
                      warning="low OCR confidence" if conf is not None and conf < LOW_OCR_CONF else None)
        except Exception as e:  # never silent
            self.stats["images_failed"] += 1
            result.failures.append({"location": loc, "error": f"image OCR failed: {e!r}"})


# =========================================================================== DOCX
def extract_docx(path, ocr_images: bool = True) -> ExtractionResult:
    from docx import Document
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    path = Path(path)
    res = ExtractionResult(path.name, "docx")
    c = _Collector(path, "docx")
    st: Counter = Counter()
    imgs = _ImageOCR(ocr_images)
    doc = Document(str(path))
    ctx = {"heading": None}

    def para_images(p_elm, part, loc, page=None):
        seen = set()
        for k, blip in enumerate(p_elm.iter(qn("a:blip")), 1):
            rid = blip.get(qn("r:embed"))
            if not rid or rid in seen or rid not in part.related_parts:
                continue
            seen.add(rid)
            ip = part.related_parts[rid]
            imgs.run(c, ip.blob, ip.content_type, f"{loc}:img{k}", page, ctx["heading"], res)

    def textboxes(p_elm, loc):
        k = 0
        for tb in p_elm.iter(qn("w:txbxContent")):
            if any(a.tag.endswith("}Fallback") for a in tb.iterancestors()):
                continue        # mc:Fallback duplicates mc:Choice
            k += 1
            text = "\n".join("".join(t.text or "" for t in p.iter(qn("w:t"))) for p in tb.iter(qn("w:p")))
            if c.add("textbox", f"{loc}:tb{k}", text, context=ctx["heading"]):
                st["textboxes"] += 1

    def table(tbl, label, kind="table_cell", part=None):
        part = part or doc.part
        seen = set()
        for r_i, row in enumerate(tbl.rows, 1):
            for c_i, cell in enumerate(row.cells, 1):
                if cell._tc in seen:                 # merged cells repeat in python-docx
                    continue
                seen.add(cell._tc)
                loc = f"{label}:r{r_i}:c{c_i}"
                st["table_cells"] += 1
                c.add(kind, loc, "\n".join(p.text for p in cell.paragraphs), context=ctx["heading"])
                for p in cell.paragraphs:
                    para_images(p._p, part, loc)
                for n_i, nested in enumerate(cell.tables, 1):
                    st["nested_tables"] += 1
                    table(nested, f"{loc}:t{n_i}", kind, part)

    # ---- body, in true document order (paragraphs and tables interleaved)
    p_i = t_i = 0
    for child in doc.element.body.iterchildren():
        try:
            if child.tag == qn("w:p"):
                p_i += 1
                st["paragraphs"] += 1
                para = Paragraph(child, doc)
                try:
                    sname = para.style.name if para.style is not None else None
                except Exception:
                    sname = None
                is_head = bool(sname) and (sname.lower().startswith("heading") or sname.lower() == "title")
                if is_head:
                    st["headings"] += 1
                seg = c.add("heading" if is_head else "paragraph", f"p{p_i}", para.text,
                            context=ctx["heading"], style=sname)
                if is_head and seg:
                    ctx["heading"] = seg.text
                    seg.context = seg.text
                textboxes(child, f"p{p_i}")
                para_images(child, doc.part, f"p{p_i}")
            elif child.tag == qn("w:tbl"):
                t_i += 1
                st["tables"] += 1
                table(Table(child, doc), f"t{t_i}")
        except Exception as e:
            res.failures.append({"location": f"body element {p_i}/{t_i}", "error": repr(e)})

    # ---- headers / footers (PII often hides here: names, doc owners, phone numbers)
    for s_i, sec in enumerate(doc.sections, 1):
        for kind, parts in (("header", (sec.header, sec.first_page_header, sec.even_page_header)),
                            ("footer", (sec.footer, sec.first_page_footer, sec.even_page_footer))):
            for v_i, hf in enumerate(parts):
                try:
                    if hf.is_linked_to_previous:
                        continue
                    st[f"{kind}s"] += 1
                    for p_k, p in enumerate(hf.paragraphs, 1):
                        c.add(kind, f"s{s_i}:{kind}{v_i}:p{p_k}", p.text, context=ctx["heading"])
                        para_images(p._p, hf.part, f"s{s_i}:{kind}{v_i}:p{p_k}")
                    for t_k, tb in enumerate(hf.tables, 1):
                        table(tb, f"s{s_i}:{kind}{v_i}:t{t_k}", kind, hf.part)
                except Exception as e:
                    res.failures.append({"location": f"section {s_i} {kind}", "error": repr(e)})

    # ---- footnotes / endnotes (python-docx has no API: read the XML part directly)
    try:
        with zipfile.ZipFile(path) as z:
            for part_name, label in (("word/footnotes.xml", "footnote"), ("word/endnotes.xml", "endnote")):
                if part_name not in z.namelist():
                    continue
                from lxml import etree
                root = etree.fromstring(z.read(part_name))
                for note in root:
                    if note.get(qn("w:type")) in ("separator", "continuationSeparator", "continuationNotice"):
                        continue
                    text = "\n".join("".join(t.text or "" for t in p.iter(qn("w:t"))) for p in note.iter(qn("w:p")))
                    if c.add("footnote", f"{label}{note.get(qn('w:id'))}", text):
                        st["footnotes"] += 1
    except Exception as e:
        res.failures.append({"location": "footnotes/endnotes", "error": repr(e)})

    st.update(imgs.stats)
    st["segments"] = len(c.segments)
    st["segments_ocr"] = sum(1 for s in c.segments if s.extraction_method == "ocr")
    res.segments, res.stats = c.segments, dict(st)
    if not ocr_images and imgs.stats["images_found"]:
        res.warnings.append(f"{imgs.stats['images_found']} embedded images were NOT OCR'd (ocr_images=False); "
                            "they may contain PII.")
    return res


# =========================================================================== PPTX
def extract_pptx(path, ocr_images: bool = True) -> ExtractionResult:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE, PP_PLACEHOLDER

    path = Path(path)
    res = ExtractionResult(path.name, "pptx")
    c = _Collector(path, "pptx")
    st: Counter = Counter()
    imgs = _ImageOCR(ocr_images)
    prs = Presentation(str(path))

    def slide_title(slide) -> Optional[str]:
        try:
            if slide.shapes.title is not None and slide.shapes.title.has_text_frame:
                return _norm(slide.shapes.title.text_frame.text) or None
        except Exception:
            pass
        return None

    def walk(shapes, prefix: str, s_no: int, title):
        for i, sh in enumerate(shapes, 1):            # i = shape index within its container (1-based)
            idx = f"{prefix}{i}"
            loc = f"sh{idx}"
            try:
                st["shapes"] += 1
                if sh.shape_type == MSO_SHAPE_TYPE.GROUP:
                    st["groups"] += 1
                    walk(sh.shapes, idx + ".", s_no, title)
                    continue
                if getattr(sh, "has_text_frame", False) and sh.has_text_frame:
                    c.add("slide_shape", loc, sh.text_frame.text, page=s_no, context=title)
                if getattr(sh, "has_table", False) and sh.has_table:
                    st["tables"] += 1
                    for r_i, row in enumerate(sh.table.rows, 1):
                        for c_i, cell in enumerate(row.cells, 1):
                            if cell.is_spanned:
                                continue
                            st["table_cells"] += 1
                            c.add("slide_table_cell", f"{loc}:r{r_i}:c{c_i}", cell.text_frame.text,
                                  page=s_no, context=title)
                if getattr(sh, "has_chart", False) and sh.has_chart:
                    st["charts"] += 1
                    ch = sh.chart
                    bits = []
                    if ch.has_title:
                        bits.append(ch.chart_title.text_frame.text)
                    try:
                        bits += [str(x) for x in ch.plots[0].categories]
                        bits += [s.name for s in ch.plots[0].series]
                    except Exception:
                        pass
                    c.add("chart", loc, "\n".join(bits), page=s_no, context=title)
                if sh.shape_type == MSO_SHAPE_TYPE.PICTURE or sh.shape_type == MSO_SHAPE_TYPE.LINKED_PICTURE:
                    imgs.run(c, sh.image.blob, sh.image.content_type, f"{loc}:img", s_no, title, res)
            except Exception as e:
                res.failures.append({"location": f"slide {s_no} shape {idx}", "error": repr(e)})

    for s_no, slide in enumerate(prs.slides, 1):
        st["slides"] += 1
        title = slide_title(slide)
        walk(slide.shapes, "", s_no, title)
        try:
            if slide.has_notes_slide:
                notes = slide.notes_slide.notes_text_frame
                if notes is not None and c.add("slide_notes", "notes", notes.text, page=s_no, context=title):
                    st["notes"] += 1
        except Exception as e:
            res.failures.append({"location": f"slide {s_no} notes", "error": repr(e)})

    st.update(imgs.stats)
    st["segments"] = len(c.segments)
    st["segments_ocr"] = sum(1 for s in c.segments if s.extraction_method == "ocr")
    res.segments, res.stats = c.segments, dict(st)
    if not ocr_images and imgs.stats["images_found"]:
        res.warnings.append(f"{imgs.stats['images_found']} pictures were NOT OCR'd (ocr_images=False).")
    return res


# =========================================================================== PDF
class _FitzPdf:
    name = "pymupdf"

    def __init__(self, path):
        import fitz
        self.doc = fitz.open(str(path))
        self.n_pages = len(self.doc)

    def native_blocks(self, i):
        page = self.doc[i]
        return [b[4] for b in page.get_text("blocks", sort=True) if b[6] == 0 and str(b[4]).strip()]

    def image_ratio(self, i):
        page = self.doc[i]
        area = page.rect.width * page.rect.height or 1
        return sum(abs(info["bbox"][2] - info["bbox"][0]) * abs(info["bbox"][3] - info["bbox"][1])
                   for info in page.get_image_info()) / area

    def render(self, i, dpi):
        from PIL import Image
        pix = self.doc[i].get_pixmap(dpi=dpi, alpha=False)
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


class _PlumberPdf:
    """Fallback when PyMuPDF is not installed (same interface)."""
    name = "pdfplumber"

    def __init__(self, path):
        import pdfplumber
        self.pdf = pdfplumber.open(str(path))
        self.n_pages = len(self.pdf.pages)

    def native_blocks(self, i):
        text = self.pdf.pages[i].extract_text() or ""
        return [b for b in re.split(r"\n\s*\n", text) if b.strip()] or ([text] if text.strip() else [])

    def image_ratio(self, i):
        p = self.pdf.pages[i]
        area = (p.width * p.height) or 1
        return sum(abs(im["x1"] - im["x0"]) * abs(im["bottom"] - im["top"]) for im in p.images) / area

    def render(self, i, dpi):
        return self.pdf.pages[i].to_image(resolution=dpi).original.convert("RGB")


def _open_pdf(path):
    try:
        return _FitzPdf(path)
    except ImportError:
        log.warning("PyMuPDF not installed - falling back to pdfplumber")
        return _PlumberPdf(path)


def extract_pdf(path, dpi: int = OCR_DPI, force_ocr: bool = False) -> ExtractionResult:
    path = Path(path)
    res = ExtractionResult(path.name, "pdf")
    c = _Collector(path, "pdf")
    st: Counter = Counter()
    be = _open_pdf(path)
    res.backend = {"pdf_text": be.name, "ocr": "tesseract", "ocr_dpi": dpi}
    st["pages"] = be.n_pages
    confs = []

    for i in range(be.n_pages):
        pg = i + 1
        try:
            blocks = be.native_blocks(i)
            nchars = sum(len(re.sub(r"\s", "", b)) for b in blocks)
            if force_ocr or nchars < MIN_NATIVE_CHARS:
                ocr = ocr_blocks(be.render(i, dpi))
                st["pages_ocr"] += 1
                if not ocr:
                    c.add("pdf_page", f"pg{pg}", "", method="ocr", page=pg, keep_empty=True,
                          warning="no text found on page (blank page or OCR failure) - review manually")
                    st["pages_empty"] += 1
                for b_i, (text, conf) in enumerate(ocr, 1):
                    low = conf is not None and conf < LOW_OCR_CONF
                    c.add("pdf_block", f"b{b_i}", text, method="ocr", page=pg, conf=conf,
                          warning="low OCR confidence - PII may be mis-read" if low else None)
                    if conf is not None:
                        confs.append(conf)
            else:
                st["pages_native"] += 1
                ratio = be.image_ratio(i)
                for b_i, text in enumerate(blocks, 1):
                    c.add("pdf_block", f"b{b_i}", text, page=pg,
                          warning="page also holds large image(s); text inside images is not captured "
                                  "(re-run with force_ocr=True)" if ratio > 0.5 else None)
        except Exception as e:
            st["pages_failed"] += 1
            res.failures.append({"location": f"page {pg}", "error": repr(e)})
            c.add("pdf_page", f"pg{pg}", "", page=pg, keep_empty=True,
                  warning=f"EXTRACTION FAILED: {e!r} - page content NOT scanned for PII")

    st["segments"] = len(c.segments)
    st["segments_ocr"] = sum(1 for s in c.segments if s.extraction_method == "ocr")
    if confs:
        st["ocr_mean_confidence"] = round(sum(confs) / len(confs), 1)
    res.segments, res.stats = c.segments, dict(st)
    return res


# =========================================================================== dispatch / CLI
_DISPATCH = {".docx": extract_docx, ".pptx": extract_pptx, ".pdf": extract_pdf}


def extract_file(path, **options: Any) -> ExtractionResult:
    """Extract any supported file into the standard segment structure.
    Options: ocr_images (docx/pptx, default True), dpi / force_ocr (pdf)."""
    path = Path(path)
    fn = _DISPATCH.get(path.suffix.lower())
    if fn is None:
        raise ValueError(f"Unsupported file type {path.suffix!r}. Supported: {sorted(_DISPATCH)}")
    if not path.exists():
        raise FileNotFoundError(path)
    return fn(path, **options)


def extract_files(paths, **options) -> dict:
    """Extract several files; one bad file never stops the batch. Returns {file_name: ExtractionResult}."""
    out = {}
    for p in paths:
        try:
            out[Path(p).name] = extract_file(p, **options)
        except Exception as e:
            r = ExtractionResult(Path(p).name, Path(p).suffix.lstrip(".").lower())
            r.failures.append({"location": "file", "error": repr(e)})
            out[r.file_name] = r
    return out


if __name__ == "__main__":
    import argparse
    import json
    ap = argparse.ArgumentParser(description="Extract text segments from docx / pptx / pdf")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--out", help="write all segments to this JSON file")
    a = ap.parse_args()
    allrec = []
    for name, r in extract_files(a.files).items():
        print(f"{name}: {r.stats} failures={len(r.failures)}")
        allrec += r.to_records()
    if a.out:
        Path(a.out).write_text(json.dumps(allrec, indent=1, ensure_ascii=False), encoding="utf-8")
