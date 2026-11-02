from flask_wtf import FlaskForm
from wtforms import StringField, BooleanField
from wtforms.validators import DataRequired, Length, Optional


class ChildForm(FlaskForm):
    first_name = StringField("First name", validators=[DataRequired(), Length(max=80)])
    last_name = StringField("Last name", validators=[DataRequired(), Length(max=80)])
    current_education = StringField("Current class / education (for example: 6, or +2 Class 11)",
                                    validators=[DataRequired(), Length(max=120)])
    living_situation_note = StringField("Living situation (optional, only what is confirmed)",
                                        validators=[Optional(), Length(max=255)])
    confirm_duplicate = BooleanField("This is a different child with the same name")
