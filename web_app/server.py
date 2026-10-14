import os
import sys
import uuid
import json
import time
import shutil
import pandas as pd
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import extractor
import pii_detector
from web_app.redactor import create_sanitized_original_file, redact_text_rtl

app = FastAPI(title="Cadence Enterprise PII Sanitization Studio")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TEMP_JOBS_DIR = Path(__file__).resolve().parent / "jobs"
TEMP_JOBS_DIR.mkdir(exist_ok=True, parents=True)

STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_DIR.mkdir(exist_ok=True, parents=True)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

PRESETS = {
    "org_pack": {
        "id": "org_pack",
        "title": "Organizational Reference Pack",
        "format": "pptx",
        "filename": "Cadence_Financial_Group_Organizational_Pack.pptx",
        "description": "Executive chart with leadership roles, direct emails & contact lines",
        "badge": "PowerPoint Presentation"
    },
    "risk_policy": {
        "id": "risk_policy",
        "title": "Group Risk Management Policy v6.0",
        "format": "pdf",
        "filename": "Cadence_Group_Risk_Management_Policy__v6.0.pdf",
        "description": "Enterprise risk governance policy containing scanned appendix pages",
        "badge": "PDF Document (OCR Fallback)"
    },
    "tprm_training": {
        "id": "tprm_training",
        "title": "TPRM Training Guide",
        "format": "docx",
        "filename": "Cadence_TPRM_Training.docx",
        "description": "Third-Party Risk Management process guide with vendor tables & role audits",
        "badge": "Word Document"
    }
}

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        return HTMLResponse("<h1>Loading application...</h1>", status_code=200)
    with open(index_file, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.get("/api/presets")
async def get_presets():
    return list(PRESETS.values())

import socket
import platform

from web_app.redactor import create_sanitized_original_file, redact_text_rtl, get_file_sha256

@app.post("/api/process")
async def process_document(
    file: Optional[UploadFile] = File(None),
    preset_id: Optional[str] = Form(None),
    operator_name: Optional[str] = Form("Aarav"),
    operator_id: Optional[str] = Form("CAD-ANALYST-402"),
    department: Optional[str] = Form("Risk, Compliance & Security"),
    justification: Optional[str] = Form("Pre-LLM Sanitization & Safe External Ingestion")
):
    start_time = time.time()
    job_id = str(uuid.uuid4())[:8]
    job_dir = TEMP_JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    target_path = None
    original_filename = ""

    if preset_id and preset_id in PRESETS:
        preset_info = PRESETS[preset_id]
        preset_src = REPO_ROOT / preset_info["filename"]
        if not preset_src.exists():
            raise HTTPException(status_code=404, detail="Preset file not found on server")
        original_filename = preset_info["filename"]
        target_path = job_dir / original_filename
        shutil.copyfile(preset_src, target_path)
    elif file and file.filename:
        original_filename = file.filename
        target_path = job_dir / original_filename
        content = await file.read()
        with open(target_path, "wb") as f:
            f.write(content)
    else:
        raise HTTPException(status_code=400, detail="No file or valid preset provided")

    ext = str(target_path).split(".")[-1].lower()
    if ext not in ["docx", "pptx", "pdf"]:
        raise HTTPException(status_code=400, detail=f"Unsupported format .{ext}. Only .pdf, .docx, and .pptx are supported.")

    file_size_bytes = os.path.getsize(target_path)
    source_sha256 = get_file_sha256(str(target_path))

    # 1. Extraction
    try:
        extraction_result = extractor.extract_file(str(target_path))
        segments = extraction_result.to_records()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Extraction failed: {str(e)}")

    # 2. Hybrid Detection
    all_findings = []
    warnings = []
    for seg in segments:
        if seg.get("warning"):
            warnings.append(f"{seg['location_type']} {seg['location_index']}: {seg['warning']}")
        try:
            hits = pii_detector.detect_pii(seg["text"], segment_id=seg["segment_id"])
            for h in hits:
                h["location_type"] = seg.get("location_type")
                h["location_index"] = seg.get("location_index")
                h["file_name"] = original_filename
            all_findings.extend(hits)
        except Exception as e:
            warnings.append(f"Detection error in segment {seg['segment_id']}: {str(e)}")

    # 3. Create Text Redaction (LLM-safe text)
    sanitized_lines = []
    for seg in segments:
        seg_hits = [h for h in all_findings if h["segment_id"] == seg["segment_id"]]
        redacted = redact_text_rtl(seg["text"], seg_hits)
        sanitized_lines.append(f"[{seg['location_type'].upper()} {seg['location_index']}]\n{redacted}\n")

    sanitized_text_content = "\n".join(sanitized_lines)
    sanitized_txt_path = job_dir / f"{original_filename}.sanitized.txt"
    with open(sanitized_txt_path, "w", encoding="utf-8") as f:
        f.write(sanitized_text_content)

    # 4. Create Sanitized Original-Format File (.docx, .pptx, or .pdf) with font auto-scaling
    sanitized_native_filename = f"Sanitized_{original_filename}"
    sanitized_native_path = job_dir / sanitized_native_filename
    changelog = []
    try:
        _, changelog = create_sanitized_original_file(str(target_path), str(sanitized_native_path), all_findings)
        native_success = True
    except Exception as e:
        native_success = False
        native_error = str(e)

    sanitized_sha256 = get_file_sha256(str(sanitized_native_path)) if native_success else ""

    # 5. Export findings CSV and JSON
    findings_csv_path = job_dir / "findings.csv"
    findings_json_path = job_dir / "findings.json"

    with open(findings_json_path, "w", encoding="utf-8") as f:
        json.dump(all_findings, f, indent=2)

    findings_records = []
    for f in all_findings:
        val = f["entity_text"]
        if "@" in val:
            masked = val[:2] + "****" + val[val.find("@"):]
        else:
            masked = val[:3] + "****" + val[-2:] if len(val) > 4 else "****"
        findings_records.append({
            "Source File": original_filename,
            "Location": f"{f.get('location_type', '').title()} {f.get('location_index', '')}",
            "PII Type": f["entity_type"],
            "Entity Text": val,
            "Masked Text": masked,
            "Method": f["detection_method"],
            "Confidence": f.get("confidence_or_strength", 0.9)
        })
    df_findings = pd.DataFrame(findings_records)
    df_findings.to_csv(findings_csv_path, index=False)

    # 6. Export Transformation Changelog CSV & Audit Certificate
    changelog_csv_path = job_dir / "transformation_audit_log.csv"
    df_changelog = pd.DataFrame(changelog)
    if not df_changelog.empty:
        df_changelog.to_csv(changelog_csv_path, index=False)
    else:
        # Fallback empty structure
        pd.DataFrame(columns=["change_id", "location", "original_text", "redacted_text", "entity_type", "method"]).to_csv(changelog_csv_path, index=False)

    # 7. Operator Custody & Certificate Telemetry
    timestamp_utc = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    timestamp_local = time.strftime("%Y-%m-%d %H:%M:%S")
    custody = {
        "session_id": f"CAD-GOV-{job_id.upper()}",
        "operator_name": operator_name.strip() if operator_name else "Aarav",
        "operator_id": operator_id.strip() if operator_id else "CAD-ANALYST-402",
        "department": department.strip() if department else "Risk, Compliance & Security",
        "justification": justification.strip() if justification else "Pre-LLM Sanitization & Safe External Ingestion",
        "timestamp_utc": timestamp_utc,
        "timestamp_local": timestamp_local,
        "machine_host": socket.gethostname(),
        "platform_os": platform.platform(),
        "source_filename": original_filename,
        "source_sha256": source_sha256,
        "sanitized_sha256": sanitized_sha256,
        "total_modifications": len(changelog)
    }

    certificate_json_path = job_dir / "audit_certificate.json"
    with open(certificate_json_path, "w", encoding="utf-8") as f:
        json.dump({
            "custody": custody,
            "summary_scorecard": {
                "segments_scanned": len(segments),
                "pii_detected": len(all_findings),
                "modifications_applied": len(changelog),
                "safety_gate": "PASS" if len(warnings) == 0 else "REVIEW REQUIRED"
            },
            "changelog": changelog
        }, f, indent=2)

    # 8. Compute statistics
    counts_by_type = {}
    for f in all_findings:
        t = f["entity_type"]
        counts_by_type[t] = counts_by_type.get(t, 0) + 1

    processing_time = round(time.time() - start_time, 2)
    is_safe = len(warnings) == 0
    safety_status = "PASS" if is_safe else "REVIEW REQUIRED"

    # 9. Highlighted HTML preview snippet
    preview_pairs = []
    for seg in [s for s in segments if s["text"].strip()][:12]:
        seg_hits = [h for h in all_findings if h["segment_id"] == seg["segment_id"]]
        raw_text = seg["text"]
        sorted_hits = sorted(seg_hits, key=lambda x: x["start_char"], reverse=True)
        highlighted = raw_text
        for h in sorted_hits:
            s_idx = h["start_char"]
            e_idx = h["end_char"]
            etype = h["entity_type"]
            badge = f'<mark class="pii-tag pii-{etype.lower()}" title="{etype} ({h["detection_method"]})">{highlighted[s_idx:e_idx]}</mark>'
            highlighted = highlighted[:s_idx] + badge + highlighted[e_idx:]

        redacted = redact_text_rtl(raw_text, seg_hits)
        preview_pairs.append({
            "location": f"{seg['location_type'].title()} {seg['location_index']}",
            "raw_html": highlighted,
            "redacted_text": redacted
        })

    return {
        "job_id": job_id,
        "filename": original_filename,
        "file_type": ext.upper(),
        "file_size_formatted": f"{round(file_size_bytes / 1024, 1)} KB" if file_size_bytes < 1048576 else f"{round(file_size_bytes / 1048576, 2)} MB",
        "processing_time_sec": processing_time,
        "segments_total": len(segments),
        "pii_total": len(all_findings),
        "pii_by_type": counts_by_type,
        "custody": custody,
        "changelog": changelog,
        "safety_gate": {
            "status": safety_status,
            "safe_for_downstream_llm": is_safe,
            "warnings_count": len(warnings),
            "warnings_sample": warnings[:5]
        },
        "preview_pairs": preview_pairs,
        "findings": findings_records,
        "downloads": {
            "native": f"/api/download/{job_id}/file/{sanitized_native_filename}",
            "native_filename": sanitized_native_filename,
            "native_available": native_success,
            "text": f"/api/download/{job_id}/file/{original_filename}.sanitized.txt",
            "csv": f"/api/download/{job_id}/file/findings.csv",
            "json": f"/api/download/{job_id}/file/findings.json",
            "changelog_csv": f"/api/download/{job_id}/file/transformation_audit_log.csv",
            "certificate_json": f"/api/download/{job_id}/file/audit_certificate.json"
        }
    }

MIME_TYPES = {
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "txt": "text/plain; charset=utf-8",
    "csv": "text/csv; charset=utf-8",
    "json": "application/json; charset=utf-8"
}

@app.get("/api/download/{job_id}/file/{filename}")
@app.get("/api/download/{job_id}/{download_type}")
async def download_file(job_id: str, filename: Optional[str] = None, download_type: Optional[str] = None):
    job_dir = TEMP_JOBS_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(status_code=404, detail="Session expired or not found")

    target_file = None
    if filename:
        target_file = job_dir / filename
    elif download_type == "native":
        candidates = list(job_dir.glob("Sanitized_*"))
        if candidates:
            target_file = candidates[0]
    elif download_type == "text":
        candidates = list(job_dir.glob("*.sanitized.txt"))
        if candidates:
            target_file = candidates[0]
    elif download_type == "csv":
        target_file = job_dir / "findings.csv"
    elif download_type == "json":
        target_file = job_dir / "findings.json"

    if not target_file or not target_file.exists():
        raise HTTPException(status_code=404, detail="Requested file not available")

    ext = target_file.name.split(".")[-1].lower()
    media_type = MIME_TYPES.get(ext, "application/octet-stream")

    return FileResponse(
        path=str(target_file),
        filename=target_file.name,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{target_file.name}"'}
    )

@app.post("/api/save-to-downloads/{job_id}")
async def save_to_downloads(job_id: str):
    """Copies the sanitized document directly into the user's system Downloads folder."""
    job_dir = TEMP_JOBS_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(status_code=404, detail="Session expired or not found")

    candidates = list(job_dir.glob("Sanitized_*"))
    if not candidates:
        raise HTTPException(status_code=404, detail="Sanitized document not available")

    src_file = candidates[0]
    user_downloads_dir = Path.home() / "Downloads"
    user_downloads_dir.mkdir(exist_ok=True, parents=True)

    dest_file = user_downloads_dir / src_file.name
    try:
        shutil.copyfile(src_file, dest_file)
    except PermissionError:
        # If the user currently has the file open in PowerPoint / Word, save with timestamp
        ts_suffix = time.strftime("%H%M%S")
        dest_file = user_downloads_dir / f"{src_file.stem}_{ts_suffix}{src_file.suffix}"
        shutil.copyfile(src_file, dest_file)

    return {
        "status": "success",
        "filename": dest_file.name,
        "saved_path": str(dest_file)
    }

@app.get("/api/view-sanitized/{job_id}")
async def view_sanitized_document(job_id: str):
    """Returns the full sanitized document structure for the in-browser visual reader."""
    job_dir = TEMP_JOBS_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(status_code=404, detail="Session expired or not found")

    # Read sanitized text
    txt_candidates = list(job_dir.glob("*.sanitized.txt"))
    if not txt_candidates:
        raise HTTPException(status_code=404, detail="Sanitized content not found")

    with open(txt_candidates[0], "r", encoding="utf-8") as f:
        full_text = f.read()

    # Parse sections
    sections = []
    current_title = "Document Start"
    current_lines = []

    for line in full_text.split("\n"):
        if line.startswith("[") and ("]" in line) and any(kw in line for kw in ["SLIDE", "PAGE", "PARAGRAPH", "TABLE"]):
            if current_lines:
                sections.append({
                    "title": current_title,
                    "content": "\n".join(current_lines).strip()
                })
                current_lines = []
            current_title = line.strip("[]")
        else:
            current_lines.append(line)

    if current_lines:
        sections.append({
            "title": current_title,
            "content": "\n".join(current_lines).strip()
        })

    return {
        "job_id": job_id,
        "filename": txt_candidates[0].name.replace(".sanitized.txt", ""),
        "sections": [s for s in sections if s["content"]],
        "full_text": full_text
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web_app.server:app", host="127.0.0.1", port=8000, reload=True)
