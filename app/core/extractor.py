"""
extractor.py - Production Multi-Format Extractor for Cadence Financial Group.
Supports .docx, .pptx, and .pdf with automated Tesseract OCR fallback for scanned pages (< 15 characters).
Strict local execution.
"""
from __future__ import annotations

import hashlib
import io
import logging
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional, List, Dict

try:
    from app.core.config import MIN_NATIVE_CHARS, LOW_OCR_CONF, OCR_DPI, OCR_LANG, MIN_IMAGE_PX
except ImportError:
    MIN_NATIVE_CHARS = 15
    LOW_OCR_CONF = 70.0
    OCR_DPI = 300
    OCR_LANG = "eng"
    MIN_IMAGE_PX = 80

log = logging.getLogger("cadence.extractor")

FIELDS = [
    "file_name", "file_type", "location_type", "location_index", "page_or_slide",
    "segment_id", "text", "extraction_method", "confidence", "context", "style", "warning",
]

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

def _norm(text: str) -> str:
    """Normalize whitespace and control characters while preserving line breaks."""
    if not text:
        return ""
    text = text.replace("\x0b", "\n").replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    text = _CTRL.sub("", text)
    return "\n".join(line.rstrip() for line in text.split("\n")).strip()

@dataclass
class Segment:
    file_name: str
    file_type: str                 # docx | pptx | pdf
    location_type: str             # paragraph | heading | table_cell | header | footer | textbox |
                                   # slide_shape | slide_table_cell | slide_notes | chart | pdf_block | pdf_page | image
    location_index: str            # e.g. "p12", "t3:r2:c1", "sh5", "b3", "pg1"
    page_or_slide: Optional[int]   # slide number / pdf page number (None for docx body)
    segment_id: str                # unique + stable: "<file>#00042"
    text: str
    extraction_method: str         # native_text | ocr
    confidence: Optional[float] = None   # OCR mean word confidence (0-100); None for native text
    context: Optional[str] = None  # nearest preceding heading / slide title
    style: Optional[str] = None    # paragraph style
    warning: Optional[str] = None

@dataclass
class ExtractionResult:
    file_name: str
    file_type: str
    segments: List[Segment] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)
    failures: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    backend: Dict[str, Any] = field(default_factory=dict)

    def to_records(self) -> List[Dict[str, Any]]:
        return [asdict(s) for s in self.segments]

    def full_text(self, sep: str = "\n\n") -> str:
        return sep.join(s.text for s in self.segments if s.text)

    def to_dataframe(self):
        import pandas as pd
        return pd.DataFrame(self.to_records(), columns=FIELDS)

class _Collector:
    def __init__(self, path: Path, ftype: str):
        self.file_name = path.name
        self.ftype = ftype
        self.segments: List[Segment] = []
        self.n = 0

    def add(self, location_type, location_index, text, *, method="native_text", page=None, conf=None,
            context=None, style=None, warning=None, keep_empty=False) -> Optional[Segment]:
        text = _norm(text)
        if not text and not keep_empty:
            return None
        self.n += 1
        seg = Segment(
            file_name=self.file_name,
            file_type=self.ftype,
            location_type=location_type,
            location_index=str(location_index),
            page_or_slide=page,
            segment_id=f"{self.file_name}#{self.n:05d}",
            text=text,
            extraction_method=method,
            confidence=conf,
            context=context,
            style=style,
            warning=warning
        )
        self.segments.append(seg)
        return seg

# --------------------------------------------------------------------------- OCR helpers
def _check_tesseract_installed() -> bool:
    """Checks if Tesseract executable is present on the host system."""
    import pytesseract
    try:
        ver = pytesseract.get_tesseract_version()
        return bool(ver)
    except Exception:
        # Check standard Windows paths if not on PATH
        standard_paths = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            shutil.which("tesseract")
        ]
        for p in standard_paths:
            if p and Path(p).exists():
                pytesseract.pytesseract.tesseract_cmd = str(p)
                return True
        return False

def _prep_image(img):
    """Convert to grayscale and autocontrast for OCR optimization."""
    from PIL import Image, ImageOps
    img = ImageOps.autocontrast(img.convert("L"))
    if img.width < 1400:
        factor = 2 if img.width >= 700 else 3
        img = img.resize((img.width * factor, img.height * factor), Image.Resampling.LANCZOS)
    return img

def ocr_blocks(img, lang: str = OCR_LANG, psm: int = 3) -> List[tuple[str, Optional[float]]]:
    """OCR an image using Tesseract. Returns list of (paragraph_text, mean_confidence)."""
    if not _check_tesseract_installed():
        raise RuntimeError("Tesseract binary not installed or found on system PATH.")

    import pytesseract
    from pytesseract import Output
    prepared = _prep_image(img)
    data = pytesseract.image_to_data(prepared, lang=lang, config=f"--oem 3 --psm {psm}", output_type=Output.DICT)

    paras: Dict[tuple, Dict[int, list]] = {}
    for i, word in enumerate(data["text"]):
        w_str = str(word).strip()
        if not w_str:
            continue
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1.0
        key = (data["block_num"][i], data["par_num"][i])
        lines = paras.setdefault(key, {})
        lines.setdefault(data["line_num"][i], []).append((w_str, conf))

    results = []
    for key, lines in paras.items():
        text = "\n".join(" ".join(w for w, _ in lines[ln]) for ln in sorted(lines))
        confs = [c for ws in lines.values() for _, c in ws if c >= 0]
        mean_conf = round(sum(confs) / len(confs), 1) if confs else None
        results.append((text, mean_conf))
    return results

# --------------------------------------------------------------------------- DOCX Parser
def extract_docx(path: Path | str, ocr_images: bool = True, **kwargs) -> ExtractionResult:
    from docx import Document
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    path = Path(path)
    res = ExtractionResult(path.name, "docx")
    c = _Collector(path, "docx")
    stats: Counter = Counter()
    doc = Document(str(path))
    ctx = {"heading": None}

    def process_table(tbl, label, kind="table_cell"):
        seen = set()
        for r_i, row in enumerate(tbl.rows, 1):
            for c_i, cell in enumerate(row.cells, 1):
                if cell._tc in seen:
                    continue
                seen.add(cell._tc)
                loc = f"{label}:r{r_i}:c{c_i}"
                stats["table_cells"] += 1
                c.add(kind, loc, "\n".join(p.text for p in cell.paragraphs), context=ctx["heading"])
                for n_i, nested in enumerate(cell.tables, 1):
                    stats["nested_tables"] += 1
                    process_table(nested, f"{loc}:t{n_i}", kind)

    # Process body paragraphs and tables in sequence
    p_i = t_i = 0
    for child in doc.element.body.iterchildren():
        try:
            if child.tag == qn("w:p"):
                p_i += 1
                stats["paragraphs"] += 1
                para = Paragraph(child, doc)
                sname = para.style.name if para.style else ""
                is_head = bool(sname) and (sname.lower().startswith("heading") or sname.lower() == "title")
                if is_head:
                    stats["headings"] += 1
                    if para.text.strip():
                        ctx["heading"] = para.text.strip()
                c.add("heading" if is_head else "paragraph", f"p{p_i}", para.text,
                      context=ctx["heading"], style=sname)

                # Check for inline textboxes inside paragraph
                for tb_idx, tb in enumerate(child.iter(qn("w:txbxContent")), 1):
                    tb_text = "\n".join("".join(t.text or "" for t in p.iter(qn("w:t"))) for p in tb.iter(qn("w:p")))
                    if c.add("textbox", f"p{p_i}:tb{tb_idx}", tb_text, context=ctx["heading"]):
                        stats["textboxes"] += 1

            elif child.tag == qn("w:tbl"):
                t_i += 1
                stats["tables"] += 1
                process_table(Table(child, doc), f"t{t_i}")
        except Exception as e:
            res.failures.append({"location": f"element p{p_i}/t{t_i}", "error": str(e)})

    # Headers & Footers
    for sec_idx, section in enumerate(doc.sections, 1):
        try:
            for hp in section.header.paragraphs:
                c.add("header", f"s{sec_idx}:hdr", hp.text)
            for fp in section.footer.paragraphs:
                c.add("footer", f"s{sec_idx}:ftr", fp.text)
        except Exception as e:
            res.failures.append({"location": f"section {sec_idx} header/footer", "error": str(e)})

    stats["segments"] = len(c.segments)
    res.segments = c.segments
    res.stats = dict(stats)
    return res

# --------------------------------------------------------------------------- PPTX Parser
def extract_pptx(path: Path | str, ocr_images: bool = True, **kwargs) -> ExtractionResult:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    path = Path(path)
    res = ExtractionResult(path.name, "pptx")
    c = _Collector(path, "pptx")
    stats: Counter = Counter()
    prs = Presentation(str(path))

    def slide_title(slide) -> Optional[str]:
        for sh in slide.shapes:
            if getattr(sh, "has_text_frame", False) and sh.has_text_frame:
                if getattr(sh, "is_placeholder", False):
                    try:
                        if sh.placeholder_format.idx in (0, 1):
                            t = sh.text_frame.text.strip()
                            if t:
                                return t
                    except Exception:
                        pass
        return None

    def walk_shapes(shapes, prefix, s_no, title):
        for i, sh in enumerate(shapes, 1):
            idx = f"{prefix}{i}"
            loc = f"sh{idx}"
            try:
                stats["shapes"] += 1
                if sh.shape_type == MSO_SHAPE_TYPE.GROUP:
                    stats["groups"] += 1
                    walk_shapes(sh.shapes, idx + ".", s_no, title)
                    continue

                if getattr(sh, "has_text_frame", False) and sh.has_text_frame:
                    c.add("slide_shape", loc, sh.text_frame.text, page=s_no, context=title)

                if getattr(sh, "has_table", False) and sh.has_table:
                    stats["tables"] += 1
                    for r_i, row in enumerate(sh.table.rows, 1):
                        for c_i, cell in enumerate(row.cells, 1):
                            if cell.is_spanned:
                                continue
                            stats["table_cells"] += 1
                            c.add("slide_table_cell", f"{loc}:r{r_i}:c{c_i}", cell.text_frame.text,
                                  page=s_no, context=title)

                if getattr(sh, "has_chart", False) and sh.has_chart:
                    stats["charts"] += 1
                    ch = sh.chart
                    chart_text = []
                    if ch.has_title and ch.chart_title.has_text_frame:
                        chart_text.append(ch.chart_title.text_frame.text)
                    try:
                        chart_text += [str(x) for x in ch.plots[0].categories]
                        chart_text += [s.name for s in ch.plots[0].series]
                    except Exception:
                        pass
                    c.add("chart", loc, "\n".join(chart_text), page=s_no, context=title)
            except Exception as e:
                res.failures.append({"location": f"slide {s_no} shape {idx}", "error": str(e)})

    for s_no, slide in enumerate(prs.slides, 1):
        stats["slides"] += 1
        title = slide_title(slide)
        walk_shapes(slide.shapes, "", s_no, title)
        try:
            if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
                c.add("slide_notes", "notes", slide.notes_slide.notes_text_frame.text, page=s_no, context=title)
                stats["notes"] += 1
        except Exception as e:
            res.failures.append({"location": f"slide {s_no} notes", "error": str(e)})

    stats["segments"] = len(c.segments)
    res.segments = c.segments
    res.stats = dict(stats)
    return res

# --------------------------------------------------------------------------- PDF Parser (PyMuPDF + OCR Fallback)
def extract_pdf(path: Path | str, dpi: int = OCR_DPI, force_ocr: bool = False, **kwargs) -> ExtractionResult:
    import fitz  # PyMuPDF
    from PIL import Image

    path = Path(path)
    res = ExtractionResult(path.name, "pdf")
    c = _Collector(path, "pdf")
    stats: Counter = Counter()
    doc = fitz.open(str(path))
    res.backend = {"pdf_text": "pymupdf", "ocr": "tesseract", "ocr_dpi": dpi}
    stats["pages"] = len(doc)
    confs: List[float] = []

    for i in range(len(doc)):
        pg = i + 1
        page = doc[i]
        try:
            # Extract native text blocks
            blocks = [b[4] for b in page.get_text("blocks", sort=True) if b[6] == 0 and str(b[4]).strip()]
            nchars = sum(len(re.sub(r"\s", "", b)) for b in blocks)

            # Check threshold (< 15 characters threshold triggers automated OCR fallback)
            if force_ocr or nchars < MIN_NATIVE_CHARS:
                stats["pages_ocr"] += 1
                try:
                    pix = page.get_pixmap(dpi=dpi, alpha=False)
                    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                    ocr_results = ocr_blocks(img)

                    if not ocr_results:
                        c.add("pdf_page", f"pg{pg}", "", method="ocr", page=pg, keep_empty=True,
                              warning="REVIEW REQUIRED: No readable text found on page (blank or degraded scan)")
                        stats["pages_empty"] += 1
                    else:
                        for b_i, (ocr_text, conf) in enumerate(ocr_results, 1):
                            low_conf = (conf is not None and conf < LOW_OCR_CONF)
                            warning_msg = "REVIEW REQUIRED: Low OCR confidence (<70%) - PII may be mis-read" if low_conf else None
                            c.add("pdf_block", f"b{b_i}", ocr_text, method="ocr", page=pg, conf=conf, warning=warning_msg)
                            if conf is not None:
                                confs.append(conf)
                except Exception as ocr_err:
                    # Self-healing fallback if Tesseract is not installed on system
                    stats["pages_failed"] += 1
                    warn = f"REVIEW REQUIRED: OCR engine unconfigured or failed ({ocr_err}). Scanned page unread."
                    res.warnings.append(warn)
                    c.add("pdf_page", f"pg{pg}", "", method="ocr", page=pg, keep_empty=True, warning=warn)
            else:
                # Page has sufficient native text (>= 15 characters)
                stats["pages_native"] += 1
                for b_i, text in enumerate(blocks, 1):
                    c.add("pdf_block", f"b{b_i}", text, method="native_text", page=pg)

        except Exception as e:
            stats["pages_failed"] += 1
            res.failures.append({"location": f"page {pg}", "error": str(e)})
            c.add("pdf_page", f"pg{pg}", "", page=pg, keep_empty=True,
                  warning=f"REVIEW REQUIRED: Extraction failed on page {pg}: {e}")

    stats["segments"] = len(c.segments)
    stats["segments_ocr"] = sum(1 for s in c.segments if s.extraction_method == "ocr")
    if confs:
        stats["ocr_mean_confidence"] = round(sum(confs) / len(confs), 1)

    res.segments = c.segments
    res.stats = dict(stats)
    return res

# --------------------------------------------------------------------------- Dispatcher
_DISPATCH = {".docx": extract_docx, ".pptx": extract_pptx, ".pdf": extract_pdf}

def extract_file(path: Path | str, **options: Any) -> ExtractionResult:
    """Extract any supported file (.docx, .pptx, .pdf) into standard Segment structure."""
    path = Path(path)
    fn = _DISPATCH.get(path.suffix.lower())
    if fn is None:
        raise ValueError(f"Unsupported file format {path.suffix!r}. Supported: {list(_DISPATCH.keys())}")
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    return fn(path, **options)
