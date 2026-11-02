from functools import wraps
from flask import abort, current_app
from flask_login import current_user
from .models import ROLE_ADMIN


def roles_required(*roles):
    """Server-side permission check for a route."""
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                return current_app.login_manager.unauthorized()
            if current_user.role not in roles:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


admin_required = roles_required(ROLE_ADMIN)
