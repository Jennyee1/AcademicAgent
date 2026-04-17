"""Quick debug for section parser regex - v2"""
import re

prefix_opt = r"(?:(?:\d+|[IVX]+)\.?\s*)?"
prefix_req = r"(?:(?:\d+|[IVX]+)\.?\s+)"

patterns = [
    (r"(?i)^abstract\s*$", "abstract"),
    (rf"(?i)^{prefix_opt}introduction\s*$", "introduction"),
    (rf"(?i)^{prefix_opt}(?:related\s+work|background|literature\s+review)\b", "related_work"),
    (rf"(?i)^{prefix_opt}(?:system\s+model|problem\s+formulation)\b", "system_model"),
    (rf"(?i)^{prefix_opt}proposed\s+(?:method|algorithm|scheme|framework)\s*$", "method"),
    (rf"(?i)^{prefix_req}(?:methodology|approach|algorithm)\b", "method"),
    (rf"(?i)^{prefix_opt}(?:simulations?\s+results?|numerical\s+results?)\b", "experiments"),
    (rf"(?i)^{prefix_req}(?:experiments?|results?|evaluation)\b", "experiments"),
    (rf"(?i)^{prefix_opt}conclusions?\s*$", "conclusion"),
    (rf"(?i)^{prefix_req}(?:summary|concluding)\b", "conclusion"),
    (r"(?i)^(?:references|bibliography)\s*$", "references"),
]

print("=== Test 1: Roman numeral IEEE format ===")
lines1 = [
    "Abstract", "Test abstract.",
    "I. Introduction", "Intro content.",
    "II. System Model", "Model content.",
    "III. Proposed Algorithm", "Algorithm content.",
    "IV. Simulation Results", "Results content.",
    "V. Conclusion", "Conclusion content.",
]
for line in lines1:
    stripped = line.strip()
    matched = None
    for pat, name in patterns:
        if re.match(pat, stripped) and len(stripped) < 80:
            matched = name
            break
    tag = matched if matched else "(content)"
    print(f"  {stripped:30s} -> {tag}")

print("\n=== Test 2: Arabic numeral format ===")
lines2 = [
    "Abstract", "This paper presents...",
    "1. Introduction", "In recent years...",
    "3. Proposed Method", "We propose...",
    "4. Experiments", "We evaluate...",
    "5. Conclusion", "In this paper...",
    "References", "[1] Zhang...",
]
for line in lines2:
    stripped = line.strip()
    matched = None
    for pat, name in patterns:
        if re.match(pat, stripped) and len(stripped) < 80:
            matched = name
            break
    tag = matched if matched else "(content)"
    print(f"  {stripped:30s} -> {tag}")

print("\n=== Test 3: Edge cases (should NOT match) ===")
false_positives = [
    "Algorithm content.",
    "Conclusion content.",
    "Results show that...",
    "In conclusion, we found...",
    "The algorithm performs well.",
]
for line in false_positives:
    stripped = line.strip()
    matched = None
    for pat, name in patterns:
        if re.match(pat, stripped) and len(stripped) < 80:
            matched = name
            break
    tag = matched if matched else "(content)"
    status = "FAIL" if matched else "OK"
    print(f"  [{status}] {stripped:40s} -> {tag}")
