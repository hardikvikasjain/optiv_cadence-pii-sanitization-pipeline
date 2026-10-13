
import json
import csv
from pii_detector import detect_pii

# Load the extracted document segments
with open("extraction_output.json", "r", encoding="utf-8") as file:
    segments = json.load(file)

all_findings = []

# Scan every extracted segment
for segment in segments:
    text = segment.get("text", "")

    if not text:
        continue

    findings = detect_pii(
        text,
        segment_id=segment.get("segment_id", "UNKNOWN")
    )

    # Preserve the original document location
    for finding in findings:
        finding["file_name"] = segment.get("file_name")
        finding["location_type"] = segment.get("location_type")
        finding["location_index"] = segment.get("location_index")
        finding["page_or_slide"] = segment.get("page_or_slide")

        all_findings.append(finding)

# Save findings as JSON
with open("pii_findings.json", "w", encoding="utf-8") as file:
    json.dump(all_findings, file, indent=2, ensure_ascii=False)

# Save findings as CSV for easy review
if all_findings:
    with open("pii_findings.csv", "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=all_findings[0].keys()
        )
        writer.writeheader()
        writer.writerows(all_findings)

# Print summary
print("EXTRACTION SCAN SUMMARY")
print("-" * 35)
print("Segments scanned:", len(segments))
print("PII findings:", len(all_findings))

counts = {}

for finding in all_findings:
    entity_type = finding["entity_type"]
    counts[entity_type] = counts.get(entity_type, 0) + 1

print("\nFindings by category:")

for entity_type, count in sorted(counts.items()):
    print(entity_type + ":", count)

print("\nSaved results to pii_findings.json and pii_findings.csv")
