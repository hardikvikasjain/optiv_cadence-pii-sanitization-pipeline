
import re
import ipaddress
import spacy

nlp = spacy.load("en_core_web_sm")


def detect_pii(text, segment_id="TEST"):
    findings = []

    patterns = [
        (
            "EMAIL",
            r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
            0
        ),
        (
            "PHONE",
            r"(?<!\d)(?:\+91[\s-]?|91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)",
            0
        ),
        (
            "IP_ADDRESS",
            r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
            0
        ),
        (
            "ACCOUNT_OR_EMPLOYEE_ID",
            r"(?i)\b(?:employee\s*id|account\s*(?:number|no\.?))\s*[:#-]?\s*([A-Z0-9-]{4,20})\b",
            1
        ),
        (
            "ACCOUNT_OR_EMPLOYEE_ID",
            r"\b(?:EMP|AC)[- ]\d{3,20}\b",
            0
        )
    ]

    for entity_type, pattern, group_number in patterns:
        for match in re.finditer(pattern, text):
            entity_text = match.group(group_number)
            start = match.start(group_number)
            end = match.end(group_number)

            if entity_type == "IP_ADDRESS":
                try:
                    ipaddress.IPv4Address(entity_text)
                except ValueError:
                    continue

            if entity_type == "ACCOUNT_OR_EMPLOYEE_ID":
                if not any(char.isdigit() for char in entity_text):
                    continue

            findings.append({
                "segment_id": segment_id,
                "entity_text": entity_text,
                "entity_type": entity_type,
                "start_char": start,
                "end_char": end,
                "detection_method": "regex",
                "confidence_or_strength": 0.95
            })

    non_person_terms = {
        "optiv", "tprm", "cadence", "ironclad",
        "description", "approver", "admin", "metadata",
        "workflow", "email", "templates", "vendor tier",
        "description key", "cancel save", "tier vendor tier",
        "diligence questionnaire", "templates archive",
        "discard", "draft", "appendix", "appendix c",
        "appendix d", "trigger", "trigger name", "trigger type",
        "vendor workflow", "vendor created", "tier contains",
        "change workflow", "artificial intelligence",
        "cloud", "cloud apps", "database", "bin",
        "continuous", "background", "legal risk",
        "assessment completed", "role holder directory",
        "framework relevance", "directors", "elevated",
        "qual", "providers", "questionnaire", "discard",
        "hil discard", "revpart questionnaire",
        "marpart questionnaire", "servpro questionnaire",
        "qrc no co branding", "templates archive",
        "templates due diligence question"
    }

    def clean_name(name):
        name = re.sub(r"\s+", " ", name).strip(" :;,.-")
        name = re.sub(r"\s*-\s*", "-", name)
        return name

    def looks_like_person(name):
        lowered = name.lower().replace("-", " ")
        words = lowered.split()

        if lowered in non_person_terms:
            return False

        if any(word in non_person_terms for word in words):
            return False

        if "@" in name or any(char.isdigit() for char in name):
            return False

        # Avoid one-word OCR fragments such as "bin", "Draft", and "Cloud".
        if len(words) < 2:
            return False

        # Multiple adjacent names are often merged by OCR or NER.
        if len(words) > 3:
            return False

        # Names should consist of alphabetic words, initials, or hyphenated names.
        for word in name.split():
            if not re.fullmatch(
                r"(?:[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ]+(?:-[A-ZÀ-ÖØ-Þ]?[a-zà-öø-ÿ]+)*|[A-Z]\.?)",
                word
            ):
                return False

        return True

    doc = nlp(text)

    for entity in doc.ents:
        if entity.label_ != "PERSON":
            continue

        name = clean_name(entity.text)

        if not looks_like_person(name):
            continue

        start = entity.start_char
        end = entity.end_char

        # Avoid overlapping an already detected email address.
        if any(
            item["entity_type"] == "EMAIL"
            and start < item["end_char"]
            and end > item["start_char"]
            for item in findings
        ):
            continue

        findings.append({
            "segment_id": segment_id,
            "entity_text": name,
            "entity_type": "PERSON_NAME",
            "start_char": start,
            "end_char": end,
            "detection_method": "NER",
            "confidence_or_strength": 0.70
        })

    unique_findings = []
    seen = set()

    for item in findings:
        key = (
            item["entity_type"],
            item["start_char"],
            item["end_char"]
        )

        if key not in seen:
            seen.add(key)
            unique_findings.append(item)

    unique_findings.sort(key=lambda item: item["start_char"])

    return unique_findings
