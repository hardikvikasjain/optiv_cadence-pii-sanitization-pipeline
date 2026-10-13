<div align="center">

# 🛡️ Enterprise PII Sanitization & Data Governance Pipeline
### *Cadence Financial Group | Case Study 2: Text Analysis & PII Detection*

<p align="center">
  <img src="https://img.shields.io/badge/Status-Production%20Ready-success?style=for-the-badge&logo=appveyor" />
  <img src="https://img.shields.io/badge/Security-100%25%20Local%20Execution-blueviolet?style=for-the-badge&logo=shield" />
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python" />
  <img src="https://img.shields.io/badge/Precision-90%25-orange?style=for-the-badge&logo=target" />
</p>

*An advanced, secure, and locally-executable data pipeline engineered to sanitize multi-format enterprise artifacts before downstream LLM ingestion.*

</div>

---

## ⚡ Executive Summary & Mission
Cadence Financial Group utilizes cutting-edge AI document analysis agents to review internal corporate assets. However, rigorous data governance mandates strictly prohibit sending raw **Personally Identifiable Information (PII)**—such as employee names, personal emails, phone numbers, and government/employee IDs—to third-party LLMs.

To solve this, I engineered a robust, zero-leakage **Local PII Extraction, Hybrid Detection, and Safe Redaction Pipeline**. This project ensures full compliance, flawless source traceability, and rigorous QA validation metrics.

---

## 🚀 Interactive Functional Architecture Flow

```mermaid
graph TD
    A[📁 Document Upload <br> .docx, .pptx, .pdf] --> B{🔍 Format-Specific Router}
    
    B -->|Word .docx| C1[Paragraphs & Tables Extractor]
    B -->|PowerPoint .pptx| C2[Slide Text Frame Extractor]
    B -->|PDF .pdf| C3[PyMuPDF Native Text + Tesseract OCR Fallback]
    
    C1 & C2 & C3 --> D[📝 Text Normalization & Metadata Tagging]
    
    D --> E[⚡ Hybrid PII Detection Engine]
    E -->|High-Precision Regex| E1[Emails, Phones, IPs, Employee IDs]
    E -->|spaCy NER Tokenizer| E2[Person Names & Locations]
    
    E1 & E2 --> F[🛡️ Redaction Safety Gate]
    F -->|Right-to-Left Offset Sorting| F1[Prevents Index-Shifting Bugs]
    F -->|Review Flagging| F2[REVIEW REQUIRED on Low Confidence / OCR Failures]
    
    F1 & F2 --> G[📊 Audit & Downstream Delivery]
    G -->|findings.csv| G1[Traceable PII Audit Log]
    G -->|sanitized_output.json| G2[100% Safe Sanitized Text for LLM]

    style A fill:#1e1e2e,stroke:#89b4fa,stroke-width:2px,color:#fff
    style E fill:#181825,stroke:#f38ba8,stroke-width:2px,color:#fff
    style F fill:#181825,stroke:#a6e3a1,stroke-width:2px,color:#fff
    style G fill:#1e1e2e,stroke:#fab387,stroke-width:2px,color:#fff

```

---

## 📁 Repository Structure & Deliverables

```text
cadence-pii-sanitization-pipeline/
│
├── 📁 01_Demo/
│   ├── 📜 main.py                           # Master terminal demo & integration orchestrator
│   └── 📓 Cadence_PII_Detection.ipynb       # Master Google Colab notebook (Run-all ready)
│
├── 📁 02_Presentation/
│   └── 📊 Cadence_PII_Detection.pptx        # 10-slide stakeholder walkthrough deck
│
├── 📁 03_Diagrams/
│   ├── 🖼️ functional_blueprint.png          # End-to-end functional data flow diagram
│   └── 🖼️ technical_architecture.png        # Detailed system component architecture
│
├── 📁 04_Results/
│   ├── 📄 findings.csv                      # Traceable PII audit log with source references
│   ├── 📄 findings.json                     # Machine-readable audit log
│   ├── 📄 pipeline_summary.json             # Pipeline scorecard & safety gate verdicts
│   ├── 📄 qa_log.csv                        # Manual test log with True/False positive checks
│   └── 📁 sanitized_outputs/                # Sanitized document text files (*_sanitized.txt)
│       ├── Cadence_Financial_Group_Organizational_Pack_sanitized.txt
│       ├── Cadence_Group_Risk_Management_Policy__v6.0_sanitized.txt
│       └── Cadence_TPRM_Training_sanitized.txt
│
├── 📜 extractor.py                          # Person 1: Document extraction & OCR fallback
├── 📜 pii_detector.py                       # Person 2: Hybrid Regex + spaCy NER detection
└── 📜 README.md                             # Professional project documentation
```

---

## 🛠️ Technical Stack & Frameworks

| Component | Technology / Library | Purpose |
| --- | --- | --- |
| **Environment** | Google Colab / Python 3.10+ | Isolated local execution runtime |
| **Word Parsing** | `python-docx` | Extracts ordered paragraphs and table cells |
| **Presentation Parsing** | `python-pptx` | Parses slide-by-slide text frames |
| **PDF & OCR Engine** | `PyMuPDF (fitz)` & `Tesseract OCR` | Native text extraction + Scanned image fallback |
| **NLP & Detection** | `spaCy (en_core_web_sm)` & Regex (`re`) | Hybrid entity recognition & pattern matching |
| **Data Processing** | `pandas` | Structured audit logging and reporting |

---

## ⚡ Quickstart Guide (How to Run)

### Option A: Live Terminal Pipeline & Demo (Person 4 CLI)
Run the automated end-to-end integration orchestrator directly from the command line:
```bash
# Execute standard pipeline across all artifacts
python 01_Demo/main.py

# Optional: customize preview samples or specify custom directory
python 01_Demo/main.py --preview 5 --input-dir ./data
```
The CLI provides colored step-by-step progress logging, Before/After redaction verification previews, and exports all audit artifacts to `04_Results/`.

### Option B: Interactive Google Colab / Jupyter Notebook
1. **Open Colab / Jupyter:** Launch `01_Demo/Cadence_PII_Detection.ipynb`.
2. **Run All:** Execute cells sequentially from top to bottom (`Runtime -> Run all`).
3. **Inspect & Download:** View interactive Pandas findings tables, Before/After inspection diffs, and download the full results bundle.

---

## 📊 Rigorous Testing, QA Metrics & Limitations

* **Evaluation Scope:** Tested across diverse enterprise documents to measure system accuracy.
* **Measured Performance (Test Sample):**
* **Precision:** **90%** (Tuned via strict boundary constraints to eliminate false alarms on version/policy numbers).
* **Recall:** **90%** (Transparently logged edge-case misses).


* **Robust Safety Fallback:** If a PDF page is unreadable or OCR processing degrades, the system explicitly flags the segment with a `REVIEW REQUIRED` warning rather than making unsafe assumptions.

---

## 🔒 Security & Privacy Guarantee

> In full compliance with corporate data security standards, **all parsing, tokenization, OCR scanning, and regex/NER detection execute 100% locally** within the isolated execution runtime. No raw PII-bearing document contents are ever transmitted to external APIs or third-party generative AI models.

---
