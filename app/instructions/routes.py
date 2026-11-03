from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy import func
from ..extensions import db
from ..models import ReportTemplate
from ..audit import log_event
from ..decorators import admin_required
from .forms import InstructionForm

bp = Blueprint("instructions", __name__, url_prefix="/instructions")


def _all_versions():
    return db.session.execute(
        db.select(ReportTemplate).order_by(ReportTemplate.version_number.desc())
    ).scalars().all()


@bp.route("/")
@login_required
def index():
    versions = _all_versions()
    active = next((v for v in versions if v.is_active), None)
    return render_template("instructions/index.html", versions=versions, active=active)


@bp.route("/<int:template_id>")
@login_required
def view(template_id):
    template = db.get_or_404(ReportTemplate, template_id)
    return render_template("instructions/view.html", template=template)


@bp.route("/new", methods=["GET", "POST"])
@admin_required
def new():
    versions = _all_versions()
    active = next((v for v in versions if v.is_active), None)
    form = InstructionForm()
    if not form.is_submitted() and active:
        form.prompt_text.data = active.prompt_text  # start from the current text
    if form.validate_on_submit():
        number = (db.session.scalar(db.select(func.max(ReportTemplate.version_number))) or 0) + 1
        for v in versions:
            v.is_active = False
        template = ReportTemplate(version_number=number, is_active=True,
                                  note=(form.note.data or "").strip() or None,
                                  prompt_text=form.prompt_text.data.replace("\r\n", "\n"),
                                  created_by_id=current_user.id)
        db.session.add(template)
        db.session.flush()
        log_event("instructions_new_version", "report_template", template.id)
        db.session.commit()
        flash(f"Saved as version {number} and made active. Older versions are kept.", "success")
        return redirect(url_for("instructions.index"))
    return render_template("instructions/new.html", form=form, active=active)


@bp.route("/<int:template_id>/activate", methods=["POST"])
@admin_required
def activate(template_id):
    template = db.get_or_404(ReportTemplate, template_id)
    for v in _all_versions():
        v.is_active = (v.id == template.id)
    log_event("instructions_activated", "report_template", template.id)
    db.session.commit()
    flash(f"Version {template.version_number} is now active.", "success")
    return redirect(url_for("instructions.index"))
