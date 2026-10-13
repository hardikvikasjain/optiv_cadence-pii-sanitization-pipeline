# Extraction test report

## Summary

| File | Processed | Segments | Failures | Coverage |
|---|---|---|---|---|
| Cadence_TPRM_Training.docx | 402 paragraphs / 16 tables | 1791 | 0 | 98.8% |
| Cadence_Financial_Group_Organizational_Pack.pptx | 9 slides / 278 shapes | 374 | 0 | 99.9% |
| Cadence_Group_Risk_Management_Policy__v6.0.pdf | 35 pages (35 OCR) | 1134 | 0 | n/a |

## Cadence_TPRM_Training.docx

- Time: 49s | backend: python-docx / python-pptx
- Segments: 1791 (native_text 1283, ocr 508)
- Stats: `{'tables': 16, 'table_cells': 1012, 'paragraphs': 402, 'headings': 35, 'textboxes': 1, 'headers': 4, 'footers': 2, 'images_found': 45, 'images_ocred': 40, 'images_duplicate_skipped': 5, 'segments': 1791, 'segments_ocr': 508}`
- Segments by type: `{'table_cell': 980, 'heading': 34, 'paragraph': 263, 'image': 508, 'textbox': 1, 'footer': 5}`
- Failures: 0
- File-level warnings: none
- Segments carrying a warning: 97
  - `Cadence_TPRM_Training.docx#00242` image p142:img1 pg/slide=None: low OCR confidence
  - `Cadence_TPRM_Training.docx#00318` image p169:img1 pg/slide=None: low OCR confidence
  - `Cadence_TPRM_Training.docx#00333` image p171:img1 pg/slide=None: low OCR confidence
  - `Cadence_TPRM_Training.docx#00348` image p173:img1 pg/slide=None: low OCR confidence
  - `Cadence_TPRM_Training.docx#00358` image p173:img1 pg/slide=None: low OCR confidence
  - `Cadence_TPRM_Training.docx#00368` image p173:img1 pg/slide=None: low OCR confidence
  - `Cadence_TPRM_Training.docx#00383` image p175:img1 pg/slide=None: low OCR confidence
  - `Cadence_TPRM_Training.docx#00388` image p175:img1 pg/slide=None: low OCR confidence
- Native-text coverage vs raw XML: 98.8% (75562 of 76495 alphanumeric chars in the raw XML)
- Quick regex sanity counts (NOT the PII detector): `{'email-like': 0, 'phone-like': 11, 'EMP-id': 0}`

## Cadence_Financial_Group_Organizational_Pack.pptx

- Time: 0s | backend: python-docx / python-pptx
- Segments: 374 (native_text 373, ocr 1)
- Stats: `{'slides': 9, 'shapes': 278, 'tables': 3, 'table_cells': 229, 'images_found': 9, 'images_ocred': 1, 'images_duplicate_skipped': 8, 'segments': 374, 'segments_ocr': 1}`
- Segments by type: `{'image': 1, 'slide_shape': 149, 'slide_table_cell': 224}`
- Failures: 0
- File-level warnings: none
- Segments carrying a warning: 1
  - `Cadence_Financial_Group_Organizational_Pack.pptx#00001` image sh3:img pg/slide=1: low OCR confidence
- Native-text coverage vs raw XML: 99.9% (6766 of 6775 alphanumeric chars in the raw XML)
- Quick regex sanity counts (NOT the PII detector): `{'email-like': 34, 'phone-like': 34, 'EMP-id': 0}`

## Cadence_Group_Risk_Management_Policy__v6.0.pdf

- Time: 265s | backend: {'pdf_text': 'pdfplumber', 'ocr': 'tesseract', 'ocr_dpi': 300}
- Segments: 1134 (native_text 0, ocr 1134)
- Stats: `{'pages': 35, 'pages_ocr': 35, 'segments': 1134, 'segments_ocr': 1134, 'ocr_mean_confidence': 90.9}`
- Segments by type: `{'pdf_block': 1134}`
- Failures: 0
- File-level warnings: none
- Segments carrying a warning: 51
  - `Cadence_Group_Risk_Management_Policy__v6.0.pdf#00128` pdf_block b11 pg/slide=6: low OCR confidence - PII may be mis-read
  - `Cadence_Group_Risk_Management_Policy__v6.0.pdf#00135` pdf_block b18 pg/slide=6: low OCR confidence - PII may be mis-read
  - `Cadence_Group_Risk_Management_Policy__v6.0.pdf#00143` pdf_block b26 pg/slide=6: low OCR confidence - PII may be mis-read
  - `Cadence_Group_Risk_Management_Policy__v6.0.pdf#00185` pdf_block b68 pg/slide=6: low OCR confidence - PII may be mis-read
  - `Cadence_Group_Risk_Management_Policy__v6.0.pdf#00193` pdf_block b76 pg/slide=6: low OCR confidence - PII may be mis-read
  - `Cadence_Group_Risk_Management_Policy__v6.0.pdf#00214` pdf_block b97 pg/slide=6: low OCR confidence - PII may be mis-read
  - `Cadence_Group_Risk_Management_Policy__v6.0.pdf#00400` pdf_block b5 pg/slide=12: low OCR confidence - PII may be mis-read
  - `Cadence_Group_Risk_Management_Policy__v6.0.pdf#00401` pdf_block b6 pg/slide=12: low OCR confidence - PII may be mis-read
- Native-text coverage vs raw XML: n/a (scanned PDF: no text layer to compare against)
- OCR mean confidence 90.9; 51 segments below 70 (listed with warnings above)
- Quick regex sanity counts (NOT the PII detector): `{'email-like': 157, 'phone-like': 158, 'EMP-id': 173}`
