from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import current_user
from ..extensions import db
from ..models import User
from ..audit import log_event
from ..decorators import admin_required
from .forms import UserCreateForm, UserEditForm

bp = Blueprint("admin", __name__, url_prefix="/admin")


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
