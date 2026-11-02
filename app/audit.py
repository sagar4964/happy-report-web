from flask_login import current_user
from .extensions import db
from .models import AuditEvent


def log_event(action, entity=None, entity_id=None, detail=None):
    """Adds an audit row. The caller must commit."""
    user_id = current_user.id if current_user.is_authenticated else None
    db.session.add(AuditEvent(user_id=user_id, action=action,
                              entity=entity, entity_id=entity_id, detail=detail))
