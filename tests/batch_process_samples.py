import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.orchestrator import PipelineOrchestrator
from app.core.config import SAMPLE_DIR, OUTPUT_DIR
from app.db.database import get_aggregate_analytics

def main():
    files = [
        "Cadence_TPRM_Training.docx",
        "Cadence_Financial_Group_Organizational_Pack.pdf",
        "Cadence_PII_Detection.pptx",
        "Cadence_Scanned_Memo.pdf",
        "Cadence_Group_Risk_Management_Policy__v6.0.pdf",
        "Cadence_TPRM_Training.pdf"
    ]

    print("=" * 80)
    print("CADENCE FINANCIAL GROUP - PIPELINE INTEGRATION & BATCH RUN")
    print("=" * 80)

    for fn in files:
        p = SAMPLE_DIR / fn
        if not p.exists():
            print(f"Skipping {fn} (not found in sample directory)")
            continue

        print(f"\nProcessing: {fn} ({p.stat().st_size / 1024:.1f} KB)...")
        res = PipelineOrchestrator.process_file(p)
        print(f"  Safety Gate:       {res['safety_status']}")
        print(f"  Segments Extracted:{res['segments_count']}")
        print(f"  PII Detected:      {res['pii_count']}")
        print(f"  Breakdown:         {res['entity_counts']}")
        print(f"  Warnings Logged:   {res['warnings_count']}")
        print(f"  Cert Digital Sig:  {res['certificate']['digital_signature'][:24]}...")

    print("\n" + "=" * 80)
    print("AGGREGATE ANALYTICS & DATABASE STORE STATUS:")
    analytics = get_aggregate_analytics()
    for k, v in analytics.items():
        print(f"  {k}: {v}")
    print("=" * 80)

if __name__ == "__main__":
    main()
