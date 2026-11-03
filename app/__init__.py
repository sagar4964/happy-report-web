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
    # Uploaded files live OUTSIDE any public folder, inside the instance folder.
    app.config.setdefault("UPLOAD_FOLDER", os.path.join(app.instance_path, "uploads"))
    app.config.setdefault("MAX_CONTENT_LENGTH", 10 * 1024 * 1024)  # 10 MB

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    from . import models  # noqa: F401  (so migrations see the tables)
    from .auth.routes import bp as auth_bp
    from .admin.routes import bp as admin_bp
    from .main.routes import bp as main_bp
    from .children.routes import bp as children_bp
    from .observations.routes import bp as observations_bp
    from .history.routes import bp as history_bp
    from .reports.routes import bp as reports_bp
    from .instructions.routes import bp as instructions_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(children_bp)
    app.register_blueprint(observations_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(instructions_bp)

    from .cli import register_cli
    register_cli(app)

    @app.context_processor
    def ai_flags():
        # AI_TEST_MODE=1 in .env shows a red reminder on every page: fictional data only.
        flag = os.environ.get("AI_TEST_MODE", "").strip().lower() in ("1", "true", "yes", "on")
        return {"ai_test_mode": flag}

    @app.after_request
    def security_headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "same-origin"
        return resp

    messages = {
        403: "You do not have permission to do that.",
        404: "That page was not found.",
        413: "That file is too large. The limit is 10 MB.",
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
