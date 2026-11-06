"""Who did how much, counted from the data that already exists.

Nothing extra is stored: the numbers are counted on demand from the notes, reports, edits, exports
and approvals, using the person and the time already saved with each of them.
"""
from sqlalchemy import func
from ..extensions import db
from ..models import (User, Observation, HistoricalReport, GeneratedReport, ReportVersion,
                      Clarification, ReportExport, ReportApproval)
from ..user_admin import is_removed
from .periods import period_bounds, to_utc, period_label, neighbours

METRICS = [
    ("notes_added", "Notes added"),
    ("notes_edited", "Notes edited"),
    ("history_uploaded", "Old reports uploaded"),
    ("reports_started", "Reports started"),
    ("questions_answered", "Questions answered"),
    ("text_edits", "Report text edits"),
    ("exports", "Word files exported"),
    ("approvals", "Approvals"),
]


def _grouped(user_column, time_column, start_utc, end_utc, *conditions):
    stmt = (db.select(user_column, func.count())
            .where(user_column.is_not(None), time_column >= start_utc, time_column < end_utc, *conditions)
            .group_by(user_column))
    return {user_id: n for user_id, n in db.session.execute(stmt).all()}


def contribution_table(view, anchor, today):
    start, end = period_bounds(view, anchor)
    s, e = to_utc(start), to_utc(end)
    counts = {
        "notes_added": _grouped(Observation.created_by_id, Observation.created_at, s, e,
                                Observation.is_deleted.is_(False)),
        "notes_edited": _grouped(Observation.updated_by_id, Observation.updated_at, s, e,
                                 Observation.is_deleted.is_(False)),
        "history_uploaded": _grouped(HistoricalReport.uploaded_by_id, HistoricalReport.uploaded_at, s, e,
                                     HistoricalReport.is_removed.is_(False)),
        "reports_started": _grouped(GeneratedReport.created_by_id, GeneratedReport.created_at, s, e),
        "questions_answered": _grouped(Clarification.answered_by_id, Clarification.answered_at, s, e),
        "text_edits": _grouped(ReportVersion.created_by_id, ReportVersion.created_at, s, e,
                               ReportVersion.kind == "edited"),
        "exports": _grouped(ReportExport.created_by_id, ReportExport.created_at, s, e),
        "approvals": _grouped(ReportApproval.approved_by_id, ReportApproval.approved_at, s, e),
    }

    rows = []
    for user in db.session.execute(db.select(User)).scalars():
        per = {key: counts[key].get(user.id, 0) for key, _label in METRICS}
        total = sum(per.values())
        if total == 0 and (not user.is_active or is_removed(user)):
            continue  # inactive people with no work in this period are not listed
        rows.append({"user": user, "counts": per, "total": total})

    team_total = sum(r["total"] for r in rows)
    for r in rows:
        r["percent"] = round(100.0 * r["total"] / team_total, 1) if team_total else 0.0
    rows.sort(key=lambda r: (-r["total"], r["user"].name.lower()))

    previous_anchor, next_anchor = neighbours(start, end, today)
    return {"rows": rows, "team_total": team_total, "label": period_label(view, start, end),
            "previous_anchor": previous_anchor, "next_anchor": next_anchor}
