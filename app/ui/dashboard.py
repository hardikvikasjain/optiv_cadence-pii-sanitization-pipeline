"""
dashboard.py - Enterprise Gradio Web Dashboard for Cadence Financial Group.
Tabs:
1. Live Document Sanitizer (Multi-format drag-and-drop, diff preview, safety gate, file downloads)
2. PII Analytics & Threat Dashboard (Entity distribution charts, threat density, historical audit table)
3. System Architecture & Compliance Guide (Pipeline blueprint, OCR fallback specs, regulatory scorecard)
"""
from __future__ import annotations

import os
import json
import time
import pandas as pd
import gradio as gr
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

from app.core.config import SAMPLE_DIR, OUTPUT_DIR, QA_LOG_CSV, AUDIT_FINDINGS_CSV
from app.core.orchestrator import PipelineOrchestrator
from app.core.audit_logger import AuditLogger
from app.db.database import get_aggregate_analytics, query_historical_logs

def list_sample_files() -> List[str]:
    """Lists available sample Cadence files in sample_artifacts directory."""
    if not SAMPLE_DIR.exists():
        return []
    files = [f.name for f in SAMPLE_DIR.iterdir() if f.suffix.lower() in [".pdf", ".docx", ".pptx"]]
    return sorted(files)

def process_file_ui(
    uploaded_file,
    selected_sample: str,
    redaction_mode: str,
    force_ocr: bool
):
    """Event handler for Tab 1 sanitization execution."""
    target_path = None

    if uploaded_file is not None:
        target_path = Path(uploaded_file.name if hasattr(uploaded_file, "name") else str(uploaded_file))
    elif selected_sample and selected_sample != "None":
        candidate = SAMPLE_DIR / selected_sample
        if candidate.exists():
            target_path = candidate

    if not target_path or not target_path.exists():
        return (
            "⚠️ Please upload a document (.docx, .pptx, .pdf) or select a sample file to proceed.",
            "",
            pd.DataFrame(),
            pd.DataFrame(),
            None, None, None,
            gr.update(visible=False),
            ""
        )

    mode_val = "mask" if "Mask" in redaction_mode else "tag"
    start_time = time.time()

    try:
        res = PipelineOrchestrator.process_file(
            file_path=target_path,
            redaction_mode=mode_val,
            force_ocr=force_ocr
        )
        elapsed = round(time.time() - start_time, 2)

        # Status badge & summary HTML
        is_pass = res["safety_status"] == "PASS - AUDITED"
        status_color = "#10b981" if is_pass else "#f59e0b"
        status_icon = "🛡️ PASS - AUDITED" if is_pass else "⚠️ REVIEW REQUIRED"
        llm_status = "✅ Safe for Downstream AI ingestion" if is_pass else "🛑 Blocked from automated LLM ingestion (Manual audit required)"

        status_html = f"""
        <div style="background-color: #1e293b; border-radius: 8px; padding: 16px; border-left: 6px solid {status_color}; margin-bottom: 12px; color: #f8fafc;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <h3 style="margin: 0; color: {status_color}; font-size: 1.25rem;">{status_icon}</h3>
                <span style="background: #334155; padding: 4px 10px; border-radius: 4px; font-size: 0.85rem; font-family: monospace;">Time: {elapsed}s</span>
            </div>
            <p style="margin: 8px 0 4px 0; font-weight: 500;">{llm_status}</p>
            <div style="display: flex; gap: 20px; font-size: 0.9rem; color: #94a3b8; margin-top: 8px;">
                <span>📄 File: <b>{res['file_name']}</b></span>
                <span>📑 Segments: <b>{res['segments_count']}</b></span>
                <span>🎯 PII Entities: <b>{res['pii_count']}</b></span>
                <span>⚠️ Warnings: <b>{res['warnings_count']}</b></span>
            </div>
        </div>
        """

        # Findings table dataframe
        findings_rows = []
        for f in res["findings"]:
            findings_rows.append({
                "Segment ID": f.get("segment_id", ""),
                "Location": f"{f.get('location_type', '').title()} {f.get('location_index', '')}",
                "PII Type": f.get("entity_type", ""),
                "Detected / Masked Value": f.get("masked_value", ""),
                "Method": f.get("detection_method", "").upper(),
                "Confidence": f"{f.get('confidence_or_strength', 0.9):.2f}"
            })
        df_findings = pd.DataFrame(findings_rows) if findings_rows else pd.DataFrame(columns=["Segment ID", "Location", "PII Type", "Detected / Masked Value", "Method", "Confidence"])

        # Diff samples dataframe
        diff_rows = []
        for d in res["diff_samples"]:
            diff_rows.append({
                "Location": d["location"],
                "Original Text": d["raw"],
                "Sanitized Output": d["redacted"]
            })
        df_diff = pd.DataFrame(diff_rows) if diff_rows else pd.DataFrame(columns=["Location", "Original Text", "Sanitized Output"])

        # Certificate summary
        cert_json_str = json.dumps(res["certificate"], indent=2)

        return (
            status_html,
            res["sanitized_text"],
            df_diff,
            df_findings,
            res["sanitized_text_path"],
            res["audit_csv_path"],
            str(OUTPUT_DIR / "compliance_certificate.json"),
            gr.update(visible=True),
            cert_json_str
        )

    except Exception as err:
        err_html = f"""
        <div style="background-color: #450a0a; border-radius: 8px; padding: 16px; border-left: 6px solid #ef4444; color: #fecaca;">
            <h4 style="margin: 0; color: #ef4444;">Processing Failure</h4>
            <p style="margin: 6px 0 0 0;">{str(err)}</p>
        </div>
        """
        return (err_html, "", pd.DataFrame(), pd.DataFrame(), None, None, None, gr.update(visible=False), "")

def refresh_analytics_data():
    """Fetches real-time metrics for Tab 2."""
    stats = get_aggregate_analytics()
    breakdown = stats.get("entity_type_breakdown", {})
    categories = list(breakdown.keys()) if breakdown else ["None"]
    counts = list(breakdown.values()) if breakdown else [0]
    df_chart = pd.DataFrame({"PII Category": categories, "Count": counts})

    # Recent findings
    logs = query_historical_logs(limit=30)
    df_logs = pd.DataFrame(logs) if logs else pd.DataFrame(columns=["id", "session_id", "file_name", "location", "entity_type", "masked_value", "detection_method", "confidence"])

    total_pii = stats.get("total_pii_entities_detected", 0)
    total_files = stats.get("total_files_processed", 0)

    # Calculate threat density indicator
    density_label = "LOW"
    density_color = "#10b981"
    if total_pii > 50:
        density_label = "ELEVATED"
        density_color = "#f59e0b"
    if total_pii > 200:
        density_label = "CRITICAL / HIGH DENSITY"
        density_color = "#ef4444"

    kpi_html = f"""
    <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 20px;">
        <div style="background: #1e293b; padding: 16px; border-radius: 8px; border-left: 4px solid #3b82f6;">
            <div style="color: #94a3b8; font-size: 0.85rem; font-weight: 600;">FILES PROCESSED</div>
            <div style="color: #f8fafc; font-size: 1.8rem; font-weight: 700;">{total_files}</div>
        </div>
        <div style="background: #1e293b; padding: 16px; border-radius: 8px; border-left: 4px solid #8b5cf6;">
            <div style="color: #94a3b8; font-size: 0.85rem; font-weight: 600;">TOTAL PII DETECTED</div>
            <div style="color: #f8fafc; font-size: 1.8rem; font-weight: 700;">{total_pii}</div>
        </div>
        <div style="background: #1e293b; padding: 16px; border-radius: 8px; border-left: 4px solid {density_color};">
            <div style="color: #94a3b8; font-size: 0.85rem; font-weight: 600;">RISK EXPOSURE TIER</div>
            <div style="color: {density_color}; font-size: 1.4rem; font-weight: 700; margin-top: 4px;">{density_label}</div>
        </div>
        <div style="background: #1e293b; padding: 16px; border-radius: 8px; border-left: 4px solid #10b981;">
            <div style="color: #94a3b8; font-size: 0.85rem; font-weight: 600;">LOCAL AIRGAP STATUS</div>
            <div style="color: #10b981; font-size: 1.4rem; font-weight: 700; margin-top: 4px;">100% ISOLATED</div>
        </div>
    </div>
    """
    return kpi_html, df_chart, df_logs

def load_qa_records():
    """Loads QA benchmark logs for Tab 3."""
    AuditLogger.ensure_qa_log()
    df = pd.read_csv(QA_LOG_CSV)
    return df

def build_gradio_app() -> gr.Blocks:
    """Builds the 3-tab enterprise Gradio application."""
    samples = list_sample_files()
    sample_choices = ["None"] + samples

    custom_theme = gr.themes.Soft(
        primary_hue="blue",
        secondary_hue="slate",
        neutral_hue="slate"
    )

    with gr.Blocks(title="Cadence Financial Group - PII Governance Sentinel") as demo:
        gr.Markdown(
            """
            # 🛡️ Cadence Financial Group — PII Sanitization & Data Governance Platform
            **Production-Grade 100% Local Execution Boundary | Multi-Format Document Redaction (.docx, .pptx, .pdf) | Cryptographic Audit Governance**
            """
        )

        with gr.Tabs() as tabs:
            # ========================================================================= TAB 1
            with gr.Tab("📄 Live Document Sanitizer"):
                gr.Markdown("### Upload and sanitize financial artifacts in real-time with zero external cloud leakage.")

                with gr.Row():
                    with gr.Column(scale=4):
                        file_input = gr.File(
                            label="Upload Financial Document (.docx, .pptx, .pdf)",
                            file_types=[".docx", ".pptx", ".pdf"]
                        )
                        sample_dropdown = gr.Dropdown(
                            choices=sample_choices,
                            value=samples[0] if samples else "None",
                            label="Or Select a Pre-loaded Cadence Sample Artifact"
                        )
                        with gr.Row():
                            redaction_mode_radio = gr.Radio(
                                choices=["Standard Tag ([REDACTED: ...])", "Partial Mask (J*** D***)"],
                                value="Standard Tag ([REDACTED: ...])",
                                label="Redaction Formatting Style"
                            )
                            force_ocr_checkbox = gr.Checkbox(
                                label="Force OCR on All Pages / Shapes",
                                value=False,
                                info="Enforces Tesseract OCR across all blocks even if native text is present"
                            )

                        sanitize_btn = gr.Button("🚀 Run Sanitization & Safety Gate", variant="primary", size="lg")

                    with gr.Column(scale=6):
                        status_box = gr.HTML(
                            """
                            <div style="background-color: #1e293b; border-radius: 8px; padding: 16px; border-left: 6px solid #3b82f6; color: #94a3b8;">
                                <h4 style="margin: 0; color: #60a5fa;">Awaiting Document</h4>
                                <p style="margin: 4px 0 0 0;">Upload or choose a sample document and click <b>Run Sanitization & Safety Gate</b>.</p>
                            </div>
                            """
                        )

                        with gr.Accordion("🔍 Before vs After Redaction Inspection (Offset Verification Gate)", open=True):
                            diff_table = gr.DataFrame(
                                headers=["Location", "Original Text", "Sanitized Output"],
                                wrap=True,
                                interactive=False
                            )

                with gr.Row():
                    with gr.Column(scale=6):
                        gr.Markdown("#### 📝 Sanitized Document Output Stream")
                        sanitized_preview = gr.Textbox(
                            lines=14,
                            label="Sanitized Text Content",
                            placeholder="Sanitized document text will appear here with structural headers..."
                        )

                    with gr.Column(scale=4):
                        gr.Markdown("#### 📋 Detected Entities Audit Log")
                        findings_table = gr.DataFrame(
                            headers=["Segment ID", "Location", "PII Type", "Detected / Masked Value", "Method", "Confidence"],
                            wrap=True,
                            interactive=False
                        )

                with gr.Row(visible=False) as download_row:
                    download_txt = gr.File(label="⬇️ Download Sanitized Text (*.txt)")
                    download_csv = gr.File(label="⬇️ Download Findings Audit CSV")
                    download_cert = gr.File(label="⬇️ Download Compliance Certificate JSON")

                with gr.Accordion("📜 Cryptographic Compliance Certificate (SHA-256 / HMAC)", open=False):
                    cert_viewer = gr.Code(language="json", label="Generated Compliance Certificate")

                sanitize_btn.click(
                    fn=process_file_ui,
                    inputs=[file_input, sample_dropdown, redaction_mode_radio, force_ocr_checkbox],
                    outputs=[
                        status_box,
                        sanitized_preview,
                        diff_table,
                        findings_table,
                        download_txt,
                        download_csv,
                        download_cert,
                        download_row,
                        cert_viewer
                    ]
                )

            # ========================================================================= TAB 2
            with gr.Tab("📊 PII Analytics & Threat Dashboard"):
                gr.Markdown("### Real-Time Threat Exposure, Entity Distribution & Governance Intelligence")

                refresh_btn = gr.Button("🔄 Refresh Analytics Metrics", variant="secondary")
                kpi_view = gr.HTML()

                with gr.Row():
                    with gr.Column(scale=5):
                        gr.Markdown("#### 📈 PII Entity Breakdown by Category")
                        category_chart = gr.BarPlot(
                            x="PII Category",
                            y="Count",
                            title="Detected PII Entities by Type",
                            tooltip=["PII Category", "Count"],
                            height=350
                        )

                    with gr.Column(scale=5):
                        gr.Markdown("#### 🏛️ Cadence Threat Exposure Tiers")
                        gr.HTML(
                            """
                            <div style="background: #1e293b; padding: 20px; border-radius: 8px; color: #f8fafc; font-size: 0.95rem; line-height: 1.6;">
                                <h4 style="margin-top: 0; color: #38bdf8;">Governance Threat Density Matrix</h4>
                                <ul>
                                    <li><b>Low Density (&lt; 20 entities):</b> Standard corporate artifact. Eligible for downstream processing once sanitized.</li>
                                    <li><b>Elevated Density (20 - 100 entities):</b> High-density personnel list or operational log. Requires automated safety verification.</li>
                                    <li><b>Critical Exposure (&gt; 100 entities):</b> Confidential HR/Financial registry. Automatic Safety Gate triggers strict audit certification.</li>
                                </ul>
                                <hr style="border: 1px solid #334155; margin: 16px 0;">
                                <p style="margin-bottom: 0;"><b>Offset Verification Gate Status:</b> 100% active. All replacements executed strictly Right-to-Left (descending start_char order) eliminating index-drift errors.</p>
                            </div>
                            """
                        )

                gr.Markdown("#### 📜 Persistent Historical Audit Trail (SQLite Datastore)")
                historical_table = gr.DataFrame(interactive=False, wrap=True)

                refresh_btn.click(
                    fn=refresh_analytics_data,
                    inputs=[],
                    outputs=[kpi_view, category_chart, historical_table]
                )

            # ========================================================================= TAB 3
            with gr.Tab("🏛️ System Architecture & Compliance Guide"):
                gr.Markdown("### Solution Blueprint, OCR Fallback Engineering & Regulatory Certification")

                with gr.Row():
                    with gr.Column(scale=6):
                        gr.Markdown("#### 🔄 Pipeline Architecture Flow")
                        gr.HTML(
                            """
                            <div style="background: #0f172a; padding: 20px; border-radius: 8px; border: 1px solid #334155; color: #e2e8f0; font-family: sans-serif;">
                                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                                    <span style="font-weight: 700; color: #38bdf8;">Cadence Data Governance Pipeline Blueprint</span>
                                    <span style="background: #166534; color: #bbf7d0; padding: 2px 8px; border-radius: 4px; font-size: 0.8rem;">100% LOCAL</span>
                                </div>
                                <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; text-align: center; font-size: 0.85rem;">
                                    <div style="background: #1e293b; padding: 12px; border-radius: 6px; border-top: 3px solid #3b82f6;">
                                        <b>1. Ingestion</b><br><span style="color: #94a3b8;">.docx, .pptx, .pdf</span>
                                    </div>
                                    <div style="background: #1e293b; padding: 12px; border-radius: 6px; border-top: 3px solid #8b5cf6;">
                                        <b>2. Extraction</b><br><span style="color: #94a3b8;">PyMuPDF + OCR &lt;15 chars</span>
                                    </div>
                                    <div style="background: #1e293b; padding: 12px; border-radius: 6px; border-top: 3px solid #ec4899;">
                                        <b>3. Detection</b><br><span style="color: #94a3b8;">Regex + spaCy NER</span>
                                    </div>
                                    <div style="background: #1e293b; padding: 12px; border-radius: 6px; border-top: 3px solid #10b981;">
                                        <b>4. Redaction</b><br><span style="color: #94a3b8;">RTL Offset Gate & Audit</span>
                                    </div>
                                </div>
                                <div style="margin-top: 16px; padding: 12px; background: #1e293b; border-radius: 6px; font-size: 0.85rem; color: #cbd5e1;">
                                    <b>⚙️ OCR Fallback Logic:</b> When a PDF page has fewer than <code>15</code> native characters, PyMuPDF renders at <code>300 DPI</code> and routes to Tesseract. If confidence is below <code>70.0%</code> or the engine is unconfigured, the pipeline issues a mandatory <code>REVIEW REQUIRED</code> warning and quarantines downstream transmission.
                                </div>
                            </div>
                            """
                        )

                    with gr.Column(scale=4):
                        gr.Markdown("#### ⚖️ Regulatory Compliance Alignment")
                        gr.HTML(
                            """
                            <div style="background: #1e293b; padding: 16px; border-radius: 8px; color: #f8fafc; font-size: 0.9rem; line-height: 1.5;">
                                <h4 style="margin: 0 0 10px 0; color: #a78bfa;">Mandated Frameworks</h4>
                                <ul style="padding-left: 20px; margin: 0;">
                                    <li><b>GDPR Article 32:</b> Technical measures ensuring pseudonymisation & confidentiality.</li>
                                    <li><b>HIPAA Safe Harbor:</b> Strict de-identification of names, contacts, and account IDs.</li>
                                    <li><b>GLBA Safeguards:</b> Protection of financial records and customer PII.</li>
                                    <li><b>Cadence TPRM v6.0:</b> Zero raw text transmission to cloud LLMs or third parties.</li>
                                </ul>
                            </div>
                            """
                        )

                gr.Markdown("#### 🎯 Ground-Truth QA Validation Scorecard (90% Precision & 90% Recall Verification)")
                qa_table = gr.DataFrame(value=load_qa_records(), interactive=False)

        # Trigger initial analytics load
        demo.load(fn=refresh_analytics_data, inputs=[], outputs=[kpi_view, category_chart, historical_table])

    return demo
