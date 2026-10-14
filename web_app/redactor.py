import os
import re
import hashlib
from typing import List, Dict, Tuple
import docx
from docx.shared import Pt as DocxPt
import pptx
from pptx.util import Pt
from pptx.dml.color import RGBColor
import fitz

TYPE_LABELS = {
    "PERSON_NAME": "[REDACTED: NAME]",
    "EMAIL": "[REDACTED: EMAIL]",
    "PHONE": "[REDACTED: PHONE]",
    "ACCOUNT_OR_EMPLOYEE_ID": "[REDACTED: ID]",
    "IP_ADDRESS": "[REDACTED: IP]"
}

def get_file_sha256(filepath: str) -> str:
    """Calculates SHA-256 hash of a file for audit chain-of-custody."""
    if not os.path.exists(filepath):
        return ""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def redact_text_rtl(text: str, detections: list[dict]) -> str:
    """Replaces detected PII substrings using right-to-left sorting to preserve offsets."""
    if not detections or not text:
        return text
    sorted_dets = sorted(detections, key=lambda d: d.get("start_char", 0), reverse=True)
    sanitized = text
    for det in sorted_dets:
        s = det.get("start_char", 0)
        e = det.get("end_char", len(text))
        tag = TYPE_LABELS.get(det.get("entity_type"), f"[REDACTED: {det.get('entity_type', 'PII')}]")
        sanitized = sanitized[:s] + tag + sanitized[e:]
    return sanitized

def redact_pptx(input_path: str, output_path: str, detections: list[dict]) -> List[Dict]:
    """
    Redacts PII in PowerPoint presentations with font auto-scaling and formatting preservation
    to prevent card overflow or text collision.
    """
    prs = pptx.Presentation(input_path)
    changelog = []
    change_idx = 1

    # Sort entities by length descending to prevent partial prefix replacements
    entities = sorted(list({d["entity_text"] for d in detections if len(d["entity_text"]) > 2}), key=len, reverse=True)

    def process_paragraph(p, loc_str: str):
        nonlocal change_idx
        orig_text = p.text
        if not orig_text or not orig_text.strip():
            return

        has_match = False
        new_text = orig_text
        for ent in entities:
            if ent in new_text:
                det = next((d for d in detections if d["entity_text"] == ent), None)
                det_type = det["entity_type"] if det else "PII"
                label = TYPE_LABELS.get(det_type, f"[REDACTED: {det_type}]")
                new_text = new_text.replace(ent, label)
                has_match = True
                
                changelog.append({
                    "change_id": f"CHG-{change_idx:03d}",
                    "location": loc_str,
                    "original_text": ent,
                    "redacted_text": label,
                    "entity_type": det_type,
                    "method": det.get("detection_method", "hybrid") if det else "hybrid",
                    "confidence": det.get("confidence_or_strength", 0.90) if det else 0.90,
                    "action": "Replaced with Compact Redaction Tag & Font Preserved",
                    "rule": "Cadence PII Governance Standard Sec 3.1"
                })
                change_idx += 1

        if has_match and new_text != orig_text:
            orig_size = None
            orig_name = None
            orig_bold = None
            orig_color = None

            if p.runs:
                r0 = p.runs[0]
                orig_size = r0.font.size
                orig_name = r0.font.name
                orig_bold = r0.font.bold
                try:
                    if hasattr(r0.font, 'color') and hasattr(r0.font.color, 'rgb') and r0.font.color.rgb:
                        orig_color = r0.font.color.rgb
                except Exception:
                    pass

            p.text = new_text

            # Reapply formatting with intelligent auto-scaling to avoid overflow
            if p.runs:
                r = p.runs[0]
                if orig_name:
                    r.font.name = orig_name
                if orig_bold is not None:
                    r.font.bold = orig_bold
                if orig_color:
                    r.font.color.rgb = orig_color

                if orig_size:
                    # If replacement text grew in length, proportionally scale font down
                    if len(new_text) > len(orig_text) * 1.25:
                        scaled_pt = max(7.0, orig_size.pt * 0.78)
                        r.font.size = Pt(scaled_pt)
                    else:
                        r.font.size = orig_size
                else:
                    # Sensible clean compact font for org cards
                    r.font.size = Pt(8.5)

    for slide_idx, slide in enumerate(prs.slides, start=1):
        for shape_idx, shape in enumerate(slide.shapes, start=1):
            if shape.has_text_frame:
                shape.text_frame.word_wrap = True
                for p in shape.text_frame.paragraphs:
                    process_paragraph(p, f"Slide {slide_idx} • Shape sh{shape_idx}")
            if shape.has_table:
                for row_idx, row in enumerate(shape.table.rows, start=1):
                    for col_idx, cell in enumerate(row.cells, start=1):
                        cell.text_frame.word_wrap = True
                        for p in cell.text_frame.paragraphs:
                            process_paragraph(p, f"Slide {slide_idx} • Table r{row_idx}:c{col_idx}")

    prs.save(output_path)
    return changelog

def redact_docx(input_path: str, output_path: str, detections: list[dict]) -> List[Dict]:
    """Redacts PII in a Word document, preserving formatting and tables."""
    doc = docx.Document(input_path)
    changelog = []
    change_idx = 1
    entities = sorted(list({d["entity_text"] for d in detections if len(d["entity_text"]) > 2}), key=len, reverse=True)

    def process_p(p, loc_str: str):
        nonlocal change_idx
        orig = p.text
        if not orig or not orig.strip():
            return
        has_match = False
        new_text = orig
        for ent in entities:
            if ent in new_text:
                det = next((d for d in detections if d["entity_text"] == ent), None)
                det_type = det["entity_type"] if det else "PII"
                label = TYPE_LABELS.get(det_type, f"[REDACTED: {det_type}]")
                new_text = new_text.replace(ent, label)
                has_match = True
                changelog.append({
                    "change_id": f"CHG-{change_idx:03d}",
                    "location": loc_str,
                    "original_text": ent,
                    "redacted_text": label,
                    "entity_type": det_type,
                    "method": det.get("detection_method", "hybrid") if det else "hybrid",
                    "confidence": det.get("confidence_or_strength", 0.90) if det else 0.90,
                    "action": "Replaced with Compact Redaction Tag",
                    "rule": "Cadence PII Governance Standard Sec 3.1"
                })
                change_idx += 1

        if has_match and new_text != orig:
            # Preserve basic run formatting if single run
            if len(p.runs) == 1:
                p.runs[0].text = new_text
            else:
                p.text = new_text

    for p_idx, p in enumerate(doc.paragraphs, start=1):
        process_p(p, f"Paragraph p{p_idx}")

    for t_idx, table in enumerate(doc.tables, start=1):
        for r_idx, row in enumerate(table.rows, start=1):
            for c_idx, cell in enumerate(row.cells, start=1):
                for p in cell.paragraphs:
                    process_p(p, f"Table t{t_idx} • r{r_idx}:c{c_idx}")

    doc.save(output_path)
    return changelog

def redact_pdf(input_path: str, output_path: str, detections: list[dict]) -> List[Dict]:
    """Applies clean, proportional redaction blocks with entity tags in a PDF using PyMuPDF."""
    doc = fitz.open(input_path)
    changelog = []
    change_idx = 1
    entities = sorted(list({d["entity_text"] for d in detections if len(d["entity_text"]) > 2}), key=len, reverse=True)

    for page_idx, page in enumerate(doc, start=1):
        for ent in entities:
            det = next((d for d in detections if d["entity_text"] == ent), None)
            det_type = det["entity_type"] if det else "PII"
            label = TYPE_LABELS.get(det_type, f"[REDACTED: {det_type}]")
            
            rects = page.search_for(ent)
            for r in rects:
                page.add_redact_annot(
                    r,
                    text=label,
                    fontsize=6.5,
                    fill=(0.11, 0.13, 0.20),
                    text_color=(0.9, 0.95, 1.0)
                )
                changelog.append({
                    "change_id": f"CHG-{change_idx:03d}",
                    "location": f"Page {page_idx}",
                    "original_text": ent,
                    "redacted_text": label,
                    "entity_type": det_type,
                    "method": det.get("detection_method", "hybrid") if det else "hybrid",
                    "confidence": det.get("confidence_or_strength", 0.90) if det else 0.90,
                    "action": "Applied Native PDF Redaction Block",
                    "rule": "Cadence PII Governance Standard Sec 3.1"
                })
                change_idx += 1
        page.apply_redactions()

    doc.save(output_path)
    return changelog

def create_sanitized_original_file(input_path: str, output_path: str, detections: list[dict]) -> Tuple[str, List[Dict]]:
    ext = input_path.split(".")[-1].lower()
    if ext == "docx":
        changelog = redact_docx(input_path, output_path, detections)
    elif ext == "pptx":
        changelog = redact_pptx(input_path, output_path, detections)
    elif ext == "pdf":
        changelog = redact_pdf(input_path, output_path, detections)
    else:
        with open(input_path, "rb") as fin, open(output_path, "wb") as fout:
            fout.write(fin.read())
        changelog = []
    return output_path, changelog
