"""
database.py - Local SQLite Database & Persistent Datastore for Cadence Governance.
Stores session execution logs, file metadata, segment counts, audit findings, and QA performance records.
"""
from __future__ import annotations

import sqlite3
import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

try:
    from app.core.config import DATABASE_URL
except ImportError:
    DATABASE_URL = "data/cadence_governance.db"

def get_connection(db_path: str = DATABASE_URL) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(db_path: str = DATABASE_URL):
    """Initializes SQLite database schema."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    # Sessions table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        timestamp TEXT NOT NULL,
        total_files INTEGER NOT NULL,
        total_segments INTEGER NOT NULL,
        total_pii INTEGER NOT NULL,
        safety_status TEXT NOT NULL,
        certificate_id TEXT
    );
    """)

    # Processed files table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS processed_files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        file_name TEXT NOT NULL,
        file_type TEXT NOT NULL,
        file_size_bytes INTEGER,
        sha256 TEXT,
        segments_count INTEGER NOT NULL,
        warnings_count INTEGER NOT NULL,
        safety_status TEXT NOT NULL,
        FOREIGN KEY (session_id) REFERENCES sessions (id)
    );
    """)

    # Audit findings table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS audit_findings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        file_name TEXT NOT NULL,
        segment_id TEXT NOT NULL,
        location TEXT,
        entity_type TEXT NOT NULL,
        masked_value TEXT NOT NULL,
        detection_method TEXT NOT NULL,
        confidence REAL NOT NULL,
        warning TEXT,
        FOREIGN KEY (session_id) REFERENCES sessions (id)
    );
    """)

    # QA performance metrics table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS qa_metrics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        test_id TEXT NOT NULL,
        precision REAL NOT NULL,
        recall REAL NOT NULL,
        f1_score REAL NOT NULL,
        evaluated_at TEXT NOT NULL,
        notes TEXT
    );
    """)

    conn.commit()
    conn.close()

def save_session_run(
    session_id: str,
    files_summary: List[Dict[str, Any]],
    findings: List[Dict[str, Any]],
    safety_status: str,
    certificate_id: Optional[str] = None,
    db_path: str = DATABASE_URL
):
    """Records full session execution run into SQLite datastore."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    total_segments = sum(f.get("segments_count", 0) for f in files_summary)
    total_pii = len(findings)
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

    cursor.execute("""
    INSERT OR REPLACE INTO sessions (id, timestamp, total_files, total_segments, total_pii, safety_status, certificate_id)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (session_id, timestamp, len(files_summary), total_segments, total_pii, safety_status, certificate_id))

    for f_info in files_summary:
        cursor.execute("""
        INSERT INTO processed_files (session_id, file_name, file_type, file_size_bytes, sha256, segments_count, warnings_count, safety_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            session_id,
            f_info.get("file_name", "Unknown"),
            f_info.get("file_type", ""),
            f_info.get("file_size_bytes", 0),
            f_info.get("sha256", ""),
            f_info.get("segments_count", 0),
            f_info.get("warnings_count", 0),
            f_info.get("safety_status", "REVIEW REQUIRED")
        ))

    for item in findings:
        cursor.execute("""
        INSERT INTO audit_findings (session_id, file_name, segment_id, location, entity_type, masked_value, detection_method, confidence, warning)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            session_id,
            item.get("file_name", "Unknown"),
            item.get("segment_id", "Unknown"),
            f"{item.get('location_type', '')} {item.get('location_index', '')}".strip(),
            item.get("entity_type", "PII"),
            item.get("masked_value", "***"),
            item.get("detection_method", "hybrid"),
            item.get("confidence_or_strength", 0.9),
            item.get("warning", "")
        ))

    conn.commit()
    conn.close()

def query_historical_logs(
    limit: int = 100,
    file_name: Optional[str] = None,
    entity_type: Optional[str] = None,
    db_path: str = DATABASE_URL
) -> List[Dict[str, Any]]:
    """Retrieves historical audit findings from SQLite."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    query = "SELECT * FROM audit_findings WHERE 1=1"
    params = []

    if file_name:
        query += " AND file_name LIKE ?"
        params.append(f"%{file_name}%")
    if entity_type:
        query += " AND entity_type = ?"
        params.append(entity_type)

    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    results = [dict(r) for r in rows]
    conn.close()
    return results

def get_aggregate_analytics(db_path: str = DATABASE_URL) -> Dict[str, Any]:
    """Computes aggregate analytics over processed records."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) as cnt FROM sessions")
    total_sessions = cursor.fetchone()["cnt"]

    cursor.execute("SELECT COUNT(*) as cnt FROM processed_files")
    total_files = cursor.fetchone()["cnt"]

    cursor.execute("SELECT COUNT(*) as cnt FROM audit_findings")
    total_pii = cursor.fetchone()["cnt"]

    cursor.execute("SELECT entity_type, COUNT(*) as cnt FROM audit_findings GROUP BY entity_type ORDER BY cnt DESC")
    breakdown_rows = cursor.fetchall()
    breakdown = {r["entity_type"]: r["cnt"] for r in breakdown_rows}

    cursor.execute("SELECT safety_status, COUNT(*) as cnt FROM sessions GROUP BY safety_status")
    status_rows = cursor.fetchall()
    statuses = {r["safety_status"]: r["cnt"] for r in status_rows}

    conn.close()
    return {
        "total_sessions": total_sessions,
        "total_files_processed": total_files,
        "total_pii_entities_detected": total_pii,
        "entity_type_breakdown": breakdown,
        "safety_status_breakdown": statuses
    }
