"""Removing user accounts safely.

A person who has worked in the app (written notes, started reports, logged in...) cannot simply be
deleted: their name is attached to that work. Such accounts are ANONYMISED instead: the login is
disabled and the name becomes "Removed user". Accounts that were never used are deleted completely.
"""
import secrets
from sqlalchemy import func
from .extensions import db
from .models import (User, ROLE_STAFF, AuditEvent, Child, Observation, HistoricalReport, ReportTemplate,
                     GeneratedReport, ReportVersion, Clarification, ReportExport, ReportApproval)

REMOVED_DOMAIN = "removed.invalid"
REMOVED_NAME = "Removed user"

# Every place in the database where a user's id is stored.
_LINKS = [
    (AuditEvent, AuditEvent.user_id),
    (Child, Child.created_by_id), (Child, Child.updated_by_id),
    (Observation, Observation.created_by_id), (Observation, Observation.updated_by_id),
    (Observation, Observation.deleted_by_id),
    (HistoricalReport, HistoricalReport.uploaded_by_id), (HistoricalReport, HistoricalReport.removed_by_id),
    (ReportTemplate, ReportTemplate.created_by_id),
    (GeneratedReport, GeneratedReport.created_by_id),
    (ReportVersion, ReportVersion.created_by_id),
    (Clarification, Clarification.answered_by_id),
    (ReportExport, ReportExport.created_by_id),
    (ReportApproval, ReportApproval.approved_by_id),
]


def is_removed(user):
    return (user.email or "").endswith("@" + REMOVED_DOMAIN)


def has_records(user_id):
    for model, column in _LINKS:
        if db.session.scalar(db.select(func.count()).select_from(model).where(column == user_id)):
            return True
    return False


def remove_user(user):
    """Returns "deleted" (never used) or "anonymised" (kept as 'Removed user'). Caller commits."""
    if not has_records(user.id):
        db.session.delete(user)
        return "deleted"
    user.name = REMOVED_NAME
    user.email = f"removed-{user.id}@{REMOVED_DOMAIN}"
    user.role = ROLE_STAFF
    user.is_active = False
    user.set_password(secrets.token_urlsafe(32))  # nobody knows this password
    return "anonymised"
