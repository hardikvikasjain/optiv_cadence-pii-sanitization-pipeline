"""
orchestrator.py - Master Pipeline Orchestrator for Cadence Financial Group.
Executes multi-format extraction, hybrid PII detection, RTL redaction with Offset Verification Gate,
safety gate evaluation, SQLite persistence, and cryptographic compliance certification.
"""
from __future__ import annotations

import os
import uuid
import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from app.core.config import OUTPUT_DIR, SAMPLE_DIR
from app.core.extractor import extract_file, ExtractionResult
from app.core.pii_detector import detect_pii
from app.core.redactor import redact_text, generate_masked_representation
from app.core.audit_logger import AuditLogger, compute_sha256_file
from app.core.security_boundary import SecurityBoundaryGuard
from app.db.database import save_session_run, init_db

# Initialize database schema on load
init_db()

class PipelineOrchestrator:
    """Enterprise Pipeline Orchestration Engine."""

    @classmethod
    def process_file(
        cls,
        file_path: Path | str,
        session_id: Optional[str] = None,
        redaction_mode: str = "tag",  # "tag" or "mask"
        force_ocr: bool = False
    ) -> Dict[str, Any]:
        """
        Processes a single artifact end-to-end:
        Extraction -> Hybrid Detection -> RTL Redaction -> Safety Gate -> Audit & Certificate
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Target file does not exist: {file_path}")

        session_id = session_id or str(uuid.uuid4())
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        file_name = file_path.name
        file_ext = file_path.suffix.lower()
        file_size = file_path.stat().st_size
        file_sha256 = compute_sha256_file(file_path)

        # 1. Extraction (Multi-format + OCR Fallback)
        extraction_res: ExtractionResult = extract_file(file_path, force_ocr=force_ocr)
        segments = extraction_res.to_records()

        # Collect extraction warnings
        warnings: List[str] = list(extraction_res.warnings)
        for fail in extraction_res.failures:
            warnings.append(f"EXTRACTION FAILURE at {fail.get('location')}: {fail.get('error')}")

        for seg in segments:
            if seg.get("warning"):
                warnings.append(f"{seg['location_type']} {seg['location_index']}: {seg['warning']}")

        # 2. Hybrid PII Detection
        all_findings: List[Dict[str, Any]] = []
        finding_seq = 0

        for seg in segments:
            text = seg.get("text", "")
            if not text:
                continue
            seg_id = seg.get("segment_id", "unknown")
            hits = detect_pii(text, segment_id=seg_id)

            for hit in hits:
                finding_seq += 1
                f_item = dict(hit)
                f_item["finding_id"] = f"PII-{session_id[:8]}-{finding_seq:04d}"
                f_item["session_id"] = session_id
                f_item["timestamp"] = timestamp
                f_item["file_name"] = file_name
                f_item["location_type"] = seg.get("location_type", "")
                f_item["location_index"] = seg.get("location_index", "")
                f_item["page_or_slide"] = seg.get("page_or_slide", "")
                f_item["warning"] = seg.get("warning", "")
                f_item["masked_value"] = generate_masked_representation(hit["entity_text"], hit["entity_type"])
                all_findings.append(f_item)

        # 3. Offset-Safe Redaction & Verification Gate
        findings_by_seg: Dict[str, List[Dict[str, Any]]] = {}
        for f in all_findings:
            findings_by_seg.setdefault(f["segment_id"], []).append(f)

        sanitized_blocks: List[str] = []
        diff_samples: List[Dict[str, str]] = []

        for seg in segments:
            raw_text = seg.get("text", "")
            seg_hits = findings_by_seg.get(seg.get("segment_id"), [])

            if raw_text and seg_hits:
                redacted, gate_warns = redact_text(raw_text, seg_hits, mode=redaction_mode)
                warnings.extend(gate_warns)
                seg["redacted_text"] = redacted

                if len(diff_samples) < 5 and raw_text != redacted:
                    diff_samples.append({
                        "location": f"{seg.get('location_type', '').title()} {seg.get('location_index', '')}",
                        "raw": raw_text[:200] + ("..." if len(raw_text) > 200 else ""),
                        "redacted": redacted[:200] + ("..." if len(redacted) > 200 else "")
                    })
            else:
                redacted = raw_text
                seg["redacted_text"] = redacted

            if redacted:
                loc_header = f"[{seg.get('location_type', 'SEGMENT').upper()} {seg.get('location_index', '')}]"
                sanitized_blocks.append(f"{loc_header}\n{redacted}\n")

        full_sanitized_text = "\n".join(sanitized_blocks)

        # 4. Safety Gate Evaluation
        # If any OCR errors, low-confidence warnings, or failure flags are present -> REVIEW REQUIRED
        has_warnings = len(warnings) > 0
        safety_status = "REVIEW REQUIRED" if has_warnings else "PASS - AUDITED"

        # Entity count distribution
        entity_counts: Dict[str, int] = {}
        for f in all_findings:
            etype = f["entity_type"]
            entity_counts[etype] = entity_counts.get(etype, 0) + 1

        # 5. Export Outputs & Cryptographic Certificate
        sanitized_out_dir = OUTPUT_DIR / "sanitized_outputs"
        sanitized_out_dir.mkdir(parents=True, exist_ok=True)
        sanitized_txt_file = sanitized_out_dir / f"{file_path.stem}_sanitized.txt"
        sanitized_txt_file.write_text(full_sanitized_text, encoding="utf-8")

        # Export findings CSV
        csv_path = AuditLogger.export_audit_findings_csv(all_findings, session_id=session_id)

        # Generate cryptographic compliance certificate
        cert_data = AuditLogger.generate_compliance_certificate(
            session_id=session_id,
            file_name=file_name,
            source_file_path=file_path,
            sanitized_content=full_sanitized_text,
            safety_status=safety_status,
            entity_counts=entity_counts,
            total_segments=len(segments),
            warnings=warnings
        )

        # Export structured sanitized_output.json
        structured_export = {
            "session_id": session_id,
            "file_name": file_name,
            "processed_at": timestamp,
            "safety_gate_verdict": safety_status,
            "total_segments": len(segments),
            "total_pii_detected": len(all_findings),
            "entity_counts": entity_counts,
            "segments": segments
        }
        AuditLogger.export_sanitized_output_json(structured_export)
        AuditLogger.ensure_qa_log()

        # 6. SQLite Database Storage
        file_summary = [{
            "file_name": file_name,
            "file_type": file_ext,
            "file_size_bytes": file_size,
            "sha256": file_sha256,
            "segments_count": len(segments),
            "warnings_count": len(warnings),
            "safety_status": safety_status
        }]
        save_session_run(
            session_id=session_id,
            files_summary=file_summary,
            findings=all_findings,
            safety_status=safety_status,
            certificate_id=cert_data["certificate_id"]
        )

        return {
            "session_id": session_id,
            "file_name": file_name,
            "file_type": file_ext,
            "file_size_bytes": file_size,
            "sha256": file_sha256,
            "segments_count": len(segments),
            "pii_count": len(all_findings),
            "entity_counts": entity_counts,
            "safety_status": safety_status,
            "safe_for_downstream_llm": (safety_status == "PASS - AUDITED"),
            "warnings_count": len(warnings),
            "warnings": warnings,
            "diff_samples": diff_samples,
            "sanitized_text": full_sanitized_text,
            "sanitized_text_path": str(sanitized_txt_file),
            "audit_csv_path": str(csv_path),
            "certificate": cert_data,
            "findings": all_findings
        }
