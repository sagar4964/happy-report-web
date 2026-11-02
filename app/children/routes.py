from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from sqlalchemy import or_
from ..extensions import db
from ..models import Child, Category, Observation
from ..audit import log_event
from ..decorators import admin_required
from ..services import get_periods, resolve_period, find_same_name
from .forms import ChildForm

bp = Blueprint("children", __name__, url_prefix="/children")

DUPLICATE_MESSAGE = ("A child with this name already exists. Check the list below, "
                     "then tick the box if this is really a different child.")


@bp.route("/")
@login_required
def index():
    q = request.args.get("q", "").strip()
    show_archived = request.args.get("archived") == "1"
    stmt = db.select(Child)
    if not show_archived:
        stmt = stmt.where(Child.is_active.is_(True))
    for term in q.split():
        like = f"%{term}%"
        stmt = stmt.where(or_(Child.first_name.ilike(like), Child.last_name.ilike(like)))
    stmt = stmt.order_by(Child.first_name, Child.last_name, Child.id)
    children = db.session.execute(stmt).scalars().all()
    return render_template("children/index.html", children=children, q=q,
                           show_archived=show_archived)


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    form = ChildForm()
    matches = []
    if form.validate_on_submit():
        first = form.first_name.data.strip()
        last = form.last_name.data.strip()
        matches = find_same_name(first, last)
        if matches and not form.confirm_duplicate.data:
            form.confirm_duplicate.errors = [DUPLICATE_MESSAGE]
        else:
            child = Child(
                first_name=first,
                last_name=last,
                current_education=form.current_education.data.strip(),
                living_situation_note=(form.living_situation_note.data or "").strip() or None,
                created_by_id=current_user.id,
            )
            db.session.add(child)
            db.session.flush()
            log_event("child_created", "child", child.id)
            db.session.commit()
            flash("Child added.", "success")
            return redirect(url_for("children.detail", child_id=child.id))
    return render_template("children/form.html", form=form, title="Add child",
                           matches=matches)


@bp.route("/<int:child_id>")
@login_required
def detail(child_id):
    child = db.get_or_404(Child, child_id)
    periods = get_periods()
    selected = resolve_period(periods, request.args.get("period"))
    category_id = request.args.get("category", type=int)

    stmt = db.select(Observation).where(
        Observation.child_id == child.id,  # only THIS child's entries
        Observation.is_deleted.is_(False),
    )
    if selected:
        stmt = stmt.where(Observation.event_date.between(selected.start_date, selected.end_date))
    if category_id:
        stmt = stmt.where(Observation.category_id == category_id)
    stmt = stmt.order_by(Observation.event_date, Observation.id)
    observations = db.session.execute(stmt).scalars().all()

    categories = db.session.execute(
        db.select(Category).order_by(Category.sort_order, Category.name)
    ).scalars().all()
    return render_template("children/detail.html", child=child, observations=observations,
                           periods=periods, selected=selected, categories=categories,
                           category_id=category_id)


@bp.route("/<int:child_id>/edit", methods=["GET", "POST"])
@login_required
def edit(child_id):
    child = db.get_or_404(Child, child_id)
    form = ChildForm(obj=child)
    matches = []
    if form.validate_on_submit():
        first = form.first_name.data.strip()
        last = form.last_name.data.strip()
        name_changed = (first.lower(), last.lower()) != (child.first_name.lower(), child.last_name.lower())
        if name_changed:
            matches = find_same_name(first, last, exclude_id=child.id)
        if matches and not form.confirm_duplicate.data:
            form.confirm_duplicate.errors = [DUPLICATE_MESSAGE]
        else:
            child.first_name = first
            child.last_name = last
            child.current_education = form.current_education.data.strip()
            child.living_situation_note = (form.living_situation_note.data or "").strip() or None
            child.updated_by_id = current_user.id
            log_event("child_updated", "child", child.id)
            db.session.commit()
            flash("Profile updated.", "success")
            return redirect(url_for("children.detail", child_id=child.id))
    return render_template("children/form.html", form=form, title="Edit profile",
                           matches=matches, child=child)


@bp.route("/<int:child_id>/archive", methods=["POST"])
@admin_required
def archive(child_id):
    child = db.get_or_404(Child, child_id)
    child.is_active = not child.is_active
    child.updated_by_id = current_user.id
    log_event("child_archived" if not child.is_active else "child_restored", "child", child.id)
    db.session.commit()
    flash("Child archived." if not child.is_active else "Child restored.", "info")
    return redirect(url_for("children.detail", child_id=child.id))
