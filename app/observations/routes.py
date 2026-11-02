from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user
from ..extensions import db
from ..models import Child, Observation, utcnow
from ..audit import log_event
from ..services import category_choices, is_duplicate_observation
from .forms import ObservationForm

bp = Blueprint("observations", __name__)

DUPLICATE_MESSAGE = ("This child already has an observation with the same wording. "
                     "Tick the box if you still want to save it.")


@bp.route("/children/<int:child_id>/observations/new", methods=["GET", "POST"])
@login_required
def new(child_id):
    child = db.get_or_404(Child, child_id)
    if not child.is_active:
        flash("This child is archived. Ask an administrator to restore the profile first.", "warning")
        return redirect(url_for("children.detail", child_id=child.id))

    form = ObservationForm()
    form.category_id.choices = category_choices()
    if not form.category_id.choices:
        flash("There are no categories yet. An administrator must add them (Admin > Categories).", "warning")
        return redirect(url_for("children.detail", child_id=child.id))

    show_confirm = False
    if form.validate_on_submit():
        if is_duplicate_observation(child.id, form.text.data) and not form.confirm_duplicate.data:
            show_confirm = True
            form.confirm_duplicate.errors = [DUPLICATE_MESSAGE]
        else:
            obs = Observation(
                child_id=child.id,  # the child comes from the address, never from the form
                category_id=form.category_id.data,
                event_date=form.event_date.data,
                text=form.text.data.strip(),
                source_note=(form.source_note.data or "").strip() or None,
                created_by_id=current_user.id,
            )
            db.session.add(obs)
            db.session.flush()
            log_event("observation_created", "observation", obs.id)
            db.session.commit()
            flash("Observation saved.", "success")
            if "save_add" in request.form:
                return redirect(url_for("observations.new", child_id=child.id))
            return redirect(url_for("children.detail", child_id=child.id))
    return render_template("observations/form.html", form=form, child=child,
                           title="Add observation", editing=False, show_confirm=show_confirm)


@bp.route("/observations/<int:obs_id>/edit", methods=["GET", "POST"])
@login_required
def edit(obs_id):
    obs = db.get_or_404(Observation, obs_id)
    if obs.is_deleted:
        abort(404)
    child = obs.child
    form = ObservationForm(obj=obs)
    form.category_id.choices = category_choices(include_id=obs.category_id)

    show_confirm = False
    if form.validate_on_submit():
        if is_duplicate_observation(child.id, form.text.data, exclude_id=obs.id) \
                and not form.confirm_duplicate.data:
            show_confirm = True
            form.confirm_duplicate.errors = [DUPLICATE_MESSAGE]
        else:
            obs.category_id = form.category_id.data
            obs.event_date = form.event_date.data
            obs.text = form.text.data.strip()
            obs.source_note = (form.source_note.data or "").strip() or None
            obs.correction_note = (form.correction_note.data or "").strip() or None
            obs.updated_by_id = current_user.id
            log_event("observation_updated", "observation", obs.id)
            db.session.commit()
            flash("Observation updated.", "success")
            return redirect(url_for("children.detail", child_id=child.id))
    return render_template("observations/form.html", form=form, child=child,
                           title="Edit observation", editing=True, show_confirm=show_confirm)


@bp.route("/observations/<int:obs_id>/delete", methods=["POST"])
@login_required
def delete(obs_id):
    obs = db.get_or_404(Observation, obs_id)
    if obs.is_deleted:
        abort(404)
    if not (current_user.is_admin or obs.created_by_id == current_user.id):
        abort(403)
    obs.is_deleted = True
    obs.deleted_at = utcnow()
    obs.deleted_by_id = current_user.id
    log_event("observation_deleted", "observation", obs.id)
    db.session.commit()
    flash("Observation removed.", "info")
    return redirect(url_for("children.detail", child_id=obs.child_id))
