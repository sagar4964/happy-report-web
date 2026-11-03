import json


def parse_ai_json(text):
    """Turn the AI's reply into a simple dict. Raises ValueError if it is not usable.

    Returns {"status": "questions"|"report", "questions": [...], "report": str, "notes": str}
    """
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"):
            t = t[4:]
        t = t.strip()
    try:
        data = json.loads(t)
    except ValueError:
        start, end = t.find("{"), t.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("no JSON found")
        data = json.loads(t[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("not an object")

    status = data.get("status")
    notes = str(data.get("notes_outside_report") or "").strip()
    if status == "questions":
        raw = data.get("questions") or []
        if not isinstance(raw, list):
            raise ValueError("questions must be a list")
        questions = [str(q).strip() for q in raw if str(q).strip()]
        if not questions:
            raise ValueError("no questions")
        return {"status": "questions", "questions": questions, "report": "", "notes": notes}
    if status == "report":
        report = str(data.get("report") or "").strip()
        if not report:
            raise ValueError("empty report")
        return {"status": "report", "questions": [], "report": report, "notes": notes}
    raise ValueError("unknown status")
