from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import current_user
from ..extensions import db
from ..models import User, Category, ReportingPeriod
from ..audit import log_event
from ..decorators import admin_required
from ..user_admin import is_removed, remove_user
from .forms import UserCreateForm, UserEditForm, CategoryForm, PeriodForm

bp = Blueprint("admin", __name__, url_prefix="/admin")


# ---------- Users ----------
@bp.route("/users")
@admin_required
def users():
    everyone = db.session.execute(db.select(User).order_by(User.name)).scalars().all()
    show_removed = request.args.get("show_removed") == "1"
    removed_count = sum(1 for u in everyone if is_removed(u))
    shown = [u for u in everyone if show_removed or not is_removed(u)]
    return render_template("admin/users.html", users=shown, show_removed=show_removed,
                           removed_count=removed_count, is_removed=is_removed)


@bp.route("/users/new", methods=["GET", "POST"])
@admin_required
def user_new():
    form = UserCreateForm()
    if form.validate_on_submit():
        user = User(name=form.name.data.strip(),
                    email=form.email.data.strip().lower(),
                    role=form.role.data)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.flush()  # gives the user an id before we log it
        log_event("user_created", "user", user.id)
        db.session.commit()
        flash("User created.", "success")
        return redirect(url_for("admin.users"))
    return render_template("admin/user_form.html", form=form, title="Add user")


@bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@admin_required
def user_edit(user_id):
    user = db.get_or_404(User, user_id)
    if is_removed(user):
        flash("This account was removed and cannot be edited.", "info")
        return redirect(url_for("admin.users"))
    form = UserEditForm(obj=user)
    if form.validate_on_submit():
        own = user.id == current_user.id
        if own and (form.role.data != user.role or not form.is_active.data):
            flash("You cannot change your own role or deactivate yourself.", "danger")
        else:
            user.name = form.name.data.strip()
            user.role = form.role.data
            user.is_active = form.is_active.data
            if form.new_password.data:
                user.set_password(form.new_password.data)
                log_event("user_password_reset", "user", user.id)
            log_event("user_updated", "user", user.id)
            db.session.commit()
            flash("User updated.", "success")
            return redirect(url_for("admin.users"))
    return render_template("admin/user_form.html", form=form, title="Edit user")


def _other_user(user_id, verb):
    """The user to act on, or None (with a message) when the admin targets their own account."""
    user = db.get_or_404(User, user_id)
    if user.id == current_user.id:
        flash(f"You cannot {verb} your own account.", "danger")
        return None
    return user


@bp.route("/users/<int:user_id>/deactivate", methods=["POST"])
@admin_required
def user_deactivate(user_id):
    user = _other_user(user_id, "deactivate")
    if user is not None:
        if is_removed(user):
            flash("This account was already removed.", "info")
        else:
            user.is_active = False
            log_event("user_deactivated", "user", user.id)
            db.session.commit()
            flash(f"{user.name} was deactivated and can no longer log in. "
                  "You can reactivate the account at any time.", "success")
    return redirect(url_for("admin.users"))


@bp.route("/users/<int:user_id>/reactivate", methods=["POST"])
@admin_required
def user_reactivate(user_id):
    user = _other_user(user_id, "change")
    if user is not None:
        if is_removed(user):
            flash("A removed account cannot be reactivated. Create a new account instead.", "danger")
        else:
            user.is_active = True
            log_event("user_reactivated", "user", user.id)
            db.session.commit()
            flash(f"{user.name} can log in again.", "success")
    return redirect(url_for("admin.users"))


@bp.route("/users/<int:user_id>/remove", methods=["POST"])
@admin_required
def user_remove(user_id):
    user = _other_user(user_id, "remove")
    if user is not None:
        if is_removed(user):
            flash("This account was already removed.", "info")
        else:
            name = user.name
            outcome = remove_user(user)
            log_event("user_removed", "user", user_id, detail=outcome)
            db.session.commit()
            if outcome == "deleted":
                flash(f"{name} was deleted. This account had no work attached to it.", "success")
            else:
                flash(f"{name} was removed. Their login is disabled and their name is replaced by "
                      "'Removed user', so notes and reports they wrote stay intact.", "success")
    return redirect(url_for("admin.users"))


# ---------- Categories ----------
@bp.route("/categories")
@admin_required
def categories():
    rows = db.session.execute(
        db.select(Category).order_by(Category.sort_order, Category.name)
    ).scalars().all()
    return render_template("admin/categories.html", categories=rows)


@bp.route("/categories/new", methods=["GET", "POST"])
@admin_required
def category_new():
    form = CategoryForm()
    if form.validate_on_submit():
        cat = Category(name=form.name.data.strip(),
                       sort_order=form.sort_order.data or 0,
                       is_active=form.is_active.data)
        db.session.add(cat)
        db.session.flush()
        log_event("category_created", "category", cat.id)
        db.session.commit()
        flash("Category added.", "success")
        return redirect(url_for("admin.categories"))
    return render_template("admin/simple_form.html", form=form, title="Add category",
                           cancel_url=url_for("admin.categories"))


@bp.route("/categories/<int:category_id>/edit", methods=["GET", "POST"])
@admin_required
def category_edit(category_id):
    cat = db.get_or_404(Category, category_id)
    form = CategoryForm(obj=cat, category_id=cat.id)
    if form.validate_on_submit():
        cat.name = form.name.data.strip()
        cat.sort_order = form.sort_order.data or 0
        cat.is_active = form.is_active.data
        log_event("category_updated", "category", cat.id)
        db.session.commit()
        flash("Category updated.", "success")
        return redirect(url_for("admin.categories"))
    return render_template("admin/simple_form.html", form=form, title="Edit category",
                           cancel_url=url_for("admin.categories"))


# ---------- Reporting periods ----------
@bp.route("/periods")
@admin_required
def periods():
    rows = db.session.execute(
        db.select(ReportingPeriod).order_by(ReportingPeriod.year.desc())
    ).scalars().all()
    return render_template("admin/periods.html", periods=rows)


@bp.route("/periods/new", methods=["GET", "POST"])
@admin_required
def period_new():
    form = PeriodForm()
    if form.validate_on_submit():
        period = ReportingPeriod(year=form.year.data, start_date=form.start_date.data,
                                 end_date=form.end_date.data)
        db.session.add(period)
        db.session.flush()
        log_event("period_created", "period", period.id)
        db.session.commit()
        flash("Reporting period added.", "success")
        return redirect(url_for("admin.periods"))
    return render_template("admin/simple_form.html", form=form, title="Add reporting period",
                           cancel_url=url_for("admin.periods"))


@bp.route("/periods/<int:period_id>/edit", methods=["GET", "POST"])
@admin_required
def period_edit(period_id):
    period = db.get_or_404(ReportingPeriod, period_id)
    form = PeriodForm(obj=period, period_id=period.id)
    if form.validate_on_submit():
        period.year = form.year.data
        period.start_date = form.start_date.data
        period.end_date = form.end_date.data
        log_event("period_updated", "period", period.id)
        db.session.commit()
        flash("Reporting period updated.", "success")
        return redirect(url_for("admin.periods"))
    return render_template("admin/simple_form.html", form=form, title="Edit reporting period",
                           cancel_url=url_for("admin.periods"))
