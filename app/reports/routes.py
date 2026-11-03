import json
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from ..extensions import db, limiter
from ..models import (Child, Observation, HistoricalReport, GeneratedReport, ReportVersion,
                      Clarification, ReportTemplate, utcnow,
                      STATUS_GENERATING, STATUS_NEEDS_ANSWERS, STATUS_DRAFT_READY, STATUS_FAILED)
from ..audit import log_event
from ..services import get_periods, resolve_period, latest_previous_report
from ..report_checks import check_report
from ..report_service import run_generation, is_busy, mark_generating

bp = Blueprint("reports", __name__)

STATUS_LABELS = {
    STATUS_GENERATING: ("Generating", "secondary"),
    STATUS_NEEDS_ANSWERS: ("Questions to answer", "warning"),
    STATUS_DRAFT_READY: ("Draft ready", "success"),
    STATUS_FAILED: ("Failed - can retry", "danger"),
}


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


def _render_detail(report, answer_values=None, errors=None):
    clars = _clarifications(report)
    version = db.session.execute(
        db.select(ReportVersion).where(ReportVersion.generated_report_id == report.id)
        .order_by(ReportVersion.version_no.desc())
    ).scalars().first()
    check = check_report(version.body_text, report.child.first_name) if version else None
    label, colour = STATUS_LABELS.get(report.status, (report.status, "secondary"))
    return render_template(
        "reports/detail.html", report=report, child=report.child, clars=clars,
        unanswered=[c for c in clars if c.answer is None], answered=[c for c in clars if c.answer],
        version=version, check=check, status_label=label, status_colour=colour,
        busy=is_busy(report), obs_count=len(json.loads(report.included_observation_ids or "[]")),
        answer_values=answer_values or {}, errors=errors or [])


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
