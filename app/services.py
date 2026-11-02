"""Small helper functions shared by several screens."""
from datetime import date
from sqlalchemy import func, or_
from .extensions import db
from .models import Category, Child, HistoricalReport, Observation, ReportingPeriod


def normalize_text(text):
    """Lower-case, collapse spaces, drop leading bullet marks (for duplicate checks)."""
    return " ".join((text or "").lower().split()).strip("-•* ")


def get_periods():
    return db.session.execute(
        db.select(ReportingPeriod).order_by(ReportingPeriod.year.desc())
    ).scalars().all()


def default_period(periods, today=None):
    """The period that contains today, otherwise the most recent one."""
    today = today or date.today()
    for p in periods:
        if p.start_date <= today <= p.end_date:
            return p
    return periods[0] if periods else None


def resolve_period(periods, period_arg):
    """Turn the ?period= value from the address into a period (None means all dates)."""
    if period_arg == "all":
        return None
    if period_arg and period_arg.isdigit():
        for p in periods:
            if p.id == int(period_arg):
                return p
    return default_period(periods)


def category_choices(include_id=None):
    """Active categories (plus one already-used inactive category when editing)."""
    stmt = (
        db.select(Category)
        .where(or_(Category.is_active.is_(True), Category.id == include_id))
        .order_by(Category.sort_order, Category.name)
    )
    return [(c.id, c.name) for c in db.session.execute(stmt).scalars()]


def find_same_name(first, last, exclude_id=None):
    stmt = db.select(Child).where(
        func.lower(Child.first_name) == first.strip().lower(),
        func.lower(Child.last_name) == last.strip().lower(),
    )
    if exclude_id:
        stmt = stmt.where(Child.id != exclude_id)
    return db.session.execute(stmt).scalars().all()


def is_duplicate_observation(child_id, text, exclude_id=None):
    """True if this child already has an observation with the same wording."""
    target = normalize_text(text)
    stmt = db.select(Observation.id, Observation.text).where(
        Observation.child_id == child_id, Observation.is_deleted.is_(False)
    )
    if exclude_id:
        stmt = stmt.where(Observation.id != exclude_id)
    for _obs_id, existing in db.session.execute(stmt):
        if normalize_text(existing) == target:
            return True
    return False


def latest_previous_report(child_id, year):
    """The most recent report of THIS child from a year before `year`.

    Within the same year a Word file is preferred over a PDF (Word has readable text).
    Returns None when the child has no earlier report.
    """
    stmt = (
        db.select(HistoricalReport)
        .where(
            HistoricalReport.child_id == child_id,
            HistoricalReport.is_removed.is_(False),
            HistoricalReport.reporting_year < year,
        )
        .order_by(
            HistoricalReport.reporting_year.desc(),
            (HistoricalReport.file_type == "docx").desc(),
            HistoricalReport.uploaded_at.desc(),
            HistoricalReport.id.desc(),
        )
        .limit(1)
    )
    return db.session.execute(stmt).scalar_one_or_none()
