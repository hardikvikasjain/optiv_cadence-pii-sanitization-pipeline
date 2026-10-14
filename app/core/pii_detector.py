"""
pii_detector.py - Hybrid High-Precision Regex & spaCy NER Engine for Cadence Financial Group.
Detects:
- Regex: EMAIL, PHONE, IP_ADDRESS, ACCOUNT_OR_EMPLOYEE_ID
- spaCy NER: PERSON_NAME, GPE (Geopolitical Entities), LOC (Locations)
Adheres to Schema B contract with strict zero cloud leakage.
"""
from __future__ import annotations

import re
import ipaddress
import logging
from typing import List, Dict, Any, Optional

log = logging.getLogger("cadence.pii_detector")

# Attempt loading spaCy model, with heuristic fallback if model fails to load
_nlp = None
try:
    import spacy
    _nlp = spacy.load("en_core_web_sm")
except Exception as e:
    log.warning(f"Could not load spaCy model en_core_web_sm directly: {e}. Will attempt lazy loading.")

def get_nlp():
    global _nlp
    if _nlp is None:
        try:
            import spacy
            _nlp = spacy.load("en_core_web_sm")
        except Exception:
            try:
                import spacy.cli
                spacy.cli.download("en_core_web_sm")
                _nlp = spacy.load("en_core_web_sm")
            except Exception as e2:
                log.error(f"Failed to load or download spaCy model: {e2}")
    return _nlp

# High-precision regular expressions
REGEX_PATTERNS = [
    (
        "EMAIL",
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
        0,
        0.98
    ),
    (
        "PHONE",
        r"(?<!\d)(?:\+91[\s-]?|91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)",
        0,
        0.95
    ),
    (
        "PHONE",
        r"(?:\+?1[\s.-]?)?\(?[2-9]\d{2}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b",
        0,
        0.92
    ),
    (
        "IP_ADDRESS",
        r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
        0,
        0.96
    ),
    (
        "ACCOUNT_OR_EMPLOYEE_ID",
        r"(?i)\b(?:employee\s*id|account\s*(?:number|no\.?))\s*[:#-]?\s*([A-Z0-9-]{4,20})\b",
        1,
        0.95
    ),
    (
        "ACCOUNT_OR_EMPLOYEE_ID",
        r"\b(?:EMP|AC)[- ]\d{3,20}\b",
        0,
        0.95
    )
]

# Corporate non-person vocabulary to prevent false positive person detections
NON_PERSON_TERMS = {
    "optiv", "tprm", "cadence", "ironclad", "description", "approver", "admin", "metadata",
    "workflow", "email", "templates", "vendor tier", "description key", "cancel save",
    "tier vendor tier", "diligence questionnaire", "templates archive", "discard", "draft",
    "appendix", "appendix c", "appendix d", "trigger", "trigger name", "trigger type",
    "vendor workflow", "vendor created", "tier contains", "change workflow",
    "artificial intelligence", "cloud", "cloud apps", "database", "bin", "continuous",
    "background", "legal risk", "assessment completed", "role holder directory",
    "framework relevance", "directors", "elevated", "qual", "providers", "questionnaire",
    "hil discard", "revpart questionnaire", "marpart questionnaire", "servpro questionnaire",
    "qrc no co branding", "templates due diligence question", "version", "policy", "cadence financial"
}

def clean_name(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip(" :;,.-_")
    name = re.sub(r"\s*-\s*", "-", name)
    return name

def looks_like_person(name: str) -> bool:
    if not name:
        return False
    lowered = name.lower().replace("-", " ")
    words = lowered.split()

    if lowered in NON_PERSON_TERMS:
        return False

    if any(word in NON_PERSON_TERMS for word in words):
        return False

    if "@" in name or any(char.isdigit() for char in name):
        return False

    # Avoid single-word noise tokens
    if len(words) < 2 or len(words) > 3:
        return False

    # Check capitalization / name format
    for word in name.split():
        if not re.fullmatch(r"(?:[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ]+(?:-[A-ZÀ-ÖØ-Þ]?[a-zà-öø-ÿ]+)*|[A-Z]\.?)", word):
            return False

    return True

def detect_pii(text: str, segment_id: str = "SEG_00001") -> List[Dict[str, Any]]:
    """
    Scans text for PII entities using Regex + spaCy NER.
    Returns Schema B compliant list of dicts.
    """
    if not text or not text.strip():
        return []

    findings: List[Dict[str, Any]] = []

    # 1. Regex Detection
    for entity_type, pattern, group_number, conf in REGEX_PATTERNS:
        for match in re.finditer(pattern, text):
            try:
                entity_text = match.group(group_number)
                start = match.start(group_number)
                end = match.end(group_number)
            except IndexError:
                continue

            if entity_type == "IP_ADDRESS":
                try:
                    ipaddress.IPv4Address(entity_text)
                except ValueError:
                    continue

            if entity_type == "ACCOUNT_OR_EMPLOYEE_ID":
                if not any(c.isdigit() for c in entity_text):
                    continue

            findings.append({
                "segment_id": segment_id,
                "entity_text": entity_text,
                "entity_type": entity_type,
                "start_char": start,
                "end_char": end,
                "detection_method": "regex",
                "confidence_or_strength": conf
            })

    # 2. spaCy NER Detection (PERSON, GPE, LOC)
    nlp = get_nlp()
    if nlp is not None:
        try:
            doc = nlp(text)
            for ent in doc.ents:
                label = ent.label_
                if label not in ("PERSON", "GPE", "LOC"):
                    continue

                raw_val = ent.text
                start, end = ent.start_char, ent.end_char

                if label == "PERSON":
                    cleaned = clean_name(raw_val)
                    if not looks_like_person(cleaned):
                        continue
                    entity_type = "PERSON_NAME"
                    conf = 0.88
                elif label == "GPE":
                    cleaned = raw_val.strip(" :;,.-_")
                    if len(cleaned) < 3 or cleaned.lower() in NON_PERSON_TERMS:
                        continue
                    entity_type = "GPE"
                    conf = 0.85
                elif label == "LOC":
                    cleaned = raw_val.strip(" :;,.-_")
                    if len(cleaned) < 3 or cleaned.lower() in NON_PERSON_TERMS:
                        continue
                    entity_type = "LOC"
                    conf = 0.82
                else:
                    continue

                # Ensure this span doesn't overlap an existing regex match
                overlaps_regex = any(
                    max(start, f["start_char"]) < min(end, f["end_char"])
                    for f in findings
                )
                if overlaps_regex:
                    continue

                findings.append({
                    "segment_id": segment_id,
                    "entity_text": cleaned,
                    "entity_type": entity_type,
                    "start_char": start,
                    "end_char": end,
                    "detection_method": "NER",
                    "confidence_or_strength": conf
                })
        except Exception as ner_err:
            log.warning(f"NER detection encountered an issue on segment {segment_id}: {ner_err}")

    # 3. Deduplication and sorting
    unique_findings = []
    seen = set()

    for item in findings:
        key = (item["entity_type"], item["start_char"], item["end_char"])
        if key not in seen:
            seen.add(key)
            unique_findings.append(item)

    # Sort in ascending order by start_char
    unique_findings.sort(key=lambda x: (x["start_char"], x["end_char"]))
    return unique_findings
