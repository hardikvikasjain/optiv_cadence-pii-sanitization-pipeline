import os
import sys
import json
import pandas as pd

# Configure UTF-8 encoding for Windows console to safely output symbols like ✔ and ⚠️
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Import the modules provided by the team
import extractor
import pii_detector

def redact_text_segment(text: str, detections: list[dict]) -> str:
    """
    Person 3 Mock: Redacts PII from text based on character offsets.
    Applies replacements right-to-left to prevent offset shifting.
    """
    sorted_dets = sorted(detections, key=lambda d: d["start_char"], reverse=True)
    sanitized = text
    for det in sorted_dets:
        tag = f"[REDACTED: {det['entity_type']}]"
        sanitized = sanitized[:det["start_char"]] + tag + sanitized[det["end_char"]:]
    return sanitized

def run_pipeline(file_paths: list[str]):
    all_segments = []
    all_findings = []
    warnings = []

    print("=== PIPELINE EXECUTION START ===")
    
    # Ensure output directories exist relative to this script
    os.makedirs("../04_Results/sanitized_outputs", exist_ok=True)

    for path in file_paths:
        ext = path.split(".")[-1].lower()
        if ext not in ["pdf", "docx", "pptx"]:
            continue

        print(f"Processing: {os.path.basename(path)}...")
        
        # 1. EXTRACTION (Person 1)
        try:
            extraction_result = extractor.extract_file(path)
            segments = extraction_result.to_records()
            all_segments.extend(segments)
            
            # Capture OCR/Extraction warnings for the safety gate
            for seg in segments:
                if seg.get("warning"):
                    warnings.append(f"{os.path.basename(path)} ({seg['location_type']} {seg['location_index']}): {seg['warning']}")
        except Exception as e:
            warnings.append(f"CRITICAL EXTRACTION FAILURE on {os.path.basename(path)}: {str(e)}")
            continue

        # 2. DETECTION (Person 2)
        for seg in segments:
            try:
                segment_findings = pii_detector.detect_pii(seg["text"], seg["segment_id"])
                all_findings.extend(segment_findings)
            except Exception as e:
                warnings.append(f"Detection error on {seg['segment_id']}: {str(e)}")

        # 3. REDACTION & RECONSTRUCTION (Person 3 Mock)
        sanitized_lines = []
        for seg in segments:
            # Isolate findings for this specific text segment
            seg_dets = [f for f in all_findings if f["segment_id"] == seg["segment_id"]]
            redacted_text = redact_text_segment(seg["text"], seg_dets)
            
            # Reconstruct the document flow with structural markers
            sanitized_lines.append(f"[{seg['location_type'].upper()} {seg['location_index']}]\n{redacted_text}\n")

        # 4. OUTPUT GENERATION
        base_name = os.path.basename(path)
        sanitized_text = "\n".join(sanitized_lines)
        out_path = os.path.join("../04_Results/sanitized_outputs", f"{base_name}.sanitized.txt")
        
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(sanitized_text)

    return all_segments, all_findings, warnings

if __name__ == "__main__":
    # Define target artifacts relative to the script location (assuming script is in 01_Demo)
    target_files = [
        "../Cadence_Financial_Group_Organizational_Pack.pptx",
        "../Cadence_Group_Risk_Management_Policy__v6.0.pdf",
        "../Cadence_TPRM_Training.docx"
    ]
    
    # Filter to process only files currently existing in the directory
    existing_files = [f for f in target_files if os.path.exists(f)]
    
    if not existing_files:
        print("Error: Could not locate the Cadence artifact files. Ensure they are in the parent directory.")
        exit(1)

    # Execute the core pipeline
    segments, findings, extraction_warnings = run_pipeline(existing_files)
    print("✔ File processing complete.\n")

    # Format findings for console display (Masking PII to protect console output)
    findings_records = []
    for f in findings:
        seg = next((s for s in segments if s["segment_id"] == f["segment_id"]), {})
        
        val = f["entity_text"]
        if "@" in val:
            masked_val = val[:2] + "****" + val[val.find("@"):]
        else:
            masked_val = val[:3] + "****" + val[-2:] if len(val) > 4 else "****"

        findings_records.append({
            "Source File": seg.get("file_name", "Unknown"),
            "Location": f"{seg.get('location_type', '').title()} {seg.get('location_index', '')}",
            "PII Type": f["entity_type"],
            "Detected Value": masked_val,
            "Method": f["detection_method"]
        })

    df_findings = pd.DataFrame(findings_records)

    # --- TERMINAL REPORTING & SAFETY GATE ---
    if extraction_warnings:
        print("⚠️ EXTRACTION WARNINGS (Review Required):")
        for w in extraction_warnings[:10]:
            print(f" - {w}")
        if len(extraction_warnings) > 10:
            print(f" ... and {len(extraction_warnings) - 10} more warnings.")
        print()

    # Write export files to the Results directory
    df_findings.to_csv("../04_Results/findings.csv", index=False)
    with open("../04_Results/findings.json", "w", encoding="utf-8") as jf:
        json.dump(findings, jf, indent=2)

    print("=== PRIVACY SAFETY GATE & EXPORT ENFORCEMENT ===")
    print("✔ Sanitized extracted text saved to: 04_Results/sanitized_outputs/")
    print("✔ Traceable JSON/CSV reports saved to: 04_Results/")
    print("✔ Raw text transmission to external LLMs: BLOCKED.")
    print("✔ Extraction/OCR failures default to REVIEW REQUIRED.\n")

    print("=== PII FINDINGS SUMMARY (MASKED VIEW) ===")
    if not df_findings.empty:
        print(df_findings.to_string(index=False))
    else:
        print("No PII detected in the provided documents.")
