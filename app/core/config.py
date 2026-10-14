"""
config.py - Core configuration for Cadence PII Sanitization & Data Governance Platform.
Enforces 100% local execution boundaries, threshold standards, and storage locations.
"""
from pathlib import Path
import os

# Root directories
BASE_DIR = Path(__file__).resolve().parent.parent.parent
APP_DIR = BASE_DIR / "app"
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"
SAMPLE_DIR = DATA_DIR / "sample_artifacts"

# Ensure output & data directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
SAMPLE_DIR.mkdir(parents=True, exist_ok=True)

# Database
DATABASE_URL = str(DATA_DIR / "cadence_governance.db")

# Output Artifact Paths
AUDIT_FINDINGS_CSV = OUTPUT_DIR / "cadence_audit_findings.csv"
SANITIZED_OUTPUT_JSON = OUTPUT_DIR / "sanitized_output.json"
COMPLIANCE_CERTIFICATE_JSON = OUTPUT_DIR / "compliance_certificate.json"
QA_LOG_CSV = OUTPUT_DIR / "qa_log.csv"

# Pipeline & OCR Config
MIN_NATIVE_CHARS = 15       # Scanned PDF page with < 15 native non-space characters triggers Tesseract OCR fallback
LOW_OCR_CONF = 70.0         # Confidence < 70% triggers explicit "REVIEW REQUIRED" flag
OCR_DPI = 300               # Resolution for rendering scanned PDF pages
OCR_LANG = "eng"
MIN_IMAGE_PX = 80           # Filter out micro-icons from OCR queue

# Security & Compliance Boundary
LOCAL_EXECUTION_STRICT = True
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".pptx"}
MAX_FILE_SIZE_MB = 100

# Redaction Settings
REDACTION_TAG_FORMAT = "[REDACTED: {entity_type}]"
HMAC_SECRET_KEY = os.environ.get("CADENCE_SECURITY_HMAC_KEY", "cadence-financial-isolated-sec-2026")
