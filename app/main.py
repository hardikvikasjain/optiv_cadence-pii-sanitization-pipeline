"""
main.py - Unified Server for Cadence PII Sanitization & Data Governance Platform.
Combines FastAPI RESTful endpoints with the 3-tab Gradio Enterprise Web Dashboard.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure root workspace is in sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import gradio as gr
import uvicorn

from app.api.routes import router as api_router
from app.ui.dashboard import build_gradio_app
from app.core.config import DATABASE_URL
from app.db.database import init_db

# Initialize database schema
init_db(DATABASE_URL)

# Create FastAPI application
app = FastAPI(
    title="Cadence Financial Group — PII Sanitization & Governance Platform",
    description="Enterprise 100% Local Multi-Format PII Extraction, Detection, and Offset-Safe Redaction Engine",
    version="2.0.0"
)

# Enable CORS for local integrations
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount REST API endpoints under /api/v1
app.include_router(api_router)

# Mount Gradio interactive 3-tab dashboard at the root ("/")
demo = build_gradio_app()
app = gr.mount_gradio_app(app, demo, path="/")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    host = os.environ.get("HOST", "0.0.0.0")
    print("=" * 75)
    print("🛡️  CADENCE FINANCIAL GROUP - PII SANITIZATION & GOVERNANCE PLATFORM")
    print("🔒  Strict Local Security Boundary: 100% Isolated Execution")
    print(f"🌐  Enterprise Dashboard & API: http://127.0.0.1:{port}")
    print(f"📚  Interactive Swagger Docs:   http://127.0.0.1:{port}/docs")
    print("=" * 75)
    uvicorn.run(app, host=host, port=port)
