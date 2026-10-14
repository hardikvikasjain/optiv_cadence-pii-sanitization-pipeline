import os
import re
import docx
import pptx
import fitz

def redact_text_rtl(text: str, detections: list[dict]) -> str:
    """Replaces detected PII substrings using right-to-left sorting to preserve offsets."""
    if not detections or not text:
        return text
    sorted_dets = sorted(detections, key=lambda d: d.get("start_char", 0), reverse=True)
    sanitized = text
    for det in sorted_dets:
        s = det.get("start_char", 0)
        e = det.get("end_char", len(text))
        tag = f"[REDACTED: {det.get('entity_type', 'PII')}]"
        sanitized = sanitized[:s] + tag + sanitized[e:]
    return sanitized

def redact_docx(input_path: str, output_path: str, detections: list[dict]):
    """Redacts PII in a Word document, preserving formatting and tables."""
    doc = docx.Document(input_path)
    # Collect unique entity texts to replace safely
    entities = sorted(list({d["entity_text"] for d in detections if len(d["entity_text"]) > 2}), key=len, reverse=True)
    
    def sanitize_str(s: str) -> str:
        res = s
        for ent in entities:
            if ent in res:
                # Find entity type
                det_type = next((d["entity_type"] for d in detections if d["entity_text"] == ent), "PII")
                res = res.replace(ent, f"[REDACTED: {det_type}]")
        return res

    for p in doc.paragraphs:
        if p.text:
            orig = p.text
            new_text = sanitize_str(orig)
            if new_text != orig:
                p.text = new_text

    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    if p.text:
                        orig = p.text
                        new_text = sanitize_str(orig)
                        if new_text != orig:
                            p.text = new_text

    doc.save(output_path)

def redact_pptx(input_path: str, output_path: str, detections: list[dict]):
    """Redacts PII in a PowerPoint presentation, preserving slide shapes and tables."""
    prs = pptx.Presentation(input_path)
    entities = sorted(list({d["entity_text"] for d in detections if len(d["entity_text"]) > 2}), key=len, reverse=True)

    def sanitize_str(s: str) -> str:
        res = s
        for ent in entities:
            if ent in res:
                det_type = next((d["entity_type"] for d in detections if d["entity_text"] == ent), "PII")
                res = res.replace(ent, f"[REDACTED: {det_type}]")
        return res

    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                for p in shape.text_frame.paragraphs:
                    if p.text:
                        orig = p.text
                        new_text = sanitize_str(orig)
                        if new_text != orig:
                            p.text = new_text
            if shape.has_table:
                for row in shape.table.rows:
                    for cell in row.cells:
                        for p in cell.text_frame.paragraphs:
                            if p.text:
                                orig = p.text
                                new_text = sanitize_str(orig)
                                if new_text != orig:
                                    p.text = new_text

    prs.save(output_path)

def redact_pdf(input_path: str, output_path: str, detections: list[dict]):
    """Applies visible black redaction blocks with entity tags in a PDF using PyMuPDF."""
    doc = fitz.open(input_path)
    entities = sorted(list({d["entity_text"] for d in detections if len(d["entity_text"]) > 2}), key=len, reverse=True)

    for page in doc:
        for ent in entities:
            det_type = next((d["entity_type"] for d in detections if d["entity_text"] == ent), "PII")
            # Search for occurrences of entity text
            rects = page.search_for(ent)
            for r in rects:
                # Add visible redaction annotation
                page.add_redact_annot(r, text=f"[REDACTED: {det_type}]", fontsize=7, fill=(0.12, 0.14, 0.22), text_color=(1, 1, 1))
        page.apply_redactions()

    doc.save(output_path)

def create_sanitized_original_file(input_path: str, output_path: str, detections: list[dict]) -> str:
    ext = input_path.split(".")[-1].lower()
    if ext == "docx":
        redact_docx(input_path, output_path, detections)
    elif ext == "pptx":
        redact_pptx(input_path, output_path, detections)
    elif ext == "pdf":
        redact_pdf(input_path, output_path, detections)
    else:
        # Fallback copy
        with open(input_path, "rb") as fin, open(output_path, "wb") as fout:
            fout.write(fin.read())
    return output_path
