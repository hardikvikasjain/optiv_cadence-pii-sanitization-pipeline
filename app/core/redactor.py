"""
redactor.py - Right-to-Left Offset-Safe Redaction Engine & Offset Verification Gate.
Applies replacements in descending start_char order to prevent index shifting.
Performs mathematical integrity validation via the Offset Verification Gate.
"""
from __future__ import annotations

import logging
from typing import List, Dict, Any, Tuple, Optional

log = logging.getLogger("cadence.redactor")

class OffsetVerificationError(Exception):
    """Raised when the Offset Verification Gate detects an index shift or collision."""
    pass

def generate_masked_representation(entity_text: str, entity_type: str) -> str:
    """Generates a human-auditable masked representation preserving format hints."""
    if not entity_text:
        return "[REDACTED]"

    if entity_type == "EMAIL" and "@" in entity_text:
        parts = entity_text.split("@", 1)
        user, domain = parts[0], parts[1]
        masked_user = user[0] + "***" if len(user) > 1 else "***"
        return f"{masked_user}@{domain}"

    elif entity_type == "PHONE":
        clean_num = entity_text.strip()
        if len(clean_num) > 7:
            return clean_num[:4] + " *** " + clean_num[-3:]
        return "***-***-****"

    elif entity_type == "PERSON_NAME":
        words = entity_text.split()
        masked_words = [w[0] + "***" if len(w) > 1 else w for w in words]
        return " ".join(masked_words)

    elif entity_type == "IP_ADDRESS":
        octets = entity_text.split(".")
        if len(octets) == 4:
            return f"{octets[0]}.{octets[1]}.***.***"
        return "***.***.***.***"

    elif entity_type == "ACCOUNT_OR_EMPLOYEE_ID":
        if len(entity_text) > 4:
            return entity_text[:2] + "****" + entity_text[-2:]
        return "****"

    else:
        return entity_text[:1] + "***" if len(entity_text) > 2 else "***"

def verify_and_clean_spans(text: str, findings: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Offset Verification Gate: Pre-replacement mathematical validation.
    Checks boundary bounds, validates text[start:end] equality, and resolves overlaps.
    """
    warnings = []
    text_len = len(text)
    valid_spans: List[Dict[str, Any]] = []

    for item in findings:
        s = item.get("start_char", -1)
        e = item.get("end_char", -1)
        expected_text = item.get("entity_text", "")

        # Boundary checks
        if s < 0 or e > text_len or s >= e:
            warn = f"Offset Verification Gate: Invalid offsets [{s}:{e}] for text length {text_len}."
            warnings.append(warn)
            continue

        actual_slice = text[s:e]
        # Text alignment verification
        if actual_slice != expected_text:
            # Self-healing attempt: check if leading/trailing whitespace difference
            if actual_slice.strip() == expected_text.strip():
                pass
            else:
                warn = (f"Offset Verification Gate: Slice mismatch at [{s}:{e}]. "
                        f"Expected '{expected_text}', found '{actual_slice}'.")
                warnings.append(warn)
                continue

        valid_spans.append(item)

    # Resolve overlapping spans: sort by start_char, resolve any overlapping intervals
    valid_spans.sort(key=lambda x: (x["start_char"], -(x["end_char"] - x["start_char"])))
    non_overlapping: List[Dict[str, Any]] = []

    for span in valid_spans:
        if not non_overlapping:
            non_overlapping.append(span)
            continue

        prev = non_overlapping[-1]
        if span["start_char"] < prev["end_char"]:
            # Overlap detected! Keep the one with higher confidence or larger span
            prev_conf = prev.get("confidence_or_strength", 0.5)
            curr_conf = span.get("confidence_or_strength", 0.5)
            if curr_conf > prev_conf or (curr_conf == prev_conf and (span["end_char"] - span["start_char"]) > (prev["end_char"] - prev["start_char"])):
                non_overlapping[-1] = span
                warnings.append(f"Offset Verification Gate: Overlap resolved by choosing higher priority entity '{span['entity_type']}'.")
            else:
                warnings.append(f"Offset Verification Gate: Dropping overlapping lower priority entity '{span['entity_type']}'.")
        else:
            non_overlapping.append(span)

    return non_overlapping, warnings

def redact_text(
    text: str,
    findings: List[Dict[str, Any]],
    mode: str = "tag"  # 'tag' (e.g. [REDACTED: EMAIL]) or 'mask' (e.g. j***@cadence.com)
) -> Tuple[str, List[str]]:
    """
    Executes Right-to-Left (descending start_char order) redaction.
    Ensures mathematical integrity and zero index drift.
    Returns (sanitized_text, warnings).
    """
    if not text or not findings:
        return text, []

    # 1. Gate: Verify spans
    clean_findings, gate_warnings = verify_and_clean_spans(text, findings)

    # 2. Right-to-left sort: descending by start_char
    clean_findings.sort(key=lambda x: x["start_char"], reverse=True)

    sanitized = text
    untouched_check_points: List[Tuple[int, int, str]] = []

    # Record untouched segments to verify mathematical integrity post-redaction
    last_end = len(text)
    for f in clean_findings:
        s, e = f["start_char"], f["end_char"]
        if e < last_end:
            untouched_check_points.append((e, last_end, text[e:last_end]))
        last_end = s
    if last_end > 0:
        untouched_check_points.append((0, last_end, text[0:last_end]))

    # 3. Apply Right-to-Left Replacements
    for f in clean_findings:
        s, e = f["start_char"], f["end_char"]
        etype = f.get("entity_type", "PII")
        raw_val = f.get("entity_text", "")

        if mode == "mask":
            replacement = generate_masked_representation(raw_val, etype)
        else:
            replacement = f"[REDACTED: {etype}]"

        sanitized = sanitized[:s] + replacement + sanitized[e:]

    # 4. Post-check verification
    for orig_s, orig_e, chunk in untouched_check_points:
        if chunk and chunk not in sanitized:
            gate_warnings.append(f"Offset Verification Gate: Warning - Untouched segment was modified unexpectedly.")

    return sanitized, gate_warnings
