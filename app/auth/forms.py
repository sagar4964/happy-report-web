from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField
from wtforms.validators import DataRequired, Email, Length, EqualTo


class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired()])


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField("Current password", validators=[DataRequired()])
    new_password = PasswordField("New password (min 12 characters)",
                                 validators=[DataRequired(), Length(min=12, max=128)])
    confirm = PasswordField("Repeat new password",
                            validators=[DataRequired(), EqualTo("new_password", "Passwords must match.")])
