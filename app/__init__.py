import os
from flask import Flask, render_template
from config import config_by_name
from .extensions import db, migrate, login_manager, csrf, limiter


def create_app(config_name=None):
    config_name = config_name or os.environ.get("APP_ENV", "development")
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_by_name[config_name])

    if not app.config.get("SECRET_KEY"):
        raise RuntimeError("SECRET_KEY is not set. Add it to your .env file.")
    os.makedirs(app.instance_path, exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    from . import models  # noqa: F401  (so migrations see the tables)
    from .auth.routes import bp as auth_bp
    from .admin.routes import bp as admin_bp
    from .main.routes import bp as main_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(main_bp)

    from .cli import register_cli
    register_cli(app)

    @app.after_request
    def security_headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "same-origin"
        return resp

    messages = {
        403: "You do not have permission to do that.",
        404: "That page was not found.",
        500: "Something went wrong. Your saved data is safe. Please try again.",
    }

    def handle_error(e):
        code = getattr(e, "code", 500)
        if code == 500:
            db.session.rollback()
        return render_template("error.html", code=code, message=messages[code]), code

    for code in messages:
        app.register_error_handler(code, handle_error)

    return app
