"""Runs report generation and revision: builds the request, calls the AI, stores the outcome."""
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
from .report_checks import check_report, WORD_MIN, WORD_MAX

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


def latest_version(report_id):
    return db.session.execute(
        db.select(ReportVersion).where(ReportVersion.generated_report_id == report_id)
        .order_by(ReportVersion.version_no.desc())
    ).scalars().first()


def _fail(report, message):
    report.status = STATUS_FAILED
    report.last_error = message[:500]
    log_event("report_failed", "generated_report", report.id)
    db.session.commit()
    return report


def _build_messages(report, revision_draft=None, revision_instruction=None):
    """Returns (system_prompt, user_message, round_no, error). error is a message or None."""
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
            return None, None, 0, ("The selected previous report is no longer available. "
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
        answers=answers, clarification_round=round_no,
        revision_draft=revision_draft, revision_instruction=revision_instruction)
    return system_prompt, user_message, round_no, None


def _ask_ai(system_prompt, user_message):
    """Returns (result, error_message). Never raises."""
    try:
        return ai.get_provider().generate(system_prompt, user_message), None
    except AIError as e:
        return None, e.user_message
    except Exception:
        log.exception("Unexpected error while contacting the AI")
        return None, "Something unexpected went wrong while contacting the AI. Please try again."


def run_generation(report, user_id):
    """Asks the AI and stores the result. AI problems never raise: they set status 'failed'
    and keep every input, so the user can simply try again."""
    system_prompt, user_message, round_no, error = _build_messages(report)
    if error:
        return _fail(report, error)
    result, error = _ask_ai(system_prompt, user_message)
    if error:
        return _fail(report, error)

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


def run_revision(report, user_id):
    """Controlled revision: the AI re-checks the CURRENT text (including staff edits) against the
    original sources and the word range. The result is a NEW version; nothing is overwritten.

    Returns (ok, message). A failed revision leaves the report as a normal draft."""
    current = latest_version(report.id)
    check = check_report(current.body_text, report.child.first_name)
    instruction = (
        f"The current report body has {check['word_count']} words. The required range is "
        f"{WORD_MIN}-{WORD_MAX} words (the two identification lines are not counted). Revise the "
        "draft so the body fits the range. Keep every name, number, relationship, exam result and "
        "the order of events exactly as in the data. Do not add facts that are not in the data. "
        "Do not drop essential events: shorten minor details first, or develop important details "
        "if the text is too short. Keep the same two identification lines. Return the full revised "
        "report.")
    system_prompt, user_message, _round, error = _build_messages(
        report, revision_draft=current.body_text, revision_instruction=instruction)

    def give_up(message):
        report.status = STATUS_DRAFT_READY  # the existing draft stays usable
        report.last_error = None
        db.session.commit()
        return False, message

    if error:
        return give_up(error)
    result, error = _ask_ai(system_prompt, user_message)
    if error:
        return give_up(error)
    try:
        parsed = parse_ai_json(result.text)
    except ValueError:
        return give_up("The AI's reply could not be understood. Your draft is unchanged.")
    if parsed["status"] != "report":
        return give_up("The AI asked a question instead of revising: " + parsed["questions"][0])

    last = latest_version(report.id).version_no
    db.session.add(ReportVersion(
        generated_report_id=report.id, version_no=last + 1, kind="ai_revision",
        body_text=parsed["report"], notes=parsed["notes"] or None,
        model_name=result.model, created_by_id=user_id))
    report.status = STATUS_DRAFT_READY
    report.model_name = result.model
    report.last_error = None
    log_event("report_revised", "generated_report", report.id)
    db.session.commit()
    return True, f"The AI prepared version {last + 1}. Please read it carefully; your earlier versions are kept."
