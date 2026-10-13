
from pii_detector import detect_pii

positive_tests = [
    ("Contact Ravi Sharma today.", "Ravi Sharma", "PERSON_NAME"),
    ("Priya Patel is the account owner.", "Priya Patel", "PERSON_NAME"),
    ("Email: ravi@example.com", "ravi@example.com", "EMAIL"),
    ("Send it to support@company.in", "support@company.in", "EMAIL"),
    ("Call +91 98765 43210", "+91 98765 43210", "PHONE"),
    ("Phone: 9876543210", "9876543210", "PHONE"),
    ("Server IP: 192.168.1.10", "192.168.1.10", "IP_ADDRESS"),
    ("Gateway IP: 10.0.0.1", "10.0.0.1", "IP_ADDRESS"),
    ("Employee ID: EMP-20481", "EMP-20481", "ACCOUNT_OR_EMPLOYEE_ID"),
    ("Account Number: AC-887120", "AC-887120", "ACCOUNT_OR_EMPLOYEE_ID")
]

negative_tests = [
    "The quarterly report is ready.",
    "Revenue increased this quarter.",
    "The meeting starts at three PM.",
    "The server is running normally.",
    "The total score was eighty five."
]

positive_passed = 0
negative_passed = 0

print("\nPOSITIVE TESTS")

for text, expected_text, expected_type in positive_tests:
    results = detect_pii(text)

    found = any(
        item["entity_text"] == expected_text
        and item["entity_type"] == expected_type
        for item in results
    )

    if found:
        print("PASS:", expected_text, "-", expected_type)
        positive_passed += 1
    else:
        print("FAIL:", expected_text, "-", expected_type)

print("\nNEGATIVE TESTS")

for text in negative_tests:
    results = detect_pii(text)

    if len(results) == 0:
        print("PASS:", text)
        negative_passed += 1
    else:
        print("FAIL:", text, "| Unexpected:", results)

print("\nFINAL SUMMARY")
print("Positive:", positive_passed, "/", len(positive_tests))
print("Negative:", negative_passed, "/", len(negative_tests))
print("Total:", positive_passed + negative_passed, "/ 15")
