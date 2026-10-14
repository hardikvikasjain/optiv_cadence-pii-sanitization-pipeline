"""
run_cadence_app.py - Root launcher for Cadence Financial Group PII Sanitization Platform.
Usage:
    python run_cadence_app.py
"""
import os
import sys
from pathlib import Path

# Set UTF-8 encoding for Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if __name__ == "__main__":
    from app.main import app
    import uvicorn
    port = int(os.environ.get("PORT", 7860))
    host = os.environ.get("HOST", "127.0.0.1")
    print(f"Starting Cadence Governance Platform on http://{host}:{port} ...")
    uvicorn.run(app, host=host, port=port)
