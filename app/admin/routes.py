from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import current_user
from ..extensions import db
from ..models import User, Category, ReportingPeriod
from ..audit import log_event
from ..decorators import admin_required
from .forms import UserCreateForm, UserEditForm, CategoryForm, PeriodForm

bp = Blueprint("admin", __name__, url_prefix="/admin")


# ---------- Users ----------
@bp.route("/users")
@admin_required
def users():
    all_users = db.session.execute(db.select(User).order_by(User.name)).scalars().all()
    return render_template("admin/users.html", users=all_users)


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
