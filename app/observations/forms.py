from datetime import date
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SelectField, BooleanField, DateField
from wtforms.validators import DataRequired, Length, Optional, ValidationError
from wtforms.widgets import DateInput


class ObservationForm(FlaskForm):
    event_date = DateField("Date it happened", validators=[DataRequired()],
                           default=date.today, widget=DateInput())
    category_id = SelectField("Category", coerce=int, validators=[DataRequired()])
    text = TextAreaField("Observation (a bullet point is fine)",
                         validators=[DataRequired(), Length(max=5000)],
                         render_kw={"rows": 5})
    source_note = StringField("Source (optional)", validators=[Optional(), Length(max=255)])
    correction_note = StringField("Why was this changed? (optional)",
                                  validators=[Optional(), Length(max=255)])
    confirm_duplicate = BooleanField("This is not a duplicate, save it anyway")

    def validate_event_date(self, field):
        if field.data and field.data > date.today():
            raise ValidationError("The date cannot be in the future. Please check the year.")
