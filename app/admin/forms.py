from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SelectField, BooleanField
from wtforms.validators import DataRequired, Email, Length, Optional, ValidationError
from ..extensions import db
from ..models import User, ROLES


class UserCreateForm(FlaskForm):
    name = StringField("Full name", validators=[DataRequired(), Length(max=120)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    role = SelectField("Role", choices=ROLES)
    password = PasswordField("Temporary password (min 12 characters)",
                             validators=[DataRequired(), Length(min=12, max=128)])

    def validate_email(self, field):
        email = field.data.strip().lower()
        if db.session.execute(db.select(User).filter_by(email=email)).scalar_one_or_none():
            raise ValidationError("That email is already in use.")


class UserEditForm(FlaskForm):
    name = StringField("Full name", validators=[DataRequired(), Length(max=120)])
    role = SelectField("Role", choices=ROLES)
    is_active = BooleanField("Account is active")
    new_password = PasswordField("Set a new password (leave blank to keep)",
                                 validators=[Optional(), Length(min=12, max=128)])
