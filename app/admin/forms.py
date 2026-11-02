from flask_wtf import FlaskForm
from wtforms import (StringField, PasswordField, SelectField, BooleanField,
                     IntegerField, DateField)
from wtforms.validators import (DataRequired, Email, Length, Optional,
                                ValidationError, NumberRange)
from wtforms.widgets import DateInput
from ..extensions import db
from ..models import User, Category, ReportingPeriod, ROLES


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


class CategoryForm(FlaskForm):
    name = StringField("Category name", validators=[DataRequired(), Length(max=80)])
    sort_order = IntegerField("Order in lists (small numbers first)", validators=[Optional()])
    is_active = BooleanField("Active (can be chosen for new observations)", default=True)

    def __init__(self, *args, category_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.category_id = category_id

    def validate_name(self, field):
        stmt = db.select(Category).filter_by(name=field.data.strip())
        existing = db.session.execute(stmt).scalar_one_or_none()
        if existing and existing.id != self.category_id:
            raise ValidationError("A category with that name already exists.")


class PeriodForm(FlaskForm):
    year = IntegerField("Reporting year (for example 2026)",
                        validators=[DataRequired(), NumberRange(min=2000, max=2100)])
    start_date = DateField("First day of the period", validators=[DataRequired()], widget=DateInput())
    end_date = DateField("Last day of the period", validators=[DataRequired()], widget=DateInput())

    def __init__(self, *args, period_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.period_id = period_id

    def validate_year(self, field):
        existing = db.session.execute(db.select(ReportingPeriod).filter_by(year=field.data)).scalar_one_or_none()
        if existing and existing.id != self.period_id:
            raise ValidationError("That year already exists.")

    def validate_end_date(self, field):
        if self.start_date.data and field.data and field.data < self.start_date.data:
            raise ValidationError("The last day must not be before the first day.")
