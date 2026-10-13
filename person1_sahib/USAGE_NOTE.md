# Extraction module: usage note (Person 1 → Person 4)

**File:** `extractor.py`  |  **Needs:** `python-docx`, `python-pptx`, `pytesseract` + Tesseract binary, `Pillow`, `lxml`, and **`pymupdf`** (falls back to `pdfplumber` if PyMuPDF is missing). LibreOffice is optional (only used to OCR EMF/WMF vector images).

```python
from extractor import extract_file, extract_files

result = extract_file("Cadence_TPRM_Training.docx")   # .docx / .pptx / .pdf
records = result.to_records()      # list of dicts: give THESE to PII detection
result.stats                       # what was processed (pages / slides / paragraphs / tables ...)
result.failures                    # errors (empty = clean run)
result.full_text()                 # all segments joined, reading order
batch = extract_files([...])       # {file_name: result}; one bad file never stops the batch
```
Options: `extract_file(p, ocr_images=True)` for docx/pptx; `extract_file(p, dpi=300, force_ocr=False)` for pdf.

## File types, libraries, location format

| File type | Library | What is extracted | `location_type` → `location_index` |
|---|---|---|---|
| DOCX | python-docx (+ lxml for footnotes) | body paragraphs and table cells **in true document order**, headings, text boxes, headers, footers, footnotes, **OCR of embedded images** | `heading`/`paragraph` → `p12` · `table_cell` → `t3:r2:c1` (nested: `t3:r2:c1:t1:r1:c1`) · `header`/`footer` → `s1:header0:p1` · `footnote` → `footnote2` · `image` → `p40:img1` |
| PPTX | python-pptx | every shape per slide (groups walked recursively), table cells, chart labels, speaker notes, OCR of pictures | `slide_shape` → `sh5` (group child `sh4.2`) · `slide_table_cell` → `sh6:r2:c3` · `slide_notes` → `notes` · `page_or_slide` = slide number |
| PDF | PyMuPDF (native text) → Tesseract (OCR) | per page: native text blocks; if a page has < 30 chars of text it is rendered at 300 DPI and OCR'd | `pdf_block` → `b3` with `page_or_slide` = page · `extraction_method` = `native_text` or `ocr` |

## Standard record (identical for every format)
`file_name, file_type, location_type, location_index, page_or_slide, segment_id, text, extraction_method, confidence, context, style, warning`

- `segment_id` is unique and stable (`<file>#00042`). Use it to trace every PII hit back to its source.
- `context` = nearest preceding heading (docx) or slide title (pptx). `style` = Word paragraph style.
- `confidence` is the OCR mean word confidence (0-100); `None` for native text.
- **`warning` must be read.** It flags low-confidence OCR, a vector image that was not OCR'd, a page that failed, or an empty OCR page. Treat any warning on a segment as "PII risk, review".

## Things Person 4 must know
1. **The PDF is 100% scanned (no text layer), so all PII from it comes through OCR.** OCR can mis-read characters (at 150 DPI an email came back as `tlindqvist@cadencetg.com`). Use fuzzy matching, not strict regex only, for emails, phone numbers and IDs.
2. **PII also lives in images inside the DOCX** (screenshots of user tables with real-looking names). These arrive as `location_type="image"`, `extraction_method="ocr"`. Do not filter them out.
3. Each segment is one paragraph / cell / shape / OCR block, so a PII span never crosses segments. Neighbouring segments in the list are the preceding / succeeding context.
4. Redaction should work on `text` per `segment_id`, then rebuild with `result.full_text()`.
5. PDF OCR is slow (≈ 3-9 s per page, ≈ 4-5 min for the 35-page policy). Cache the result of `extract_file` while developing.
6. If `result.failures` is non-empty, do not pass that file downstream.
