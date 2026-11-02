import os
from flask import (Blueprint, render_template, redirect, url_for, flash, abort,
                   send_file, current_app)
from flask_login import login_required, current_user
from ..extensions import db
from ..models import Child, HistoricalReport, utcnow
from ..audit import log_event
from ..decorators import admin_required
from ..files import inspect_upload, save_bytes, stored_path, UploadError, MIME_TYPES
from .forms import HistoryUploadForm

bp = Blueprint("history", __name__)


def _get_report_or_404(report_id):
    report = db.get_or_404(HistoricalReport, report_id)
    if report.is_removed:
        abort(404)
    return report


@bp.route("/children/<int:child_id>/history")
@login_required
def index(child_id):
    child = db.get_or_404(Child, child_id)
    reports = db.session.execute(
        db.select(HistoricalReport)
        .where(HistoricalReport.child_id == child.id,  # only THIS child's reports
               HistoricalReport.is_removed.is_(False))
        .order_by(HistoricalReport.reporting_year.desc(), HistoricalReport.id.desc())
    ).scalars().all()
    return render_template("history/list.html", child=child, reports=reports)


@bp.route("/children/<int:child_id>/history/upload", methods=["GET", "POST"])
@login_required
def upload(child_id):
    child = db.get_or_404(Child, child_id)
    form = HistoryUploadForm()
    if form.validate_on_submit():
        f = form.file.data
        original = os.path.basename((f.filename or "").replace("\\", "/"))[:255]
        ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
        if ext not in ("docx", "pdf"):
            form.file.errors = ["Only .docx (Word) and .pdf files are allowed."]
        else:
            try:
                data = f.read()
                file_type, text = inspect_upload(data, ext)
            except UploadError as e:
                form.file.errors = [str(e)]
            else:
                stored = save_bytes(data, file_type)
                report = HistoricalReport(
                    child_id=child.id,  # the child comes from the address
                    reporting_year=form.reporting_year.data,
                    original_filename=original,
                    stored_name=stored,
                    file_type=file_type,
                    file_size=len(data),
                    extracted_text=text,
                    uploaded_by_id=current_user.id,
                )
                db.session.add(report)
                db.session.flush()
                log_event("history_uploaded", "historical_report", report.id)
                db.session.commit()
                if file_type == "docx" and not (text or "").strip():
                    flash("Saved, but no readable text was found in the Word file.", "warning")
                else:
                    flash("Report saved.", "success")
                return redirect(url_for("history.index", child_id=child.id))
    return render_template("history/upload.html", form=form, child=child)


@bp.route("/history/<int:report_id>")
@login_required
def view(report_id):
    report = _get_report_or_404(report_id)
    text = report.extracted_text or ""
    return render_template("history/view.html", report=report, child=report.child,
                           text=text, word_count=len(text.split()))


@bp.route("/history/<int:report_id>/download")
@login_required
def download(report_id):
    report = _get_report_or_404(report_id)
    path = stored_path(report.stored_name)
    if not os.path.exists(path):
        current_app.logger.error("Stored file missing for report id %s", report.id)
        abort(404)
    log_event("history_downloaded", "historical_report", report.id)
    db.session.commit()
    resp = send_file(path, as_attachment=True, download_name=report.original_filename,
                     mimetype=MIME_TYPES[report.file_type])
    resp.headers["Cache-Control"] = "private, no-store"
    return resp


@bp.route("/history/<int:report_id>/remove", methods=["POST"])
@admin_required
def remove(report_id):
    report = _get_report_or_404(report_id)
    report.is_removed = True
    report.removed_at = utcnow()
    report.removed_by_id = current_user.id
    log_event("history_removed", "historical_report", report.id)
    db.session.commit()
    flash("Report hidden. The original file is kept on the server.", "info")
    return redirect(url_for("history.index", child_id=report.child_id))
