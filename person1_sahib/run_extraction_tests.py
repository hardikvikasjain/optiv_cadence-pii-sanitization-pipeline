"""
run_extraction_tests.py -- step 7: run extractor.py on the three sample files and record what was processed.

    python run_extraction_tests.py "<folder with the 3 sample files>"

Writes (next to this script):
    extraction_test_report.md   counts, failures, warnings, coverage check
    extraction_output.json      every segment from every file (feed this to PII detection while testing)
"""
import json
import re
import sys
import time
import zipfile
from collections import Counter
from pathlib import Path

from extractor import extract_file

HERE = Path(__file__).parent
SAMPLES = ["Cadence_TPRM_Training.docx",
           "Cadence_Financial_Group_Organizational_Pack.pptx",
           "Cadence_Group_Risk_Management_Policy__v6.0.pdf"]

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
alnum = lambda s: len(re.sub(r"[^0-9A-Za-z]", "", s))


def raw_text_chars(path: Path) -> int:
    """Independent count of text characters stored in the file's XML (ground truth for coverage)."""
    from lxml import etree
    total = 0
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            if path.suffix == ".docx" and re.fullmatch(r"word/(document|header\d*|footer\d*|footnotes|endnotes)\.xml", n):
                root = etree.fromstring(z.read(n))
                for t in root.iter(W + "t"):
                    if any(a.tag.endswith("}Fallback") for a in t.iterancestors()):
                        continue                       # duplicate of mc:Choice
                    total += alnum(t.text or "")
            elif path.suffix == ".pptx" and re.fullmatch(r"ppt/(slides/slide\d+|notesSlides/notesSlide\d+)\.xml", n):
                root = etree.fromstring(z.read(n))
                for t in root.iter(A + "t"):
                    total += alnum(t.text or "")
    return total


PII_PATTERNS = {                       # informational only - real detection is Person 4's job
    "email-like": r"[\w.+-]+@[\w-]+\.[\w.-]+",
    "phone-like": r"\+?\d[\d\s().-]{8,}\d",
    "EMP-id": r"\bEMP-\d{4,6}\b",
}


def main(folder: str):
    folder = Path(folder)
    lines = ["# Extraction test report", ""]
    all_records, summary = [], []
    for name in SAMPLES:
        p = folder / name
        t0 = time.time()
        try:
            r = extract_file(p)
        except Exception as e:                           # record, don't crash
            lines += [f"## {name}", f"**FAILED TO PROCESS:** `{e!r}`", ""]
            summary.append((name, "FAILED", "-", "-", "-"))
            continue
        secs = time.time() - t0
        recs = r.to_records()
        all_records += recs
        methods = Counter(s.extraction_method for s in r.segments)
        types = Counter(s.location_type for s in r.segments)
        lines += [f"## {name}", "",
                  f"- Time: {secs:.0f}s | backend: {r.backend or 'python-docx / python-pptx'}",
                  f"- Segments: {len(recs)} (native_text {methods.get('native_text', 0)}, ocr {methods.get('ocr', 0)})",
                  f"- Stats: `{r.stats}`",
                  f"- Segments by type: `{dict(types)}`",
                  f"- Failures: {len(r.failures)}" + (f" -> `{r.failures}`" if r.failures else ""),
                  f"- File-level warnings: {r.warnings or 'none'}"]
        warned = [s for s in r.segments if s.warning]
        lines.append(f"- Segments carrying a warning: {len(warned)}")
        for s in warned[:8]:
            lines.append(f"  - `{s.segment_id}` {s.location_type} {s.location_index} pg/slide={s.page_or_slide}: {s.warning}")

        cov = "n/a (scanned PDF: no text layer to compare against)"
        if p.suffix in (".docx", ".pptx"):
            raw = raw_text_chars(p)
            native = sum(alnum(s.text) for s in r.segments if s.extraction_method == "native_text"
                         and s.location_type != "image")
            cov = f"{100 * native / raw:.1f}% ({native} of {raw} alphanumeric chars in the raw XML)" if raw else "n/a"
        lines.append(f"- Native-text coverage vs raw XML: {cov}")

        if r.file_type == "pdf":
            low = [s for s in r.segments if s.confidence is not None and s.confidence < 70]
            lines.append(f"- OCR mean confidence {r.stats.get('ocr_mean_confidence')}; "
                         f"{len(low)} segments below 70 (listed with warnings above)")

        text = r.full_text()
        pii = {k: len(re.findall(v, text)) for k, v in PII_PATTERNS.items()}
        lines += [f"- Quick regex sanity counts (NOT the PII detector): `{pii}`", ""]
        unit = {"docx": f"{r.stats.get('paragraphs', 0)} paragraphs / {r.stats.get('tables', 0)} tables",
                "pptx": f"{r.stats.get('slides', 0)} slides / {r.stats.get('shapes', 0)} shapes",
                "pdf": f"{r.stats.get('pages', 0)} pages ({r.stats.get('pages_ocr', 0)} OCR)"}[r.file_type]
        summary.append((name, unit, len(recs), len(r.failures), cov.split(" ")[0]))

    head = ["## Summary", "", "| File | Processed | Segments | Failures | Coverage |", "|---|---|---|---|---|"]
    head += [f"| {a} | {b} | {c} | {d} | {e} |" for a, b, c, d, e in summary] + [""]
    lines[2:2] = head
    (HERE / "extraction_test_report.md").write_text("\n".join(lines), encoding="utf-8")
    (HERE / "extraction_output.json").write_text(json.dumps(all_records, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
