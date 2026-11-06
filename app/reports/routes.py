import json
import os
from flask import Blueprint, render_template, redirect, url_for, flash, request, abort, send_file
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError
from ..extensions import db, limiter
from ..models import (Child, Observation, HistoricalReport, GeneratedReport, ReportVersion,
                      Clarification, ReportTemplate, ReportExport, ReportApproval, utcnow,
                      STATUS_GENERATING, STATUS_NEEDS_ANSWERS, STATUS_DRAFT_READY, STATUS_FAILED,
                      STATUS_APPROVED)
from ..audit import log_event
from ..decorators import admin_required
from ..services import get_periods, resolve_period, latest_previous_report
from ..report_checks import check_report, split_report
from ..report_service import run_generation, run_revision, is_busy, mark_generating, latest_version
from ..docx_export import build_docx, report_filename
from ..pagecheck import check_pages
from ..files import save_generated, generated_path

bp = Blueprint("reports", __name__)

STATUS_LABELS = {
    STATUS_GENERATING: ("Generating", "secondary"),
    STATUS_NEEDS_ANSWERS: ("Questions to answer", "warning"),
    STATUS_DRAFT_READY: ("Draft ready", "success"),
    STATUS_FAILED: ("Failed - can retry", "danger"),
    STATUS_APPROVED: ("Approved", "primary"),
}

VERSION_LABELS = {"ai_draft": "AI draft", "edited": "Edited by staff", "ai_revision": "AI length revision"}
MAX_TEXT = 20000


def _active_template():
    return db.session.execute(
        db.select(ReportTemplate).where(ReportTemplate.is_active.is_(True))
        .order_by(ReportTemplate.version_number.desc())
    ).scalars().first()


def _period_observations(child, period):
    return db.session.execute(
        db.select(Observation).where(
            Observation.child_id == child.id,
            Observation.is_deleted.is_(False),
            Observation.event_date.between(period.start_date, period.end_date))
        .order_by(Observation.event_date, Observation.id)
    ).scalars().all()


def _child_reports(child):
    return db.session.execute(
        db.select(HistoricalReport).where(HistoricalReport.child_id == child.id,
                                          HistoricalReport.is_removed.is_(False))
        .order_by(HistoricalReport.reporting_year.desc(), HistoricalReport.id.desc())
    ).scalars().all()


@bp.route("/reports/")
@login_required
def index():
    rows = db.session.execute(
        db.select(GeneratedReport).order_by(GeneratedReport.created_at.desc()).limit(200)
    ).scalars().all()
    return render_template("reports/list.html", reports=rows, labels=STATUS_LABELS)


def _render_prepare(child, periods, selected, errors=None, values=None):
    observations = _period_observations(child, selected) if selected else []
    history = _child_reports(child)
    default_prev = latest_previous_report(child.id, selected.year) if selected else None
    values = values or {}
    return render_template(
        "reports/prepare.html", child=child, periods=periods, selected=selected,
        observations=observations, history=history, default_prev=default_prev,
        errors=errors or [], values=values, template=_active_template())


@bp.route("/children/<int:child_id>/reports/new", methods=["GET", "POST"])
@login_required
@limiter.limit("20 per hour", methods=["POST"])
def new(child_id):
    child = db.get_or_404(Child, child_id)
    if not child.is_active:
        flash("This child is archived. Ask an administrator to restore the profile first.", "warning")
        return redirect(url_for("children.detail", child_id=child.id))
    periods = get_periods()
    if not periods:
        flash("There are no reporting periods yet. An administrator must add one (Periods).", "warning")
        return redirect(url_for("children.detail", child_id=child.id))

    source = request.form if request.method == "POST" else request.args
    selected = resolve_period(periods, source.get("period"))
    if selected is None:
        selected = periods[0]

    if request.method == "GET":
        return _render_prepare(child, periods, selected)

    # ---- POST: validate everything on the server ----
    errors = []
    allowed = {o.id: o for o in _period_observations(child, selected)}
    chosen_ids = []
    for raw in request.form.getlist("obs_ids"):
        if raw.isdigit() and int(raw) in allowed:
            chosen_ids.append(int(raw))
        else:
            errors.append("One of the selected observations does not belong to this child and year.")
            break
    extra = (request.form.get("extra_bullets") or "").strip()
    receipt = (request.form.get("receipt_context") or "").strip()
    prev_raw = (request.form.get("previous_report_id") or "").strip()
    values = {"obs_ids": set(chosen_ids), "extra_bullets": extra, "receipt_context": receipt,
              "previous_report_id": prev_raw,
              "confirm_identity": bool(request.form.get("confirm_identity")),
              "confirm_no_previous": bool(request.form.get("confirm_no_previous"))}

    if not values["confirm_identity"]:
        errors.append("Please confirm the child's identity and current education.")
    if not chosen_ids and not extra:
        errors.append("Select at least one observation or paste some bullet points.")
    if len(extra) > 20000:
        errors.append("The pasted bullet points are too long (limit 20,000 characters).")
    if len(receipt) > 255:
        errors.append("The timing note is too long (limit 255 characters).")

    previous = None
    if prev_raw:
        previous = next((r for r in _child_reports(child) if str(r.id) == prev_raw), None)
        if previous is None:
            errors.append("The chosen previous report does not belong to this child.")
        elif previous.file_type != "docx" or not (previous.extracted_text or "").strip():
            errors.append("The chosen previous report has no readable text. Upload the Word (.docx) "
                          "version, or choose 'No previous report' and confirm.")
    elif not values["confirm_no_previous"]:
        errors.append("Choose a previous report, or tick the box to confirm there is none.")

    template = _active_template()
    if template is None:
        errors.append("No Report Writing Instructions are active. Run 'flask --app run seed-defaults' "
                      "or ask an administrator.")

    if errors:
        return _render_prepare(child, periods, selected, errors=errors, values=values)

    report = GeneratedReport(
        child_id=child.id,  # the child comes from the address
        reporting_year=selected.year,
        template_id=template.id,
        previous_report_id=previous.id if previous else None,
        previous_report_confirmed_missing=previous is None,
        included_observation_ids=json.dumps(sorted(chosen_ids)),
        extra_bullets=extra or None,
        receipt_context=receipt or None,
        status=STATUS_GENERATING,
        created_by_id=current_user.id,
    )
    db.session.add(report)
    db.session.flush()
    log_event("report_started", "generated_report", report.id)
    db.session.commit()  # inputs are saved BEFORE the AI is called
    run_generation(report, current_user.id)
    return redirect(url_for("reports.detail", report_id=report.id))


def _clarifications(report):
    return db.session.execute(
        db.select(Clarification).where(Clarification.generated_report_id == report.id)
        .order_by(Clarification.round_no, Clarification.id)
    ).scalars().all()


@bp.route("/reports/<int:report_id>")
@login_required
def detail(report_id):
    return _render_detail(db.get_or_404(GeneratedReport, report_id))


def _all_versions(report):
    return db.session.execute(
        db.select(ReportVersion).where(ReportVersion.generated_report_id == report.id)
        .order_by(ReportVersion.version_no)
    ).scalars().all()


def _exports(report):
    return db.session.execute(
        db.select(ReportExport).where(ReportExport.generated_report_id == report.id)
        .order_by(ReportExport.created_at.desc(), ReportExport.id.desc())
    ).scalars().all()


def _issues(report, version):
    """Everything a person should look at before approving this exact text."""
    check = check_report(version.body_text, report.child.first_name)
    issues = list(check["issues"])
    export = db.session.execute(
        db.select(ReportExport).where(ReportExport.generated_report_id == report.id,
                                      ReportExport.version_id == version.id)
        .order_by(ReportExport.created_at.desc(), ReportExport.id.desc())
    ).scalars().first()
    if export is None:
        issues.append("This exact text has not been exported and page-checked yet. "
                      "Press 'Export Word file' first.")
    elif export.page_check in ("too_long", "estimated_long"):
        issues.append(export.page_note or "The Word file may not fit on one page.")
    return check, issues, export


def _render_detail(report, answer_values=None, errors=None, editor_text=None):
    clars = _clarifications(report)
    versions = _all_versions(report)
    version = versions[-1] if versions else None
    check = issues = export = None
    approval = None
    if version and report.status in (STATUS_DRAFT_READY, STATUS_APPROVED):
        check, issues, export = _issues(report, version)
    if report.status == STATUS_APPROVED:
        approval = db.session.execute(
            db.select(ReportApproval).where(ReportApproval.generated_report_id == report.id)
            .order_by(ReportApproval.approved_at.desc(), ReportApproval.id.desc())
        ).scalars().first()
    label, colour = STATUS_LABELS.get(report.status, (report.status, "secondary"))
    return render_template(
        "reports/detail.html", report=report, child=report.child, clars=clars,
        unanswered=[c for c in clars if c.answer is None], answered=[c for c in clars if c.answer],
        version=version, versions=versions, version_labels=VERSION_LABELS, check=check,
        issues=issues, export=export, exports=_exports(report), approval=approval,
        status_label=label, status_colour=colour,
        busy=is_busy(report), obs_count=len(json.loads(report.included_observation_ids or "[]")),
        answer_values=answer_values or {}, errors=errors or [],
        editor_text=editor_text if editor_text is not None else (version.body_text if version else ""))


@bp.route("/reports/<int:report_id>/answers", methods=["POST"])
@login_required
@limiter.limit("20 per hour")
def answers(report_id):
    report = db.get_or_404(GeneratedReport, report_id)
    if is_busy(report):
        flash("This report is still being generated. Please wait.", "warning")
        return redirect(url_for("reports.detail", report_id=report.id))
    if report.status != STATUS_NEEDS_ANSWERS:
        flash("There are no open questions for this report.", "info")
        return redirect(url_for("reports.detail", report_id=report.id))

    open_questions = [c for c in _clarifications(report) if c.answer is None]
    values, missing = {}, False
    for c in open_questions:
        text = (request.form.get(f"answer_{c.id}") or "").strip()
        values[c.id] = text
        if not text:
            missing = True
    if missing:
        return _render_detail(report, answer_values=values,
                              errors=["Please answer every question (write 'not known' if the team does not know)."])
    for c in open_questions:
        c.answer = values[c.id][:5000]
        c.answered_by_id = current_user.id
        c.answered_at = utcnow()
    log_event("report_answers_saved", "generated_report", report.id)
    mark_generating(report)
    run_generation(report, current_user.id)
    return redirect(url_for("reports.detail", report_id=report.id))


@bp.route("/reports/<int:report_id>/retry", methods=["POST"])
@login_required
@limiter.limit("20 per hour")
def retry(report_id):
    report = db.get_or_404(GeneratedReport, report_id)
    if is_busy(report):
        flash("This report is still being generated. Please wait.", "warning")
        return redirect(url_for("reports.detail", report_id=report.id))
    if report.status not in (STATUS_FAILED, STATUS_GENERATING):
        flash("Nothing to retry for this report.", "info")
        return redirect(url_for("reports.detail", report_id=report.id))
    log_event("report_retry", "generated_report", report.id)
    mark_generating(report)
    run_generation(report, current_user.id)
    return redirect(url_for("reports.detail", report_id=report.id))


# ---------------- review, edit, revise, export, approve ----------------
def _draft_or_redirect(report):
    """Editing actions are only allowed on a draft that is not being generated."""
    if report.status != STATUS_DRAFT_READY or is_busy(report):
        flash("This report cannot be changed right now (it is approved or still being generated).", "warning")
        return redirect(url_for("reports.detail", report_id=report.id))
    return None


@bp.route("/reports/<int:report_id>/save", methods=["POST"])
@login_required
def save(report_id):
    report = db.get_or_404(GeneratedReport, report_id)
    blocked = _draft_or_redirect(report)
    if blocked:
        return blocked
    text = (request.form.get("text") or "").replace("\r\n", "\n").strip()
    latest = latest_version(report.id)
    if not text:
        return _render_detail(report, errors=["The report text cannot be empty."], editor_text=text)
    if len(text) > MAX_TEXT:
        return _render_detail(report, errors=[f"The text is too long (limit {MAX_TEXT:,} characters)."],
                              editor_text=text)
    if request.form.get("base_version") != str(latest.version_no):
        return _render_detail(report, editor_text=text, errors=[
            "Someone saved a newer version while you were editing. Your text is still in the box below. "
            "Copy it, check the newest version, and save again."])
    if text == latest.body_text.strip():
        flash("No changes to save.", "info")
        return redirect(url_for("reports.detail", report_id=report.id))
    db.session.add(ReportVersion(generated_report_id=report.id, version_no=latest.version_no + 1,
                                 kind="edited", body_text=text, created_by_id=current_user.id))
    try:
        log_event("report_edited", "generated_report", report.id)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return _render_detail(report, editor_text=text, errors=[
            "Someone saved at the same moment. Your text is still in the box below. Please save again."])
    flash(f"Saved as version {latest.version_no + 1}. The original AI draft is kept.", "success")
    return redirect(url_for("reports.detail", report_id=report.id))


@bp.route("/reports/<int:report_id>/revise", methods=["POST"])
@login_required
@limiter.limit("20 per hour")
def revise(report_id):
    report = db.get_or_404(GeneratedReport, report_id)
    blocked = _draft_or_redirect(report)
    if blocked:
        return blocked
    mark_generating(report)
    ok, message = run_revision(report, current_user.id)
    flash(message, "success" if ok else "danger")
    return redirect(url_for("reports.detail", report_id=report.id))


@bp.route("/reports/<int:report_id>/versions/<int:version_id>")
@login_required
def version_view(report_id, version_id):
    report = db.get_or_404(GeneratedReport, report_id)
    version = db.get_or_404(ReportVersion, version_id)
    if version.generated_report_id != report.id:
        abort(404)
    check = check_report(version.body_text, report.child.first_name)
    return render_template("reports/version.html", report=report, child=report.child,
                           version=version, check=check, labels=VERSION_LABELS)


@bp.route("/reports/<int:report_id>/restore/<int:version_id>", methods=["POST"])
@login_required
def restore(report_id, version_id):
    report = db.get_or_404(GeneratedReport, report_id)
    blocked = _draft_or_redirect(report)
    if blocked:
        return blocked
    old = db.get_or_404(ReportVersion, version_id)
    if old.generated_report_id != report.id:
        abort(404)
    latest = latest_version(report.id)
    db.session.add(ReportVersion(generated_report_id=report.id, version_no=latest.version_no + 1,
                                 kind="edited", body_text=old.body_text, created_by_id=current_user.id))
    try:
        log_event("report_version_restored", "generated_report", report.id)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("Someone saved at the same moment. Please try again.", "warning")
        return redirect(url_for("reports.detail", report_id=report.id))
    flash(f"Version {old.version_no} was copied as the new version {latest.version_no + 1}.", "success")
    return redirect(url_for("reports.detail", report_id=report.id))


@bp.route("/reports/<int:report_id>/export", methods=["POST"])
@login_required
def export(report_id):
    report = db.get_or_404(GeneratedReport, report_id)
    if report.status not in (STATUS_DRAFT_READY, STATUS_APPROVED) or is_busy(report):
        flash("There is no finished text to export yet.", "warning")
        return redirect(url_for("reports.detail", report_id=report.id))
    version = latest_version(report.id)
    check = check_report(version.body_text, report.child.first_name)
    if not check["format_ok"]:
        flash("Fix the two identification lines first: they must read 'Name: ...' and "
              "'Class/Education: ...'.", "danger")
        return redirect(url_for("reports.detail", report_id=report.id))
    name_line, class_line, body = split_report(version.body_text)
    data = build_docx(name_line, class_line, body)
    pages = check_pages(data, name_line, class_line, body)
    all_children = db.session.execute(db.select(Child)).scalars().all()
    exp = ReportExport(
        generated_report_id=report.id, version_id=version.id,
        filename=report_filename(report.child, all_children),
        stored_name=save_generated(data), page_count=pages["count"],
        page_check=pages["status"], page_note=pages["note"], created_by_id=current_user.id)
    db.session.add(exp)
    db.session.flush()
    log_event("report_exported", "generated_report", report.id)
    db.session.commit()
    if pages["status"] in ("too_long", "estimated_long"):
        flash("Word file created, but it may not fit on one page. Please review.", "warning")
    else:
        flash("Word file created.", "success")
    return redirect(url_for("reports.detail", report_id=report.id))


@bp.route("/exports/<int:export_id>/download")
@login_required
def download_export(export_id):
    exp = db.get_or_404(ReportExport, export_id)
    path = generated_path(exp.stored_name)
    if not os.path.exists(path):
        abort(404)
    log_event("report_downloaded", "generated_report", exp.generated_report_id)
    db.session.commit()
    resp = send_file(path, as_attachment=True, download_name=exp.filename,
                     mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    resp.headers["Cache-Control"] = "private, no-store"
    return resp


@bp.route("/reports/<int:report_id>/approve", methods=["POST"])
@admin_required
def approve(report_id):
    report = db.get_or_404(GeneratedReport, report_id)
    blocked = _draft_or_redirect(report)
    if blocked:
        return blocked
    version = latest_version(report.id)
    check, issues, _export = _issues(report, version)
    if not request.form.get("confirm_read"):
        flash("Please confirm that you have read the whole report before approving it.", "danger")
        return redirect(url_for("reports.detail", report_id=report.id))
    if issues and not request.form.get("confirm_warnings"):
        flash("There are warnings. Tick the box to accept them, or fix them first.", "danger")
        return redirect(url_for("reports.detail", report_id=report.id))
    db.session.add(ReportApproval(generated_report_id=report.id, version_id=version.id,
                                  approved_by_id=current_user.id, accepted_warnings=bool(issues)))
    report.status = STATUS_APPROVED
    log_event("report_approved", "generated_report", report.id)
    db.session.commit()
    flash(f"Version {version.version_no} is approved. Nothing is sent to sponsors automatically.", "success")
    return redirect(url_for("reports.detail", report_id=report.id))


@bp.route("/reports/<int:report_id>/reopen", methods=["POST"])
@admin_required
def reopen(report_id):
    report = db.get_or_404(GeneratedReport, report_id)
    if report.status != STATUS_APPROVED:
        flash("This report is not approved.", "info")
        return redirect(url_for("reports.detail", report_id=report.id))
    report.status = STATUS_DRAFT_READY
    log_event("report_reopened", "generated_report", report.id)
    db.session.commit()
    flash("The report is open for changes again. It needs a new approval.", "info")
    return redirect(url_for("reports.detail", report_id=report.id))
