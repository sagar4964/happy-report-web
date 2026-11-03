"""Runs one report generation: builds the request, calls the AI, stores the outcome."""
import json
import logging
from datetime import date, timedelta, timezone
from sqlalchemy import func
from . import ai
from .ai.base import AIError
from .ai.parse import parse_ai_json
from .audit import log_event
from .extensions import db
from .models import (Observation, HistoricalReport, ReportVersion, Clarification, utcnow,
                     STATUS_GENERATING, STATUS_NEEDS_ANSWERS, STATUS_DRAFT_READY, STATUS_FAILED)
from .prompt_builder import build_system_prompt, build_user_message

log = logging.getLogger(__name__)
BUSY_MINUTES = 5  # a "generating" job older than this is treated as stuck and may be retried


def _aware(dt):
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def is_busy(report):
    """True while a generation for this report is (probably) still running."""
    if report.status != STATUS_GENERATING:
        return False
    stamp = _aware(report.updated_at or report.created_at)
    return utcnow() - stamp < timedelta(minutes=BUSY_MINUTES)


def mark_generating(report):
    report.status = STATUS_GENERATING
    report.last_error = None
    db.session.commit()


def _fail(report, message):
    report.status = STATUS_FAILED
    report.last_error = message[:500]
    log_event("report_failed", "generated_report", report.id)
    db.session.commit()
    return report


def run_generation(report, user_id):
    """Asks the AI and stores the result. AI problems never raise: they set status 'failed'
    and keep every input, so the user can simply try again."""
    ids = json.loads(report.included_observation_ids or "[]")
    observations = []
    if ids:
        observations = db.session.execute(
            db.select(Observation)
            .where(Observation.id.in_(ids),
                   Observation.child_id == report.child_id,  # never another child's notes
                   Observation.is_deleted.is_(False))
            .order_by(Observation.event_date, Observation.id)
        ).scalars().all()

    previous = None
    if report.previous_report_id:
        previous = db.session.get(HistoricalReport, report.previous_report_id)
        if previous is None or previous.child_id != report.child_id or previous.is_removed:
            return _fail(report, "The selected previous report is no longer available. "
                                 "Please start a new report.")

    clarifications = db.session.execute(
        db.select(Clarification).where(Clarification.generated_report_id == report.id)
        .order_by(Clarification.round_no, Clarification.id)
    ).scalars().all()
    answers = [(c.question, c.answer) for c in clarifications if c.answer]
    round_no = max([c.round_no for c in clarifications], default=0)

    system_prompt = build_system_prompt(report.template.prompt_text)
    user_message = build_user_message(
        child=report.child, year=report.reporting_year, today=date.today(),
        receipt_context=report.receipt_context, observations=observations,
        extra_bullets=report.extra_bullets, previous_report=previous,
        previous_confirmed_missing=report.previous_report_confirmed_missing,
        answers=answers, clarification_round=round_no)

    try:
        result = ai.get_provider().generate(system_prompt, user_message)
    except AIError as e:
        return _fail(report, e.user_message)
    except Exception:
        log.exception("Unexpected error while contacting the AI")
        return _fail(report, "Something unexpected went wrong while contacting the AI. Please try again.")

    try:
        parsed = parse_ai_json(result.text)
    except ValueError:
        return _fail(report, "The AI's reply could not be understood. Please try again.")

    report.model_name = result.model
    if parsed["status"] == "questions":
        for q in parsed["questions"]:
            db.session.add(Clarification(generated_report_id=report.id,
                                         round_no=round_no + 1, question=q))
        report.status = STATUS_NEEDS_ANSWERS
        report.last_error = None
        log_event("report_questions", "generated_report", report.id)
    else:
        last = db.session.scalar(
            db.select(func.max(ReportVersion.version_no))
            .where(ReportVersion.generated_report_id == report.id)) or 0
        db.session.add(ReportVersion(
            generated_report_id=report.id, version_no=last + 1, kind="ai_draft",
            body_text=parsed["report"], notes=parsed["notes"] or None,
            model_name=result.model, created_by_id=user_id))
        report.status = STATUS_DRAFT_READY
        report.last_error = None
        log_event("report_draft_created", "generated_report", report.id)
    db.session.commit()
    return report
