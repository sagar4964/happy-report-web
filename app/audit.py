from flask import has_request_context
from flask_login import current_user
from .extensions import db
from .models import AuditEvent


def log_event(action, entity=None, entity_id=None, detail=None):
    """Adds an audit row. The caller must commit. Works inside a web request and in
    command-line tasks (where nobody is logged in, so user_id stays empty)."""
    user_id = None
    if has_request_context() and current_user.is_authenticated:
        user_id = current_user.id
    db.session.add(AuditEvent(user_id=user_id, action=action,
                              entity=entity, entity_id=entity_id, detail=detail))
