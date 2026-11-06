"""Automatic checks of a draft against rules in the Report Writing Instructions."""
import re

WORD_MIN, WORD_MAX = 480, 500

# Phrases the instructions tell the writer to avoid or never to use.
AVOID_PHRASES = [
    ("Happy Home", r"happy home"),
    ("tutor", r"\btutors?\b"),
    ("last year's report", r"last year[’']s report"),
    ("Grade", r"\bgrade\b"),
    ("testament to", r"testament to"),
    ("remarkable journey", r"remarkable journey"),
    ("finding her way / his way", r"finding (her|his|their) way"),
    ("triumphant moment", r"triumphant moment"),
    ("better version of", r"better version of"),
]


def split_report(text):
    """Returns (name_line, class_line, body). The body excludes the two identification lines."""
    lines = (text or "").replace("\r\n", "\n").split("\n")
    found, i = [], 0
    while i < len(lines) and len(found) < 2:
        if lines[i].strip():
            found.append(lines[i].strip())
        i += 1
    body = "\n".join(lines[i:]).strip()
    return (found[0] if found else ""), (found[1] if len(found) > 1 else ""), body


def count_words(body):
    return len((body or "").split())


def check_report(text, first_name=None):
    name_line, class_line, body = split_report(text)
    issues = []
    format_ok = True
    if not name_line.startswith("Name: ") or len(name_line) <= len("Name: "):
        format_ok = False
        issues.append('The first line must read "Name: " followed by the first name.')
    elif first_name and name_line[len("Name: "):].strip().lower() != first_name.strip().lower():
        issues.append(f'The name line does not match the selected child ("{first_name}").')
    if not class_line.startswith("Class/Education: ") or len(class_line) <= len("Class/Education: "):
        format_ok = False
        issues.append('The second line must read "Class/Education: " followed by the class or education.')
    words = count_words(body)
    if words < WORD_MIN or words > WORD_MAX:
        issues.append(f"The body has {words} words; the target is {WORD_MIN}-{WORD_MAX}.")
    for label, pattern in AVOID_PHRASES:
        if re.search(pattern, body, flags=re.IGNORECASE):
            issues.append(f'The text contains "{label}", which the instructions say to avoid.')
    return {"name_line": name_line, "class_line": class_line, "body": body,
            "word_count": words, "in_range": WORD_MIN <= words <= WORD_MAX, "issues": issues,
            "format_ok": format_ok}
