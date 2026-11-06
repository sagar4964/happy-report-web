"""Permanent deletion of one child's data (for the retention and deletion policy)."""
import json
import logging
import os
from .audit import log_event
from .extensions import db
from .files import stored_path, generated_path
from .models import (Child, Observation, HistoricalReport, GeneratedReport, ReportVersion,
                     ReportExport, ReportApproval, Clarification)

log = logging.getLogger(__name__)


def delete_child_permanently(child_id):
    """Deletes the child and EVERYTHING linked to them, including stored files.
    Returns a dict of counts. The audit log keeps only the id and the fact of deletion."""
    child = db.session.get(Child, child_id)
    if child is None:
        raise ValueError("No child with that ID.")

    report_ids = [r for r in db.session.scalars(
        db.select(GeneratedReport.id).where(GeneratedReport.child_id == child_id))]
    files_to_remove = []
    counts = {}

    if report_ids:
        for exp in db.session.scalars(db.select(ReportExport).where(
                ReportExport.generated_report_id.in_(report_ids))):
            files_to_remove.append(generated_path(exp.stored_name))
        for model in (ReportApproval, ReportExport, Clarification, ReportVersion):
            result = db.session.execute(
                db.delete(model).where(model.generated_report_id.in_(report_ids)))
            counts[model.__tablename__] = result.rowcount
        counts["generated_reports"] = db.session.execute(
            db.delete(GeneratedReport).where(GeneratedReport.id.in_(report_ids))).rowcount

    for hist in db.session.scalars(db.select(HistoricalReport).where(
            HistoricalReport.child_id == child_id)):
        files_to_remove.append(stored_path(hist.stored_name))
    counts["historical_reports"] = db.session.execute(
        db.delete(HistoricalReport).where(HistoricalReport.child_id == child_id)).rowcount
    counts["observations"] = db.session.execute(
        db.delete(Observation).where(Observation.child_id == child_id)).rowcount
    db.session.execute(db.delete(Child).where(Child.id == child_id))
    counts["children"] = 1

    log_event("child_deleted_permanently", "child", child_id,
              detail=json.dumps(counts)[:250])  # no names, only the id and counts
    db.session.commit()

    for path in files_to_remove:  # files are removed only after the database change succeeded
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            log.error("Could not remove a stored file while deleting child %s", child_id)
    counts["files_removed"] = len(files_to_remove)
    return counts
