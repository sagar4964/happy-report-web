from datetime import datetime, timezone
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from .extensions import db, login_manager

ROLE_ADMIN = "admin"
ROLE_STAFF = "staff"
ROLES = [(ROLE_STAFF, "Staff member"), (ROLE_ADMIN, "Administrator")]

# Report generation states
STATUS_GENERATING = "generating"
STATUS_NEEDS_ANSWERS = "needs_answers"
STATUS_DRAFT_READY = "draft_ready"
STATUS_FAILED = "failed"


def utcnow():
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default=ROLE_STAFF)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    last_login_at = db.Column(db.DateTime(timezone=True))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == ROLE_ADMIN


class AuditEvent(db.Model):
    """Who did what, and when. Keep 'detail' free of personal information."""
    __tablename__ = "audit_events"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    action = db.Column(db.String(60), nullable=False)
    entity = db.Column(db.String(60))
    entity_id = db.Column(db.Integer)
    detail = db.Column(db.String(255))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


class Category(db.Model):
    """Observation categories. Admin-configurable, never hardcoded in code."""
    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)


class ReportingPeriod(db.Model):
    """A reporting year with its start and end dates."""
    __tablename__ = "reporting_periods"

    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, unique=True, nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)


class Child(db.Model):
    __tablename__ = "children"

    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(80), nullable=False, index=True)
    last_name = db.Column(db.String(80), nullable=False, index=True)
    current_education = db.Column(db.String(120), nullable=False)
    living_situation_note = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    updated_at = db.Column(db.DateTime(timezone=True), onupdate=utcnow)

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"


class Observation(db.Model):
    __tablename__ = "observations"

    id = db.Column(db.Integer, primary_key=True)
    child_id = db.Column(db.Integer, db.ForeignKey("children.id"), nullable=False, index=True)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=False)
    event_date = db.Column(db.Date, nullable=False)
    text = db.Column(db.Text, nullable=False)
    source_note = db.Column(db.String(255))
    correction_note = db.Column(db.String(255))
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    updated_at = db.Column(db.DateTime(timezone=True), onupdate=utcnow)
    # Soft delete: the row stays in the database, it is just hidden.
    is_deleted = db.Column(db.Boolean, nullable=False, default=False, index=True)
    deleted_at = db.Column(db.DateTime(timezone=True))
    deleted_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    child = db.relationship("Child")
    category = db.relationship("Category")
    created_by = db.relationship("User", foreign_keys=[created_by_id])
    updated_by = db.relationship("User", foreign_keys=[updated_by_id])

    __table_args__ = (db.Index("ix_observations_child_date", "child_id", "event_date"),)


class HistoricalReport(db.Model):
    """A previously written annual report (uploaded file) that belongs to ONE child."""
    __tablename__ = "historical_reports"

    id = db.Column(db.Integer, primary_key=True)
    child_id = db.Column(db.Integer, db.ForeignKey("children.id"), nullable=False, index=True)
    reporting_year = db.Column(db.Integer, nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    stored_name = db.Column(db.String(64), unique=True, nullable=False)  # server-made name
    file_type = db.Column(db.String(10), nullable=False)  # "docx" or "pdf"
    file_size = db.Column(db.Integer, nullable=False)
    extracted_text = db.Column(db.Text)  # filled for .docx only
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    uploaded_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    # Soft remove: the file stays on disk, it is just hidden.
    is_removed = db.Column(db.Boolean, nullable=False, default=False, index=True)
    removed_at = db.Column(db.DateTime(timezone=True))
    removed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    child = db.relationship("Child")
    uploaded_by = db.relationship("User", foreign_keys=[uploaded_by_id])

    __table_args__ = (db.Index("ix_historical_child_year", "child_id", "reporting_year"),)


class ReportTemplate(db.Model):
    """One version of the Report Writing Instructions. Old versions are never changed."""
    __tablename__ = "report_templates"

    id = db.Column(db.Integer, primary_key=True)
    version_number = db.Column(db.Integer, unique=True, nullable=False)
    note = db.Column(db.String(255))
    prompt_text = db.Column(db.Text, nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=False, index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    created_by = db.relationship("User", foreign_keys=[created_by_id])


class GeneratedReport(db.Model):
    """One report-writing job for one child and one reporting year."""
    __tablename__ = "generated_reports"

    id = db.Column(db.Integer, primary_key=True)
    child_id = db.Column(db.Integer, db.ForeignKey("children.id"), nullable=False, index=True)
    reporting_year = db.Column(db.Integer, nullable=False)
    template_id = db.Column(db.Integer, db.ForeignKey("report_templates.id"), nullable=False)
    previous_report_id = db.Column(db.Integer, db.ForeignKey("historical_reports.id"))
    previous_report_confirmed_missing = db.Column(db.Boolean, nullable=False, default=False)
    included_observation_ids = db.Column(db.Text, nullable=False, default="[]")  # JSON list of ids
    extra_bullets = db.Column(db.Text)
    receipt_context = db.Column(db.String(255))
    status = db.Column(db.String(20), nullable=False, default=STATUS_GENERATING)
    last_error = db.Column(db.String(500))
    model_name = db.Column(db.String(100))
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), onupdate=utcnow)

    child = db.relationship("Child")
    template = db.relationship("ReportTemplate")
    previous_report = db.relationship("HistoricalReport")
    created_by = db.relationship("User", foreign_keys=[created_by_id])


class ReportVersion(db.Model):
    """A saved piece of report text. AI drafts are never overwritten."""
    __tablename__ = "report_versions"

    id = db.Column(db.Integer, primary_key=True)
    generated_report_id = db.Column(db.Integer, db.ForeignKey("generated_reports.id"),
                                    nullable=False, index=True)
    version_no = db.Column(db.Integer, nullable=False)
    kind = db.Column(db.String(20), nullable=False, default="ai_draft")
    body_text = db.Column(db.Text, nullable=False)  # includes the two identification lines
    notes = db.Column(db.Text)  # AI remarks meant for the team, not part of the report
    model_name = db.Column(db.String(100))
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    __table_args__ = (db.UniqueConstraint("generated_report_id", "version_no"),)


class Clarification(db.Model):
    """A question the AI asked and the team's answer."""
    __tablename__ = "clarifications"

    id = db.Column(db.Integer, primary_key=True)
    generated_report_id = db.Column(db.Integer, db.ForeignKey("generated_reports.id"),
                                    nullable=False, index=True)
    round_no = db.Column(db.Integer, nullable=False)
    question = db.Column(db.Text, nullable=False)
    answer = db.Column(db.Text)
    answered_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    answered_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


@login_manager.user_loader
def load_user(user_id):
    user = db.session.get(User, int(user_id))
    # A deactivated user is logged out on their very next request.
    if user is None or not user.is_active:
        return None
    return user
