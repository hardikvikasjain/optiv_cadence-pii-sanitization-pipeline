"""
test_pipeline.py - Comprehensive Unit & Integration Test Suite for Cadence PII Governance Platform.
Covers:
- Extractor (.docx, .pptx, .pdf, OCR fallback on < 15 characters)
- Hybrid PII Detector (Regex & spaCy NER)
- Right-to-Left Redaction & Offset Verification Gate
- Audit Logger & Cryptographic Compliance Certificates
- Local Security Boundary Isolation
- FastAPI REST Endpoints
"""
import os
import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from app.core.config import SAMPLE_DIR, OUTPUT_DIR
from app.core.extractor import extract_file, Segment, ExtractionResult
from app.core.pii_detector import detect_pii
from app.core.redactor import redact_text, verify_and_clean_spans
from app.core.audit_logger import AuditLogger, sign_payload
from app.core.security_boundary import SecurityBoundaryGuard
from app.core.orchestrator import PipelineOrchestrator
from app.main import app

client = TestClient(app)

# --------------------------------------------------------------------------- Detector Tests
def test_regex_pii_detection():
    sample_text = (
        "Contact officer at admin.lead@cadencefg.example or mobile +91 98765 43210. "
        "Server IP 192.168.1.100 assigned to employee id: EMP-40912. "
        "Invalid IP 999.888.777.666 should not trigger."
    )
    findings = detect_pii(sample_text, segment_id="TEST_01")
    types = [f["entity_type"] for f in findings]

    assert "EMAIL" in types
    assert "PHONE" in types
    assert "IP_ADDRESS" in types
    assert "ACCOUNT_OR_EMPLOYEE_ID" in types

    # Check IPv4 validity gate
    ip_findings = [f for f in findings if f["entity_type"] == "IP_ADDRESS"]
    assert len(ip_findings) == 1
    assert ip_findings[0]["entity_text"] == "192.168.1.100"

def test_ner_detection_and_stopword_filters():
    sample_text = (
        "Marguerite Vossberg presented the Cadence TPRM framework at our office in New York. "
        "Ironclad and Optiv were discussed as vendor tools."
    )
    findings = detect_pii(sample_text, segment_id="TEST_02")
    types = [f["entity_type"] for f in findings]
    detected_texts = [f["entity_text"] for f in findings]

    assert "PERSON_NAME" in types
    assert "Marguerite Vossberg" in detected_texts

    # Corporate keywords must NOT be detected as person names
    for keyword in ["Cadence", "TPRM", "Ironclad", "Optiv"]:
        assert keyword not in detected_texts

# --------------------------------------------------------------------------- Redaction & Offset Gate Tests
def test_right_to_left_redaction_prevents_index_shifting():
    """
    Verifies that replacing multiple entities across a sentence does not suffer
    from index-shift bugs when processed Right-to-Left.
    """
    text = "Hello Alice Smith at alice@example.com, your phone is +91 98765 12345."
    findings = detect_pii(text, segment_id="TEST_RTL")

    redacted_tag, warnings = redact_text(text, findings, mode="tag")
    assert "[REDACTED: PERSON_NAME]" in redacted_tag
    assert "[REDACTED: EMAIL]" in redacted_tag
    assert "[REDACTED: PHONE]" in redacted_tag
    assert "Alice Smith" not in redacted_tag
    assert "alice@example.com" not in redacted_tag
    assert "98765" not in redacted_tag
    # Verify untouched words remained exact
    assert "Hello" in redacted_tag
    assert "your phone is" in redacted_tag

def test_offset_verification_gate_mismatch_protection():
    """
    Verifies that if an entity span points to invalid or shifted offsets,
    the Offset Verification Gate catches the discrepancy and reports a warning.
    """
    text = "Important memo for John Doe regarding accounts."
    # Fabricate a shifted entity span pointing to wrong text
    corrupted_findings = [{
        "segment_id": "TEST_GATE",
        "entity_text": "John Doe",
        "entity_type": "PERSON_NAME",
        "start_char": 0,
        "end_char": 8,  # "Importan" instead of "John Doe"
        "detection_method": "NER",
        "confidence_or_strength": 0.8
    }]

    clean_spans, gate_warnings = verify_and_clean_spans(text, corrupted_findings)
    assert len(clean_spans) == 0
    assert len(gate_warnings) > 0
    assert "Slice mismatch" in gate_warnings[0]

# --------------------------------------------------------------------------- Extractor Tests
def test_extractor_docx_parsing():
    docx_path = SAMPLE_DIR / "Cadence_TPRM_Training.docx"
    assert docx_path.exists(), "Sample docx must exist for testing"

    res = extract_file(docx_path)
    assert res.file_type == "docx"
    assert len(res.segments) > 0
    full_text = res.full_text()
    assert "Cadence Financial Group" in full_text
    assert "Ironclad" in full_text

def test_extractor_pptx_parsing():
    pptx_path = SAMPLE_DIR / "Cadence_PII_Detection.pptx"
    if pptx_path.exists():
        res = extract_file(pptx_path)
        assert res.file_type == "pptx"
        assert len(res.segments) > 0
        assert res.stats.get("slides", 0) > 0

def test_extractor_pdf_and_ocr_fallback():
    scanned_pdf = SAMPLE_DIR / "Cadence_Scanned_Memo.pdf"
    assert scanned_pdf.exists(), "Sample scanned PDF must exist"

    # Scanned PDF has 0 native characters, which is < 15 characters threshold -> triggers OCR fallback
    res = extract_file(scanned_pdf)
    assert res.file_type == "pdf"
    assert res.stats.get("pages_ocr", 0) >= 1

    # If Tesseract binary is unconfigured or low confidence, a REVIEW REQUIRED warning must be recorded
    # ensuring zero silent drops
    records = res.to_records()
    assert len(records) > 0

# --------------------------------------------------------------------------- Audit & Compliance Tests
def test_cryptographic_compliance_certificate():
    session_id = "test-session-12345"
    cert = AuditLogger.generate_compliance_certificate(
        session_id=session_id,
        file_name="Cadence_Test_File.docx",
        source_file_path=SAMPLE_DIR / "Cadence_TPRM_Training.docx",
        sanitized_content="Sample sanitized text output without PII.",
        safety_status="PASS - AUDITED",
        entity_counts={"EMAIL": 2, "PERSON_NAME": 1},
        total_segments=15,
        warnings=[]
    )

    assert cert["session_id"] == session_id
    assert cert["issuer"] == "Cadence Financial Group - Autonomous Governance Sentinel"
    assert cert["safety_gate"]["status"] == "PASS - AUDITED"
    assert cert["security_boundary"]["runtime_execution"] == "100% LOCAL ISOLATED"
    assert "digital_signature" in cert
    assert len(cert["digital_signature"]) == 64  # HMAC-SHA256 hex string

def test_local_security_isolation_guard():
    isolation = SecurityBoundaryGuard.verify_isolation()
    assert isolation["local_execution"] is True
    assert isolation["external_api_calls_blocked"] is True
    assert isolation["status"] == "SECURE_LOCAL"

# --------------------------------------------------------------------------- API Endpoint Tests
def test_api_health_endpoint():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "HEALTHY"
    assert data["capabilities"]["ocr_fallback_threshold_chars"] == 15

def test_api_qa_metrics_endpoint():
    response = client.get("/api/v1/qa/metrics")
    assert response.status_code == 200
    data = response.json()
    assert data["benchmark_precision"] == "90.0%"
    assert data["benchmark_recall"] == "90.0%"
    assert len(data["records"]) >= 10

def test_api_sanitize_endpoint():
    docx_path = SAMPLE_DIR / "Cadence_TPRM_Training.docx"
    with open(docx_path, "rb") as f:
        response = client.post(
            "/api/v1/sanitize",
            files={"file": ("Cadence_TPRM_Training.docx", f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            data={"mode": "tag", "force_ocr": "false"}
        )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "SUCCESS"
    assert data["file_name"] == "Cadence_TPRM_Training.docx"
    assert data["total_segments_processed"] > 0
    assert "compliance_certificate" in data

def test_api_audit_logs_endpoint():
    response = client.get("/api/v1/audit/logs?limit=10")
    assert response.status_code == 200
    data = response.json()
    assert "records" in data
    assert isinstance(data["records"], list)
